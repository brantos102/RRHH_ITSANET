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
