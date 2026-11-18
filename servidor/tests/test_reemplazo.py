"""Quién cubre el puesto: lo elige el jefe; Talento Humano confirma o, si no hay
nadie, asigna y el jefe lo confirma o lo cambia."""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_uno
from tests.conftest import Sql, persona
from tests.test_folio_calendario import _crear, auth, companero, jefe_auth  # noqa: F401

CEDULA_OTRO = "1200000006"
# Talento Humano propio: los ayudantes de otros módulos usan para Talento
# Humano la misma cédula que para el jefe, y aquí tienen que ser dos personas.
CEDULA_TH = "1700000100"


@pytest.fixture
async def rrhh_auth(cliente, codigos, empleado):
    await persona(CEDULA_TH, al_existir={"rol": "rrhh"}, nombre="API Talento Reemplazo",
                  email="threemplazo@api.test", rol="rrhh",
                  fecha_ingreso=Sql("current_date() - interval 2000 day"))
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_TH})
    r = await cliente.post("/auth/validar-token", json={"cedula": CEDULA_TH, "codigo": codigos[-1]})
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}
    await ejecutar("update requests set rrhh_aprobado_por = null, reemplazo_confirmado_por = null "
                   "where rrhh_aprobado_por = (select id from users where cedula = %s) "
                   "or reemplazo_confirmado_por = (select id from users where cedula = %s)",
                   (CEDULA_TH, CEDULA_TH))
    await ejecutar("delete from users where cedula = %s", (CEDULA_TH,))


@pytest.fixture
def correos(monkeypatch) -> list[dict]:
    from app import correo
    enviados: list[dict] = []

    async def falso(destino, asunto, texto, html=None, **_):
        enviados.append({"para": destino, "asunto": asunto})

    monkeypatch.setattr(correo, "enviar", falso)
    return enviados


@pytest.fixture
async def otro(empleado):
    """Otro compañero del mismo departamento."""
    fila = await persona(CEDULA_OTRO, nombre="API Otro Compañero", email="otro@api.test",
                         rol="empleado", departamento="Operaciones",
                         fecha_ingreso=Sql("current_date() - interval 700 day"))
    return str(fila["id"])


async def _reemplazo(id_):
    return await obtener_uno(
        """select reemplazo_id, reemplazo_asignado_por, reemplazo_confirmado_en
             from requests where id = %s""", (id_,))


async def test_el_jefe_elige_y_queda_confirmado(cliente, auth, companero, jefe_auth):
    creada = await _crear(cliente, auth)
    r = await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=jefe_auth,
                           json={"accion": "aprobar", "reemplazo_id": companero})
    assert r.status_code == 200, r.text
    fila = await _reemplazo(creada["id"])
    assert fila["reemplazo_asignado_por"] == "jefe" and fila["reemplazo_confirmado_en"] is not None


async def test_talento_humano_no_cambia_lo_que_eligio_el_jefe(
        cliente, auth, companero, jefe_auth, rrhh_auth, otro):
    creada = await _crear(cliente, auth)
    await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=jefe_auth,
                       json={"accion": "aprobar", "reemplazo_id": companero})
    r = await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=rrhh_auth,
                           json={"accion": "aprobar", "reemplazo_id": otro})
    assert r.status_code == 409
    assert "jefe inmediato" in r.json()["detail"]["mensaje"]
    assert str((await _reemplazo(creada["id"]))["reemplazo_id"]) == companero

    # Confirmarlo —aprobar sin tocarlo— sí se puede.
    r = await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=rrhh_auth,
                           json={"accion": "aprobar"})
    assert r.status_code == 200, r.text
    assert str((await _reemplazo(creada["id"]))["reemplazo_id"]) == companero


async def test_si_nadie_eligio_talento_humano_asigna_y_se_avisa_al_jefe(
        cliente, auth, companero, jefe_auth, rrhh_auth, correos):
    creada = await _crear(cliente, auth)
    await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=jefe_auth,
                       json={"accion": "aprobar"})
    r = await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=rrhh_auth,
                           json={"accion": "aprobar", "reemplazo_id": companero})
    assert r.status_code == 200, r.text

    fila = await _reemplazo(creada["id"])
    assert fila["reemplazo_asignado_por"] == "rrhh"
    assert fila["reemplazo_confirmado_en"] is None, "queda pendiente de que el jefe lo confirme"
    assert any(c["para"] == "jefatura@api.test" and "Confirme el reemplazo" in c["asunto"]
               for c in correos)

    pendientes = (await cliente.get("/aprobaciones/reemplazos-por-confirmar", headers=jefe_auth)).json()
    assert [p["id"] for p in pendientes] == [creada["id"]]


async def test_el_jefe_confirma_el_reemplazo_asignado(cliente, auth, companero, jefe_auth, rrhh_auth):
    creada = await _crear(cliente, auth)
    await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=jefe_auth, json={"accion": "aprobar"})
    await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=rrhh_auth,
                       json={"accion": "aprobar", "reemplazo_id": companero})
    r = await cliente.post(f"/aprobaciones/{creada['id']}/reemplazo", headers=jefe_auth,
                           json={"accion": "confirmar"})
    assert r.status_code == 200, r.text
    assert (await _reemplazo(creada["id"]))["reemplazo_confirmado_en"] is not None
    assert (await cliente.get("/aprobaciones/reemplazos-por-confirmar", headers=jefe_auth)).json() == []


async def test_el_jefe_cambia_el_reemplazo_y_se_avisa_a_talento_humano(
        cliente, auth, companero, jefe_auth, rrhh_auth, otro, correos):
    creada = await _crear(cliente, auth)
    await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=jefe_auth, json={"accion": "aprobar"})
    await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=rrhh_auth,
                       json={"accion": "aprobar", "reemplazo_id": companero})
    r = await cliente.post(f"/aprobaciones/{creada['id']}/reemplazo", headers=jefe_auth,
                           json={"accion": "cambiar", "reemplazo_id": otro})
    assert r.status_code == 200, r.text
    fila = await _reemplazo(creada["id"])
    assert str(fila["reemplazo_id"]) == otro and fila["reemplazo_asignado_por"] == "jefe"
    assert any(c["para"] == "threemplazo@api.test" and "cambió el reemplazo" in c["asunto"] for c in correos)


async def test_solo_el_jefe_confirma(cliente, auth, companero, jefe_auth, rrhh_auth):
    creada = await _crear(cliente, auth)
    await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=jefe_auth, json={"accion": "aprobar"})
    await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=rrhh_auth,
                       json={"accion": "aprobar", "reemplazo_id": companero})
    r = await cliente.post(f"/aprobaciones/{creada['id']}/reemplazo", headers=auth,
                           json={"accion": "confirmar"})
    assert r.status_code == 403


async def test_sin_jefe_lo_que_asigna_talento_humano_queda_confirmado(
        cliente, auth, empleado, companero, rrhh_auth):
    """No hay a quién pedirle confirmación: queda confirmado por quien decide."""
    await ejecutar("update users set jefe_id = null where id = %s", (empleado["id"],))
    creada = await _crear(cliente, auth)
    for _ in range(2):   # decide la etapa de jefatura y la suya
        r = await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=rrhh_auth,
                               json={"accion": "aprobar", "reemplazo_id": companero})
        assert r.status_code == 200, r.text
    fila = await _reemplazo(creada["id"])
    assert fila["reemplazo_asignado_por"] == "rrhh" and fila["reemplazo_confirmado_en"] is not None
