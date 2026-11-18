"""Eliminar una solicitud con justificación, quitar un adjunto equivocado
y enviar una solicitud a un jefe alterno cuando el directo no puede."""
from __future__ import annotations

from datetime import timedelta

from app.db import ejecutar, obtener_uno
from tests.conftest import Sql, persona
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R, _aprobada, auth,  # noqa: F401
                                      jefe_auth, lunes_sin_feriados, rrhh_auth)
from tests.test_respaldo_a_pedido import PDF, _permiso

CEDULA_ALTERNO = "1200000006"


# ----------------------------------------------------------------- eliminar
async def test_el_colaborador_elimina_una_pendiente_con_motivo(cliente, auth, jefe_auth):
    creada, _, _ = await _permiso(cliente, auth, semanas=36)
    sid = creada["id"]
    assert (await cliente.post(f"/solicitudes/{sid}/eliminar", headers=auth,
                               json={"motivo": "corto"})).status_code == 422
    r = await cliente.post(f"/solicitudes/{sid}/eliminar", headers=auth,
                           json={"motivo": "La registré con la fecha equivocada."})
    assert r.status_code == 200, r.text
    fila = await obtener_uno("SELECT estado, eliminada_en, eliminacion_motivo FROM requests WHERE id = %s", (sid,))
    assert fila["estado"] == "cancelado" and fila["eliminada_en"] and fila["eliminacion_motivo"].startswith("La registré")
    # Ya no aparece en sus listas ni en la bandeja del jefe; el jefe recibe el aviso.
    assert not any(s["id"] == sid for s in (await cliente.get("/solicitudes/mias", headers=auth)).json())
    assert not any(s["id"] == sid for s in (await cliente.get("/aprobaciones/pendientes", headers=jefe_auth)).json())
    assert await obtener_uno("SELECT 1 AS x FROM notifications WHERE entidad_id = %s AND titulo LIKE '%%eliminada'", (sid,))
    assert await obtener_uno("SELECT 1 AS x FROM audit_logs WHERE accion = 'solicitud_eliminada' AND entidad_id = %s",
                             (sid,))
    # Dos veces, no.
    assert (await cliente.post(f"/solicitudes/{sid}/eliminar", headers=auth,
                               json={"motivo": "Otra vez por si acaso."})).status_code == 409


async def test_una_aprobada_la_elimina_talento_humano_y_devuelve_los_dias(cliente, auth, jefe_auth, rrhh_auth):
    aprobada = await _aprobada(cliente, auth, jefe_auth, rrhh_auth)
    sid = aprobada["id"]
    yo = await obtener_uno("SELECT u.id, u.dias_vacaciones FROM users u JOIN requests r ON r.user_id = u.id "
                           "WHERE r.id = %s", (sid,))
    # El colaborador no: una aprobada se anula por Talento Humano.
    r = await cliente.post(f"/solicitudes/{sid}/eliminar", headers=auth, json={"motivo": "Ya no voy a viajar."})
    assert r.status_code == 409 and "anulación" in r.json()["detail"]["mensaje"]

    r = await cliente.post(f"/solicitudes/{sid}/eliminar", headers=rrhh_auth,
                           json={"motivo": "Se registró dos veces por error del sistema anterior."})
    assert r.status_code == 200, r.text
    assert "devolvieron" in r.json()["mensaje"]
    fila = await obtener_uno("SELECT estado, eliminada_por, anulacion_resuelta_por FROM requests WHERE id = %s", (sid,))
    assert fila["estado"] == "cancelado" and fila["anulacion_resuelta_por"] == fila["eliminada_por"]
    despues = await obtener_uno("SELECT dias_vacaciones FROM users WHERE id = %s", (yo["id"],))
    assert float(despues["dias_vacaciones"]) > float(yo["dias_vacaciones"])
    # La persona recibe el aviso con el motivo.
    assert await obtener_uno(
        "SELECT 1 AS x FROM notifications WHERE user_id = %s AND entidad_id = %s AND mensaje LIKE 'Motivo:%%'",
        (yo["id"], sid))


async def test_nadie_ajeno_elimina(cliente, auth, jefe_auth):
    creada, _, _ = await _permiso(cliente, auth, semanas=37)
    # El jefe (no es Talento Humano ni el dueño) no la elimina.
    r = await cliente.post(f"/solicitudes/{creada['id']}/eliminar", headers=jefe_auth,
                           json={"motivo": "No me corresponde eliminarla."})
    assert r.status_code == 404


# ----------------------------------------------------------- quitar adjunto
async def test_quitar_un_adjunto_equivocado(cliente, auth, rrhh_auth):
    creada, _, _ = await _permiso(cliente, auth, semanas=38)
    sid = creada["id"]
    await cliente.post(f"/aprobaciones/{sid}/pedir-respaldo", headers=rrhh_auth,
                       json={"mensaje": "Adjunte el certificado de la institución."})
    subido = (await cliente.post(f"/solicitudes/adjuntos?solicitud_id={sid}", headers=auth,
                                 files={"archivo": ("otro.pdf", PDF, "application/pdf")})).json()
    await cliente.post(f"/solicitudes/{sid}/respaldo", headers=auth, json={"adjuntos": [subido]})
    adj = (await cliente.get(f"/solicitudes/{sid}/adjuntos", headers=auth)).json()[0]

    r = await cliente.post(f"/solicitudes/{sid}/adjuntos/{adj['id']}/quitar", headers=auth,
                           json={"motivo": "Subí el documento de otra persona"})
    assert r.status_code == 200, r.text
    assert r.json()["quedan"] == 0
    assert (await cliente.get(f"/solicitudes/{sid}/adjuntos", headers=auth)).json() == []
    # El pedido de Talento Humano vuelve a quedar abierto, y la bitácora guarda la huella.
    assert (await obtener_uno("SELECT respaldo_entregado_en FROM requests WHERE id = %s", (sid,)))[
        "respaldo_entregado_en"] is None
    rastro = await obtener_uno("SELECT detalle FROM audit_logs WHERE accion = 'adjunto_quitado' AND entidad_id = %s",
                               (adj["id"],))
    assert rastro and "otro.pdf" in str(rastro["detalle"]) and subido["hash_sha256"] in str(rastro["detalle"])
    # El archivo ya no se puede abrir.
    assert (await cliente.get(f"/solicitudes/{sid}/adjuntos/{adj['id']}", headers=rrhh_auth)).status_code == 404


async def test_talento_humano_quita_y_un_jefe_no(cliente, auth, jefe_auth, rrhh_auth):
    creada, _, _ = await _permiso(cliente, auth, semanas=39)
    sid = creada["id"]
    subido = (await cliente.post(f"/solicitudes/adjuntos?solicitud_id={sid}", headers=auth,
                                 files={"archivo": ("a.pdf", PDF, "application/pdf")})).json()
    await cliente.post(f"/solicitudes/{sid}/respaldo", headers=auth, json={"adjuntos": [subido]})
    adj = (await cliente.get(f"/solicitudes/{sid}/adjuntos", headers=auth)).json()[0]
    assert (await cliente.post(f"/solicitudes/{sid}/adjuntos/{adj['id']}/quitar", headers=jefe_auth,
                               json={"motivo": "No es el respaldo"})).status_code == 404
    assert (await cliente.post(f"/solicitudes/{sid}/adjuntos/{adj['id']}/quitar", headers=rrhh_auth,
                               json={"motivo": "No es el respaldo"})).status_code == 200


# ------------------------------------------------------------- jefe alterno
async def _alterno(email="alterno@api.test"):
    return await persona(CEDULA_ALTERNO, nombre="API Jefe Alterno", email=email, rol="jefe",
                         departamento="Operaciones", fecha_ingreso=Sql("current_date() - interval 900 day"))


async def test_jefe_sin_correo_permite_elegir_un_alterno(cliente, auth, jefe_auth):
    await ejecutar("UPDATE users SET email = NULL WHERE cedula = %s", (CEDULA_JEFE_R,))
    alterno = await _alterno()
    creada, _, _ = await _permiso(cliente, auth, semanas=40)
    sid = creada["id"]
    # La respuesta al crearla ya lo dice.
    assert "no tiene correo" in creada["mensaje"] and creada["jefe_no_disponible"]["motivo"] == "sin_correo"

    op = (await cliente.get(f"/solicitudes/{sid}/jefe-alterno", headers=auth)).json()
    assert op["motivo"]["motivo"] == "sin_correo"
    ids = [c["id"] for c in op["candidatos"]]
    assert str(alterno["id"]) in ids
    jefe = await obtener_uno("SELECT id FROM users WHERE cedula = %s", (CEDULA_JEFE_R,))
    assert str(jefe["id"]) not in ids  # el propio jefe no es alterno de sí mismo

    r = await cliente.post(f"/solicitudes/{sid}/jefe-alterno", headers=auth, json={"aprobador_id": str(alterno["id"])})
    assert r.status_code == 200, r.text
    fila = await obtener_uno("SELECT jefe_id, jefe_original_id, jefe_alterno_motivo FROM requests WHERE id = %s", (sid,))
    assert str(fila["jefe_id"]) == str(alterno["id"]) and str(fila["jefe_original_id"]) == str(jefe["id"])
    # La ficha NO cambia: el jefe directo sigue siendo el mismo.
    yo = await obtener_uno("SELECT jefe_id FROM users WHERE cedula = '1700000001'")
    assert str(yo["jefe_id"]) == str(jefe["id"])
    # El alterno recibe el aviso; el jefe directo, la constancia.
    assert await obtener_uno("SELECT 1 AS x FROM notifications WHERE user_id = %s AND entidad_id = %s "
                             "AND tipo = 'solicitud_pendiente'", (str(alterno["id"]), sid))
    mia = next(s for s in (await cliente.get("/solicitudes/mias", headers=auth)).json() if s["id"] == sid)
    assert mia["jefe_original"] == "API Jefatura" and mia["jefe_no_disponible"] is None


async def test_jefe_de_vacaciones_hoy_permite_alterno(cliente, auth, jefe_auth):
    jefe = await obtener_uno("SELECT id FROM users WHERE cedula = %s", (CEDULA_JEFE_R,))
    await ejecutar(
        """INSERT INTO requests (id, user_id, tipo, fecha_inicio, fecha_fin, descripcion,
                                 dias_solicitados, saldo_al_solicitar, estado)
           VALUES (UUID(), %s, 'vacacion', CURRENT_DATE() - INTERVAL 1 DAY, CURRENT_DATE() + INTERVAL 5 DAY,
                   'Vacaciones del jefe', 7, 15, 'aprobado')""", (str(jefe["id"]),))
    alterno = await _alterno()
    creada, _, _ = await _permiso(cliente, auth, semanas=41)
    assert creada["jefe_no_disponible"]["motivo"] == "ausente"
    r = await cliente.post(f"/solicitudes/{creada['id']}/jefe-alterno", headers=auth,
                           json={"aprobador_id": str(alterno["id"])})
    assert r.status_code == 200, r.text


async def test_con_el_jefe_disponible_no_se_cambia(cliente, auth, jefe_auth):
    alterno = await _alterno()
    creada, _, _ = await _permiso(cliente, auth, semanas=42)
    assert creada["jefe_no_disponible"] is None
    r = await cliente.post(f"/solicitudes/{creada['id']}/jefe-alterno", headers=auth,
                           json={"aprobador_id": str(alterno["id"])})
    assert r.status_code == 409


async def test_el_alterno_decide_como_jefe(cliente, auth, jefe_auth, codigos):
    await ejecutar("UPDATE users SET email = NULL WHERE cedula = %s", (CEDULA_JEFE_R,))
    alterno = await _alterno()
    creada, _, _ = await _permiso(cliente, auth, semanas=43)
    await cliente.post(f"/solicitudes/{creada['id']}/jefe-alterno", headers=auth,
                       json={"aprobador_id": str(alterno["id"])})
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_ALTERNO})
    r = await cliente.post("/auth/validar-token", json={"cedula": CEDULA_ALTERNO, "codigo": codigos[-1]})
    alt = {"Authorization": f"Bearer {r.json()['access_token']}"}
    pend = (await cliente.get("/aprobaciones/pendientes", headers=alt)).json()
    tarjeta = next(s for s in pend if s["id"] == creada["id"])
    assert tarjeta["jefe_original"] == "API Jefatura"
    r = await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=alt, json={"accion": "aprobar"})
    assert r.status_code == 200, r.text
    assert (await obtener_uno("SELECT estado FROM requests WHERE id = %s", (creada["id"],)))["estado"] == "pendiente_rrhh"
