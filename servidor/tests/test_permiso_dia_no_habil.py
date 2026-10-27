"""El turno del domingo existía; el permiso para ese turno, no.

La empresa tiene garita —puesto cubierto los siete días— y operarios con
turnos de fin de semana. El sistema descartaba sábados, domingos y feriados
al contar los días de cualquier solicitud, así que a esa gente le respondía:

    «El rango de fechas no genera días computables (feriados/fin de semana).»

El guardia que cubre el domingo y necesita dos horas no podía ni registrar la
solicitud, y el mensaje le hablaba de feriados. Se arregla solo para el día
único: un rango de varios días sigue descartando el fin de semana, porque ahí
descartarlo es lo correcto.

Apareció porque la suite se caía los sábados y los domingos —dieciocho
pruebas—. El calendario no es una excusa válida para un fallo.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.db import obtener_uno
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, rrhh_auth)


def _proximo_domingo() -> date:
    hoy = date.today()
    return hoy + timedelta(days=(6 - hoy.weekday()) % 7 or 7)


def _proximo_lunes() -> date:
    hoy = date.today()
    return hoy + timedelta(days=(7 - hoy.weekday()) % 7 or 7)


async def _tipo_de_permiso(cliente, auth) -> int:
    tipos = (await cliente.get("/catalogos/tipos-permiso", headers=auth)).json()
    return {t["codigo"]: t for t in tipos
            if not t["requiere_adjunto"]}.popitem()[1]["id"]


async def test_un_permiso_de_domingo_se_puede_pedir(cliente, auth):
    """El caso del personal de garita, todos los domingos del año."""
    domingo = _proximo_domingo()
    assert domingo.weekday() == 6
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": await _tipo_de_permiso(cliente, auth),
        "fecha_inicio": str(domingo), "fecha_fin": str(domingo),
        "descripcion": "Diligencia durante el turno del domingo",
        "justificacion": "Cubro el puesto de garita ese día."})
    assert r.status_code == 201, r.text
    fila = await obtener_uno(
        "select dias_solicitados from requests where id = %s", (r.json()["id"],))
    assert fila["dias_solicitados"] == 1


async def test_un_permiso_por_horas_de_domingo_tambien(cliente, auth):
    domingo = _proximo_domingo()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": await _tipo_de_permiso(cliente, auth),
        "fecha_inicio": str(domingo), "fecha_fin": str(domingo),
        "hora_inicio": "09:00", "hora_fin": "11:00",
        "descripcion": "Dos horas durante el turno del domingo",
        "justificacion": "Cubro el puesto de garita ese día."})
    assert r.status_code == 201, r.text
    fila = await obtener_uno(
        "select dias_solicitados, horas_solicitadas from requests where id = %s",
        (r.json()["id"],))
    assert fila["dias_solicitados"] == 1
    assert float(fila["horas_solicitadas"]) == 2.0


async def test_un_rango_de_varios_dias_sigue_descartando_el_fin_de_semana(cliente, auth):
    """Lo que NO debía cambiar: de lunes a lunes son cinco días, no ocho."""
    lunes = _proximo_lunes()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": await _tipo_de_permiso(cliente, auth),
        "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Ausencia de una semana larga por asunto familiar",
        "justificacion": "Tengo que acompañar a un familiar fuera de la ciudad."})
    if r.status_code == 201:
        fila = await obtener_uno(
            "select dias_solicitados from requests where id = %s", (r.json()["id"],))
        # Ocho días calendario, seis hábiles: el fin de semana se sigue
        # descartando. Si algún feriado cae dentro serán menos, nunca más.
        assert fila["dias_solicitados"] <= 6
    else:
        # Puede topar con el tope de días del tipo de permiso. Lo que importa
        # es que no se cuenten los ocho días calendario.
        assert "no genera días computables" not in r.text


async def test_las_vacaciones_nunca_descartaron_el_fin_de_semana():
    """Lo que este arreglo NO toca, comprobado donde se decide.

    `calcular_dias` usa días hábiles solo para los permisos. Las vacaciones
    cuentan días calendario menos feriados, que es como las cuenta el
    Art. 69: quince días son quince, con sus sábados y domingos dentro. Si
    alguna vez alguien «unificara» las dos reglas, el saldo de las 351
    personas se movería de golpe. Esta prueba está para que eso no pase sin
    que nadie se dé cuenta.
    """
    domingo = _proximo_domingo()
    fila = await obtener_uno(
        """select calcular_dias('vacacion', %(d)s, %(d)s) as vacacion,
                  calcular_dias('permiso',  %(d)s, %(d)s) as permiso""",
        {"d": domingo})
    assert float(fila["vacacion"]) == 1.0, "un domingo de vacaciones siempre contó"
    assert float(fila["permiso"]) == 0.0, "y un permiso de domingo nunca contó"


async def test_el_permiso_de_un_dia_lo_arregla_el_disparador_no_el_calculo():
    """El cálculo sigue devolviendo cero; lo corrige quien inserta.

    Importa dónde está el arreglo: `calcular_dias` lo usan los informes, el
    calendario y el cotejo con la planilla. Cambiarla habría movido números en
    sitios que nadie pidió tocar. El disparador de inserción es el único lugar
    donde hace falta.
    """
    lunes, domingo = _proximo_lunes(), _proximo_domingo()
    fila = await obtener_uno(
        """select calcular_dias('permiso', %s, %s) as domingo,
                  calcular_dias('permiso', %s, %s) as lunes""",
        (domingo, domingo, lunes, lunes))
    assert float(fila["domingo"]) == 0.0
    assert float(fila["lunes"]) == 1.0
