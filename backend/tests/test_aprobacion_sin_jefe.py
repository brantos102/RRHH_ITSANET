"""La solicitud de quien no tiene jefe asignado no la veía nadie.

El disparador de inserción pone toda solicitud en `pendiente_jefe` y le copia
el `jefe_id` del colaborador. Si el colaborador no tiene jefe —en la planilla
real son quince de trescientas cincuenta y una—, el campo queda nulo, y
entonces:

  · la bandeja del jefe filtra por `jefe_id = <el mío>`, y nulo no es nadie;
  · la de Talento Humano filtra por `pendiente_rrhh`, y esta está un paso antes;
  · la de Administración, igual.

Resultado: la solicitud existe, el colaborador la ve «pendiente» en su panel,
y no hay una sola pantalla en el sistema desde la que alguien pueda decidirla.
No da error, no avisa a nadie y no vence: se queda ahí.

Decidirla sí se podía —el endpoint ya dejaba a Talento Humano resolver la
etapa de jefatura—, pero no había forma de encontrarla. Un permiso que se
puede firmar y no se puede ver es lo mismo que uno que no se puede firmar.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.db import ejecutar, obtener_uno
from tests.test_panel_configurable import admin_auth  # noqa: F401
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, lunes_sin_feriados,
                                      rrhh_auth)


@pytest.fixture
async def sin_jefe(empleado):
    """El colaborador se queda sin jefe, como los quince de la planilla."""
    antes = await obtener_uno("select jefe_id from public.users where id = %s",
                              (empleado["id"],))
    await ejecutar("update public.users set jefe_id = null where id = %s",
                   (empleado["id"],))
    yield empleado
    await ejecutar("update public.users set jefe_id = %s where id = %s",
                   (antes["jefe_id"], empleado["id"]))


async def _pedir(cliente, auth) -> dict:
    lunes = await lunes_sin_feriados()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Descanso programado con la familia", "firmar": False})
    assert r.status_code == 201, r.text
    return r.json()


async def test_la_solicitud_queda_sin_jefe_asignado(cliente, auth, sin_jefe):
    """El punto de partida: así queda la fila, y es correcto que quede así."""
    pedida = await _pedir(cliente, auth)
    fila = await obtener_uno(
        "select estado::text as estado, jefe_id from public.requests where id = %s",
        (pedida["id"],))
    assert fila["estado"] == "pendiente_jefe"
    assert fila["jefe_id"] is None


async def test_talento_humano_la_ve(cliente, auth, rrhh_auth, sin_jefe):
    """Lo que no pasaba: se quedaba invisible para todos."""
    pedida = await _pedir(cliente, auth)
    pendientes = (await cliente.get("/aprobaciones/pendientes", headers=rrhh_auth)).json()
    assert pedida["id"] in {p["id"] for p in pendientes}, \
        "una solicitud sin jefe asignado no la veía nadie, ni Talento Humano"


async def test_administracion_tambien_la_ve(cliente, auth, admin_auth, sin_jefe):
    pedida = await _pedir(cliente, auth)
    pendientes = (await cliente.get("/aprobaciones/pendientes", headers=admin_auth)).json()
    assert pedida["id"] in {p["id"] for p in pendientes}


async def test_la_bandeja_dice_que_no_tiene_jefe(cliente, auth, rrhh_auth, sin_jefe):
    """Decidir por un jefe que no existe no es lo mismo que decidir por uno
    que no contesta, y quien resuelve tiene que poder distinguirlo."""
    pedida = await _pedir(cliente, auth)
    pendientes = (await cliente.get("/aprobaciones/pendientes", headers=rrhh_auth)).json()
    mia = {p["id"]: p for p in pendientes}[pedida["id"]]
    assert mia["sin_jefe"] is True
    assert mia["jefe_nombre"] is None


async def test_talento_humano_la_puede_resolver(cliente, auth, rrhh_auth, sin_jefe):
    pedida = await _pedir(cliente, auth)
    r = await cliente.post(f"/aprobaciones/{pedida['id']}/decidir", headers=rrhh_auth,
                           json={"accion": "aprobar"})
    assert r.status_code == 200, r.text
    fila = await obtener_uno(
        "select estado::text as estado from public.requests where id = %s", (pedida["id"],))
    # La etapa de jefatura queda resuelta y pasa a la de Talento Humano, que
    # es la que falta. No se salta ningún control.
    assert fila["estado"] == "pendiente_rrhh"


async def test_un_jefe_cualquiera_no_se_apropia_de_las_huerfanas(
        cliente, auth, jefe_auth, sin_jefe):
    """Que nadie pueda verla era el problema; que la vea cualquiera sería otro."""
    pedida = await _pedir(cliente, auth)
    pendientes = (await cliente.get("/aprobaciones/pendientes", headers=jefe_auth)).json()
    assert pedida["id"] not in {p["id"] for p in pendientes}


async def test_las_normales_siguen_yendo_a_su_jefe(cliente, auth, jefe_auth, rrhh_auth):
    """Lo que no debía cambiar: con jefe asignado, decide el jefe."""
    pedida = await _pedir(cliente, auth)
    del_jefe = (await cliente.get("/aprobaciones/pendientes", headers=jefe_auth)).json()
    assert pedida["id"] in {p["id"] for p in del_jefe}

    de_rrhh = (await cliente.get("/aprobaciones/pendientes", headers=rrhh_auth)).json()
    assert pedida["id"] not in {p["id"] for p in de_rrhh}, \
        "Talento Humano no debe ver lo que todavía le toca al jefe"


async def test_el_contador_de_la_region_no_se_lleva_las_de_la_otra(
        cliente, auth, rrhh_auth, sin_jefe, empleado):
    """Talento Humano resuelve lo de SU región, también lo huérfano."""
    pedida = await _pedir(cliente, auth)
    await ejecutar("update public.requests set region = 'costa' where id = %s",
                   (pedida["id"],))
    pendientes = (await cliente.get("/aprobaciones/pendientes", headers=rrhh_auth)).json()
    assert pedida["id"] not in {p["id"] for p in pendientes}, \
        "la huérfana de la Costa no le toca a quien atiende la Sierra"
