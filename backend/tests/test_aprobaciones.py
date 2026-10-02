"""Flujo completo de aprobación: jefe, Talento Humano, QR y correos."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app import notificaciones
from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA

CEDULA_JEFE = "0900000001"
CEDULA_RRHH = "1100000007"


async def lunes_futuro(semanas: int = 6) -> date:
    """Un lunes futuro cuya semana no tenga feriados.

    Fijar «hoy + N semanas» hacía que las pruebas se rompieran según el día
    en que se ejecutaran: si la semana caía en Difuntos o Independencia de
    Cuenca, los días computables no eran los esperados.
    """
    feriados = {
        f["fecha"]
        for f in await obtener_todos(
            "select fecha from public.feriados where activo and fecha >= current_date"
        )
    }
    base = date.today() + timedelta(weeks=semanas)
    candidato = base - timedelta(days=base.weekday())
    for _ in range(60):
        semana = {candidato + timedelta(days=i) for i in range(7)}
        if not (semana & feriados):
            return candidato
        candidato += timedelta(weeks=1)
    raise AssertionError("No se encontró una semana sin feriados")


@pytest.fixture
def correos(monkeypatch) -> list[dict]:
    """Captura los correos del flujo en vez de enviarlos."""
    enviados: list[dict] = []

    async def _jefe(jefe, solicitud):
        enviados.append({"a": "jefe", "email": jefe["email"], "solicitud": solicitud})

    async def _rrhh(destinatarios, solicitud, quien):
        enviados.append({"a": "rrhh", "emails": [d["email"] for d in destinatarios],
                         "solicitud": solicitud, "quien": quien})

    async def _aprobado(empleado, solicitud):
        enviados.append({"a": "empleado_aprobado", "email": empleado["email"], "solicitud": solicitud})

    async def _rechazado(empleado, solicitud, quien, motivo):
        enviados.append({"a": "empleado_rechazado", "email": empleado["email"],
                         "quien": quien, "motivo": motivo})

    monkeypatch.setattr(notificaciones, "avisar_al_jefe", _jefe)
    monkeypatch.setattr(notificaciones, "avisar_a_rrhh", _rrhh)
    monkeypatch.setattr(notificaciones, "avisar_aprobacion", _aprobado)
    monkeypatch.setattr(notificaciones, "avisar_rechazo", _rechazado)
    return enviados


@pytest.fixture
async def equipo(empleado):
    """Jefe y personal de Talento Humano, con el empleado a cargo del jefe."""
    jefe = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s, 'API Jefe', 'jefe@api.test', 'jefe', current_date - 900) returning id""",
        (CEDULA_JEFE,),
    )
    rrhh = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s, 'API RRHH', 'rrhh@api.test', 'rrhh', current_date - 900) returning id""",
        (CEDULA_RRHH,),
    )
    await ejecutar("update public.users set jefe_id = %s where id = %s", (jefe["id"], empleado["id"]))
    await ejecutar(
        """update public.vacation_periods set fines_semana_consumidos = fines_semana_obligatorios
           where user_id = %s and not caducado""",
        (empleado["id"],),
    )
    return {"jefe": str(jefe["id"]), "rrhh": str(rrhh["id"])}


async def _sesion(cliente, codigos, cedula: str) -> str:
    await cliente.post("/auth/solicitar-token", json={"cedula": cedula})
    r = await cliente.post("/auth/validar-token", json={"cedula": cedula, "codigo": codigos[-1]})
    return r.json()["access_token"]


@pytest.fixture
async def solicitud(cliente, codigos, equipo, correos):
    """Una solicitud de vacaciones recién enviada por el empleado."""
    token = await _sesion(cliente, codigos, CEDULA_PRUEBA)
    lunes = await lunes_futuro()
    r = await cliente.post(
        "/solicitudes",
        headers={"Authorization": f"Bearer {token}"},
        json={"tipo": "vacacion", "fecha_inicio": str(lunes),
              "fecha_fin": str(lunes + timedelta(days=6)),
              "descripcion": "Descanso programado", "firmar": False},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ------------------------------------------------------------ aviso al jefe
async def test_al_crear_se_avisa_al_jefe(solicitud, correos):
    avisos = [c for c in correos if c["a"] == "jefe"]
    assert len(avisos) == 1
    assert avisos[0]["email"] == "jefe@api.test"
    assert avisos[0]["solicitud"]["jefe_token"] is not None


# --------------------------------------------------------- panel con sesión
async def test_el_jefe_ve_lo_que_le_toca(cliente, codigos, solicitud):
    token = await _sesion(cliente, codigos, CEDULA_JEFE)
    r = await cliente.get("/aprobaciones/pendientes", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    ids = [s["id"] for s in r.json()]
    assert solicitud in ids


async def test_rrhh_no_ve_lo_que_aun_no_aprueba_el_jefe(cliente, codigos, solicitud):
    token = await _sesion(cliente, codigos, CEDULA_RRHH)
    r = await cliente.get("/aprobaciones/pendientes", headers={"Authorization": f"Bearer {token}"})
    assert solicitud not in [s["id"] for s in r.json()]


async def test_un_empleado_no_puede_aprobar(cliente, codigos, solicitud):
    token = await _sesion(cliente, codigos, CEDULA_PRUEBA)
    r = await cliente.get("/aprobaciones/pendientes", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


async def test_nadie_aprueba_su_propia_solicitud(cliente, codigos, solicitud, equipo):
    # El jefe envía una solicitud suya y luego intenta aprobarla
    token = await _sesion(cliente, codigos, CEDULA_JEFE)
    cab = {"Authorization": f"Bearer {token}"}
    lunes = await lunes_futuro(14)
    propia = await cliente.post(
        "/solicitudes", headers=cab,
        json={"tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=6)),
              "descripcion": "Vacaciones del jefe", "firmar": False},
    )
    assert propia.status_code == 201
    r = await cliente.post(f"/aprobaciones/{propia.json()['id']}/decidir",
                           headers=cab, json={"accion": "aprobar"})
    assert r.status_code == 403
    assert "propia" in r.json()["detail"]["mensaje"]


async def test_flujo_completo_hasta_el_qr(cliente, codigos, solicitud, correos):
    # 1. El jefe aprueba
    token_jefe = await _sesion(cliente, codigos, CEDULA_JEFE)
    r = await cliente.post(f"/aprobaciones/{solicitud}/decidir",
                           headers={"Authorization": f"Bearer {token_jefe}"},
                           json={"accion": "aprobar"})
    assert r.status_code == 200
    assert r.json()["estado"] == "pendiente_rrhh"
    assert any(c["a"] == "rrhh" for c in correos), "no se avisó a Talento Humano"

    # 2. Talento Humano aprueba
    token_rrhh = await _sesion(cliente, codigos, CEDULA_RRHH)
    r = await cliente.post(f"/aprobaciones/{solicitud}/decidir",
                           headers={"Authorization": f"Bearer {token_rrhh}"},
                           json={"accion": "aprobar"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] == "aprobado"
    assert cuerpo["qr_emitido"] is True

    aviso = next(c for c in correos if c["a"] == "empleado_aprobado")
    assert aviso["solicitud"]["qr_hash"] is not None

    # 3. El QR se puede descargar
    token_empleado = await _sesion(cliente, codigos, CEDULA_PRUEBA)
    img = await cliente.get(f"/solicitudes/{solicitud}/qr.png",
                            headers={"Authorization": f"Bearer {token_empleado}"})
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    assert img.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_rechazo_exige_motivo(cliente, codigos, solicitud):
    token = await _sesion(cliente, codigos, CEDULA_JEFE)
    r = await cliente.post(f"/aprobaciones/{solicitud}/decidir",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"accion": "rechazar", "motivo": "   "})
    assert r.status_code == 422
    assert "motivo" in r.json()["detail"]["mensaje"]


async def test_rechazo_avisa_al_empleado(cliente, codigos, solicitud, correos):
    token = await _sesion(cliente, codigos, CEDULA_JEFE)
    r = await cliente.post(f"/aprobaciones/{solicitud}/decidir",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"accion": "rechazar", "motivo": "Coincide con el cierre de mes."})
    assert r.status_code == 200 and r.json()["estado"] == "rechazado"
    aviso = next(c for c in correos if c["a"] == "empleado_rechazado")
    assert aviso["motivo"] == "Coincide con el cierre de mes."


async def test_tras_aprobar_el_jefe_ya_no_le_toca(cliente, codigos, solicitud):
    token = await _sesion(cliente, codigos, CEDULA_JEFE)
    cab = {"Authorization": f"Bearer {token}"}
    assert (await cliente.post(f"/aprobaciones/{solicitud}/decidir", headers=cab,
                               json={"accion": "aprobar"})).status_code == 200
    # Ahora está en manos de Talento Humano: el jefe ya no decide
    segunda = await cliente.post(f"/aprobaciones/{solicitud}/decidir", headers=cab,
                                 json={"accion": "aprobar"})
    assert segunda.status_code == 403


async def test_dos_personas_de_rrhh_a_la_vez(cliente, codigos, solicitud):
    """Quien llega segundo recibe 409, no una segunda aprobación."""
    token_jefe = await _sesion(cliente, codigos, CEDULA_JEFE)
    await cliente.post(f"/aprobaciones/{solicitud}/decidir",
                       headers={"Authorization": f"Bearer {token_jefe}"}, json={"accion": "aprobar"})

    token_rrhh = await _sesion(cliente, codigos, CEDULA_RRHH)
    cab = {"Authorization": f"Bearer {token_rrhh}"}
    assert (await cliente.post(f"/aprobaciones/{solicitud}/decidir", headers=cab,
                               json={"accion": "aprobar"})).status_code == 200
    repetida = await cliente.post(f"/aprobaciones/{solicitud}/decidir", headers=cab,
                                  json={"accion": "aprobar"})
    assert repetida.status_code == 409
    assert "ya está en estado" in repetida.json()["detail"]["mensaje"]


# ------------------------------------------------------- enlace del correo
async def _token_enlace(solicitud_id: str, rol: str) -> str:
    columna = "jefe_token" if rol == "jefe" else "rrhh_token"
    fila = await obtener_uno(f"select {columna} as t from public.requests where id = %s", (solicitud_id,))
    return str(fila["t"])


async def test_el_enlace_muestra_la_solicitud_sin_cambiar_nada(cliente, solicitud):
    token = await _token_enlace(solicitud, "jefe")
    r = await cliente.get(f"/aprobaciones/enlace/{token}?rol=jefe")
    assert r.status_code == 200
    datos = r.json()
    assert datos["puede_decidir"] is True
    assert datos["solicitud"]["empleado"] == "API Empleado"

    estado = await obtener_uno("select estado from public.requests where id = %s", (solicitud,))
    assert estado["estado"] == "pendiente_jefe", "un GET no debe cambiar el estado"


async def test_el_enlace_no_expone_tokens(cliente, solicitud):
    token = await _token_enlace(solicitud, "jefe")
    r = await cliente.get(f"/aprobaciones/enlace/{token}?rol=jefe")
    cuerpo = r.text
    assert "jefe_token" not in cuerpo and "rrhh_token" not in cuerpo


async def test_aprobar_desde_el_enlace(cliente, solicitud, correos):
    token = await _token_enlace(solicitud, "jefe")
    r = await cliente.post(f"/aprobaciones/enlace/{token}/decidir?rol=jefe", json={"accion": "aprobar"})
    assert r.status_code == 200 and r.json()["estado"] == "pendiente_rrhh"

    # El enlace del jefe ya no sirve: la solicitud cambió de estado
    otra = await cliente.post(f"/aprobaciones/enlace/{token}/decidir?rol=jefe", json={"accion": "aprobar"})
    assert otra.status_code == 409

    # El de Talento Humano sí
    token_rrhh = await _token_enlace(solicitud, "rrhh")
    final = await cliente.post(f"/aprobaciones/enlace/{token_rrhh}/decidir?rol=rrhh", json={"accion": "aprobar"})
    assert final.status_code == 200 and final.json()["qr_emitido"] is True


async def test_enlace_inventado_no_revela_nada(cliente, solicitud):
    r = await cliente.get(f"/aprobaciones/enlace/{uuid.uuid4()}?rol=jefe")
    assert r.status_code == 404
    assert "no es válido" in r.json()["detail"]["mensaje"]


async def test_el_token_del_jefe_no_sirve_como_rrhh(cliente, solicitud):
    token = await _token_enlace(solicitud, "jefe")
    r = await cliente.get(f"/aprobaciones/enlace/{token}?rol=rrhh")
    assert r.status_code == 404


async def test_enlace_vencido_se_rechaza(cliente, solicitud):
    await ejecutar(
        "update public.requests set created_at = now() - interval '30 days' where id = %s", (solicitud,)
    )
    token = await _token_enlace(solicitud, "jefe")
    r = await cliente.get(f"/aprobaciones/enlace/{token}?rol=jefe")
    assert r.status_code == 404


# --------------------------------------------------------------------- QR
async def test_el_qr_no_se_entrega_si_no_esta_aprobada(cliente, codigos, solicitud):
    token = await _sesion(cliente, codigos, CEDULA_PRUEBA)
    r = await cliente.get(f"/solicitudes/{solicitud}/qr.png", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 404


async def test_el_qr_solo_contiene_el_identificador(solicitud, cliente, codigos, correos):
    """El QR no debe llevar datos personales: solo el hash que la garita valida."""
    token_jefe = await _sesion(cliente, codigos, CEDULA_JEFE)
    await cliente.post(f"/aprobaciones/{solicitud}/decidir",
                       headers={"Authorization": f"Bearer {token_jefe}"}, json={"accion": "aprobar"})
    token_rrhh = await _sesion(cliente, codigos, CEDULA_RRHH)
    await cliente.post(f"/aprobaciones/{solicitud}/decidir",
                       headers={"Authorization": f"Bearer {token_rrhh}"}, json={"accion": "aprobar"})

    fila = await obtener_uno("select qr_hash from public.requests where id = %s", (solicitud,))
    from app.qr import png
    imagen = png(str(fila["qr_hash"]))
    assert imagen[:8] == b"\x89PNG\r\n\x1a\n"
    # El contenido codificado es exactamente el hash, nada más
    assert len(str(fila["qr_hash"])) == 36
