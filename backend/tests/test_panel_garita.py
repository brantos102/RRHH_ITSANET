"""El panel del día en la garita.

La garita ya sabía validar un código y registrar la salida y el regreso. Lo
que faltaba era la vista de conjunto: el guardia tenía la lista de quién
tiene permiso hoy, pero no de en qué punto va cada uno.

La pregunta que se hace un guardia a las cuatro de la tarde no es «¿quién
tiene permiso?» sino «¿quién está fuera y ya debería haber vuelto?», y eso
no se responde mirando una lista de autorizaciones.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, rrhh_auth)
from tests.test_retorno import guardia_auth, _permiso_por_horas_aprobado  # noqa: F401


async def _situacion(request_id) -> dict:
    return await obtener_uno(
        """select situacion, debe_volver_hoy, minutos_de_atraso, se_espera_a_las
             from public.v_garita_hoy where request_id = %s""", (request_id,))


async def test_sin_salir_mientras_no_use_el_codigo(
    cliente, auth, jefe_auth, rrhh_auth
):
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    s = await _situacion(p["id"])
    assert s["situacion"] == "sin_salir"
    assert s["minutos_de_atraso"] is None


async def test_fuera_cuando_salio_y_todavia_no_vence(
    cliente, auth, jefe_auth, rrhh_auth, guardia_auth
):
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    # Una franja que termina bien entrada la noche: salió y aún no le toca.
    await ejecutar(
        "update public.requests set hora_inicio = '00:01', hora_fin = '23:59' where id = %s",
        (p["id"],))
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})

    s = await _situacion(p["id"])
    assert s["situacion"] == "fuera"
    assert s["debe_volver_hoy"] is True
    assert s["minutos_de_atraso"] is None


async def test_fuera_y_atrasado_cuando_paso_la_hora(
    cliente, auth, jefe_auth, rrhh_auth, guardia_auth
):
    """Es lo único del panel que exige actuar, y por eso va primero."""
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    await ejecutar(
        "update public.requests set hora_inicio = '00:01', hora_fin = '00:02' where id = %s",
        (p["id"],))
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})

    s = await _situacion(p["id"])
    assert s["situacion"] == "fuera_atrasado"
    assert s["minutos_de_atraso"] is not None and s["minutos_de_atraso"] > 0


async def test_una_ausencia_de_jornada_completa_no_esta_atrasada(
    cliente, auth, jefe_auth, rrhh_auth, guardia_auth
):
    """Quien no tiene hora de regreso no puede llegar tarde a ella.

    Marcar en rojo cada jornada completa sería una falsa alarma diaria, y una
    alarma que suena todos los días sin motivo enseña al guardia a ignorar el
    panel, que es peor que no tener panel.
    """
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    # Sin horas declaradas: la ausencia ocupa la jornada, no una franja de ella.
    await ejecutar(
        "update public.requests set hora_inicio = null, hora_fin = null where id = %s",
        (p["id"],))
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})

    s = await _situacion(p["id"])
    assert s["situacion"] == "no_vuelve_hoy"
    assert s["debe_volver_hoy"] is False
    assert s["minutos_de_atraso"] is None
    assert s["se_espera_a_las"] is None


async def test_completo_cuando_volvio(
    cliente, auth, jefe_auth, rrhh_auth, guardia_auth
):
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})

    s = await _situacion(p["id"])
    assert s["situacion"] == "completo"
    assert s["minutos_de_atraso"] is None


async def test_el_panel_llega_por_la_api_ordenado(
    cliente, auth, jefe_auth, rrhh_auth, guardia_auth
):
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    await ejecutar(
        "update public.requests set hora_inicio = '00:01', hora_fin = '00:02' where id = %s",
        (p["id"],))
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})

    r = await cliente.get("/garita/hoy", headers=guardia_auth)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["atrasados"] >= 1
    assert cuerpo["movimientos"][0]["situacion"] == "fuera_atrasado", (
        "lo que exige actuar tiene que ir primero, no ordenado por nombre"
    )
    for clave in ("salio_en", "se_espera_a_las", "minutos_de_atraso", "debe_volver_hoy"):
        assert clave in cuerpo["movimientos"][0]


async def test_una_solicitud_no_aprobada_no_entra_al_panel(
    cliente, auth, jefe_auth, rrhh_auth
):
    """El panel es de quien PUEDE salir, no de quien lo pidió."""
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": 7,
        "fecha_inicio": str(__import__("datetime").date.today()),
        "fecha_fin": str(__import__("datetime").date.today()),
        "hora_inicio": "09:00", "hora_fin": "10:00",
        "descripcion": "Permiso que se queda en trámite",
        "justificacion": "Trámite personal que no admite espera.",
    })
    assert r.status_code == 201, r.text
    filas = await obtener_todos(
        "select request_id from public.v_garita_hoy where request_id = %s",
        (r.json()["id"],))
    assert not filas
