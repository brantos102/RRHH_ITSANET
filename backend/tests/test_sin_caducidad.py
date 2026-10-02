"""Nadie ve una fecha de vencimiento que no va a cumplirse.

El sistema le mostraba a cada colaborador una fecha de caducidad de sus
vacaciones. A quien había entrado el 1 de junio de 2026 le decía «vence el
31 de mayo de 2030». Esa fecha no existe en ninguna parte: la hoja con la
que Talento Humano lleva los saldos desde hace años no tiene columna de
caducidad, y la empresa nunca ha extinguido días a nadie.

Salía de aplicar el Art. 75 del Código del Trabajo como si fuera una
obligación. No lo es: PERMITE acumular hasta tres años, no manda extinguir
lo que pase de ahí. Aplicarlo por omisión convirtió un derecho del
trabajador en un plazo en su contra.

Y no era cosmético. En la copia de la nómina real había 559 períodos de 76
personas marcados como caducados, con 9.554 días anotados como perdidos: una
afirmación del sistema sobre un pasivo laboral de la empresa. Más las
alertas de severidad crítica avisando de pérdidas que no iban a ocurrir.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA


CED_RRHH_SC = "1700000043"


@pytest.fixture
async def rrhh_auth(cliente, codigos, empleado):
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso, ciudad)
           values (%s, 'Talento Caducidad', 'caducidad@api.test', 'rrhh',
                   current_date - 900, 'Quito')
           on conflict (cedula) do update set rol = 'rrhh' returning id""",
        (CED_RRHH_SC,))
    await cliente.post("/auth/solicitar-token", json={"cedula": CED_RRHH_SC})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CED_RRHH_SC, "codigo": codigos[-1]})
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}
    await ejecutar("delete from public.users where cedula = %s", (CED_RRHH_SC,))


@pytest.fixture
async def auth(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_esta_apagada_por_omision():
    fila = await obtener_uno("select public.caducidad_activa() as activa")
    assert fila["activa"] is False, (
        "La caducidad no puede estar activa por omisión: el Art. 75 permite "
        "acumular, no obliga a extinguir."
    )


async def test_ante_la_duda_no_se_extingue():
    """Si la clave falta o trae basura, no se pierde ningún día de nadie."""
    previo = await obtener_uno(
        "select valor from public.app_config where clave = 'caducidad_activa'")
    try:
        for valor in ("", "  ", "no", "1", "TRUE_PERO_NO", "sí"):
            await ejecutar(
                "update public.app_config set valor = %s where clave = 'caducidad_activa'",
                (valor,))
            fila = await obtener_uno("select public.caducidad_activa() as activa")
            assert fila["activa"] is False, f"«{valor}» no debería activar la caducidad"

        await ejecutar("delete from public.app_config where clave = 'caducidad_activa'")
        fila = await obtener_uno("select public.caducidad_activa() as activa")
        assert fila["activa"] is False, "sin la clave tampoco se extingue nada"
    finally:
        await ejecutar(
            """insert into public.app_config (clave, valor, descripcion)
               values ('caducidad_activa', %s, 'restaurada por la prueba')
               on conflict (clave) do update set valor = excluded.valor""",
            (previo["valor"] if previo else "false",))


async def test_los_periodos_nacen_sin_fecha_de_vencimiento(empleado):
    await obtener_uno("select public.generar_periodos_vacaciones(%s) as n", (empleado["id"],))
    filas = await obtener_todos(
        "select periodo, vence_en from public.vacation_periods where user_id = %s",
        (empleado["id"],))
    assert filas, "la persona debería tener períodos"
    con_fecha = [f["periodo"] for f in filas if f["vence_en"] is not None]
    assert not con_fecha, f"los períodos {con_fecha} nacieron con fecha de vencimiento"


async def test_no_se_caduca_nada(empleado):
    """Aunque se fuerce una fecha vencida, no se extingue el período."""
    await obtener_uno("select public.generar_periodos_vacaciones(%s) as n", (empleado["id"],))
    await ejecutar(
        """update public.vacation_periods
              set vence_en = current_date - 1
            where user_id = %s and dias_saldo > 0""", (empleado["id"],))

    fila = await obtener_uno(
        "select public.caducar_periodos_de(%s) as n", (empleado["id"],))
    assert fila["n"] == 0

    caducados = await obtener_uno(
        """select count(*) as n from public.vacation_periods
            where user_id = %s and caducado""", (empleado["id"],))
    assert caducados["n"] == 0, "se extinguió un período con la caducidad apagada"


async def test_no_se_avisa_de_una_perdida_que_no_va_a_ocurrir(empleado):
    """El aviso decía «Perderá 2,83 días el 07/02/2029», en rojo."""
    await obtener_uno("select public.generar_periodos_vacaciones(%s) as n", (empleado["id"],))
    await ejecutar(
        """update public.vacation_periods
              set vence_en = current_date + 10
            where user_id = %s and dias_saldo > 0""", (empleado["id"],))
    await ejecutar("delete from public.notifications where user_id = %s", (empleado["id"],))

    await obtener_uno("select public.generar_alertas_vacaciones() as r")

    avisos = await obtener_todos(
        """select titulo from public.notifications
            where user_id = %s and tipo = 'vacaciones_por_caducar'""",
        (empleado["id"],))
    assert not avisos, f"se avisó de una pérdida que no va a ocurrir: {avisos}"


async def test_reparar_no_mueve_ningun_saldo(empleado):
    """Es la condición que hace segura la reparación de la base cargada.

    Un período marcado «caducado» no suma al saldo; uno consumido por
    completo tampoco. Pasar de lo primero a lo segundo deja el saldo igual y
    cambia lo único que estaba mal: lo que el sistema afirma que pasó con
    esos días. Des-caducarlos sin más habría devuelto al saldo días que la
    persona sí gozó.
    """
    await obtener_uno("select public.generar_periodos_vacaciones(%s) as n", (empleado["id"],))
    antes = await obtener_uno(
        "select dias_vacaciones from public.users where id = %s", (empleado["id"],))

    # Se simula el estado viejo: un período marcado como caducado.
    await ejecutar(
        """update public.vacation_periods
              set caducado = true, vence_en = current_date - 1
            where user_id = %s and periodo = 1""", (empleado["id"],))
    con_caducado = await obtener_uno(
        "select dias_vacaciones from public.users where id = %s", (empleado["id"],))

    # Y la reparación, que es lo que hace la migración 0020.
    await ejecutar(
        """update public.vacation_periods
              set dias_consumidos = dias_asignados, caducado = false, vence_en = null
            where user_id = %s and caducado""", (empleado["id"],))
    despues = await obtener_uno(
        "select dias_vacaciones from public.users where id = %s", (empleado["id"],))

    assert despues["dias_vacaciones"] == con_caducado["dias_vacaciones"], (
        "reparar movió el saldo: es exactamente lo que no debe pasar"
    )
    # Y queda constancia de que el período sí cambió de significado: figuraba
    # como extinguido y ahora figura como gozado.
    periodo = await obtener_uno(
        """select caducado, dias_consumidos, dias_asignados, vence_en
             from public.vacation_periods where user_id = %s and periodo = 1""",
        (empleado["id"],))
    assert periodo["caducado"] is False
    assert periodo["vence_en"] is None
    assert periodo["dias_consumidos"] == periodo["dias_asignados"]


async def test_la_pantalla_de_colaboradores_sabe_que_no_hay_caducidad(
    cliente, rrhh_auth, empleado
):
    """Sin el dato, la tabla mostraría una columna entera de guiones."""
    r = await cliente.get("/rrhh/colaboradores", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    filas = r.json()
    assert filas, "debería devolver al menos al empleado de prueba"
    for fila in filas:
        assert fila["caducidad_activa"] is False, (
            "la pantalla necesita saberlo para no dibujar la columna «Vence»"
        )
        assert fila["proximo_vencimiento"] is None


async def test_la_vista_de_control_deja_verlo_de_un_vistazo():
    fila = await obtener_uno("select * from public.v_caducidad")
    assert fila["activa"] is False
    assert fila["periodos_caducados"] == 0, (
        "quedan períodos marcados como caducados con la caducidad apagada"
    )
    assert fila["periodos_con_fecha_de_vencimiento"] == 0


async def test_se_avisa_de_la_acumulacion_que_si_hay_que_resolver(empleado):
    """El aviso cambia de sentido, no desaparece.

    Antes decía «Perderá 2,83 días el 07/02/2029», en rojo, citando un
    Art. 75 que no dice eso. Ahora dice lo que sí corresponde: esta persona
    arrastra tres o más años sin gozar, el Art. 75 agota ahí lo que ella
    puede decidir por su cuenta, y programar las vacaciones pasa a ser cosa
    de la empresa (Art. 73). Ningún día se pierde: lo no gozado se paga
    (Art. 76).
    """
    # Una antigüedad que deja tres períodos cumplidos sin gozar.
    await ejecutar(
        """update public.users set fecha_ingreso = current_date - interval '5 years'
            where id = %s""", (empleado["id"],))
    await ejecutar("delete from public.vacation_periods where user_id = %s", (empleado["id"],))
    await obtener_uno("select public.generar_periodos_vacaciones(%s) as n", (empleado["id"],))
    await ejecutar("delete from public.notifications where user_id = %s", (empleado["id"],))

    acumula = await obtener_uno(
        "select periodos_sin_gozar, dias_de_anios_cumplidos "
        "from public.v_acumulacion_excesiva where user_id = %s", (empleado["id"],))
    assert acumula is not None, "cinco años sin gozar nada deberían figurar"
    assert acumula["periodos_sin_gozar"] >= 3

    await obtener_uno("select public.generar_alertas_vacaciones() as r")

    avisos = await obtener_todos(
        """select titulo, mensaje from public.notifications
            where user_id = %s and tipo = 'vacaciones_acumuladas'""", (empleado["id"],))
    assert avisos, "debería avisarse de la acumulación"
    texto = " ".join(a["mensaje"] for a in avisos)
    assert "Ningún día se pierde" in texto, "el aviso tiene que decir que los días no se pierden"
    assert "Art. 76" in texto, "y citar el artículo que dice que se pagan"
    for aviso in avisos:
        assert "Perderá" not in aviso["titulo"]


async def test_quien_esta_al_dia_no_recibe_ese_aviso(empleado):
    await ejecutar("delete from public.notifications where user_id = %s", (empleado["id"],))
    await obtener_uno("select public.generar_periodos_vacaciones(%s) as n", (empleado["id"],))
    # Consumido todo lo de años cumplidos: no arrastra nada.
    await ejecutar(
        """update public.vacation_periods set dias_consumidos = dias_asignados
            where user_id = %s and devengado""", (empleado["id"],))

    await obtener_uno("select public.generar_alertas_vacaciones() as r")
    avisos = await obtener_todos(
        """select titulo from public.notifications
            where user_id = %s and tipo = 'vacaciones_acumuladas'""", (empleado["id"],))
    assert not avisos, "quien está al día no tiene por qué recibir este aviso"


async def test_el_texto_del_articulo_75_es_el_de_la_ley():
    """Citar mal un artículo en un sistema oficial no es un detalle de estilo.

    El sistema tenía guardado «Si no las gozare, perderá el derecho sobre las
    acumuladas de más de tres años». Esa frase no está en la ley, y de ella
    salía todo lo demás: la fecha de vencimiento, los 9.554 días marcados
    como perdidos y las alertas de severidad crítica.
    """
    art75 = await obtener_uno(
        "select texto from public.legal_references where codigo = 'CT_ART_75'")
    assert "perderá" not in art75["texto"].lower(), (
        "el Art. 75 no habla de perder días; el Art. 76 dice que se pagan"
    )
    assert "tres años" in art75["texto"]

    art76 = await obtener_uno(
        "select texto from public.legal_references where codigo = 'CT_ART_76'")
    assert art76 is not None, "faltaba el artículo que dice qué pasa con lo no gozado"
    assert "equivalente de las remuneraciones" in art76["texto"]

    const = await obtener_uno(
        "select texto from public.legal_references where codigo = 'CONST_ART_326_2'")
    assert const is not None
    assert "irrenunciables" in const["texto"]
