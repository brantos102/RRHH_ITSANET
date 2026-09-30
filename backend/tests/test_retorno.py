"""Quién volvió, cuándo, y si se pasó de la hora que declaró.

El tipo de acceso `retorno_empleado` existía desde la primera migración y
nadie lo escribía: garita solo anotaba la salida. De un permiso de 12:00 a
15:00 quedaba constancia de que la persona salió y ninguna de si volvió a las
15:00 o a las 18:00. Ahora el mismo código leído por segunda vez es el regreso.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, lunes_sin_feriados,
                                      rrhh_auth)

CEDULA_GUARDIA = "1713175071"


@pytest.fixture
async def guardia_auth(cliente, codigos, empleado):
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s, 'Garita Prueba', 'garita@api.test', 'guardia', current_date - 800)
           on conflict (cedula) do update set rol = 'guardia', activo = true
           returning id""",
        (CEDULA_GUARDIA,),
    )
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_GUARDIA})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_GUARDIA, "codigo": codigos[-1]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth,
                                      hora_inicio: str = "12:00",
                                      hora_fin: str = "15:00") -> dict:
    """Un permiso de hoy, por horas, ya aprobado y con su QR."""
    tipo = await obtener_uno(
        """select id from public.permission_types
            where admite_horas and not requiere_adjunto and activo
              and (max_horas is null or max_horas >= 4) order by id limit 1""")
    creada = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": tipo["id"],
        "fecha_inicio": str(date.today()), "fecha_fin": str(date.today()),
        "hora_inicio": hora_inicio, "hora_fin": hora_fin,
        "descripcion": "Diligencia personal de la tarde",
        "justificacion": "Turno asignado para esa tarde.", "firmar": False})
    assert creada.status_code == 201, creada.text
    cuerpo = creada.json()
    for etapa in (jefe_auth, rrhh_auth):
        await cliente.post(f"/aprobaciones/{cuerpo['id']}/decidir", headers=etapa,
                           json={"accion": "aprobar"})
    fila = await obtener_uno(
        "select qr_hash, folio from public.requests where id = %s", (cuerpo["id"],))
    return {"id": cuerpo["id"], "qr": str(fila["qr_hash"]), "folio": fila["folio"]}


async def test_la_primera_lectura_es_salida(cliente, auth, jefe_auth, rrhh_auth, guardia_auth):
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    r = await cliente.post("/garita/validar-qr", headers=guardia_auth,
                           json={"codigo": p["qr"]})
    assert r.status_code == 200, r.text
    assert r.json()["autorizado"] is True
    assert r.json()["movimiento"] == "salida"


async def test_la_segunda_lectura_es_el_regreso(cliente, auth, jefe_auth, rrhh_auth, guardia_auth):
    """Antes quedaba anotada como otra salida, y el regreso no existía."""
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})

    r = await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["movimiento"] == "retorno"
    assert "Regreso registrado" in cuerpo["motivo"]

    fila = await obtener_uno(
        "select retorno_en, retorno_exceso_minutos from public.requests where id = %s",
        (p["id"],))
    assert fila["retorno_en"] is not None, "debe quedar la hora real de regreso"
    assert fila["retorno_exceso_minutos"] is not None


async def test_queda_en_la_bitacora_de_accesos(cliente, auth, jefe_auth, rrhh_auth, guardia_auth):
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})

    accesos = await obtener_todos(
        """select tipo_acceso::text from public.access_logs
            where request_id = %s order by created_at""", (p["id"],))
    tipos = [a["tipo_acceso"] for a in accesos]
    assert tipos == ["salida_empleado", "retorno_empleado"], tipos


async def test_volver_tarde_queda_medido(cliente, auth, jefe_auth, rrhh_auth, guardia_auth):
    """La hora declarada ya pasó: el sistema debe decir cuánto se excedió."""
    # Se declara el regreso a una hora que ya pasó hoy.
    # Un horario de madrugada: cuando corre la prueba ya pasó de largo.
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth,
                                          hora_inicio="00:05", hora_fin="00:30")
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})
    r = await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})

    retorno = r.json()["retorno"]
    assert retorno["exceso_minutos"] > 0, "volvió después de la hora declarada"
    assert retorno["a_tiempo"] is False
    assert "después de la hora autorizada" in r.json()["motivo"]


async def test_no_se_registra_un_regreso_sin_salida(cliente, auth, jefe_auth, rrhh_auth,
                                                    guardia_auth, empleado):
    """Sería anotar que volvió alguien que nunca se fue."""
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    with pytest.raises(Exception) as fallo:
        await obtener_uno(
            "select public.registrar_retorno(%s, %s) as r",
            (p["id"], (await obtener_uno(
                "select id from public.users where cedula = %s", (CEDULA_GUARDIA,)))["id"]),
        )
    assert "salida" in str(fallo.value).lower()


async def test_el_tercer_paso_no_inventa_otro_movimiento(cliente, auth, jefe_auth, rrhh_auth,
                                                         guardia_auth):
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    for _ in range(2):
        await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})

    r = await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})
    assert r.json()["movimiento"] == "ya_completo"

    accesos = await obtener_todos(
        "select count(*) as n from public.access_logs where request_id = %s", (p["id"],))
    assert accesos[0]["n"] == 2, "no debe acumular movimientos falsos"


async def test_la_vista_de_informes_clasifica_la_puntualidad(cliente, auth, jefe_auth,
                                                             rrhh_auth, guardia_auth):
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth,
                                          hora_inicio="00:05", hora_fin="00:30")
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})

    fila = await obtener_uno(
        "select puntualidad, salio_en, retorno_en from public.v_retornos where folio = %s",
        (p["folio"],))
    assert fila is not None, "la solicitud con salida debe aparecer en la vista"
    assert fila["puntualidad"] == "volvió tarde"
    assert fila["salio_en"] is not None and fila["retorno_en"] is not None


async def test_solo_garita_o_talento_humano_registran_el_retorno(cliente, auth, jefe_auth,
                                                                 rrhh_auth, guardia_auth,
                                                                 empleado):
    """Un empleado no se marca a sí mismo la vuelta."""
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)
    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})

    with pytest.raises(Exception) as fallo:
        await obtener_uno("select public.registrar_retorno(%s, %s) as r",
                          (p["id"], empleado["id"]))
    assert "garita" in str(fallo.value).lower() or "solo" in str(fallo.value).lower()


async def test_volver_antes_de_hora_no_es_un_exceso_negativo(
    cliente, auth, jefe_auth, rrhh_auth, guardia_auth
):
    """Volver antes no es un exceso de nada.

    Quedaba anotado como «exceso: -528 minutos». La clasificación de
    puntualidad seguía siendo correcta —solo cuenta como tarde lo que pasa de
    cero—, pero cualquier informe que sumara o promediara esa columna quedaba
    falseado: los regresos puntuales restaban. La hora exacta no se pierde,
    está en `retorno_en`.
    """
    p = await _permiso_por_horas_aprobado(cliente, auth, jefe_auth, rrhh_auth)

    # Una franja que termina mucho después de ahora: el regreso es temprano.
    await ejecutar(
        """update public.requests
              set hora_inicio = '00:01', hora_fin = '23:59'
            where id = %s""", (p["id"],))

    await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})
    r = await cliente.post("/garita/validar-qr", headers=guardia_auth, json={"codigo": p["qr"]})
    assert r.status_code == 200, r.text
    assert r.json()["retorno"]["exceso_minutos"] == 0
    assert r.json()["retorno"]["a_tiempo"] is True

    fila = await obtener_uno(
        "select retorno_exceso_minutos from public.requests where id = %s", (p["id"],))
    assert fila["retorno_exceso_minutos"] == 0
