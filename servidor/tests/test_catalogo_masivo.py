"""Catálogo de cargos y áreas, actualización masiva por Excel, teléfonos
adicionales y domicilio.

  · Renombrar o unificar en el catálogo cambia las fichas, no solo la lista.
  · La carga masiva primero muestra qué cambiaría; solo con «aplicar» y un
    motivo cambia algo, y queda con folio y detalle.
  · Una celda vacía no borra nada.
  · Teléfonos y domicilio los corrige la persona; el cargo y el área, no.
"""
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook, load_workbook

from app.db import ejecutar, obtener_uno
from tests.test_reglas_nuevas import CEDULA_JEFE_R, CEDULA_RRHH_R, auth, jefe_auth, rrhh_auth  # noqa: F401


@pytest.fixture(autouse=True)
async def _limpio(empleado):
    yield
    await ejecutar("DELETE FROM areas WHERE nombre LIKE %s", ("Prueba %",))
    await ejecutar("DELETE FROM cargos WHERE nombre LIKE %s", ("Prueba %",))
    await ejecutar("DELETE FROM cargas_masivas WHERE archivo LIKE %s", ("prueba%",))


def _excel(filas: list[list]) -> bytes:
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Personas"
    hoja.append(["Cédula", "Nombre (referencia, no se cambia aquí)", "Cargo", "Área", "Cédula del jefe",
                 "Ciudad de trabajo", "Bodega", "Centro de costo", "Cliente", "Tipo de contrato",
                 "Fin del contrato (dd/mm/aaaa)"])
    for f in filas:
        hoja.append(f)
    memoria = io.BytesIO()
    libro.save(memoria)
    return memoria.getvalue()


# ---------------------------------------------------------------- catálogo
async def test_renombrar_y_unificar_cambian_las_fichas(cliente, auth, rrhh_auth, empleado):
    assert (await cliente.get("/admin/catalogo", headers=auth)).status_code == 403
    r = await cliente.post("/admin/catalogo/areas", headers=rrhh_auth, json={"nombre": "Prueba Bodega Norte"})
    assert r.status_code == 201, r.text
    origen = r.json()["id"]
    destino = (await cliente.post("/admin/catalogo/areas", headers=rrhh_auth,
                                  json={"nombre": "Prueba Bodega"})).json()["id"]
    r = await cliente.post("/admin/catalogo/cargos", headers=rrhh_auth,
                           json={"nombre": "Prueba Auxiliar", "area_id": origen})
    assert r.status_code == 201
    await ejecutar("UPDATE users SET departamento = 'Prueba Bodega Norte', cargo = 'Prueba Auxiliar' WHERE id = %s",
                   (empleado["id"],))

    # Duplicado: no.
    r = await cliente.post("/admin/catalogo/areas", headers=rrhh_auth, json={"nombre": "prueba bodega"})
    assert r.status_code == 422

    r = await cliente.post(f"/admin/catalogo/areas/{origen}/unificar", headers=rrhh_auth,
                           json={"destino_id": destino})
    assert r.status_code == 200 and r.json()["fichas"] == 1
    assert (await obtener_uno("SELECT departamento FROM users WHERE id = %s",
                              (empleado["id"],)))["departamento"] == "Prueba Bodega"
    cargo = await obtener_uno("SELECT id, area_id FROM cargos WHERE nombre = 'Prueba Auxiliar'")
    assert cargo["area_id"] == destino, "el cargo se mudó con el área"

    r = await cliente.patch(f"/admin/catalogo/cargos/{cargo['id']}", headers=rrhh_auth,
                            json={"nombre": "Prueba Auxiliar de bodega"})
    assert r.status_code == 200 and r.json()["fichas"] == 1
    assert (await obtener_uno("SELECT cargo FROM users WHERE id = %s",
                              (empleado["id"],)))["cargo"] == "Prueba Auxiliar de bodega"

    # Lo que se elige al entrar sale del catálogo.
    cat = (await cliente.get("/catalogos/cargos", headers=auth)).json()
    assert any(c["cargo"] == "Prueba Auxiliar de bodega" and c["area"] == "Prueba Bodega" for c in cat["cargos"])


async def test_lo_que_decide_talento_humano_entra_al_catalogo(cliente, rrhh_auth, empleado):
    r = await cliente.patch(f"/admin/usuarios/{empleado['id']}", headers=rrhh_auth,
                            json={"cargo": "Prueba Coordinador", "departamento": "Prueba Logística"})
    assert r.status_code == 200, r.text
    fila = await obtener_uno(
        """SELECT c.nombre FROM cargos c JOIN areas a ON a.id = c.area_id
            WHERE c.nombre = 'Prueba Coordinador' AND a.nombre = 'Prueba Logística'""")
    assert fila


# ---------------------------------------------------------- carga masiva
async def test_carga_masiva_revisa_y_solo_aplica_con_motivo(cliente, rrhh_auth, empleado):
    await ejecutar("UPDATE users SET tipo_contrato = NULL, centro_costo = NULL WHERE id = %s", (empleado["id"],))
    jefe = await obtener_uno("SELECT cedula FROM users WHERE cedula = %s", (CEDULA_RRHH_R,))
    plantilla = await cliente.get("/admin/masivo/plantilla.xlsx", headers=rrhh_auth)
    assert plantilla.status_code == 200
    hojas = load_workbook(io.BytesIO(plantilla.content)).sheetnames
    assert hojas == ["Personas", "Listas", "Cómo usarla"]

    contenido = _excel([
        [empleado["cedula"], "x", "Prueba Analista", "Prueba Operaciones", jefe["cedula"],
         None, None, "CC-99", None, "Indefinido", None],
        ["0000000000", "nadie", "Cargo", None, None, None, None, None, None, None, None],
        [CEDULA_RRHH_R, "x", None, None, CEDULA_RRHH_R, None, None, None, None, None, None],
    ])
    r = await cliente.post("/admin/masivo/revisar", headers=rrhh_auth,
                           files={"archivo": ("prueba.xlsx", contenido,
                                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    d = r.json()
    campos = {c["campo"] for c in d["cambios"] if c["cedula"] == empleado["cedula"]}
    assert campos == {"cargo", "departamento", "jefe_cedula", "centro_costo", "tipo_contrato"}
    assert any("No hay nadie" in e["mensaje"] for e in d["errores"])
    assert any("propio jefe" in e["mensaje"] for e in d["errores"])
    assert any("se agregará al catálogo" in a["mensaje"] for a in d["avisos"])

    # Revisar no cambia nada.
    u = await obtener_uno("SELECT cargo, centro_costo FROM users WHERE id = %s", (empleado["id"],))
    assert u["centro_costo"] != "CC-99"

    folio = d["folio"]
    assert (await cliente.post(f"/admin/masivo/{folio}/aplicar", headers=rrhh_auth,
                               json={"motivo": "corto"})).status_code == 422
    r = await cliente.post(f"/admin/masivo/{folio}/aplicar", headers=rrhh_auth,
                           json={"motivo": "Reorganización de áreas de noviembre"})
    assert r.status_code == 200, r.text
    u = await obtener_uno(
        """SELECT u.cargo, u.departamento, u.centro_costo, u.tipo_contrato, j.cedula AS jefe
             FROM users u LEFT JOIN users j ON j.id = u.jefe_id WHERE u.id = %s""", (empleado["id"],))
    assert (u["cargo"], u["departamento"], u["centro_costo"], u["tipo_contrato"], u["jefe"]) == \
        ("Prueba Analista", "Prueba Operaciones", "CC-99", "indefinido", CEDULA_RRHH_R)
    assert await obtener_uno("SELECT 1 AS x FROM cargos WHERE nombre = 'Prueba Analista'")
    # No se aplica dos veces.
    r = await cliente.post(f"/admin/masivo/{folio}/aplicar", headers=rrhh_auth,
                           json={"motivo": "Reorganización de áreas de noviembre"})
    assert r.status_code == 422
    historial = (await cliente.get("/admin/masivo", headers=rrhh_auth)).json()
    assert any(h["folio"] == folio and h["estado"] == "aplicada" for h in historial)


async def test_celda_vacia_no_borra_y_cedula_sin_cero(cliente, rrhh_auth, empleado):
    await ejecutar("UPDATE users SET bodega = 'Bodega Uno' WHERE id = %s", (empleado["id"],))
    cedula_numero = int(empleado["cedula"])          # como la deja Excel: sin el cero inicial
    contenido = _excel([[cedula_numero, None, None, None, None, None, None, None, None, None, None]])
    d = (await cliente.post("/admin/masivo/revisar", headers=rrhh_auth,
                            files={"archivo": ("prueba-vacia.xlsx", contenido, "application/octet-stream")})).json()
    assert d["cambios"] == [] and d["errores"] == []


# ------------------------------------------------- teléfonos y domicilio
async def test_telefonos_y_domicilio_los_corrige_la_persona(cliente, auth, empleado):
    for i in range(5):
        r = await cliente.post("/mi-ficha/telefonos", headers=auth,
                               json={"numero": f"09911122{i}0", "tipo": "celular", "etiqueta": f"N{i}"})
        assert r.status_code == 201, r.text
    r = await cliente.post("/mi-ficha/telefonos", headers=auth, json={"numero": "0991112299"})
    assert r.status_code == 422, "máximo cinco"
    lista = (await cliente.get("/mi-ficha/telefonos", headers=auth)).json()
    assert (await cliente.delete(f"/mi-ficha/telefonos/{lista[0]['id']}", headers=auth)).status_code == 200

    r = await cliente.patch("/mi-ficha", headers=auth, json={
        "domicilio_provincia": "Pichincha", "domicilio_canton": "Quito", "domicilio_parroquia": "Iñaquito",
        "domicilio_calle": "Av. Amazonas", "domicilio_numero": "N34-12",
        "domicilio_interseccion": "Naciones Unidas", "domicilio_referencia": "frente al parque"})
    assert r.status_code == 200, r.text
    ficha = (await cliente.get("/mi-ficha", headers=auth)).json()
    assert ficha["persona"]["domicilio_parroquia"] == "Iñaquito"
    assert len(ficha["telefonos"]) == 4
    u = await obtener_uno("SELECT direccion FROM users WHERE id = %s", (empleado["id"],))
    assert u["direccion"] == ("Av. Amazonas N34-12 y Naciones Unidas, Iñaquito, Quito, Pichincha "
                              "(frente al parque)")
    await ejecutar("DELETE FROM telefonos_adicionales WHERE user_id = %s", (empleado["id"],))


async def test_el_jefe_no_ve_telefonos_ni_domicilio(cliente, jefe_auth, empleado):
    r = await cliente.get(f"/personas/{empleado['id']}", headers=jefe_auth)
    assert r.status_code == 200 and r.json()["ficha"] is None


# --------------------------------------------------- altas (personas nuevas)
def _cedula_valida(base9: str) -> str:
    suma = 0
    for i, c in enumerate(base9):
        d = int(c) * (2 if i % 2 == 0 else 1)
        suma += d - 9 if d > 9 else d
    return base9 + str((10 - suma % 10) % 10)


def _excel_altas(filas: list[list]) -> bytes:
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Personas nuevas"
    hoja.append(["Cédula", "Apellidos y nombres", "Fecha de ingreso (dd/mm/aaaa)",
                 "Días de vacaciones disponibles (conciliados)", "Correo personal", "Celular", "Cargo", "Área",
                 "Cédula del jefe", "Ciudad de trabajo"])
    for f in filas:
        hoja.append(f)
    memoria = io.BytesIO()
    libro.save(memoria)
    return memoria.getvalue()


@pytest.fixture
async def nuevas():
    cedulas = [_cedula_valida(f"17010{i:04d}") for i in range(1, 4)]
    yield cedulas
    for c in cedulas:
        u = await obtener_uno("SELECT id FROM users WHERE cedula = %s", (c,))
        if u:
            await ejecutar("DELETE FROM vacation_periods WHERE user_id = %s", (u["id"],))
            await ejecutar("UPDATE users SET jefe_id = NULL WHERE jefe_id = %s", (u["id"],))
    for c in cedulas:
        await ejecutar("DELETE FROM users WHERE cedula = %s", (c,))


async def test_altas_registra_solo_a_quien_falta(cliente, auth, rrhh_auth, empleado, nuevas):
    assert (await cliente.get("/admin/masivo/plantilla-altas.xlsx", headers=auth)).status_code == 403
    r = await cliente.get("/admin/masivo/plantilla-altas.xlsx", headers=rrhh_auth)
    assert r.status_code == 200
    assert load_workbook(io.BytesIO(r.content)).sheetnames == ["Personas nuevas", "Listas", "Cómo usarla"]

    jefe_nuevo, colaborador, sin_saldo = nuevas
    contenido = _excel_altas([
        # Ya registrado: se reconoce y se omite.
        [empleado["cedula"], "Alguien que ya está", "01/01/2020", None, None, None, None, None, None, None],
        # Jefe nuevo con saldo conciliado y su colaborador (jefe en el mismo archivo).
        [jefe_nuevo, "Prueba Jefa Nueva", "01/03/2019", "12,5", "prueba.jefa@itsanet.test", "991234567",
         "Prueba Supervisor", "Prueba Altas", None, "Quito"],
        [colaborador, "Prueba Colaborador Nuevo", "15/06/2024", "3", None, None,
         "Prueba Auxiliar", "Prueba Altas", jefe_nuevo, "Guayaquil"],
        # Sin saldo: se calcula y se avisa.
        [int(sin_saldo), "Prueba Sin Saldo", "01/01/2025", None, None, None, None, None, None, None],
        # Errores.
        ["1799000099", "Cédula mala", "01/01/2020", None, None, None, None, None, None, None],
        [_cedula_valida("170100050"), "Prueba Futura", "01/01/2099", None, None, None, None, None, None, None],
        [_cedula_valida("170100060"), "Prueba Saldo Imposible", "01/10/2025", "300", None, None,
         None, None, None, None],
    ])
    r = await cliente.post("/admin/masivo/revisar-altas", headers=rrhh_auth,
                           files={"archivo": ("prueba-altas.xlsx", contenido, "application/octet-stream")})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ya_registradas"] == 1
    assert {a["cedula"] for a in d["altas"]} == set(nuevas), d["errores"]
    mensajes = " | ".join(e["mensaje"] for e in d["errores"])
    assert "no es válida" in mensajes and "futura" in mensajes and "supera lo devengado" in mensajes
    assert any("como si no hubiera gozado" in a["mensaje"] for a in d["avisos"])
    assert d["no_en_archivo"]["total"] >= 1
    # La revisión no registra a nadie (el ensayo se deshace).
    assert not await obtener_uno("SELECT 1 AS x FROM users WHERE cedula = %s", (jefe_nuevo,))

    r = await cliente.post(f"/admin/masivo/{d['folio']}/aplicar", headers=rrhh_auth,
                           json={"motivo": "Completar la nómina de noviembre"})
    assert r.status_code == 200, r.text
    assert r.json()["personas"] == 3 and r.json()["sin_correo"] == 2
    jefa = await obtener_uno("SELECT id, dias_vacaciones, telefono, email FROM users WHERE cedula = %s", (jefe_nuevo,))
    assert float(jefa["dias_vacaciones"]) == 12.5 and jefa["telefono"] == "0991234567"
    col = await obtener_uno("SELECT jefe_id, region, rol FROM users WHERE cedula = %s", (colaborador,))
    assert col["jefe_id"] == jefa["id"] and col["rol"] == "empleado"
    assert await obtener_uno("""SELECT 1 AS x FROM cargos c JOIN areas a ON a.id = c.area_id
                                 WHERE c.nombre = 'Prueba Auxiliar' AND a.nombre = 'Prueba Altas'""")
    historial = (await cliente.get("/admin/masivo", headers=rrhh_auth)).json()
    assert any(h["folio"] == d["folio"] and h["tipo"] == "altas" and h["estado"] == "aplicada" for h in historial)
    # Volver a subir el mismo archivo ya no registra a nadie de nuevo.
    d2 = (await cliente.post("/admin/masivo/revisar-altas", headers=rrhh_auth,
                             files={"archivo": ("prueba-altas.xlsx", contenido, "application/octet-stream")})).json()
    assert d2["altas"] == [] and d2["ya_registradas"] == 4


async def test_altas_jefe_con_error_arrastra_a_su_equipo(cliente, rrhh_auth, nuevas):
    jefe, colaborador, _ = nuevas
    contenido = _excel_altas([
        [jefe, "Prueba Jefe Con Error", "01/01/2099", None, None, None, None, None, None, None],
        [colaborador, "Prueba Del Equipo", "01/01/2024", "1", None, None, None, None, jefe, None],
    ])
    d = (await cliente.post("/admin/masivo/revisar-altas", headers=rrhh_auth,
                            files={"archivo": ("prueba-altas2.xlsx", contenido,
                                               "application/octet-stream")})).json()
    assert d["altas"] == []
    assert any(e["cedula"] == colaborador for e in d["errores"])
    # Una carga de altas no se aplica por la vía de actualizaciones ni al revés.
    r = await cliente.post(f"/admin/masivo/{d['folio']}/aplicar", headers=rrhh_auth,
                           json={"motivo": "Prueba de altas sin personas"})
    assert r.status_code == 422
