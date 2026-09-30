"""Personal temporal: nadie queda sin salida registrada.

Es un sistema pequeño dentro del grande y con otra lógica: el temporal viene
por jornadas y se le paga por lo que trabajó esa semana. De ahí sale la regla
que manda todo lo demás —una jornada sin cerrar no se puede pagar—, y la
decisión de no inventar salidas: una salida automática a las seis de la tarde
convertiría un dato que falta en uno falso, que es peor que no tenerlo.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA

CED_GUARDIA_T = "1713175071"
CED_RRHH_T = "1700000068"
CED_OPERARIO = "1300000054"


@pytest.fixture
async def guardia_auth(cliente, codigos, empleado):
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s, 'Guardia Temporal', 'guardiat@api.test', 'guardia',
                   current_date - 400)
           on conflict (cedula) do update set rol = 'guardia' returning id""",
        (CED_GUARDIA_T,))
    await cliente.post("/auth/solicitar-token", json={"cedula": CED_GUARDIA_T})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CED_GUARDIA_T, "codigo": codigos[-1]})
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def rrhh_auth(cliente, codigos, empleado):
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s, 'Talento Temporal', 'rrhht@api.test', 'rrhh', current_date - 900)
           on conflict (cedula) do update set rol = 'rrhh' returning id""",
        (CED_RRHH_T,))
    await cliente.post("/auth/solicitar-token", json={"cedula": CED_RRHH_T})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CED_RRHH_T, "codigo": codigos[-1]})
    yield {"Authorization": f"Bearer {r.json()['access_token']}"}
    await ejecutar("delete from public.users where cedula = %s", (CED_RRHH_T,))


@pytest.fixture
async def operario(rrhh_auth, cliente):
    await ejecutar("delete from public.personal_temporal where cedula = %s", (CED_OPERARIO,))
    r = await cliente.post("/temporal", headers=rrhh_auth, json={
        "cedula": CED_OPERARIO, "nombre": "Operario De Prueba",
        "labor": "Estibador", "proveedor": "Servicios ACME", "valor_hora": 4.5,
    })
    assert r.status_code == 201, r.text
    yield {"id": r.json()["id"], "cedula": CED_OPERARIO}
    await ejecutar("delete from public.personal_temporal where cedula = %s", (CED_OPERARIO,))


# ----------------------------------------------------------------- registro
async def test_el_temporal_no_es_un_usuario_del_sistema(operario):
    """No tiene acceso, ni vacaciones, ni jefe: no está en `users`."""
    fila = await obtener_uno(
        "select 1 as x from public.users where cedula = %s", (CED_OPERARIO,))
    assert fila is None, (
        "un operario temporal en `users` tendría saldo de vacaciones que nadie "
        "le debe y un acceso al sistema que no necesita"
    )


async def test_la_cedula_se_valida(cliente, rrhh_auth):
    r = await cliente.post("/temporal", headers=rrhh_auth,
                           json={"cedula": "1234567890", "nombre": "Cedula Falsa"})
    assert r.status_code == 422, r.text


async def test_la_garita_no_da_de_alta_gente(cliente, guardia_auth):
    """Registrar quién trabaja es de Talento Humano; la garita registra horas."""
    r = await cliente.post("/temporal", headers=guardia_auth,
                           json={"cedula": CED_OPERARIO, "nombre": "Alguien"})
    assert r.status_code == 403


# ----------------------------------------------------------------- jornadas
async def test_entrada_y_salida(cliente, guardia_auth, operario):
    r = await cliente.post("/temporal/entrada", headers=guardia_auth,
                           json={"temporal_id": operario["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["movimiento"] == "entrada"

    dentro = await cliente.get("/temporal/dentro", headers=guardia_auth)
    assert operario["id"] in [d["temporal_id"] for d in dentro.json()]

    r = await cliente.post("/temporal/salida", headers=guardia_auth,
                           json={"temporal_id": operario["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["movimiento"] == "salida"
    assert r.json()["horas"] is not None

    dentro = await cliente.get("/temporal/dentro", headers=guardia_auth)
    assert operario["id"] not in [d["temporal_id"] for d in dentro.json()]


async def test_no_se_entra_dos_veces_el_mismo_dia(cliente, guardia_auth, operario):
    await cliente.post("/temporal/entrada", headers=guardia_auth,
                       json={"temporal_id": operario["id"]})
    r = await cliente.post("/temporal/entrada", headers=guardia_auth,
                           json={"temporal_id": operario["id"]})
    assert r.status_code >= 400
    assert "ya tiene su entrada" in str(r.json())


async def test_no_sale_quien_no_entro(cliente, guardia_auth, operario):
    r = await cliente.post("/temporal/salida", headers=guardia_auth,
                           json={"temporal_id": operario["id"]})
    assert r.status_code >= 400
    assert "No puede salir quien no entró" in str(r.json())


async def test_no_se_sale_dos_veces(cliente, guardia_auth, operario):
    await cliente.post("/temporal/entrada", headers=guardia_auth,
                       json={"temporal_id": operario["id"]})
    await cliente.post("/temporal/salida", headers=guardia_auth,
                       json={"temporal_id": operario["id"]})
    r = await cliente.post("/temporal/salida", headers=guardia_auth,
                           json={"temporal_id": operario["id"]})
    assert r.status_code >= 400
    assert "ya registró su salida" in str(r.json())


async def test_una_sola_jornada_por_dia(cliente, guardia_auth, operario):
    """Dos filas del mismo día se pagarían dos veces."""
    await cliente.post("/temporal/entrada", headers=guardia_auth,
                       json={"temporal_id": operario["id"]})
    with pytest.raises(Exception):
        await ejecutar(
            """insert into public.jornadas_temporales (temporal_id, fecha)
               values (%s, current_date)""", (operario["id"],))


# --------------------------------------------------- lo que quedó sin cerrar
async def test_una_jornada_de_ayer_sin_salida_se_señala(cliente, guardia_auth, operario):
    await obtener_uno(
        """insert into public.jornadas_temporales
             (temporal_id, fecha, entrada_en)
           values (%s, current_date - 1, now() - interval '1 day')
           returning id""", (operario["id"],))

    r = await cliente.get("/temporal/sin-cerrar", headers=guardia_auth)
    assert r.status_code == 200, r.text
    pendientes = [j for j in r.json() if j["temporal_id"] == operario["id"]]
    assert pendientes, "una jornada sin salida tiene que aparecer en la lista"
    assert pendientes[0]["dias_sin_cerrar"] == 1


async def test_el_sistema_no_inventa_una_hora_de_salida(cliente, guardia_auth, operario):
    """Una salida automática convertiría un dato que falta en uno falso."""
    fila = await obtener_uno(
        """insert into public.jornadas_temporales (temporal_id, fecha, entrada_en)
           values (%s, current_date - 2, now() - interval '2 days')
           returning id""", (operario["id"],))
    guardada = await obtener_uno(
        "select salida_en, horas from public.jornadas_temporales where id = %s",
        (fila["id"],))
    assert guardada["salida_en"] is None
    assert guardada["horas"] is None


async def test_talento_humano_cierra_a_mano_y_queda_constancia(
    cliente, rrhh_auth, operario
):
    fila = await obtener_uno(
        """insert into public.jornadas_temporales (temporal_id, fecha, entrada_en)
           values (%s, current_date - 1, (current_date - 1)::timestamptz + interval '8 hours')
           returning id""", (operario["id"],))

    r = await cliente.post(f"/temporal/jornadas/{fila['id']}/cerrar", headers=rrhh_auth,
                           json={"salida": "2026-09-29T17:00:00Z",
                                 "motivo": "Se retiró sin timbrar; lo confirma el supervisor"})
    assert r.status_code == 200, r.text

    guardada = await obtener_uno(
        """select salida_en, horas, observacion, registro_salida
             from public.jornadas_temporales where id = %s""", (fila["id"],))
    assert guardada["salida_en"] is not None
    assert guardada["horas"] is not None
    assert "Cerrada a mano" in guardada["observacion"]
    assert guardada["registro_salida"] is not None


async def test_cerrar_a_mano_exige_explicacion(cliente, rrhh_auth, operario):
    fila = await obtener_uno(
        """insert into public.jornadas_temporales (temporal_id, fecha, entrada_en)
           values (%s, current_date - 1, now() - interval '1 day') returning id""",
        (operario["id"],))
    r = await cliente.post(f"/temporal/jornadas/{fila['id']}/cerrar", headers=rrhh_auth,
                           json={"salida": "2026-09-29T17:00:00Z", "motivo": "ok"})
    assert r.status_code == 422


async def test_la_garita_no_cierra_jornadas_a_mano(cliente, guardia_auth, operario):
    fila = await obtener_uno(
        """insert into public.jornadas_temporales (temporal_id, fecha, entrada_en)
           values (%s, current_date - 1, now() - interval '1 day') returning id""",
        (operario["id"],))
    r = await cliente.post(f"/temporal/jornadas/{fila['id']}/cerrar", headers=guardia_auth,
                           json={"salida": "2026-09-29T17:00:00Z",
                                 "motivo": "Intento de cerrar sin ser Talento Humano"})
    assert r.status_code == 403


# ------------------------------------------------------------- la liquidación
async def test_la_semana_cuenta_horas_y_valor(cliente, rrhh_auth, operario):
    await obtener_uno(
        """insert into public.jornadas_temporales
             (temporal_id, fecha, entrada_en, salida_en, horas)
           values (%s, current_date, now() - interval '8 hours', now(), 8)
           returning id""", (operario["id"],))

    r = await cliente.get("/temporal/semana", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    mio = next(p for p in cuerpo["personas"] if p["temporal_id"] == operario["id"])
    assert mio["horas"] == 8
    assert mio["dias"] == 1
    assert mio["total"] == 36.0, "8 horas por 4,50 la hora"
    assert cuerpo["jornadas_sin_cerrar"] == 0
    assert cuerpo["aviso"] is None


async def test_el_total_avisa_cuando_esta_incompleto(cliente, rrhh_auth, operario):
    """Sumar una columna que no cuadra es peor que no sumarla."""
    await obtener_uno(
        """insert into public.jornadas_temporales (temporal_id, fecha, entrada_en)
           values (%s, current_date, now() - interval '3 hours') returning id""",
        (operario["id"],))

    r = await cliente.get("/temporal/semana", headers=rrhh_auth)
    cuerpo = r.json()
    assert cuerpo["jornadas_sin_cerrar"] >= 1
    assert cuerpo["aviso"] and "incompleto" in cuerpo["aviso"]


async def test_sin_valor_hora_se_dan_las_horas_sin_valorar(cliente, rrhh_auth, operario):
    """Hay quien se paga por obra. Las horas siguen siendo lo que se presenció."""
    await cliente.patch(f"/temporal/{operario['id']}", headers=rrhh_auth,
                        json={"valor_hora": None})
    await obtener_uno(
        """insert into public.jornadas_temporales
             (temporal_id, fecha, entrada_en, salida_en, horas)
           values (%s, current_date, now() - interval '6 hours', now(), 6)
           returning id""", (operario["id"],))

    r = await cliente.get("/temporal/semana", headers=rrhh_auth)
    mio = next(p for p in r.json()["personas"] if p["temporal_id"] == operario["id"])
    assert mio["horas"] == 6
    assert mio["total"] is None


async def test_la_garita_no_ve_la_liquidacion(cliente, guardia_auth, operario):
    """Cuánto gana cada quien no es asunto de la garita (LOPDP, Art. 10)."""
    r = await cliente.get("/temporal/semana", headers=guardia_auth)
    assert r.status_code == 403
