"""El historial de vacaciones de antes de este sistema.

Talento Humano llevaba una hoja con 3.339 vacaciones de 346 personas. Sin
ella, un colaborador entraba, veía su saldo y no podía responder la pregunta
más simple que se le ocurre a cualquiera: «¿cuándo tomé vacaciones la última
vez?».

Lo delicado de cargarla es el emparejamiento: la hoja identifica por NOMBRE y
el sistema por CÉDULA. Equivocarse ahí significa cargarle a una persona las
vacaciones de otra, y eso no se nota nunca. De ahí las dos reglas que fijan
estas pruebas:

  · Lo cargado NO toca el saldo. El saldo ya venía de esta misma hoja y es
    correcto; sumarlo otra vez sería descontar dos veces los mismos días.
  · Lo de antes y lo de ahora conviven en una línea de tiempo, pero nunca
    mezclados sin distinguir: quien ve «15 días en marzo de 2019» tiene
    derecho a saber de dónde sale ese dato.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA


@pytest.fixture
async def auth(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def historico(empleado):
    await ejecutar("delete from public.vacaciones_historicas where user_id = %s",
                   (empleado["id"],))
    for ini, fin, dias, fila in [
        ("2022-01-20", "2022-01-26", 7, 1025),
        ("2023-03-10", "2023-03-12", 3, 1029),
        ("2024-02-14", "2024-02-18", 5, 1036),
    ]:
        await obtener_uno(
            """insert into public.vacaciones_historicas
                 (user_id, fecha_inicio, fecha_fin, dias, fila_origen)
               values (%s, %s, %s, %s, %s) returning id""",
            (empleado["id"], ini, fin, dias, fila))
    yield
    await ejecutar("delete from public.vacaciones_historicas where user_id = %s",
                   (empleado["id"],))


async def test_el_historial_no_toca_el_saldo(empleado, historico):
    """Sumarlo otra vez seria descontar dos veces los mismos dias."""
    antes = await obtener_uno(
        "select dias_vacaciones from public.users where id = %s", (empleado["id"],))
    await obtener_uno(
        """insert into public.vacaciones_historicas
             (user_id, fecha_inicio, fecha_fin, dias)
           values (%s, '2021-05-03', '2021-05-07', 5) returning id""",
        (empleado["id"],))
    despues = await obtener_uno(
        "select dias_vacaciones from public.users where id = %s", (empleado["id"],))
    assert despues["dias_vacaciones"] == antes["dias_vacaciones"]


async def test_cargar_dos_veces_no_duplica(empleado, historico):
    """Volver a pasar el mismo archivo tiene que ser inofensivo."""
    antes = await obtener_uno(
        "select count(*) as n from public.vacaciones_historicas where user_id = %s",
        (empleado["id"],))
    await ejecutar(
        """insert into public.vacaciones_historicas
             (user_id, fecha_inicio, fecha_fin, dias)
           values (%s, '2022-01-20', '2022-01-26', 7)
           on conflict (user_id, fecha_inicio, fecha_fin) do nothing""",
        (empleado["id"],))
    despues = await obtener_uno(
        "select count(*) as n from public.vacaciones_historicas where user_id = %s",
        (empleado["id"],))
    assert despues["n"] == antes["n"]


async def test_no_se_admite_un_rango_invertido(empleado):
    with pytest.raises(Exception) as fallo:
        await ejecutar(
            """insert into public.vacaciones_historicas
                 (user_id, fecha_inicio, fecha_fin, dias)
               values (%s, '2022-03-10', '2022-03-01', 5)""",
            (empleado["id"],))
    assert "historicas_rango" in str(fallo.value)


async def test_ni_dias_en_cero(empleado):
    with pytest.raises(Exception):
        await ejecutar(
            """insert into public.vacaciones_historicas
                 (user_id, fecha_inicio, fecha_fin, dias)
               values (%s, '2022-03-01', '2022-03-01', 0)""",
            (empleado["id"],))


async def test_la_persona_ve_su_historial(cliente, auth, historico):
    r = await cliente.get("/mi-historial", headers=auth)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["veces"] == 3
    assert cuerpo["total_dias"] == 15
    assert cuerpo["desde_la_hoja"] == 3
    # Más reciente primero: es el orden en que a alguien le interesa mirarlo.
    fechas = [v["fecha_inicio"] for v in cuerpo["vacaciones"]]
    assert fechas == sorted(fechas, reverse=True)


async def test_cada_registro_dice_de_donde_viene(cliente, auth, historico):
    """Mezclarlas sin distinguir seria el error a evitar."""
    r = await cliente.get("/mi-historial", headers=auth)
    for v in r.json()["vacaciones"]:
        assert v["procedencia"] in ("historico", "solicitud")
        assert v["detalle"], "cada registro tiene que decir de dónde sale"
        if v["procedencia"] == "historico":
            assert v["folio"] is None, (
                "un registro de la hoja no pasó por este sistema: no puede "
                "tener número de solicitud"
            )


async def test_nadie_ve_el_historial_de_otro(cliente, auth, empleado, historico):
    """Es la comprobación que importa cuando se carga por nombre."""
    otro = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values ('1700000076', 'Otro Con Historial', 'otrohist@api.test',
                   'empleado', current_date - 800)
           on conflict (cedula) do update set nombre = excluded.nombre returning id""")
    await obtener_uno(
        """insert into public.vacaciones_historicas
             (user_id, fecha_inicio, fecha_fin, dias)
           values (%s, '2020-08-01', '2020-08-10', 10) returning id""", (otro["id"],))
    try:
        r = await cliente.get("/mi-historial", headers=auth)
        fechas = [v["fecha_inicio"] for v in r.json()["vacaciones"]]
        assert "2020-08-01" not in fechas, "se está viendo el historial de otra persona"
        assert r.json()["veces"] == 3
    finally:
        await ejecutar("delete from public.users where cedula = '1700000076'")


async def test_el_resumen_cuadra_con_lo_cargado(empleado, historico):
    fila = await obtener_uno(
        """select vacaciones_registradas, dias_gozados_historicos
             from public.v_historico_resumen where user_id = %s""", (empleado["id"],))
    assert fila["vacaciones_registradas"] == 3
    assert float(fila["dias_gozados_historicos"]) == 15
