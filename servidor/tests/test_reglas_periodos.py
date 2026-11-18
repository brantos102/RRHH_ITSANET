"""Períodos de vacaciones en Python, comparados con PostgreSQL.

generar_periodos_vacaciones corre en cada inicio de sesión y decide cuántos
días tiene cada persona. Se compara con la original en fechas de ingreso
elegidas para romperla: el 29 de febrero, el aniversario exacto de hoy, el
día antes y el día después, alguien que entró este año y alguien con treinta
años de antigüedad; con la caducidad encendida y apagada; y con períodos
que Talento Humano ya había ajustado a mano.
"""
from __future__ import annotations

import datetime as dt
import itertools

import pytest

from app.reglas import periodos
from tests.diferencial import cedula_de_prueba, dos  # noqa: F401

_n = itertools.count(1)


def _hoy() -> dt.date:
    from app.db import ZONA_ECUADOR
    return dt.datetime.now(ZONA_ECUADOR).date()


def _ingresos() -> list[dt.date]:
    hoy = _hoy()
    def hace(anios, dias=0):
        return periodos.mas_anios(hoy, -anios) + dt.timedelta(days=dias)
    return [
        hoy, hace(0, -1), hace(0, -200),
        hace(1), hace(1, 1), hace(1, -1),          # el aniversario: hoy, mañana, ayer
        hace(3), hace(5, 1), hace(7, -1), hace(30, -45),
        dt.date(2024, 2, 29), dt.date(2020, 2, 29), dt.date(2016, 2, 29),
        dt.date(2023, 3, 1), dt.date(2019, 12, 31), dt.date(2010, 1, 1),
        dt.date(1996, 6, 30), dt.date(2026, 1, 1),
    ]


def test_sumar_anios_como_la_base():
    assert periodos.mas_anios(dt.date(2024, 2, 29), 1) == dt.date(2025, 2, 28)
    assert periodos.mas_anios(dt.date(2024, 2, 29), 4) == dt.date(2028, 2, 29)
    assert periodos.mas_anios(dt.date(2023, 3, 1), 1) == dt.date(2024, 3, 1)


@pytest.mark.parametrize("caducidad", ["false", "true"])
@pytest.mark.parametrize("prorrateado", ["false", "true"])
async def test_generar_desde_cero(dos, caducidad, prorrateado):
    await dos.misma_configuracion(caducidad_activa=caducidad, vacaciones_extra_prorrateado=prorrateado)
    for ingreso in _ingresos():
        pid = await dos.persona(cedula_de_prueba(next(_n)), ingreso)
        res_pg, err_pg = dos.pg_llamar("select generar_periodos_vacaciones(%s)", (pid,))
        res_my = await periodos.generar_periodos_vacaciones(pid)
        assert err_pg is None
        assert res_my == res_pg, ingreso
        en_pg, en_my = await dos.foto(pid)
        assert en_my == en_pg, f"ingreso {ingreso}"


async def test_generar_respeta_lo_ajustado_y_completa_lo_que_cumplio_el_anio(dos):
    """Tres situaciones de una persona que ya tenía períodos:
    uno devengado que Talento Humano ajustó (no se toca), uno «en curso» cuyo
    año ya se cumplió (pasa a devengado con sus días) y el en curso de
    verdad con un ajuste hacia arriba (no se baja)."""
    await dos.misma_configuracion(caducidad_activa="true")
    hoy = _hoy()
    ingreso = periodos.mas_anios(hoy, -3) - dt.timedelta(days=40)
    pid = await dos.persona(cedula_de_prueba(next(_n)), ingreso)
    def p(k):
        return {"periodo": k, "fecha_desde": periodos.mas_anios(ingreso, k - 1),
                "fecha_hasta": periodos.mas_anios(ingreso, k) - dt.timedelta(days=1),
                "fines_semana_obligatorios": 2}
    await dos.periodo(pid, **p(1), dias_asignados=20, dias_consumidos=4, devengado=True)
    await dos.periodo(pid, **p(2), dias_asignados=3, devengado=False)
    await dos.periodo(pid, **p(4), dias_asignados=14, devengado=False)
    dos.pg_llamar("select generar_periodos_vacaciones(%s)", (pid,))
    await periodos.generar_periodos_vacaciones(pid)
    en_pg, en_my = await dos.foto(pid)
    assert en_my == en_pg
    assert en_my["periodos"][0][3] == 20, "el ajuste de Talento Humano se respeta"


async def test_generar_dos_veces_no_cambia_nada(dos):
    pid = await dos.persona(cedula_de_prueba(next(_n)), dt.date(2018, 5, 14))
    await periodos.generar_periodos_vacaciones(pid)
    _, antes = await dos.foto(pid)
    await periodos.generar_periodos_vacaciones(pid)
    _, despues = await dos.foto(pid)
    assert antes == despues


@pytest.mark.parametrize("saldo, fds", [
    (0, 0), (10, 0), (37.5, 1), (63, 2), (-8, 0), (1000, 0), (12.25, 5),
])
async def test_cargar_saldo_inicial(dos, saldo, fds):
    """El caso de la carga de datos reales: la planilla dice cuánto le queda
    a cada uno, y el sistema reparte lo tomado entre sus períodos."""
    await dos.misma_configuracion()
    pid = await dos.persona(cedula_de_prueba(next(_n)), dt.date(2019, 8, 5))
    res_pg, err_pg = dos.pg_llamar("select cargar_saldo_inicial(%s, %s, %s)",
                                   (pid, str(saldo), fds))
    try:
        res_my, err_my = await periodos.cargar_saldo_inicial(pid, saldo, fds), None
    except Exception as exc:  # noqa: BLE001
        res_my, err_my = None, getattr(exc, "mensaje", str(exc))
    assert err_my == err_pg
    if err_pg is None:
        assert res_my == res_pg
        en_pg, en_my = await dos.foto(pid)
        assert en_my == en_pg


async def test_caducar_con_la_caducidad_encendida(dos):
    await dos.misma_configuracion(caducidad_activa="true")
    pid = await dos.persona(cedula_de_prueba(next(_n)), dt.date(2014, 3, 10))
    dos.pg_llamar("select generar_periodos_vacaciones(%s)", (pid,))
    await periodos.generar_periodos_vacaciones(pid)
    # Los generados ya nacen caducados si vencieron; se reabren para que
    # caducar tenga algo que hacer.
    dos.pg.execute("update vacation_periods set caducado = false where user_id = %s", (pid,))
    from app.db import ejecutar
    await ejecutar("UPDATE vacation_periods SET caducado = FALSE WHERE user_id = %s", (pid,))
    res_pg, _ = dos.pg_llamar("select caducar_periodos_de(%s)", (pid,))
    res_my = await periodos.caducar_periodos_de(pid)
    assert res_my == res_pg and res_my > 0
    en_pg, en_my = await dos.foto(pid)
    assert en_my == en_pg


async def test_con_la_caducidad_apagada_no_se_pierde_ningun_dia(dos):
    await dos.misma_configuracion(caducidad_activa="false")
    pid = await dos.persona(cedula_de_prueba(next(_n)), dt.date(2010, 3, 10))
    await periodos.generar_periodos_vacaciones(pid)
    assert await periodos.caducar_periodos_de(pid) == 0
    _, en_my = await dos.foto(pid)
    assert not any(p[7] for p in en_my["periodos"])


@pytest.mark.parametrize("consumidos, motivo, por_rrhh", [
    (1, "Ya los tomó en 2023, constan en la planilla", True),
    (3, "Ya los tomó en 2023, constan en la planilla", True),
    (-1, "Ya los tomó en 2023, constan en la planilla", True),
    (1, "corto", True),
    (1, "Ya los tomó en 2023, constan en la planilla", False),
])
async def test_corregir_fines_semana(dos, consumidos, motivo, por_rrhh):
    pid = await dos.persona(cedula_de_prueba(next(_n)), dt.date(2019, 8, 5))
    rol = "rrhh" if por_rrhh else "jefe"
    por = await dos.persona(cedula_de_prueba(next(_n)), dt.date(2015, 1, 1), rol=rol)
    dos.pg_llamar("select generar_periodos_vacaciones(%s)", (pid,))
    await periodos.generar_periodos_vacaciones(pid)
    _, err_pg = dos.pg_llamar("select corregir_fines_semana(%s, 1, %s, %s, %s)",
                              (pid, consumidos, motivo, por))
    try:
        await periodos.corregir_fines_semana(pid, 1, consumidos, motivo, por)
        err_my = None
    except Exception as exc:  # noqa: BLE001
        err_my = getattr(exc, "mensaje", str(exc))
    assert err_my == err_pg
    en_pg, en_my = await dos.foto(pid)
    assert en_my == en_pg
    if err_pg is None:
        bit_pg = dos.pg.execute("select detalle from audit_logs where user_id = %s "
                                "and accion = 'fines_semana_corregidos'", (por,)).fetchone()["detalle"]
        from app.db import obtener_uno
        bit_my = (await obtener_uno("SELECT detalle FROM audit_logs WHERE user_id = %s "
                                    "AND accion = 'fines_semana_corregidos'", (por,)))["detalle"]
        assert bit_my == bit_pg
