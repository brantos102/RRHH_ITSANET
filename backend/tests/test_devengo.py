"""Devengo mensual, caducidad y carga de saldos.

El sistema otorgaba los 15 días de golpe al cumplir el año: quien llevaba
once meses tenía saldo cero. La planilla real de Talento Humano acumula
1.25 días por mes, que es como se genera el derecho. Estas pruebas fijan
esa aritmética y los bordes que aparecieron al cargar la planilla completa.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_uno


async def _crear(cedula: str, meses_antiguedad: int) -> str:
    fila = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s, 'Devengo Prueba', %s, 'empleado',
                   (current_date - make_interval(months => %s))::date)
           on conflict (cedula) do update
             set fecha_ingreso = (current_date - make_interval(months => %s))::date
           returning id""",
        (cedula, f"dev{cedula}@api.test", meses_antiguedad, meses_antiguedad),
    )
    await obtener_uno("select public.generar_periodos_vacaciones(%s)", (fila["id"],))
    return str(fila["id"])


@pytest.fixture(autouse=True)
async def limpiar():
    yield
    await ejecutar("delete from public.users where email like 'dev%%@api.test'")


@pytest.mark.parametrize("meses,esperado", [
    (1, 1.25), (3, 3.75), (8, 10.0), (11, 13.75),
])
async def test_se_devenga_uno_y_cuarto_por_mes(meses, esperado):
    """15 días al año son 1.25 por mes, como los calcula Talento Humano."""
    user_id = await _crear("1700000019", meses)
    fila = await obtener_uno(
        "select dias_vacaciones from public.users where id = %s", (user_id,))
    assert float(fila["dias_vacaciones"]) == pytest.approx(esperado, abs=0.01)


async def test_al_cumplir_el_anio_se_completa_el_periodo():
    user_id = await _crear("1700000019", 12)
    fila = await obtener_uno(
        "select dias_vacaciones from public.users where id = %s", (user_id,))
    # 15 del año cumplido, más lo devengado del que empieza
    assert float(fila["dias_vacaciones"]) >= 15


async def test_la_antiguedad_larga_no_acumula_mas_de_lo_que_la_ley_permite():
    """Un período que nace vencido está caducado desde el primer momento.

    Con 18 años de servicio la suma de todos los períodos pasa de 360 días.
    Si no se marcan caducados al crearlos, el saldo desborda el rango de la
    columna y la persona no puede cargarse: era la mayoría de la planilla.
    """
    user_id = await _crear("1700000019", 18 * 12 + 7)
    fila = await obtener_uno(
        "select dias_vacaciones from public.users where id = %s", (user_id,))
    saldo = float(fila["dias_vacaciones"])
    assert 0 < saldo < 100, f"saldo irreal tras 18 años: {saldo}"

    vencidos = await obtener_uno(
        """select count(*) filter (where caducado) as caducados,
                  count(*) as total
             from public.vacation_periods where user_id = %s""", (user_id,))
    assert vencidos["caducados"] > 0, "los períodos viejos deben nacer caducados"


async def test_la_carga_inicial_respeta_el_saldo_de_la_planilla():
    user_id = await _crear("1700000019", 8)
    await obtener_uno("select public.cargar_saldo_inicial(%s, 7.5, 0)", (user_id,))
    fila = await obtener_uno(
        "select dias_vacaciones from public.users where id = %s", (user_id,))
    assert float(fila["dias_vacaciones"]) == pytest.approx(7.5, abs=0.01)


async def test_la_carga_conserva_un_saldo_negativo():
    """Diez personas de la planilla ya adelantaron días. Redondear a cero
    haría perder el registro de esa deuda."""
    user_id = await _crear("1700000019", 8)
    await obtener_uno("select public.cargar_saldo_inicial(%s, -1.0, 0)", (user_id,))
    fila = await obtener_uno(
        "select dias_vacaciones from public.users where id = %s", (user_id,))
    assert float(fila["dias_vacaciones"]) == pytest.approx(-1.0, abs=0.01)


async def test_la_carga_rechaza_un_saldo_imposible():
    """Más días de los devengados no es un saldo: es un dato mal conciliado."""
    user_id = await _crear("1700000019", 3)
    with pytest.raises(Exception) as err:
        await obtener_uno("select public.cargar_saldo_inicial(%s, 40, 0)", (user_id,))
    assert "supera lo devengado" in str(err.value)
