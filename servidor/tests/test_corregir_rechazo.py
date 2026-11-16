"""Corregir un rechazo hecho por error.

Quien rechazó (o Talento Humano) puede corregir la decisión: la solicitud
vuelve a la etapa en que se rechazó y se aprueba en el mismo paso, con un
motivo que queda en la bitácora. La base no deja hacerlo con un UPDATE
suelto: solo por esta vía.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.db import ejecutar, obtener_uno
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R, auth, jefe_auth,  # noqa: F401
                                      lunes_sin_feriados, rrhh_auth)


async def _vacacion(cliente, auth, semanas=10):
    lunes = await lunes_sin_feriados(semanas)
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Ocho dias con la familia", "firmar": False})
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_el_jefe_corrige_su_rechazo_y_pasa_a_talento_humano(cliente, auth, jefe_auth, rrhh_auth):
    sid = await _vacacion(cliente, auth)
    r = await cliente.post(f"/aprobaciones/{sid}/decidir", headers=jefe_auth,
                           json={"accion": "rechazar", "motivo": "Me equivoqué de persona"})
    assert r.status_code == 200, r.text

    lista = (await cliente.get("/aprobaciones/rechazadas", headers=jefe_auth)).json()
    assert any(x["id"] == sid and x["rechazado_en_etapa"] == "jefe" for x in lista)
    assert (await cliente.get("/aprobaciones/rechazadas", headers=auth)).json() == []

    # El propio solicitante no puede; un motivo corto, tampoco.
    r = await cliente.post(f"/aprobaciones/{sid}/corregir-rechazo", headers=auth,
                           json={"motivo": "Quiero mis vacaciones"})
    assert r.status_code == 403
    r = await cliente.post(f"/aprobaciones/{sid}/corregir-rechazo", headers=jefe_auth, json={"motivo": "error"})
    assert r.status_code == 422

    r = await cliente.post(f"/aprobaciones/{sid}/corregir-rechazo", headers=jefe_auth,
                           json={"motivo": "Rechacé la solicitud equivocada"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "pendiente_rrhh"
    fila = await obtener_uno("SELECT motivo_rechazo, rechazado_en, jefe_aprobado_por FROM requests WHERE id = %s",
                             (sid,))
    assert fila["motivo_rechazo"] is None and fila["rechazado_en"] is None and fila["jefe_aprobado_por"]
    assert await obtener_uno(
        "SELECT 1 AS x FROM audit_logs WHERE accion = 'rechazo_corregido' AND entidad_id = %s", (sid,))
    aviso = await obtener_uno(
        "SELECT titulo FROM notifications WHERE entidad_id = %s AND titulo LIKE %s", (sid, "Se corrigió%"))
    assert aviso, "el colaborador se entera de que ya no está rechazada"

    # Sigue la ruta normal: Talento Humano aprueba.
    r = await cliente.post(f"/aprobaciones/{sid}/decidir", headers=rrhh_auth, json={"accion": "aprobar"})
    assert r.status_code == 200 and r.json()["estado"] == "aprobado"
    # Una vez corregida, no se corrige otra vez.
    r = await cliente.post(f"/aprobaciones/{sid}/corregir-rechazo", headers=rrhh_auth,
                           json={"motivo": "Rechacé la solicitud equivocada"})
    assert r.status_code == 409


async def test_talento_humano_corrige_y_queda_aprobada(cliente, auth, jefe_auth, rrhh_auth):
    sid = await _vacacion(cliente, auth, semanas=14)
    assert (await cliente.post(f"/aprobaciones/{sid}/decidir", headers=jefe_auth,
                               json={"accion": "aprobar"})).status_code == 200
    assert (await cliente.post(f"/aprobaciones/{sid}/decidir", headers=rrhh_auth,
                               json={"accion": "rechazar", "motivo": "Falta el reemplazo"})).status_code == 200
    contar = """SELECT COUNT(*) AS n FROM notifications WHERE entidad_id = %s AND titulo LIKE %s"""
    avisos_antes = (await obtener_uno(contar, (sid, "%aprobada por el jefe%")))["n"]
    saldo_antes = (await obtener_uno("SELECT u.dias_vacaciones AS s FROM requests r JOIN users u ON u.id = r.user_id "
                                     "WHERE r.id = %s", (sid,)))["s"]
    r = await cliente.post(f"/aprobaciones/{sid}/corregir-rechazo", headers=rrhh_auth,
                           json={"motivo": "El reemplazo sí estaba asignado"})
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "aprobado"
    fila = await obtener_uno("SELECT r.qr_hash, u.dias_vacaciones AS s FROM requests r JOIN users u ON u.id = r.user_id "
                             "WHERE r.id = %s", (sid,))
    assert fila["qr_hash"], "se emite el QR como en cualquier aprobación"
    assert fila["s"] < saldo_antes, "se descuentan los días"
    # No sale el aviso falso de «aprobada por el jefe» al volver de un rechazo.
    avisos_despues = (await obtener_uno(contar, (sid, "%aprobada por el jefe%")))["n"]
    assert avisos_despues == avisos_antes, "la corrección no genera avisos de aprobación del jefe"


async def test_la_base_no_deja_deshacer_un_rechazo_a_mano(cliente, auth, jefe_auth):
    sid = await _vacacion(cliente, auth, semanas=18)
    await cliente.post(f"/aprobaciones/{sid}/decidir", headers=jefe_auth,
                       json={"accion": "rechazar", "motivo": "No corresponde"})
    with pytest.raises(Exception, match="Transición de estado inválida"):
        await ejecutar("UPDATE requests SET estado = 'pendiente_jefe' WHERE id = %s", (sid,))
