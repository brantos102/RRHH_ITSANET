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
