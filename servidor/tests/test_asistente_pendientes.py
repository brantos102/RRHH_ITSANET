"""Asistente guiado y pendientes de Talento Humano por sede."""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_todos
from app.routers.asistente import _tema, normal
from tests.test_folio_calendario import _crear, auth, companero, jefe_auth  # noqa: F401
from tests.test_reemplazo import rrhh_auth  # noqa: F401


@pytest.fixture(autouse=True)
async def _limpio(empleado):
    await ejecutar("delete from asistente_respuestas")
    await ejecutar("delete from atenciones")
    yield
    await ejecutar("delete from asistente_respuestas")
    await ejecutar("delete from atenciones")
    await ejecutar("delete from asistente_consultas")


def test_entiende_sin_tildes_ni_mayusculas():
    assert normal("¿CUÁNTOS Días?") == "cuantos dias"
    assert _tema("cuantos días de vacaciones me quedan")[0] == "saldo"
    assert _tema("En qué va mi solicitud")[0] == "solicitudes"
    assert _tema("necesito un permiso médico")[0] == "permisos"


async def test_responde_el_saldo_de_quien_pregunta(cliente, auth, empleado):
    r = await cliente.post("/asistente/preguntar", headers=auth,
                           json={"texto": "¿Cuántos días de vacaciones tengo?"})
    assert r.status_code == 200, r.text
    assert "día(s) de vacaciones disponibles" in r.json()["texto"]


async def test_lo_que_no_sabe_lo_deriva_y_lo_registra_sin_decir_quien(cliente, auth):
    r = await cliente.post("/asistente/preguntar", headers=auth,
                           json={"texto": "¿Hay bus de la empresa los sábados?"})
    assert r.json()["derivar"] is True
    fila = (await obtener_todos("select * from asistente_consultas order by id desc limit 1"))[0]
    assert fila["respondida"] == 0 and "bus" in fila["texto"]
    assert set(fila) == {"id", "tema", "respondida", "texto", "region", "created_at"}


async def test_talento_humano_agrega_una_respuesta_y_el_asistente_la_usa(cliente, auth, rrhh_auth):
    r = await cliente.post("/admin/asistente/respuestas", headers=rrhh_auth, json={
        "titulo": "Transporte", "palabras_clave": "bus, transporte, recorrido",
        "respuesta": "El recorrido sale a las 6:30 desde el parque central.",
        "enlace_texto": "Ver lineamientos", "enlace_url": "dashboard.html"})
    assert r.status_code == 201, r.text
    r = await cliente.post("/asistente/preguntar", headers=auth,
                           json={"texto": "¿Hay bus de la empresa?"})
    assert "6:30" in r.json()["texto"]


async def test_el_enlace_no_puede_ser_javascript(cliente, rrhh_auth):
    r = await cliente.post("/admin/asistente/respuestas", headers=rrhh_auth, json={
        "titulo": "Malo", "palabras_clave": "x", "respuesta": "texto largo",
        "enlace_url": "javascript:alert(1)"})
    assert r.status_code == 422


async def test_un_colaborador_no_edita_el_asistente(cliente, auth):
    r = await cliente.get("/admin/asistente", headers=auth)
    assert r.status_code == 403


async def test_pendientes_y_quien_los_tiene(cliente, auth, jefe_auth, rrhh_auth):
    creada = await _crear(cliente, auth)
    await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=jefe_auth,
                       json={"accion": "aprobar"})
    r = await cliente.get("/rrhh/pendientes?sede=todas", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    mia = next(i for i in r.json()["items"] if i["tipo"] == "solicitud" and i["id"] == creada["id"])
    assert mia["atencion"] is None

    r = await cliente.post(f"/rrhh/pendientes/solicitud/{creada['id']}/tomar", headers=rrhh_auth)
    assert r.status_code == 200
    r = await cliente.get("/rrhh/pendientes?sede=todas", headers=rrhh_auth)
    mia = next(i for i in r.json()["items"] if i["id"] == creada["id"])
    assert mia["atencion"]["propio"] is True

    # El jefe (otra persona) no puede tomarlo sin forzar: no es de Talento Humano.
    r = await cliente.post(f"/rrhh/pendientes/solicitud/{creada['id']}/tomar", headers=jefe_auth)
    assert r.status_code == 403


async def test_filtrar_por_sede(cliente, rrhh_auth):
    for sede in ("mia", "sierra", "costa", "todas"):
        r = await cliente.get(f"/rrhh/pendientes?sede={sede}", headers=rrhh_auth)
        assert r.status_code == 200, (sede, r.text)
