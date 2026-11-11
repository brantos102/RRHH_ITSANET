"""Primer ingreso por correo y ficha inicial.

Quien no tiene correo registrado escribe el suyo, recibe ahí el código y con
él entra: recibir el código es la prueba de que el buzón es suyo, y recién
entonces el correo pasa al expediente. Antes de usar el sistema completa lo
que falte: fecha de nacimiento, confirmar la fecha de ingreso (o pedir que la
revisen), jefe, cargo, teléfono y contacto de emergencia.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, lista, obtener_todos, obtener_uno
from tests.conftest import Sql, persona

CED = "1700000035"
CED_OTRA = "1700000043"
CORREO = "nuevo.ingreso@itsanet.com.ec"


@pytest.fixture
async def sin_correo(empleado):
    await ejecutar("delete from users where cedula in %s", (lista([CED, CED_OTRA]),))
    fila = await persona(CED, nombre="Ingreso Por Correo", email=None, rol="empleado",
                         correo_pendiente=True, ficha_completa=False, ciudad="Quito",
                         region="sierra", fecha_ingreso="2021-02-01")
    yield {"id": str(fila["id"]), "cedula": CED}
    await ejecutar("delete from cambios_ficha where user_id in "
                   "(select id from users where cedula in %s)", (lista([CED, CED_OTRA]),))
    await ejecutar("delete from users where cedula in %s", (lista([CED, CED_OTRA]),))
    await ejecutar("update app_config set valor = 'correo' where clave = 'alta_verificacion'")
    await ejecutar("update app_config set valor = %s where clave = 'ficha_inicial_campos'",
                   ("fecha_nacimiento,fecha_ingreso,jefe,cargo,telefono,emergencia",))


@pytest.fixture
async def rrhh_auth(cliente, codigos, empleado):
    await persona("1700000076", al_existir={"rol": "rrhh"}, nombre="Talento Ingreso",
                  email="thingreso@api.test", rol="rrhh",
                  fecha_ingreso=Sql("current_date() - interval 900 day"))
    await cliente.post("/auth/solicitar-token", json={"cedula": "1700000076"})
    r = await cliente.post("/auth/validar-token", json={"cedula": "1700000076", "codigo": codigos[-1]})
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}
    await ejecutar("update cambios_ficha set resuelto_por = null where resuelto_por = "
                   "(select id from users where cedula = '1700000076')")
    await ejecutar("delete from users where cedula = '1700000076'")


@pytest.fixture
def avisos(monkeypatch) -> list[dict]:
    from app import notificaciones
    enviados: list[dict] = []

    async def falso(destinatarios, nombre, cedula, email):
        enviados.append({"nombre": nombre, "email": email})

    monkeypatch.setattr(notificaciones, "avisar_alta_completada", falso)
    return enviados


async def _entrar(cliente, codigos, correo=CORREO) -> dict:
    r = await cliente.post("/auth/registrar-correo", json={"cedula": CED, "email": correo})
    assert r.status_code == 200, r.text
    r = await cliente.post("/auth/validar-token", json={"cedula": CED, "codigo": codigos[-1]})
    assert r.status_code == 200, r.text
    return r.json()


async def test_quien_no_tiene_correo_sabe_que_debe_registrarlo(cliente, sin_correo):
    r = await cliente.post("/auth/necesita-ficha", json={"cedula": CED})
    assert r.json() == {"necesita": True, "modo": "correo"}


async def test_a_quien_tiene_correo_no_se_le_dice_nada(cliente, empleado):
    r = await cliente.post("/auth/necesita-ficha", json={"cedula": empleado["cedula"]})
    assert r.json() == {"necesita": False, "modo": None}


async def test_el_correo_rige_recien_al_entrar_con_el_codigo(cliente, codigos, sin_correo, avisos):
    r = await cliente.post("/auth/registrar-correo", json={"cedula": CED, "email": CORREO})
    assert r.status_code == 200, r.text
    assert r.json()["correo"].endswith("@itsanet.com.ec") and "***" in r.json()["correo"]
    antes = await obtener_uno("select email, correo_pendiente from users where cedula = %s", (CED,))
    assert antes["email"] is None, "declarar un correo no lo guarda: hay que recibir el código"

    r = await cliente.post("/auth/validar-token", json={"cedula": CED, "codigo": codigos[-1]})
    assert r.status_code == 200, r.text
    despues = await obtener_uno("select email, correo_pendiente from users where cedula = %s", (CED,))
    assert despues["email"] == CORREO and not despues["correo_pendiente"]
    assert avisos and avisos[0]["email"] == CORREO, "Talento Humano se entera"
    # Y ya no puede volver a usarse este camino para cambiarlo.
    r = await cliente.post("/auth/necesita-ficha", json={"cedula": CED})
    assert r.json()["necesita"] is False


async def test_al_entrar_se_le_pide_lo_que_falta(cliente, codigos, sin_correo, avisos):
    sesion = await _entrar(cliente, codigos)
    assert set(sesion["perfil"]["pendientes"]) >= {"fecha_nacimiento", "fecha_ingreso",
                                                   "telefono", "emergencia"}


async def test_un_codigo_equivocado_no_guarda_el_correo(cliente, codigos, sin_correo):
    await cliente.post("/auth/registrar-correo", json={"cedula": CED, "email": CORREO})
    r = await cliente.post("/auth/validar-token", json={"cedula": CED, "codigo": "000000"})
    assert r.status_code == 401
    assert (await obtener_uno("select email from users where cedula = %s", (CED,)))["email"] is None


async def test_no_sirve_para_quitarle_la_cuenta_a_quien_ya_tiene_correo(cliente, codigos, empleado):
    r = await cliente.post("/auth/registrar-correo",
                           json={"cedula": empleado["cedula"], "email": "intruso@itsanet.com.ec"})
    assert r.status_code == 409
    assert not codigos


async def test_no_se_puede_usar_el_correo_de_otra_persona(cliente, codigos, sin_correo):
    await persona(CED_OTRA, nombre="Otra Persona", email="otra.persona@itsanet.com.ec",
                  rol="empleado")
    r = await cliente.post("/auth/registrar-correo",
                           json={"cedula": CED, "email": "Otra.Persona@itsanet.com.ec"})
    assert r.status_code == 409
    assert not codigos


async def test_en_modo_nacimiento_el_correo_solo_no_alcanza(cliente, codigos, sin_correo):
    await ejecutar("update app_config set valor = 'nacimiento' where clave = 'alta_verificacion'")
    r = await cliente.post("/auth/necesita-ficha", json={"cedula": CED})
    assert r.json()["modo"] == "nacimiento"
    r = await cliente.post("/auth/registrar-correo", json={"cedula": CED, "email": CORREO})
    assert r.status_code == 409
    assert not codigos


async def test_con_la_fecha_de_nacimiento_basta_sin_la_de_ingreso(cliente, sin_correo):
    await ejecutar("update users set fecha_nacimiento = '1995-10-16' where cedula = %s", (CED,))
    r = await cliente.post("/auth/probar-identidad",
                           json={"cedula": CED, "fecha_nacimiento": "1995-10-16"})
    assert r.status_code == 200, r.text


# ------------------------------------------------------------ ficha inicial
async def _sesion(cliente, codigos) -> dict:
    s = await _entrar(cliente, codigos)
    return {"Authorization": f"Bearer {s['access_token']}"}


async def test_la_ficha_inicial_dice_que_falta_y_que_consta(cliente, codigos, sin_correo, avisos):
    auth = await _sesion(cliente, codigos)
    r = await cliente.get("/mi-ficha/inicial", headers=auth)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert "fecha_nacimiento" in cuerpo["pendientes"]
    assert str(cuerpo["persona"]["fecha_ingreso"]).startswith("2021-02-01")


async def test_sin_responder_todo_no_se_guarda(cliente, codigos, sin_correo, avisos):
    auth = await _sesion(cliente, codigos)
    r = await cliente.post("/mi-ficha/inicial", headers=auth, json={"fecha_nacimiento": "1995-10-16"})
    assert r.status_code == 422
    assert "Falta" in r.json()["detail"]["mensaje"]


async def test_completa_la_ficha_y_pide_revisar_su_fecha_de_ingreso(
        cliente, codigos, sin_correo, avisos):
    auth = await _sesion(cliente, codigos)
    r = await cliente.post("/mi-ficha/inicial", headers=auth, json={
        "fecha_nacimiento": "1995-10-16",
        "fecha_ingreso_correcta": False, "fecha_ingreso_propuesta": "2020-11-15",
        "fecha_ingreso_motivo": "Entré por un proveedor antes de pasar a nómina",
        "jefe_correcto": True, "cargo_correcto": True,
        "telefono": "099 111 2223",
        "emergencia_nombre": "Contacto Prueba", "emergencia_parentesco": "madre",
        "emergencia_telefono": "0991112224",
    })
    assert r.status_code == 200, r.text
    assert r.json()["pendientes"] == []
    assert r.json()["en_revision"] == ["Fecha de ingreso que indica"]

    u = await obtener_uno("""select fecha_nacimiento, fecha_ingreso, telefono, ficha_completa,
                                    fecha_ingreso_confirmada_en from users where cedula = %s""", (CED,))
    assert str(u["fecha_nacimiento"]) == "1995-10-16"
    assert str(u["fecha_ingreso"]) == "2021-02-01", "la fecha de ingreso no cambia sola"
    assert u["telefono"] == "0991112223" and u["ficha_completa"]
    pedido = await obtener_todos("select campo, valor_nuevo, estado from cambios_ficha "
                                 "where user_id = %s", (sin_correo["id"],))
    assert pedido == [{"campo": "fecha_ingreso", "valor_nuevo": "2020-11-15", "estado": "pendiente"}]

    # La siguiente vez que entra ya no se le pide nada.
    perfil = (await cliente.get("/auth/me", headers=auth)).json()
    assert perfil["pendientes"] == []


async def test_lo_que_se_pide_lo_decide_talento_humano(cliente, codigos, sin_correo, avisos):
    await ejecutar("update app_config set valor = 'fecha_nacimiento' "
                   "where clave = 'ficha_inicial_campos'")
    sesion = await _entrar(cliente, codigos)
    assert sesion["perfil"]["pendientes"] == ["fecha_nacimiento"]


async def test_al_aprobar_la_fecha_de_ingreso_queda_confirmada(
        cliente, codigos, sin_correo, avisos, rrhh_auth):
    auth = await _sesion(cliente, codigos)
    await ejecutar("update app_config set valor = 'fecha_ingreso' where clave = 'ficha_inicial_campos'")
    await cliente.post("/mi-ficha/inicial", headers=auth, json={
        "fecha_ingreso_correcta": False, "fecha_ingreso_propuesta": "2020-11-15"})
    cambio = await obtener_uno("select id from cambios_ficha where user_id = %s", (sin_correo["id"],))
    r = await cliente.post(f"/rrhh/cambios-ficha/{cambio['id']}", headers=rrhh_auth,
                           json={"accion": "aprobar"})
    assert r.status_code == 200, r.text
    u = await obtener_uno("select fecha_ingreso, fecha_ingreso_confirmada_en from users "
                          "where cedula = %s", (CED,))
    assert str(u["fecha_ingreso"]) == "2020-11-15" and u["fecha_ingreso_confirmada_en"]


# ------------------------------------------- jefe no registrado y área
async def test_un_jefe_que_no_esta_registrado_se_pide_por_nombre(
        cliente, codigos, sin_correo, avisos, rrhh_auth):
    auth = await _sesion(cliente, codigos)
    await ejecutar("update app_config set valor = 'jefe,cargo' where clave = 'ficha_inicial_campos'")
    r = await cliente.post("/mi-ficha/inicial", headers=auth, json={
        "jefe_correcto": False, "jefe_nombre_propuesto": "  Pedro   Inventado Pérez ",
        "cargo_correcto": False, "cargo_propuesto": "Supervisor de bodega",
        "departamento_propuesto": "Logística"})
    assert r.status_code == 200, r.text
    assert r.json()["pendientes"] == []
    pedidos = {f["campo"]: f["valor_nuevo"] for f in await obtener_todos(
        "select campo, valor_nuevo from cambios_ficha where user_id = %s", (sin_correo["id"],))}
    assert pedidos == {"jefe_por_registrar": "Pedro Inventado Pérez",
                       "cargo": "Supervisor de bodega", "departamento": "Logística"}

    # Aprobarlo solo lo marca como atendido: no toca ninguna columna.
    cambio = await obtener_uno("select id from cambios_ficha where user_id = %s "
                               "and campo = 'jefe_por_registrar'", (sin_correo["id"],))
    r = await cliente.post(f"/rrhh/cambios-ficha/{cambio['id']}", headers=rrhh_auth,
                           json={"accion": "aprobar"})
    assert r.status_code == 200, r.text


async def test_un_jefe_sin_apellido_no_alcanza(cliente, codigos, sin_correo, avisos):
    auth = await _sesion(cliente, codigos)
    await ejecutar("update app_config set valor = 'jefe' where clave = 'ficha_inicial_campos'")
    r = await cliente.post("/mi-ficha/inicial", headers=auth, json={
        "jefe_correcto": False, "jefe_nombre_propuesto": "Pedro"})
    assert r.status_code == 422


async def test_el_catalogo_sugiere_cargos_y_areas_sin_datos_personales(cliente, codigos, sin_correo,
                                                                      avisos):
    auth = await _sesion(cliente, codigos)
    r = await cliente.get("/catalogos/cargos", headers=auth)
    assert r.status_code == 200
    assert set(r.json()) == {"cargos", "areas"}
    assert all(set(c) == {"cargo", "area"} for c in r.json()["cargos"])
