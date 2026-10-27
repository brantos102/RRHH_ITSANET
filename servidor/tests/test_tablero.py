"""El tablero de indicadores, por bloques que se encienden y se apagan.

Dos cosas se vigilan aquí, y la segunda es la que importa:

  · Que las cifras sean las de la base y no una copia que envejece. Un
    tablero con números guardados miente en cuanto alguien aprueba una
    solicitud, y lo peor es que miente con aire de informe.

  · Que no se escape ni un nombre. Son agregados: «cuántos están de
    vacaciones» es un número, y quién está es el calendario del equipo, que
    tiene sus propios permisos. Un tablero que enseña nombres a quien no le
    toca es una fuga de datos con buena presentación (LOPDP, Art. 10).
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from app.reglas.tablero import tablero_indicadores
from tests.conftest import Sql, insertar
from tests.test_panel_configurable import admin_auth  # noqa: F401
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, lunes_sin_feriados,
                                      rrhh_auth)


@pytest.fixture(autouse=True)
async def _tablero_de_fabrica():
    """Cada prueba parte del tablero recién instalado."""
    antes = {f["clave"]: (f["visible"], f["orden"], f["titulo"], json.dumps(f["ajustes"]))
             for f in await obtener_todos(
                 "select clave, visible, orden, titulo, ajustes from tablero_bloques")}
    yield
    for clave, (visible, orden, titulo, ajustes) in antes.items():
        await ejecutar(
            """update tablero_bloques
                  set visible = %s, orden = %s, titulo = %s, ajustes = %s,
                      actualizado_en = null, actualizado_por = null
                where clave = %s""",
            (visible, orden, titulo, ajustes, clave))


# ------------------------------------------------------------- los números
async def test_los_nueve_indicadores_salen_con_su_cifra(cliente, rrhh_auth):
    r = await cliente.get("/tablero", headers=rrhh_auth)
    assert r.status_code == 200
    bloques = r.json()["bloques"]
    assert len(bloques) == 9
    for b in bloques:
        assert b["cifra"] is not None, b["clave"]
        assert b["pregunta"], b["clave"]
        assert "error" not in b, f"{b['clave']}: {b.get('error')}"


async def test_cada_cifra_viene_con_la_hora_en_que_se_calculo(cliente, rrhh_auth):
    """Un tablero sin ella se queda abierto toda la tarde y se lee como de ahora."""
    r = await cliente.get("/tablero", headers=rrhh_auth)
    assert r.json()["calculado_en"]


async def test_los_activos_son_los_activos(cliente, rrhh_auth):
    cuerpo = (await cliente.get("/tablero", headers=rrhh_auth)).json()
    activos = {b["clave"]: b for b in cuerpo["bloques"]}["activos"]
    real = await obtener_uno("select count(*) as n from users where activo")
    assert activos["cifra"] == real["n"]


async def test_sin_jefe_cuenta_a_los_que_no_tienen_jefe(cliente, rrhh_auth, jefe_auth,
                                                        empleado):
    """`jefe_auth` le pone jefe al empleado, así que parte de tenerlo."""
    d = {b["clave"]: b for b in
         (await cliente.get("/tablero", headers=rrhh_auth)).json()["bloques"]}["sin_jefe"]
    real = await obtener_uno(
        "select count(*) as n from users where activo and jefe_id is null")
    assert d["cifra"] == real["n"]

    await ejecutar("update users set jefe_id = null where id = %s", (empleado["id"],))
    try:
        de_nuevo = {b["clave"]: b for b in
                    (await cliente.get("/tablero", headers=rrhh_auth)).json()["bloques"]}["sin_jefe"]
        assert de_nuevo["cifra"] == real["n"] + 1
    finally:
        jefe = await obtener_uno("select id from users where cedula = %s", (CEDULA_JEFE_R,))
        await ejecutar("update users set jefe_id = %s where id = %s", (jefe["id"], empleado["id"]))


async def test_los_de_hoy_cuentan_hoy(cliente, auth, jefe_auth, rrhh_auth, empleado):
    """Lo que de verdad decide si el turno se cubre."""
    antes = {b["clave"]: b for b in
             (await cliente.get("/tablero", headers=rrhh_auth)).json()["bloques"]}["ausentes_hoy"]

    # Una ausencia aprobada que cubre hoy. Se arma en tres pasos porque el
    # sistema no deja pedir vacaciones para hoy —hacen falta diez días de
    # anticipación— ni cambiar las fechas de una ya aprobada, y ambas reglas
    # están bien donde están: lo que se mide aquí es el conteo, no ellas.
    # El saldo al solicitar lo anota el sistema al crear la solicitud (en
    # PostgreSQL lo hacía un disparador); insertando directo hay que darlo.
    saldo = (await obtener_uno("select dias_vacaciones as s from users where id = %s",
                               (empleado["id"],)))["s"]
    fila = await insertar("requests", user_id=empleado["id"], tipo="vacacion",
                          saldo_al_solicitar=saldo,
                          fecha_inicio=Sql("CURRENT_DATE() + INTERVAL 60 DAY"),
                          fecha_fin=Sql("CURRENT_DATE() + INTERVAL 67 DAY"),
                          descripcion="Ausencia de control del tablero")
    await ejecutar(
        """update requests
              set fecha_inicio = current_date(), fecha_fin = current_date() + interval 7 day
            where id = %s""", (fila["id"],))
    # Las dos etapas, en orden: la máquina de estados no admite saltos, y hace
    # bien en no admitirlos.
    for etapa in ("pendiente_rrhh", "aprobado"):
        await ejecutar("update requests set estado = %s where id = %s",
                       (etapa, fila["id"]))
    try:
        d = {b["clave"]: b for b in
             (await cliente.get("/tablero", headers=rrhh_auth)).json()["bloques"]}["ausentes_hoy"]
        assert d["cifra"] == antes["cifra"] + 1
        assert d["detalle"]["vacaciones"] == antes["detalle"]["vacaciones"] + 1
        # El total contra el que se compara va DENTRO del detalle: fuera, la
        # pantalla lo leía como vacío e imprimía «de — activos».
        assert d["detalle"]["de"] > 0
    finally:
        await ejecutar("delete from requests where id = %s", (fila["id"],))


async def test_el_crecimiento_trae_un_renglon_por_mes(cliente, rrhh_auth):
    cuerpo = (await cliente.get("/tablero", headers=rrhh_auth)).json()
    c = {b["clave"]: b for b in cuerpo["bloques"]}["crecimiento"]
    assert len(c["detalle"]["meses"]) == 12
    assert all({"mes", "altas", "bajas"} <= set(m) for m in c["detalle"]["meses"])


async def test_las_areas_vienen_de_mayor_a_menor(cliente, rrhh_auth):
    cuerpo = (await cliente.get("/tablero", headers=rrhh_auth)).json()
    areas = {b["clave"]: b for b in cuerpo["bloques"]}["por_area"]["detalle"]["areas"]
    personas = [a["personas"] for a in areas]
    assert personas == sorted(personas, reverse=True)


# ------------------------------------------------------- ni un solo nombre
async def test_el_tablero_no_lleva_nombres_ni_cedulas(cliente, rrhh_auth, empleado):
    """La comprobación que justifica todo el diseño del tablero."""
    crudo = (await cliente.get("/tablero", headers=rrhh_auth)).text
    persona = await obtener_uno(
        "select nombre, cedula, email from users where id = %s", (empleado["id"],))
    for dato in (persona["nombre"], persona["cedula"], persona["email"]):
        if dato:
            assert dato not in crudo, f"el tablero está filtrando «{dato}»"
    # Las áreas sí salen: son el reparto de la plantilla, no una persona.
    assert "areas" in crudo


# ------------------------------------------------------------ configurarlo
async def test_apagar_un_indicador_lo_quita_de_la_pantalla(cliente, rrhh_auth):
    r = await cliente.patch("/admin/tablero/pasivo", headers=rrhh_auth,
                            json={"visible": False})
    assert r.status_code == 200
    assert "oculto" in r.json()["mensaje"]
    claves = {b["clave"] for b in
              (await cliente.get("/tablero", headers=rrhh_auth)).json()["bloques"]}
    assert "pasivo" not in claves
    assert len(claves) == 8


async def test_apagarlo_tambien_deja_de_calcularlo(cliente, rrhh_auth):
    """Apagar un bloque lo quita de la pantalla Y deja de costarlo."""
    await cliente.patch("/admin/tablero/crecimiento", headers=rrhh_auth,
                        json={"visible": False})
    filas = await tablero_indicadores()
    assert "crecimiento" not in {f["clave"] for f in filas}


async def test_el_orden_se_respeta(cliente, rrhh_auth):
    await cliente.patch("/admin/tablero/papeles", headers=rrhh_auth, json={"orden": 1})
    bloques = (await cliente.get("/tablero", headers=rrhh_auth)).json()["bloques"]
    assert bloques[0]["clave"] == "papeles"


async def test_se_puede_renombrar_un_indicador(cliente, rrhh_auth):
    await cliente.patch("/admin/tablero/pasivo", headers=rrhh_auth,
                        json={"titulo": "Deuda de vacaciones"})
    bloques = {b["clave"]: b for b in
               (await cliente.get("/tablero", headers=rrhh_auth)).json()["bloques"]}
    assert bloques["pasivo"]["titulo"] == "Deuda de vacaciones"


async def test_un_ajuste_cambia_el_calculo(cliente, rrhh_auth):
    """Si el ajuste no moviera el número sería un adorno."""
    antes = {b["clave"]: b for b in
             (await cliente.get("/tablero", headers=rrhh_auth)).json()["bloques"]}["crecimiento"]
    assert len(antes["detalle"]["meses"]) == 12

    r = await cliente.patch("/admin/tablero/crecimiento", headers=rrhh_auth,
                            json={"ajustes": {"meses": 3}})
    assert r.status_code == 200
    d = {b["clave"]: b for b in
         (await cliente.get("/tablero", headers=rrhh_auth)).json()["bloques"]}["crecimiento"]
    assert len(d["detalle"]["meses"]) == 3


async def test_un_ajuste_fuera_de_rango_se_explica(cliente, rrhh_auth):
    r = await cliente.patch("/admin/tablero/crecimiento", headers=rrhh_auth,
                            json={"ajustes": {"meses": 900}})
    assert r.status_code == 422
    assert "entre" in r.json()["detail"]["mensaje"]


async def test_un_ajuste_que_ese_indicador_no_tiene_se_rechaza(cliente, rrhh_auth):
    r = await cliente.patch("/admin/tablero/sin_jefe", headers=rrhh_auth,
                            json={"ajustes": {"meses": 3}})
    assert r.status_code == 422
    assert "no es un ajuste" in r.json()["detail"]["mensaje"]


async def test_un_indicador_inventado_da_404(cliente, rrhh_auth):
    r = await cliente.patch("/admin/tablero/lo_que_sea", headers=rrhh_auth,
                            json={"visible": False})
    assert r.status_code == 404


async def test_el_cambio_queda_en_la_bitacora(cliente, rrhh_auth):
    await cliente.patch("/admin/tablero/pasivo", headers=rrhh_auth,
                        json={"ajustes": {"umbral_persona": 45}})
    reg = await obtener_uno(
        """select detalle from audit_logs
            where accion = 'tablero_modificado' and entidad_id = 'pasivo'
            order by created_at desc limit 1""")
    assert reg["detalle"]["ahora"]["ajustes"]["umbral_persona"] == 45


# ------------------------------------------------------------- quién mira
async def test_el_colaborador_no_entra_al_tablero(cliente, auth):
    assert (await cliente.get("/tablero", headers=auth)).status_code == 403
    assert (await cliente.get("/admin/tablero", headers=auth)).status_code == 403


async def test_el_jefe_tampoco(cliente, jefe_auth):
    """Ve a su equipo en el calendario; los agregados de la empresa, no."""
    assert (await cliente.get("/tablero", headers=jefe_auth)).status_code == 403


async def test_administracion_lo_configura(cliente, admin_auth):
    r = await cliente.patch("/admin/tablero/papeles", headers=admin_auth,
                            json={"visible": False})
    assert r.status_code == 200
