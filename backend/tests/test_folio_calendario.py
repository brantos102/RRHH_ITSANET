"""Número de solicitud, reemplazo, desglose de días y calendario del equipo."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA

CEDULA_COMPA = "0900000001"
CEDULA_JEFE = "1100000007"


async def lunes_limpio(semanas: int = 6) -> date:
    feriados = {
        f["fecha"] for f in await obtener_todos(
            "select fecha from public.feriados where activo and fecha >= current_date")
    }
    base = date.today() + timedelta(weeks=semanas)
    candidato = base - timedelta(days=base.weekday())
    for _ in range(60):
        if not ({candidato + timedelta(days=i) for i in range(7)} & feriados):
            return candidato
        candidato += timedelta(weeks=1)
    raise AssertionError("sin semana libre de feriados")


@pytest.fixture
async def companero(empleado):
    """Un compañero del mismo departamento, candidato a reemplazo."""
    await ejecutar("update public.users set departamento = 'Operaciones' where id = %s",
                   (empleado["id"],))
    fila = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, departamento, fecha_ingreso)
           values (%s, 'API Compañero', 'compa@api.test', 'empleado', 'Operaciones',
                   current_date - 800)
           returning id""",
        (CEDULA_COMPA,),
    )
    return str(fila["id"])


@pytest.fixture
async def auth(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]})
    await ejecutar(
        """update public.vacation_periods set fines_semana_consumidos = fines_semana_obligatorios
           where user_id = %s and not caducado""",
        (empleado["id"],),
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def jefe_auth(cliente, codigos, empleado, companero):
    """El jefe inmediato del empleado de prueba, con sesión iniciada.

    El compañero creado por el fixture `companero` pasa a ser jefe: así hay
    a quién asignar como reemplazo y quién decida, sin inventar más gente.
    """
    jefe = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, departamento, fecha_ingreso)
           values (%s, 'API Jefatura', 'jefatura@api.test', 'jefe', 'Operaciones',
                   current_date - 1500)
           on conflict (cedula) do update set rol = 'jefe'
           returning id""",
        (CEDULA_JEFE,),
    )
    await ejecutar("update public.users set jefe_id = %s where id = %s",
                   (jefe["id"], empleado["id"]))

    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_JEFE})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_JEFE, "codigo": codigos[-1]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _crear(cliente, auth, **extra) -> dict:
    lunes = await lunes_limpio()
    cuerpo = {"tipo": "vacacion", "fecha_inicio": str(lunes),
              "fecha_fin": str(lunes + timedelta(days=6)),
              "descripcion": "Solicitud de prueba", "firmar": False} | extra
    r = await cliente.post("/solicitudes", headers=auth, json=cuerpo)
    assert r.status_code == 201, r.text
    return r.json()


# ------------------------------------------------------------------- folio
async def test_la_solicitud_recibe_un_numero_legible(cliente, auth):
    creada = await _crear(cliente, auth)
    assert isinstance(creada["folio"], int) and creada["folio"] > 0
    assert f"Nº {creada['folio']}" in creada["mensaje"]


async def test_el_numero_es_correlativo(cliente, auth):
    primera = await _crear(cliente, auth)
    lunes = await lunes_limpio(20)
    segunda = await cliente.post(
        "/solicitudes", headers=auth,
        json={"tipo": "vacacion", "fecha_inicio": str(lunes),
              "fecha_fin": str(lunes + timedelta(days=6)),
              "descripcion": "Segunda solicitud", "firmar": False},
    )
    assert segunda.json()["folio"] == primera["folio"] + 1


async def test_el_numero_aparece_en_mis_solicitudes(cliente, auth):
    creada = await _crear(cliente, auth)
    listado = await (await cliente.get("/solicitudes/mias", headers=auth)).aread()
    assert str(creada["folio"]).encode() in listado


# ---------------------------------------------------------------- desglose
async def test_el_desglose_explica_de_que_se_componen_los_dias(cliente, auth):
    """Con un feriado dentro del rango, debe decir cuántos días no se descuentan."""
    feriado = await obtener_uno(
        """select fecha from public.feriados
           where activo and fecha > current_date + 30 and extract(isodow from fecha) between 1 and 5
           order by fecha limit 1"""
    )
    inicio = feriado["fecha"] - timedelta(days=feriado["fecha"].weekday())
    r = await cliente.post("/solicitudes/previsualizar", headers=auth,
                           json={"tipo": "vacacion", "fecha_inicio": str(inicio),
                                 "fecha_fin": str(inicio + timedelta(days=6))})
    d = r.json()["desglose"]
    assert d["total_calendario"] == 7
    assert d["dias_no_laborables"] >= 1
    assert d["dias_descontar"] == 7 - d["dias_no_laborables"]
    assert any(f["nombre"] for f in d["feriados"]), "debe nombrar el feriado"


async def test_el_desglose_cuenta_los_fines_de_semana(cliente, auth):
    lunes = await lunes_limpio()
    r = await cliente.post("/solicitudes/previsualizar", headers=auth,
                           json={"tipo": "vacacion", "fecha_inicio": str(lunes),
                                 "fecha_fin": str(lunes + timedelta(days=6))})
    assert r.json()["desglose"]["fines_de_semana"] == 2


# -------------------------------------------------------------- reemplazo
async def test_el_solicitante_no_puede_elegir_quien_lo_cubre(cliente, auth, companero):
    """Aunque lo envíe a mano: quien conoce la carga del equipo es el jefe."""
    creada = await _crear(cliente, auth, reemplazo_id=companero)
    fila = await obtener_uno("select reemplazo_id from public.requests where id = %s",
                             (creada["id"],))
    assert fila["reemplazo_id"] is None


async def test_el_jefe_asigna_el_reemplazo_al_aprobar(cliente, auth, codigos,
                                                      companero, jefe_auth):
    creada = await _crear(cliente, auth)
    r = await cliente.post(
        f"/aprobaciones/{creada['id']}/decidir", headers=jefe_auth,
        json={"accion": "aprobar", "reemplazo_id": companero},
    )
    assert r.status_code == 200, r.text

    fila = await obtener_uno("select reemplazo_id from public.requests where id = %s",
                             (creada["id"],))
    assert str(fila["reemplazo_id"]) == companero

    listado = (await cliente.get("/solicitudes/mias", headers=auth)).json()
    assert listado[0]["reemplazo"] == "API Compañero"


async def test_nadie_se_reemplaza_a_si_mismo(cliente, auth, empleado, jefe_auth):
    creada = await _crear(cliente, auth)
    r = await cliente.post(
        f"/aprobaciones/{creada['id']}/decidir", headers=jefe_auth,
        json={"accion": "aprobar", "reemplazo_id": empleado["id"]},
    )
    assert r.status_code == 422


async def test_los_candidatos_avisan_quien_tambien_estara_ausente(
        cliente, auth, companero, jefe_auth):
    """Proponer a alguien que también falta es el error más fácil de cometer."""
    creada = await _crear(cliente, auth)
    r = await cliente.get(f"/aprobaciones/{creada['id']}/candidatos", headers=jefe_auth)
    assert r.status_code == 200, r.text
    candidatos = {c["id"]: c for c in r.json()}
    assert companero in candidatos
    assert "tambien_ausente" in candidatos[companero]


async def test_los_companeros_son_del_mismo_equipo(cliente, auth, companero, empleado):
    r = await cliente.get("/catalogos/companeros", headers=auth)
    assert r.status_code == 200
    ids = [c["id"] for c in r.json()]
    assert companero in ids
    assert empleado["id"] not in ids, "uno mismo no puede ser su reemplazo"


# -------------------------------------------------------------- calendario
async def test_el_calendario_muestra_al_equipo(cliente, auth, companero):
    await _crear(cliente, auth)
    r = await cliente.get("/calendario", headers=auth)
    assert r.status_code == 200
    assert any(a["nombre"] == "API Empleado" for a in r.json())


async def test_el_calendario_no_revela_el_motivo(cliente, auth, companero):
    """Entre compañeros se ve quién falta, no por qué: es un dato de salud."""
    tipos = (await cliente.get("/catalogos/tipos-permiso", headers=auth)).json()
    medica = next(t for t in tipos if t["codigo"] == "cita_medica")
    lunes = await lunes_limpio(8)

    # Este permiso exige respaldo y firma: sin ambos, la base rechaza el conjunto
    import base64
    firma = "data:image/png;base64," + base64.b64encode(
        b"\x89PNG\r\n\x1a\n" + b"trazo " * 60).decode()
    assert (await cliente.post("/firmas/dibujada", headers=auth,
                               json={"contenido": firma})).status_code == 201

    solicitud_id = str(uuid.uuid4())
    adjunto = await cliente.post(
        f"/solicitudes/adjuntos?solicitud_id={solicitud_id}", headers=auth,
        files={"archivo": ("cita.pdf", b"%PDF-1.4 respaldo", "application/pdf")},
    )
    assert adjunto.status_code == 200
    creada = await cliente.post(
        "/solicitudes", headers=auth,
        json={"id": solicitud_id, "tipo": "permiso", "permission_type_id": medica["id"],
              "fecha_inicio": str(lunes), "fecha_fin": str(lunes),
              "hora_inicio": "08:00", "hora_fin": "12:00",
              "descripcion": "Control con el especialista",
              "justificacion": "Cita programada en el hospital del IESS.",
              "adjuntos": [adjunto.json()], "firmar": True},
    )
    assert creada.status_code == 201, creada.text

    cuerpo = (await cliente.get("/calendario", headers=auth)).text
    assert "Permiso" in cuerpo
    assert "Cita médica" not in cuerpo, "no debe aparecer la categoría del permiso"
    assert "especialista" not in cuerpo, "no debe aparecer la descripción"
    assert "IESS" not in cuerpo, "no debe aparecer la justificación"
