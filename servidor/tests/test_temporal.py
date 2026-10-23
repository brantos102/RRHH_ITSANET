"""Personal temporal: nadie queda sin salida registrada.

Es un sistema pequeño dentro del grande y con otra lógica: el temporal viene
por jornadas y se le paga por lo que trabajó esa semana. De ahí sale la regla
que manda todo lo demás —una jornada sin cerrar no se puede pagar—, y la
decisión de no inventar salidas: una salida automática a las seis de la tarde
convertiría un dato que falta en uno falso, que es peor que no tenerlo.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA

CED_GUARDIA_T = "1713175071"
CED_RRHH_T = "1700000068"
CED_OPERARIO = "1300000054"


def salida_de_ayer(hora: int = 17) -> str:
    """La hora de salida de la jornada de ayer, calculada y no escrita a mano.

    Estaba fija —«2026-09-29T17:00:00Z»— y las jornadas se insertan con
    `current_date - 1`: al día siguiente la salida caía un día ANTES de la
    entrada, la base la rechazaba con razón y la prueba fallaba sin que nada
    estuviera roto en el sistema.
    """
    ayer = date.today() - timedelta(days=1)
    return f"{ayer.isoformat()}T{hora:02d}:00:00Z"


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
                           json={"salida": salida_de_ayer(),
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
           values (%s, current_date - 1,
                   (current_date - 1)::timestamptz + interval '8 hours') returning id""",
        (operario["id"],))
    r = await cliente.post(f"/temporal/jornadas/{fila['id']}/cerrar", headers=rrhh_auth,
                           json={"salida": salida_de_ayer(), "motivo": "ok"})
    assert r.status_code == 422


async def test_la_garita_no_cierra_jornadas_a_mano(cliente, guardia_auth, operario):
    fila = await obtener_uno(
        """insert into public.jornadas_temporales (temporal_id, fecha, entrada_en)
           values (%s, current_date - 1,
                   (current_date - 1)::timestamptz + interval '8 hours') returning id""",
        (operario["id"],))
    r = await cliente.post(f"/temporal/jornadas/{fila['id']}/cerrar", headers=guardia_auth,
                           json={"salida": salida_de_ayer(),
                                 "motivo": "Intento de cerrar sin ser Talento Humano"})
    assert r.status_code == 403


# ------------------------------------------------------------- la liquidación
async def test_la_semana_cuenta_jornadas_y_horas(cliente, rrhh_auth, operario):
    """Lo que la garita presenció, y nada más.

    Antes esta prueba comprobaba un total en dólares. El módulo ya no lo
    calcula: cuánto se paga sale del contrato del proveedor y esa cuenta la
    hace Finanzas. Un importe impreso aquí se toma por la cifra buena, y el
    día que cambie la tarifa sigue saliendo igual de convincente.
    """
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
    assert mio["jornadas"] == 1
    assert "total" not in mio and "valor_hora" not in mio, (
        "el módulo volvió a hablar de dinero")
    assert cuerpo["jornadas_sin_cerrar"] == 0
    assert cuerpo["aviso"] is None


async def test_las_horas_avisan_cuando_estan_incompletas(cliente, rrhh_auth, operario):
    """Dar por buenas unas horas que no cuadran es peor que no darlas."""
    await obtener_uno(
        """insert into public.jornadas_temporales (temporal_id, fecha, entrada_en)
           values (%s, current_date, now() - interval '3 hours') returning id""",
        (operario["id"],))

    r = await cliente.get("/temporal/semana", headers=rrhh_auth)
    cuerpo = r.json()
    assert cuerpo["jornadas_sin_cerrar"] >= 1
    assert cuerpo["aviso"] and "incompleta" in cuerpo["aviso"]


async def test_el_alta_ya_no_acepta_una_tarifa(cliente, rrhh_auth):
    """Y si alguien la manda igual, se ignora en vez de guardarse a escondidas."""
    from app.db import obtener_todos

    r = await cliente.post("/temporal", headers=rrhh_auth, json={
        "cedula": "1717171717", "nombre": "Operario Sin Tarifa",
        "labor": "Estibador", "valor_hora": 4.5})
    if r.status_code == 201:
        columnas = await obtener_todos(
            """select column_name from information_schema.columns
                where table_schema = 'public' and table_name = 'personal_temporal'""")
        assert "valor_hora" not in {c["column_name"] for c in columnas}


async def test_la_garita_no_ve_la_liquidacion(cliente, guardia_auth, operario):
    """Cuánto gana cada quien no es asunto de la garita (LOPDP, Art. 10)."""
    r = await cliente.get("/temporal/semana", headers=guardia_auth)
    assert r.status_code == 403


# ------------------------------------------------------- informe a Finanzas

async def _jornada(temporal_id, dia: int, horas: float = 8, cerrada: bool = True):
    from app.db import obtener_uno as uno
    return await uno(
        """insert into public.jornadas_temporales
             (temporal_id, fecha, entrada_en, salida_en, horas)
           values (%s, current_date - %s,
                   (current_date - %s)::timestamptz + interval '8 hours',
                   case when %s then (current_date - %s)::timestamptz + interval '16 hours' end,
                   case when %s then %s end)
           returning id""",
        (temporal_id, dia, dia, cerrada, dia, cerrada, horas))


async def test_el_informe_resume_y_detalla(cliente, rrhh_auth, operario):
    for dia in (1, 2, 3):
        await _jornada(operario["id"], dia)

    r = await cliente.post("/temporal/informe", headers=rrhh_auth, json={})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    mio = next(x for x in cuerpo["resumen"] if x["cedula"] == operario["cedula"])
    assert mio["jornadas"] == 3 and mio["horas"] == 24
    assert len([j for j in cuerpo["jornadas"] if j["cedula"] == operario["cedula"]]) == 3
    assert cuerpo["total_horas"] >= 24


async def test_el_informe_no_lleva_importes(cliente, rrhh_auth, operario):
    """La razón del módulo: el sistema sabe cuánto estuvo, no cuánto se paga."""
    await _jornada(operario["id"], 1)
    r = await cliente.post("/temporal/informe", headers=rrhh_auth, json={})
    crudo = r.text.lower()
    for palabra in ("valor_hora", "total_pagar", "importe", "tarifa"):
        assert palabra not in crudo, f"el informe habla de «{palabra}»"


async def test_se_puede_pedir_una_sola_persona(cliente, rrhh_auth, operario):
    """Es la pregunta que llega cuando alguien reclama su pago."""
    await _jornada(operario["id"], 1)
    otro = await cliente.post("/temporal", headers=rrhh_auth, json={
        "cedula": "0968067396", "nombre": "Otro Operario Cualquiera"})
    if otro.status_code == 201:
        await _jornada(otro.json()["id"], 1)

    r = await cliente.post("/temporal/informe", headers=rrhh_auth,
                           json={"temporales": [operario["id"]]})
    cedulas = {x["cedula"] for x in r.json()["resumen"]}
    assert cedulas == {operario["cedula"]}


async def test_el_rango_de_fechas_acota(cliente, rrhh_auth, operario):
    import datetime as dt
    await _jornada(operario["id"], 20)
    await _jornada(operario["id"], 1)

    ayer = dt.date.today() - dt.timedelta(days=2)
    r = await cliente.post("/temporal/informe", headers=rrhh_auth,
                           json={"desde": str(ayer)})
    mio = next(x for x in r.json()["resumen"] if x["cedula"] == operario["cedula"])
    assert mio["jornadas"] == 1, "entró una jornada de hace veinte días"


async def test_avisa_de_las_jornadas_sin_cerrar(cliente, rrhh_auth, operario):
    """Una jornada sin salida no se puede pagar, y el informe no la cuenta."""
    await _jornada(operario["id"], 1, cerrada=False)
    r = await cliente.post("/temporal/informe", headers=rrhh_auth, json={})
    cuerpo = r.json()
    assert cuerpo["jornadas_sin_cerrar"] >= 1
    assert cuerpo["aviso"] and "sin salida" in cuerpo["aviso"]

    solo = await cliente.post("/temporal/informe", headers=rrhh_auth,
                              json={"solo_sin_cerrar": True})
    assert all(j["sin_cerrar"] for j in solo.json()["jornadas"])


async def test_se_baja_en_los_tres_formatos(cliente, rrhh_auth, operario):
    await _jornada(operario["id"], 1)
    # Cada formato por su firma real: un CSV es texto y los otros dos traen
    # su marca en los primeros bytes. Comprobar solo el código de respuesta
    # dejaría pasar un archivo vacío.
    for formato in ("csv", "xlsx", "pdf"):
        r = await cliente.post(f"/temporal/informe.{formato}", headers=rrhh_auth,
                               json={"detalle": True})
        assert r.status_code == 200, f"{formato}: {r.text[:200]}"
        assert "attachment" in r.headers.get("content-disposition", "")
        if formato == "csv":
            texto = r.content.decode("utf-8-sig")
            assert "Cédula" in texto and operario["cedula"] in texto
        elif formato == "xlsx":
            assert r.content[:2] == b"PK", "no es un libro de Excel"
        else:
            assert r.content[:4] == b"%PDF", "no es un PDF"
        assert len(r.content) > 500, f"{formato} salió prácticamente vacío"


async def test_el_archivo_dice_que_no_lleva_importes(cliente, rrhh_auth, operario):
    """Dentro del archivo, no en el correo: el archivo se reenvía solo."""
    await _jornada(operario["id"], 1)
    r = await cliente.post("/temporal/informe.csv", headers=rrhh_auth, json={})
    texto = r.content.decode("utf-8", "ignore")
    assert "Finanzas" in texto and "no incluye importes" in texto


async def test_las_opciones_de_filtro_salen_de_los_datos(cliente, rrhh_auth, operario):
    r = await cliente.get("/temporal/opciones-informe", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert any(p["cedula"] == operario["cedula"] for p in cuerpo["personas"])
    assert isinstance(cuerpo["proveedores"], list)


async def test_la_garita_no_baja_informes(cliente, guardia_auth, operario):
    """Registra jornadas; liquidarlas es de Talento Humano."""
    assert (await cliente.post("/temporal/informe", headers=guardia_auth,
                               json={})).status_code == 403
    assert (await cliente.post("/temporal/informe.xlsx", headers=guardia_auth,
                               json={})).status_code == 403
