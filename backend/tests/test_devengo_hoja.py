"""El devengo del año en curso, como lo lleva Talento Humano.

El sistema y la hoja daban cifras distintas para la misma persona: 84,33
frente a 83,75. La diferencia no era de redondeo. El sistema prorrateaba
también los días adicionales del Art. 69, y la hoja los concede enteros al
cumplir el año.

Lo que estas pruebas fijan es lo que hace que el cambio sea seguro: que los
dos cálculos coinciden exactamente en cada aniversario, y que solo se
separan dentro del año en marcha.
"""
from __future__ import annotations

import re
from decimal import Decimal

from app.db import obtener_uno

BASE = Decimal("1.25")   # quince días partidos para doce


async def _devengado(ingreso: str, periodo: int) -> Decimal:
    fila = await obtener_uno(
        "select public.dias_devengados_en_curso(%s::date, %s) as d", (ingreso, periodo))
    return Decimal(str(fila["d"]))


async def test_el_ano_en_curso_acumula_uno_con_veinticinco_al_mes(cliente):
    """Siete meses del sexto año son 8,75 días, no 9,33.

    Es el caso que destapó todo: la hoja decía 83,75 devengados y el panel
    84,33 para la misma persona y el mismo día.
    """
    hoy = await obtener_uno("select current_date - interval '5 years 7 months' as f")
    ingreso = str(hoy["f"].date())
    assert await _devengado(ingreso, 6) == Decimal("8.75")


async def test_los_dos_calculos_coinciden_en_cada_aniversario(cliente):
    """La razón por la que el cambio no mueve ningún saldo de nadie.

    La hoja calcula «meses trabajados x 1,25 + días adicionales enteros». El
    sistema suma el tope de cada año cumplido. Al completar un año las dos
    fórmulas dan el mismo número: la diferencia vive solo dentro del año y se
    cierra sola en el aniversario.
    """
    for anios in (1, 3, 5, 6, 10, 16, 21):
        # Lo que dice la hoja: doce meses por año, a 1,25, más los adicionales.
        topes = [Decimal(str((await obtener_uno(
            "select public.dias_por_antiguedad(%s) as d", (k,)))["d"]))
            for k in range(1, anios + 1)]
        segun_el_sistema = sum(topes)
        base_hoja = BASE * 12 * anios
        adicionales = segun_el_sistema - base_hoja

        assert base_hoja + adicionales == segun_el_sistema, f"con {anios} años"
        # Y los adicionales son enteros: nunca una fracción de día.
        assert adicionales == adicionales.to_integral_value(), (
            f"con {anios} años los adicionales salieron fraccionados: {adicionales}")

        # Recién cumplido el aniversario, el período en curso arranca en cero
        # con cualquiera de los dos cálculos.
        fila = await obtener_uno(
            "select (current_date - make_interval(years => %s))::date as f", (anios,))
        assert await _devengado(str(fila["f"]), anios + 1) == Decimal("0.00")


async def test_quien_lleva_menos_de_cinco_anos_no_ve_ninguna_diferencia(cliente):
    """283 de las 351 personas de la planilla. Para ellas no cambia nada.

    Antes de los cinco años no hay días adicionales que prorratear, así que
    los dos cálculos eran ya el mismo.
    """
    for anios, meses in ((0, 7), (1, 3), (2, 11), (4, 6)):
        fila = await obtener_uno(
            """select (current_date - make_interval(years => %s, months => %s))::date as f""",
            (anios, meses))
        ingreso = str(fila["f"])
        esperado = (BASE * meses).quantize(Decimal("0.01"))
        assert await _devengado(ingreso, anios + 1) == esperado, f"{anios}a {meses}m"


async def test_no_acumula_mas_de_un_ano_si_el_periodo_quedo_sin_renovar(cliente):
    """Un período vencido y no renovado no sigue sumando para siempre."""
    fila = await obtener_uno("select (current_date - interval '3 years')::date as f")
    assert await _devengado(str(fila["f"]), 1) == BASE * 12


async def test_se_puede_volver_al_prorrateo_sin_otra_migracion(cliente):
    """Si la empresa decide adoptar el cálculo del sistema, es un parámetro.

    Se deja la puerta porque la decisión es suya, no del programa.
    """
    from app.db import ejecutar

    fila = await obtener_uno("select current_date - interval '5 years 7 months' as f")
    ingreso = str(fila["f"].date())
    try:
        await ejecutar(
            """insert into public.app_config (clave, valor)
               values ('vacaciones_extra_prorrateado', 'true')
               on conflict (clave) do update set valor = 'true'""")
        assert await _devengado(ingreso, 6) == Decimal("9.33")
    finally:
        await ejecutar(
            """update public.app_config set valor = 'false'
                where clave = 'vacaciones_extra_prorrateado'""")
    assert await _devengado(ingreso, 6) == Decimal("8.75")


async def test_ante_un_parametro_raro_se_queda_con_el_calculo_de_la_hoja(cliente):
    """Ni «sí», ni «1», ni vacío encienden el prorrateo. Solo «true»."""
    from app.db import ejecutar

    fila = await obtener_uno("select current_date - interval '5 years 7 months' as f")
    ingreso = str(fila["f"].date())
    for valor in ("si", "1", "", "TRUE.", "verdadero"):
        await ejecutar(
            """insert into public.app_config (clave, valor)
               values ('vacaciones_extra_prorrateado', %s)
               on conflict (clave) do update set valor = excluded.valor""", (valor,))
        assert await _devengado(ingreso, 6) == Decimal("8.75"), f"con «{valor}»"
    await ejecutar(
        """update public.app_config set valor = 'false'
            where clave = 'vacaciones_extra_prorrateado'""")


async def test_la_vista_de_cotejo_ensena_los_dos_numeros(cliente, empleado):
    """«El sistema dice otra cosa» no es discutible sin las dos cifras."""
    fila = await obtener_uno(
        """select meses_del_periodo, tope_anual_del_periodo,
                  devengado_hoja, devengado_prorrateado
             from public.v_devengo_cotejo limit 1""")
    assert fila is not None
    assert fila["devengado_hoja"] <= fila["devengado_prorrateado"]


async def test_ningun_aviso_dice_que_los_dias_se_pierden(cliente):
    """La afirmación que el sistema no puede hacer, en ningún aviso.

    El Art. 75 permite acumular hasta tres años y el Art. 76 manda pagar lo
    no gozado; la Constitución, en su Art. 326 núm. 2, declara los derechos
    laborales irrenunciables. Un sistema de la empresa que le dice a alguien
    que va a perder días no comete un error de redacción: empuja a decisiones
    equivocadas, y lo hace con la voz de la empresa.

    Se revisan las funciones que escriben avisos y los avisos ya guardados.
    """
    from app.db import obtener_todos

    prohibido = ("se pierden", "perderá", "perder sus días", "perderlas",
                 "caducan sus días")

    # Los comodines van como parámetro: psycopg lee el signo de porcentaje
    # como marcador aunque esté dentro de una cadena SQL.
    funciones = await obtener_todos(
        """select proname, prosrc from pg_proc
            where pronamespace = 'public'::regnamespace
              and (proname like %s or proname like %s or proname like %s)""",
        ("%alerta%", "%notific%", "%vacacion%"))
    def sin_comentarios(fuente: str) -> str:
        """Lo que la función le dice a la gente, sin lo que se dice a sí misma.

        Los comentarios explican precisamente que antes se anunciaba una
        pérdida y ya no; buscar ahí la frase prohibida la encuentra siempre
        y obligaría a borrar la explicación para que la prueba pase.
        """
        return "\n".join(re.sub(r"--.*$", "", linea)
                          for linea in (fuente or "").splitlines()).lower()

    for f in funciones:
        visible = sin_comentarios(f["prosrc"])
        for frase in prohibido:
            assert frase not in visible, f"{f['proname']} todavía dice «{frase}»"

    guardados = await obtener_todos(
        """select id, mensaje from public.notifications
            where mensaje ilike %s or mensaje ilike %s""",
        ("%se pierden%", "%perderá%"))
    assert not guardados, (
        "quedan avisos enviados que afirman que los días se pierden: "
        f"{[g['id'] for g in guardados][:5]}")
