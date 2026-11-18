"""El asistente para quien gestiona: jefes, Talento Humano y administración.

Responde dónde está cada cosa y cuánto hay pendiente, según el perfil. Un
colaborador no recibe respuestas de gestión.
"""
from __future__ import annotations

import pytest

from app.reglas import asistente_gestion as gestion
from app.routers.asistente import normal
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R, auth, jefe_auth,  # noqa: F401
                                      rrhh_auth)


@pytest.mark.parametrize("pregunta, rol, esperado", [
    ("¿Qué tengo pendiente?", "rrhh", "pendientes"),
    ("¿Dónde apruebo las solicitudes?", "jefe", "pendientes"),
    ("Rechacé una solicitud por error", "jefe", "corregir_rechazo"),
    ("¿Dónde cambio un parámetro?", "rrhh", "parametros"),
    ("Registrar personas nuevas", "admin", "registrar_persona"),
    ("Dar de baja a alguien", "rrhh", "baja"),
    ("Exportar datos", "rrhh", "exportar"),
    ("¿Dónde cambio un parámetro?", "jefe", None),       # no es del jefe
    ("¿Qué tengo pendiente?", "empleado", None),          # ni del colaborador
])
def test_entiende_la_pregunta_segun_el_perfil(pregunta, rol, esperado):
    assert gestion.tema(normal(pregunta), rol)[0] == esperado


async def test_talento_humano_recibe_sus_pendientes_con_enlaces(cliente, rrhh_auth):
    inicio = (await cliente.get("/asistente/inicio", headers=rrhh_auth)).json()
    assert "¿Qué tengo pendiente?" in inicio["sugerencias"]
    r = (await cliente.post("/asistente/preguntar", headers=rrhh_auth,
                            json={"texto": "¿Qué tengo pendiente?"})).json()
    assert any(a["url"] == "administracion.html#pendientes" for a in r["acciones"])
    r = (await cliente.post("/asistente/preguntar", headers=rrhh_auth,
                            json={"texto": "¿Dónde cambio un parámetro?"})).json()
    assert "Bloque mínimo" in " ".join(r["detalles"])
    # Su propio saldo lo sigue respondiendo.
    r = (await cliente.post("/asistente/preguntar", headers=rrhh_auth,
                            json={"texto": "¿Cuántos días de vacaciones tengo?"})).json()
    assert "día(s) de vacaciones disponibles" in r["texto"]


async def test_el_jefe_ve_lo_suyo_y_como_corregir(cliente, jefe_auth):
    r = (await cliente.post("/asistente/preguntar", headers=jefe_auth,
                            json={"texto": "¿Qué tengo por aprobar?"})).json()
    assert "por aprobar" in r["texto"] and r["acciones"][0]["url"] == "dashboard.html#aprobaciones"
    r = (await cliente.post("/asistente/preguntar", headers=jefe_auth,
                            json={"texto": "Rechacé una solicitud por error"})).json()
    assert any("Corregir y aprobar" in d for d in r["detalles"])


async def test_el_colaborador_no_recibe_respuestas_de_gestion(cliente, auth):
    inicio = (await cliente.get("/asistente/inicio", headers=auth)).json()
    assert "¿Qué tengo pendiente?" not in inicio["sugerencias"]
    r = (await cliente.post("/asistente/preguntar", headers=auth,
                            json={"texto": "¿Dónde cambio un parámetro?"})).json()
    assert "Parámetros" not in r["texto"]


# ------------------------------------------------ seguimiento de una solicitud
async def test_seguimiento_de_una_solicitud_y_recordatorio_al_jefe(cliente, auth, jefe_auth, rrhh_auth):
    from datetime import timedelta
    from app.db import obtener_uno
    from tests.test_reglas_nuevas import lunes_sin_feriados
    lunes = await lunes_sin_feriados(12)
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Ocho dias con la familia", "firmar": False})
    assert r.status_code == 201, r.text
    folio, sid = r.json()["folio"], r.json()["id"]

    r = (await cliente.post("/asistente/preguntar", headers=rrhh_auth,
                            json={"texto": f"¿En qué va la solicitud Nº {folio}?"})).json()
    assert "espera la decisión del jefe" in r["texto"]
    assert any(d.startswith("Aviso al jefe en el sistema") for d in r["detalles"])
    assert any(a.get("accion") == "recordar" and a["id"] == sid for a in r["acciones"])

    # El jefe ve las de su equipo; el colaborador no recibe seguimiento ajeno.
    r = (await cliente.post("/asistente/preguntar", headers=jefe_auth,
                            json={"texto": f"solicitud {folio}"})).json()
    assert "espera la decisión del jefe" in r["texto"]
    r = (await cliente.post("/asistente/preguntar", headers=rrhh_auth,
                            json={"texto": "¿Qué solicitudes esperan al jefe?"})).json()
    assert any(f"Nº {folio}" in d for d in r["detalles"])

    assert (await cliente.post(f"/aprobaciones/{sid}/recordar-al-jefe", headers=auth)).status_code == 403
    r = await cliente.post(f"/aprobaciones/{sid}/recordar-al-jefe", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    assert (await cliente.post(f"/aprobaciones/{sid}/recordar-al-jefe", headers=rrhh_auth)).status_code == 429
    assert await obtener_uno(
        "SELECT 1 AS x FROM notifications WHERE entidad_id = %s AND titulo LIKE %s", (sid, "Recordatorio%"))

    # Después de que el jefe decide, el seguimiento lo cuenta.
    await cliente.post(f"/aprobaciones/{sid}/decidir", headers=jefe_auth,
                       json={"accion": "rechazar", "motivo": "Fechas de cierre de mes"})
    r = (await cliente.post("/asistente/preguntar", headers=rrhh_auth,
                            json={"texto": f"Nº {folio}"})).json()
    assert "rechazada" in r["texto"]
    assert any("Fechas de cierre de mes" in d for d in r["detalles"])
    assert any("Recordatorio al jefe" in d for d in r["detalles"])


async def test_sin_numero_explica_como_preguntar(cliente, rrhh_auth):
    r = (await cliente.post("/asistente/preguntar", headers=rrhh_auth,
                            json={"texto": "¿En qué va la solicitud Nº …?"})).json()
    assert "número" in r["texto"]


# ------------------------------------------------------- consulta por cédula
async def test_talento_humano_consulta_por_cedula(cliente, auth, jefe_auth, rrhh_auth, empleado):
    from datetime import timedelta
    from app.db import ejecutar, obtener_uno
    from tests.test_reglas_nuevas import lunes_sin_feriados
    lunes = await lunes_sin_feriados(16)
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Ocho dias con la familia", "firmar": False})
    folio = r.json()["folio"]

    r = (await cliente.post("/asistente/preguntar", headers=rrhh_auth,
                            json={"texto": f"estado de {empleado['cedula']}"})).json()
    texto = " ".join(r["detalles"])
    assert f"Nº {folio}" in texto and "espera la decisión del jefe" in texto
    assert "Saldo de vacaciones" in texto and "Jefe:" in texto
    assert any(a["url"].startswith("persona.html?id=") for a in r["acciones"])
    assert await obtener_uno(
        "SELECT 1 AS x FROM audit_logs WHERE accion = 'asistente_consulta_persona' AND entidad_id = %s",
        (str(empleado["id"]),)), "la consulta queda en la bitácora"

    # Sin el cero inicial también la encuentra.
    if empleado["cedula"].startswith("0"):
        r = (await cliente.post("/asistente/preguntar", headers=rrhh_auth,
                                json={"texto": empleado["cedula"][1:]})).json()
        assert "No hay nadie" not in r["texto"]

    # El jefe consulta a su equipo, no a otros.
    r = (await cliente.post("/asistente/preguntar", headers=jefe_auth,
                            json={"texto": empleado["cedula"]})).json()
    assert "no es de su equipo" not in r["texto"]
    r = (await cliente.post("/asistente/preguntar", headers=jefe_auth,
                            json={"texto": CEDULA_RRHH_R})).json()
    assert "no es de su equipo" in r["texto"]

    # El colaborador no consulta a nadie por cédula.
    r = (await cliente.post("/asistente/preguntar", headers=auth, json={"texto": CEDULA_RRHH_R})).json()
    assert "Saldo de vacaciones" not in " ".join(r["detalles"])

    r = (await cliente.post("/asistente/preguntar", headers=rrhh_auth, json={"texto": "1799999999"})).json()
    assert "No hay nadie registrado" in r["texto"]
    r = (await cliente.post("/asistente/preguntar", headers=rrhh_auth,
                            json={"texto": "Consultar por cédula"})).json()
    assert "Escríbame la cédula" in r["texto"]
