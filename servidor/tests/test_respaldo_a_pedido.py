"""Permisos: justificación opcional, «días a descontar» solo cuando
descuenta, y el respaldo a pedido de Talento Humano.

Un permiso no lleva justificación obligatoria (el motivo va en la
descripción). Si Talento Humano necesita el certificado, lo pide desde el
sistema; la persona lo recibe por correo y lo adjunta desde «Mis
solicitudes», sin volver a pedir el permiso. Los respaldos son datos
sensibles: los ven la persona, su jefe en esa solicitud y Talento Humano.
"""
from __future__ import annotations

from datetime import timedelta

from app.db import obtener_uno
from tests.conftest import persona
from tests.test_reglas_nuevas import Sql
from tests.test_reglas_nuevas import (CEDULA_RRHH_R, auth, jefe_auth,  # noqa: F401
                                      lunes_sin_feriados, rrhh_auth)

PDF = b"%PDF-1.4\n% respaldo de prueba\n"


async def _permiso(cliente, auth, codigo="estudios", semanas=30, **extra):
    tipo = await obtener_uno("SELECT id FROM permission_types WHERE codigo = %s", (codigo,))
    dia = await lunes_sin_feriados(semanas)
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": tipo["id"], "fecha_inicio": str(dia),
        "fecha_fin": str(dia), "descripcion": "Examen final de la maestría en la PUCE", **extra})
    assert r.status_code == 201, r.text
    return r.json(), tipo["id"], dia


async def test_un_permiso_sin_justificacion_se_registra(cliente, auth):
    creada, _, _ = await _permiso(cliente, auth)
    fila = await obtener_uno("SELECT justificacion, estado FROM requests WHERE id = %s", (creada["id"],))
    assert fila["justificacion"] is None and fila["estado"] == "pendiente_jefe"


async def test_la_previsualizacion_no_descuenta_un_permiso(cliente, auth):
    tipo = await obtener_uno("SELECT id FROM permission_types WHERE codigo = 'estudios'")
    dia = await lunes_sin_feriados(31)
    p = (await cliente.post("/solicitudes/previsualizar", headers=auth, json={
        "tipo": "permiso", "fecha_inicio": str(dia), "fecha_fin": str(dia),
        "permission_type_id": tipo["id"]})).json()
    assert p["descuenta_vacaciones"] is False
    assert p["saldo_despues"] == p["saldo_actual"]
    assert p["requiere_justificacion"] is False
    assert not any("exige" in a for a in p["avisos"])

    # «Con cargo a vacaciones» sí descuenta, y lo dice.
    cargo = await obtener_uno("SELECT id FROM permission_types WHERE codigo = 'permiso_personal'")
    p = (await cliente.post("/solicitudes/previsualizar", headers=auth, json={
        "tipo": "permiso", "fecha_inicio": str(dia), "fecha_fin": str(dia),
        "permission_type_id": cargo["id"]})).json()
    assert p["descuenta_vacaciones"] is True
    assert float(p["saldo_despues"]) == float(p["saldo_actual"]) - float(p["dias"])


async def test_talento_humano_pide_el_respaldo_y_la_persona_lo_entrega(
        cliente, auth, jefe_auth, rrhh_auth):
    creada, _, _ = await _permiso(cliente, auth, semanas=32)
    sid = creada["id"]

    # El colaborador no puede pedirse respaldos a sí mismo.
    assert (await cliente.post(f"/aprobaciones/{sid}/pedir-respaldo", headers=auth,
                               json={"mensaje": "Adjunte el certificado"})).status_code == 403

    r = await cliente.post(f"/aprobaciones/{sid}/pedir-respaldo", headers=rrhh_auth,
                           json={"mensaje": "Adjunte la convocatoria al examen con la fecha."})
    assert r.status_code == 200, r.text
    fila = await obtener_uno(
        """SELECT respaldo_pedido_en, respaldo_pedido_mensaje, respaldo_entregado_en, estado
             FROM requests WHERE id = %s""", (sid,))
    assert fila["respaldo_pedido_en"] and fila["respaldo_entregado_en"] is None
    assert fila["estado"] == "pendiente_jefe"  # pedir el respaldo no cambia el estado
    assert await obtener_uno(
        """SELECT 1 AS x FROM notifications n JOIN requests r ON r.user_id = n.user_id
            WHERE r.id = %s AND n.tipo = 'documento_faltante' AND n.entidad_id = %s""", (sid, sid))

    # Lo ve en «Mis solicitudes».
    mia = next(s for s in (await cliente.get("/solicitudes/mias", headers=auth)).json() if s["id"] == sid)
    assert mia["respaldo_pedido_mensaje"].startswith("Adjunte la convocatoria")

    # Sube el archivo y lo entrega.
    subido = await cliente.post(f"/solicitudes/adjuntos?solicitud_id={sid}", headers=auth,
                                files={"archivo": ("convocatoria.pdf", PDF, "application/pdf")})
    assert subido.status_code == 200, subido.text
    r = await cliente.post(f"/solicitudes/{sid}/respaldo", headers=auth, json={"adjuntos": [subido.json()]})
    assert r.status_code == 200, r.text
    fila = await obtener_uno("SELECT respaldo_entregado_en, respaldo_pedido_por FROM requests WHERE id = %s",
                             (sid,))
    assert fila["respaldo_entregado_en"] is not None
    # Avisa a quien lo pidió.
    assert await obtener_uno(
        """SELECT 1 AS x FROM notifications WHERE user_id = %s AND entidad_id = %s
              AND titulo LIKE 'Respaldo entregado%%'""", (str(fila["respaldo_pedido_por"]), sid))

    # Talento Humano y el jefe lo ven; queda en la bitácora.
    lista = (await cliente.get(f"/solicitudes/{sid}/adjuntos", headers=rrhh_auth)).json()
    assert [a["nombre_archivo"] for a in lista] == ["convocatoria.pdf"]
    archivo = await cliente.get(f"/solicitudes/{sid}/adjuntos/{lista[0]['id']}", headers=rrhh_auth)
    assert archivo.status_code == 200 and archivo.content == PDF
    assert archivo.headers["x-integridad"] == "ok"
    assert await obtener_uno("SELECT 1 AS x FROM audit_logs WHERE accion = 'adjunto_visto' AND entidad_id = %s",
                             (lista[0]["id"],))
    assert (await cliente.get(f"/solicitudes/{sid}/adjuntos", headers=jefe_auth)).status_code == 200

    # En la bandeja y el seguimiento de Talento Humano consta la entrega.
    seg = (await cliente.get("/aprobaciones/seguimiento?sede=todas", headers=rrhh_auth)).json()
    s = next(x for x in seg["solicitudes"] if x["id"] == sid)
    assert s["adjuntos"] == 1 and s["respaldo_entregado_en"]


async def test_nadie_mas_ve_ni_entrega_respaldos_ajenos(cliente, auth, rrhh_auth, codigos):
    creada, _, _ = await _permiso(cliente, auth, semanas=33)
    sid = creada["id"]
    # Talento Humano no puede entregar a nombre de otro: la solicitud no es suya.
    falso = {"storage_path": f"x/{sid}/a.pdf", "nombre_archivo": "a.pdf", "mime_type": "application/pdf",
             "tamano_bytes": 10}
    assert (await cliente.post(f"/solicitudes/{sid}/respaldo", headers=rrhh_auth,
                               json={"adjuntos": [falso]})).status_code == 404
    # El dueño no puede colgar un archivo de otra ruta.
    yo = await obtener_uno("SELECT user_id FROM requests WHERE id = %s", (sid,))
    ajeno = {**falso, "storage_path": f"{yo['user_id']}/otra-solicitud/a.pdf"}
    assert (await cliente.post(f"/solicitudes/{sid}/respaldo", headers=auth,
                               json={"adjuntos": [ajeno]})).status_code == 422
    # Una persona sin relación con la solicitud no la ve.
    await persona("1200000006", nombre="API Otra Persona", email="otra.persona@api.test", rol="empleado",
                  fecha_ingreso=Sql("current_date() - interval 700 day"))
    await cliente.post("/auth/solicitar-token", json={"cedula": "1200000006"})
    r = await cliente.post("/auth/validar-token", json={"cedula": "1200000006", "codigo": codigos[-1]})
    otra = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await cliente.get(f"/solicitudes/{sid}/adjuntos", headers=otra)).status_code == 404


async def test_no_se_pide_respaldo_de_una_cancelada(cliente, auth, rrhh_auth):
    creada, _, _ = await _permiso(cliente, auth, semanas=34)
    await cliente.post(f"/solicitudes/{creada['id']}/cancelar", headers=auth, json={"motivo": None})
    r = await cliente.post(f"/aprobaciones/{creada['id']}/pedir-respaldo", headers=rrhh_auth,
                           json={"mensaje": "Adjunte el certificado del examen"})
    assert r.status_code == 409
