"""Talento Humano ve la gestión completa de solicitudes y la mueve.

No solo lo que le toca decidir: todas las vacaciones y permisos en trámite
(esperen al jefe, a Talento Humano o una anulación) y lo decidido hace poco,
con quién la tiene y desde cuándo. Puede recordarla a quien la tiene y
reasignar la decisión del jefe a otra persona.
"""
from __future__ import annotations

from datetime import timedelta

from app.db import obtener_uno
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R, auth, jefe_auth,  # noqa: F401
                                      lunes_sin_feriados, rrhh_auth)


async def _crear(cliente, auth, semanas):
    lunes = await lunes_sin_feriados(semanas)
    vac = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Ocho dias con la familia", "firmar": False})
    assert vac.status_code == 201, vac.text
    tipo = await obtener_uno("SELECT id FROM permission_types WHERE codigo = 'tramite_gobierno'")
    dia = lunes + timedelta(days=14)
    per = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": tipo["id"], "fecha_inicio": str(dia), "fecha_fin": str(dia),
        "descripcion": "Renovación de la cédula en el Registro Civil",
        "justificacion": "Turno asignado a las 09:00 en el Registro Civil", "firmar": False})
    assert per.status_code == 201, per.text
    return vac.json(), per.json()


async def test_talento_humano_ve_todas_y_las_mueve(cliente, auth, jefe_auth, rrhh_auth, monkeypatch):
    vac, per = await _crear(cliente, auth, 20)
    assert (await cliente.get("/aprobaciones/seguimiento", headers=auth)).status_code == 403

    d = (await cliente.get("/aprobaciones/seguimiento?sede=todas", headers=rrhh_auth)).json()
    por_id = {s["id"]: s for s in d["solicitudes"]}
    assert por_id[vac["id"]]["tipo"] == "vacacion" and por_id[per["id"]]["tipo"] == "permiso"
    assert por_id[vac["id"]]["estado"] == "pendiente_jefe"
    assert por_id[vac["id"]]["quien"] == "API Jefatura"
    assert por_id[per["id"]]["categoria"]

    # Recordar al jefe, una vez por hora.
    r = await cliente.post(f"/aprobaciones/{vac['id']}/recordar", headers=rrhh_auth)
    assert r.status_code == 200 and "API Jefatura" in r.json()["mensaje"]
    assert (await cliente.post(f"/aprobaciones/{vac['id']}/recordar", headers=rrhh_auth)).status_code == 429

    # Reasignar el permiso a Talento Humano: el enlace viejo deja de servir.
    rrhh = await obtener_uno("SELECT id FROM users WHERE cedula = %s", (CEDULA_RRHH_R,))
    token_viejo = (await obtener_uno("SELECT jefe_token FROM requests WHERE id = %s", (per["id"],)))["jefe_token"]
    r = await cliente.post(f"/aprobaciones/{per['id']}/reasignar", headers=rrhh_auth,
                           json={"aprobador_id": str(rrhh["id"]), "motivo": "El jefe está de vacaciones"})
    assert r.status_code == 200, r.text
    fila = await obtener_uno("SELECT jefe_id, jefe_token FROM requests WHERE id = %s", (per["id"],))
    assert str(fila["jefe_id"]) == str(rrhh["id"]) and fila["jefe_token"] != token_viejo
    assert await obtener_uno(
        "SELECT 1 AS x FROM audit_logs WHERE accion = 'aprobador_reasignado' AND entidad_id = %s", (per["id"],))
    # El jefe original ya no la tiene; la nueva persona sí.
    assert not any(s["id"] == per["id"] for s in (await cliente.get("/aprobaciones/pendientes",
                                                                    headers=jefe_auth)).json())
    assert any(s["id"] == per["id"] for s in (await cliente.get("/aprobaciones/pendientes",
                                                               headers=rrhh_auth)).json())

    # Cuando la vacación pasa a Talento Humano, el recordatorio va a Talento Humano.
    await cliente.post(f"/aprobaciones/{vac['id']}/decidir", headers=jefe_auth, json={"accion": "aprobar"})
    # (la bitácora no se borra: se simula que pasó la hora)
    from app.routers import aprobaciones

    async def _nunca(_):
        return False
    monkeypatch.setattr(aprobaciones, "_ya_recordada", _nunca)
    r = await cliente.post(f"/aprobaciones/{vac['id']}/recordar", headers=rrhh_auth)
    assert r.status_code == 200 and "Talento Humano" in r.json()["mensaje"]

    # Decidida: sigue en el listado (últimos 30 días) y ya no se recuerda.
    await cliente.post(f"/aprobaciones/{vac['id']}/decidir", headers=rrhh_auth, json={"accion": "aprobar"})
    d = (await cliente.get("/aprobaciones/seguimiento?sede=todas", headers=rrhh_auth)).json()
    assert next(s for s in d["solicitudes"] if s["id"] == vac["id"])["estado"] == "aprobado"
    assert (await cliente.post(f"/aprobaciones/{vac['id']}/recordar", headers=rrhh_auth)).status_code == 409


async def test_no_se_reasigna_a_quien_no_aprueba(cliente, auth, rrhh_auth, empleado):
    vac, _ = await _crear(cliente, auth, 26)
    r = await cliente.post(f"/aprobaciones/{vac['id']}/reasignar", headers=rrhh_auth,
                           json={"aprobador_id": str(empleado["id"]), "motivo": "Prueba de reasignación"})
    assert r.status_code == 422
    lista = (await cliente.get("/aprobaciones/aprobadores", headers=rrhh_auth)).json()
    assert lista and all(a["rol"] in ("jefe", "rrhh", "admin") for a in lista)
