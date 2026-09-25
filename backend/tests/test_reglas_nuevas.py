"""Bloque mínimo de vacaciones, ruta invertida y ajustes de Talento Humano.

Las tres reglas que cambian quién decide y cuándo. Se prueban contra la API
porque es donde el cliente las ve, y la base es la que las hace cumplir: un
formulario alterado no puede saltárselas.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA

CEDULA_RRHH_R = "1100000007"
CEDULA_JEFE_R = "0900000001"


async def lunes_sin_feriados(semanas: int = 8) -> date:
    feriados = {
        f["fecha"] for f in await obtener_todos(
            "select fecha from public.feriados where activo and fecha >= current_date")
    }
    base = date.today() + timedelta(weeks=semanas)
    candidato = base - timedelta(days=base.weekday())
    for _ in range(80):
        if not ({candidato + timedelta(days=i) for i in range(10)} & feriados):
            return candidato
        candidato += timedelta(weeks=1)
    raise AssertionError("sin semana libre de feriados")


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
async def rrhh_auth(cliente, codigos, empleado):
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s, 'API Talento', 'talento@api.test', 'rrhh', current_date - 2000)
           on conflict (cedula) do update set rol = 'rrhh' returning id""",
        (CEDULA_RRHH_R,),
    )
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_RRHH_R})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_RRHH_R, "codigo": codigos[-1]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def jefe_auth(cliente, codigos, empleado):
    jefe = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s, 'API Jefatura', 'jefatura2@api.test', 'jefe', current_date - 2000)
           on conflict (cedula) do update set rol = 'jefe' returning id""",
        (CEDULA_JEFE_R,),
    )
    await ejecutar("update public.users set jefe_id = %s where id = %s",
                   (jefe["id"], empleado["id"]))
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_JEFE_R})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_JEFE_R, "codigo": codigos[-1]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ------------------------------------------------- bloque mínimo de días
async def test_menos_del_minimo_se_rechaza_con_el_numero_a_la_vista(cliente, auth):
    lunes = await lunes_sin_feriados()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=3)),
        "descripcion": "Cuatro dias de descanso", "firmar": False,
    })
    assert r.status_code == 422
    detalle = r.json()["detail"]
    # El formulario necesita el número para ofrecer una salida, no solo el texto
    assert detalle["bloque_minimo"] == "7"
    assert "7" in detalle["mensaje"]


async def test_el_bloque_completo_pasa_sin_objeciones(cliente, auth):
    lunes = await lunes_sin_feriados()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Ocho dias con la familia", "firmar": False,
    })
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "pendiente_jefe"


async def test_la_excepcion_exige_justificacion_de_verdad(cliente, auth):
    lunes = await lunes_sin_feriados()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=3)),
        "descripcion": "Cuatro dias", "bloque_menor_justificado": True,
        "justificacion": "urgente", "firmar": False,
    })
    assert r.status_code == 422
    assert "30 caracteres" in r.json()["detail"]["mensaje"]


async def test_la_excepcion_la_decide_talento_humano_antes_que_el_jefe(
        cliente, auth, empleado, jefe_auth, rrhh_auth):
    """La regla del negocio: apartarse de la política no lo autoriza el jefe."""
    lunes = await lunes_sin_feriados()
    creada = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=3)),
        "descripcion": "Matrimonio de mi hermana", "bloque_menor_justificado": True,
        "justificacion": "Debo viajar a Loja al matrimonio de mi hermana; adjunto la invitacion.",
        "firmar": False,
        "adjuntos": [{"storage_path": "solicitudes/x.pdf", "nombre_archivo": "invitacion.pdf",
                      "mime_type": "application/pdf", "tamano_bytes": 2048,
                      "hash_sha256": "b" * 64}],
    })
    assert creada.status_code == 201, creada.text
    cuerpo = creada.json()
    assert cuerpo["estado"] == "pendiente_rrhh", "debe saltarse al jefe en el primer paso"

    # El jefe todavía no puede tocarla
    negado = await cliente.post(f"/aprobaciones/{cuerpo['id']}/decidir", headers=jefe_auth,
                                json={"accion": "aprobar"})
    assert negado.status_code in (403, 409)

    # Talento Humano autoriza la excepción y recién ahí pasa al jefe
    paso1 = await cliente.post(f"/aprobaciones/{cuerpo['id']}/decidir", headers=rrhh_auth,
                               json={"accion": "aprobar"})
    assert paso1.status_code == 200, paso1.text
    assert paso1.json()["estado"] == "pendiente_jefe"

    paso2 = await cliente.post(f"/aprobaciones/{cuerpo['id']}/decidir", headers=jefe_auth,
                               json={"accion": "aprobar"})
    assert paso2.status_code == 200, paso2.text
    assert paso2.json()["estado"] == "aprobado"


# ------------------------------------------------- ajustes de Talento Humano
async def _aprobada(cliente, auth, jefe_auth, rrhh_auth) -> dict:
    lunes = await lunes_sin_feriados(10)
    creada = (await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Ocho dias de vacaciones", "firmar": False,
    })).json()
    await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=jefe_auth,
                       json={"accion": "aprobar"})
    await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=rrhh_auth,
                       json={"accion": "aprobar"})
    return creada | {"inicio": lunes}


async def test_talento_humano_extiende_una_ausencia_y_queda_constancia(
        cliente, auth, jefe_auth, rrhh_auth, empleado):
    creada = await _aprobada(cliente, auth, jefe_auth, rrhh_auth)
    nuevo_fin = creada["inicio"] + timedelta(days=10)

    r = await cliente.post(f"/aprobaciones/{creada['id']}/ajustar", headers=rrhh_auth, json={
        "fecha_inicio": str(creada["inicio"]), "fecha_fin": str(nuevo_fin),
        "motivo": "El colaborador presento reposo medico de tres dias adicionales",
        "resolucion": "Se extiende la ausencia hasta el nuevo fin con el certificado del IESS",
    })
    assert r.status_code == 200, r.text
    assert r.json()["fecha_fin"] == str(nuevo_fin)

    fila = await obtener_uno(
        "select fecha_fin, ajustada_en, ajustada_por from public.requests where id = %s",
        (creada["id"],))
    assert str(fila["fecha_fin"]) == str(nuevo_fin)
    assert fila["ajustada_en"] is not None

    historial = (await cliente.get(f"/solicitudes/{creada['id']}/ajustes", headers=auth)).json()
    assert len(historial) == 1
    assert historial[0]["ajustado_por"] == "API Talento"
    assert "reposo medico" in historial[0]["motivo"]


async def test_el_ajuste_sin_explicacion_no_se_admite(cliente, auth, jefe_auth, rrhh_auth):
    creada = await _aprobada(cliente, auth, jefe_auth, rrhh_auth)
    r = await cliente.post(f"/aprobaciones/{creada['id']}/ajustar", headers=rrhh_auth, json={
        "fecha_inicio": str(creada["inicio"]),
        "fecha_fin": str(creada["inicio"] + timedelta(days=9)),
        "motivo": "reposo", "resolucion": "ok",
    })
    assert r.status_code == 422


async def test_el_jefe_no_puede_ajustar_ausencias(cliente, auth, jefe_auth, rrhh_auth):
    """Corregir lo ya autorizado es competencia de Talento Humano."""
    creada = await _aprobada(cliente, auth, jefe_auth, rrhh_auth)
    r = await cliente.post(f"/aprobaciones/{creada['id']}/ajustar", headers=jefe_auth, json={
        "fecha_inicio": str(creada["inicio"]),
        "fecha_fin": str(creada["inicio"] + timedelta(days=12)),
        "motivo": "Quiero extenderle las vacaciones a mi colaborador",
        "resolucion": "Lo autorizo por mi cuenta sin pasar por Talento Humano",
    })
    assert r.status_code == 403


async def test_el_ajuste_corrige_el_saldo_de_vacaciones(
        cliente, auth, jefe_auth, rrhh_auth, empleado):
    """Extender tres días no puede dejar el saldo como estaba."""
    creada = await _aprobada(cliente, auth, jefe_auth, rrhh_auth)
    antes = (await obtener_uno("select dias_vacaciones from public.users where id = %s",
                               (empleado["id"],)))["dias_vacaciones"]

    await cliente.post(f"/aprobaciones/{creada['id']}/ajustar", headers=rrhh_auth, json={
        "fecha_inicio": str(creada["inicio"]),
        "fecha_fin": str(creada["inicio"] + timedelta(days=10)),
        "motivo": "Se prolongo el reposo medico por indicacion del especialista",
        "resolucion": "Se amplia la ausencia en tres dias con el certificado correspondiente",
    })

    despues = (await obtener_uno("select dias_vacaciones from public.users where id = %s",
                                 (empleado["id"],)))["dias_vacaciones"]
    assert float(despues) == float(antes) - 3, "los 3 días extra deben salir del saldo"


# ------------------------------------------------- catálogo por pilares
async def test_el_catalogo_llega_agrupado_y_con_ejemplos(cliente, auth):
    r = await cliente.get("/catalogos/permisos", headers=auth)
    assert r.status_code == 200
    datos = r.json()

    assert datos["mandato"], "debe venir el texto que exige declarar todo"
    codigos = {p["codigo"] for p in datos["pilares"]}
    assert codigos == {"calamidad_domestica", "cita_medica", "permiso_personal"}

    for pilar in datos["pilares"]:
        assert pilar["subtipos"], f"{pilar['codigo']} sin subtipos"
        for sub in pilar["subtipos"]:
            assert sub["guia_ejemplo"], f"{sub['codigo']} sin ejemplo de redacción"
            assert sub["guia_adjuntos"], f"{sub['codigo']} sin guía de adjuntos"
