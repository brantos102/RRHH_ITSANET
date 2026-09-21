"""Solicitudes del empleado: catálogo, previsualización, envío, firma y adjuntos."""
from __future__ import annotations

import base64
import uuid
from datetime import date, timedelta

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA

def _firma(trazo: bytes = b"trazo de prueba ") -> str:
    """Data URI con cabecera PNG real y tamaño suficiente."""
    crudo = b"\x89PNG\r\n\x1a\n" + trazo * 40
    return "data:image/png;base64," + base64.b64encode(crudo).decode()


FIRMA_PNG = _firma()


@pytest.fixture
async def token(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    r = await cliente.post(
        "/auth/validar-token", json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]}
    )
    # Se dan por consumidos los fines de semana obligatorios para aislar
    # estas pruebas de esa regla (ya cubierta por el smoke test de la base).
    await ejecutar(
        """update public.vacation_periods set fines_semana_consumidos = fines_semana_obligatorios
           where user_id = %s and not caducado""",
        (empleado["id"],),
    )
    return r.json()["access_token"]


@pytest.fixture
def auth(token):
    return {"Authorization": f"Bearer {token}"}


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


# ------------------------------------------------------------------ catálogo
async def test_catalogo_requiere_token(cliente):
    assert (await cliente.get("/catalogos/tipos-permiso")).status_code == 401


async def test_catalogo_trae_tipos_con_base_legal(cliente, auth):
    r = await cliente.get("/catalogos/tipos-permiso", headers=auth)
    assert r.status_code == 200
    tipos = r.json()
    assert len(tipos) >= 16
    medica = next(t for t in tipos if t["codigo"] == "cita_medica")
    assert medica["requiere_adjunto"] is True
    assert medica["articulo"] is not None          # viene del glosario


# ----------------------------------------------------------- previsualización
async def test_previsualizar_calcula_dias_y_saldo(cliente, auth):
    lunes = await lunes_futuro()
    r = await cliente.post(
        "/solicitudes/previsualizar",
        headers=auth,
        json={"tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=6))},
    )
    assert r.status_code == 200
    datos = r.json()
    assert datos["dias"] == 7
    assert datos["fines_semana_incluidos"] == 1
    assert datos["saldo_despues"] == datos["saldo_actual"] - 7


async def test_previsualizar_avisa_si_excede_el_saldo(cliente, auth):
    lunes = await lunes_futuro()
    r = await cliente.post(
        "/solicitudes/previsualizar",
        headers=auth,
        json={"tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=60))},
    )
    assert r.json()["requiere_justificacion"] is True


# ------------------------------------------------------------------- envío
async def test_enviar_vacacion(cliente, auth):
    lunes = await lunes_futuro()
    r = await cliente.post(
        "/solicitudes",
        headers=auth,
        json={
            "tipo": "vacacion",
            "fecha_inicio": str(lunes),
            "fecha_fin": str(lunes + timedelta(days=6)),
            "descripcion": "Viaje familiar programado",
            "firmar": False,
        },
    )
    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo["estado"] == "pendiente_jefe"
    assert cuerpo["dias_solicitados"] == 7


async def test_descripcion_larga_se_rechaza(cliente, auth):
    lunes = await lunes_futuro()
    r = await cliente.post(
        "/solicitudes",
        headers=auth,
        json={"tipo": "vacacion", "fecha_inicio": str(lunes),
              "fecha_fin": str(lunes + timedelta(days=6)), "descripcion": "x" * 201},
    )
    assert r.status_code == 422


async def test_exceder_saldo_sin_justificar_da_mensaje_util(cliente, auth):
    lunes = await lunes_futuro()
    r = await cliente.post(
        "/solicitudes",
        headers=auth,
        json={"tipo": "vacacion", "fecha_inicio": str(lunes),
              "fecha_fin": str(lunes + timedelta(days=60)),
              "descripcion": "Vacaciones largas", "firmar": False},
    )
    assert r.status_code == 422
    assert "justificación" in r.json()["detail"]["mensaje"]


async def test_regla_de_fin_de_semana_devuelve_rango_sugerido(cliente, auth, empleado):
    # Se reponen los fines de semana pendientes para activar la regla
    await ejecutar(
        "update public.vacation_periods set fines_semana_consumidos = 0 where user_id = %s",
        (empleado["id"],),
    )
    lunes = await lunes_futuro()
    r = await cliente.post(
        "/solicitudes",
        headers=auth,
        json={"tipo": "vacacion", "fecha_inicio": str(lunes),
              "fecha_fin": str(lunes + timedelta(days=4)),   # termina viernes
              "descripcion": "Semana de descanso", "firmar": False},
    )
    assert r.status_code == 422
    detalle = r.json()["detail"]
    assert "sábado y domingo" in detalle["mensaje"]
    assert detalle["rango_sugerido"]["fin"] == str(lunes + timedelta(days=6))


async def test_permiso_sin_categoria_se_rechaza(cliente, auth):
    lunes = await lunes_futuro()
    r = await cliente.post(
        "/solicitudes",
        headers=auth,
        json={"tipo": "permiso", "fecha_inicio": str(lunes), "fecha_fin": str(lunes),
              "descripcion": "Permiso sin tipo", "justificacion": "Motivo suficientemente largo.",
              "firmar": False},
    )
    assert r.status_code == 422


async def test_permiso_medico_sin_respaldo_se_rechaza(cliente, auth):
    tipos = (await cliente.get("/catalogos/tipos-permiso", headers=auth)).json()
    medica = next(t for t in tipos if t["codigo"] == "cita_medica")
    lunes = await lunes_futuro()
    r = await cliente.post(
        "/solicitudes",
        headers=auth,
        json={"tipo": "permiso", "permission_type_id": medica["id"],
              "fecha_inicio": str(lunes), "fecha_fin": str(lunes),
              "hora_inicio": "08:00", "hora_fin": "12:00",
              "descripcion": "Control médico",
              "justificacion": "Cita programada en el hospital del IESS.",
              "firmar": False},
    )
    assert r.status_code == 422
    assert "respaldo" in r.json()["detail"]["mensaje"]


# -------------------------------------------------------------------- firma
async def test_sin_firma_registrada(cliente, auth):
    assert (await cliente.get("/firmas/mia", headers=auth)).json()["registrada"] is False


async def test_firma_dibujada_invalida(cliente, auth):
    r = await cliente.post("/firmas/dibujada", headers=auth, json={"contenido": "no-es-una-firma"})
    assert r.status_code == 422


async def test_firma_que_no_es_imagen_se_rechaza(cliente, auth):
    """Aunque el base64 sea válido, si no empieza con la cabecera PNG/JPEG se rechaza."""
    falsa = "data:image/png;base64," + base64.b64encode(b"<svg onload=alert(1)>" * 20).decode()
    r = await cliente.post("/firmas/dibujada", headers=auth, json={"contenido": falsa})
    assert r.status_code == 422
    assert "no es una imagen" in r.json()["detail"]["mensaje"]


async def test_trazo_vacio_se_rechaza(cliente, auth):
    r = await cliente.post(
        "/firmas/dibujada", headers=auth,
        json={"contenido": "data:image/png;base64,iVBORw0KGgo="},
    )
    assert r.status_code == 422
    assert "vacío" in r.json()["detail"]["mensaje"]


async def test_registrar_firma_y_reemplazarla(cliente, auth):
    r = await cliente.post("/firmas/dibujada", headers=auth, json={"contenido": FIRMA_PNG})
    assert r.status_code == 201
    primera = r.json()["hash_sha256"]

    consulta = (await cliente.get("/firmas/mia", headers=auth)).json()
    assert consulta["registrada"] is True and consulta["tipo"] == "dibujada"

    # Registrar otra desactiva la anterior: siempre hay una sola activa
    r2 = await cliente.post("/firmas/dibujada", headers=auth,
                            json={"contenido": _firma(b"otro trazo real ")})
    assert r2.status_code == 201
    assert r2.json()["hash_sha256"] != primera


async def test_solicitud_firmada_guarda_la_firma(cliente, auth, empleado):
    await cliente.post("/firmas/dibujada", headers=auth, json={"contenido": FIRMA_PNG})
    lunes = await lunes_futuro()
    r = await cliente.post(
        "/solicitudes", headers=auth,
        json={"tipo": "vacacion", "fecha_inicio": str(lunes),
              "fecha_fin": str(lunes + timedelta(days=6)),
              "descripcion": "Vacaciones firmadas", "firmar": True},
    )
    assert r.status_code == 201
    fila = await obtener_uno(
        "select count(*) as n from public.request_signatures where request_id = %s",
        (r.json()["id"],),
    )
    assert fila["n"] == 1


# ----------------------------------------------------------------- consultas
async def test_listar_y_cancelar(cliente, auth):
    lunes = await lunes_futuro()
    creada = await cliente.post(
        "/solicitudes", headers=auth,
        json={"tipo": "vacacion", "fecha_inicio": str(lunes),
              "fecha_fin": str(lunes + timedelta(days=6)),
              "descripcion": "Para cancelar", "firmar": False},
    )
    listado = (await cliente.get("/solicitudes/mias", headers=auth)).json()
    assert any(s["id"] == creada.json()["id"] for s in listado)

    r = await cliente.post(f"/solicitudes/{creada.json()['id']}/cancelar", headers=auth)
    assert r.status_code == 200 and r.json()["estado"] == "cancelado"


async def test_no_se_cancela_una_solicitud_ajena(cliente, auth):
    r = await cliente.post(f"/solicitudes/{uuid.uuid4()}/cancelar", headers=auth)
    assert r.status_code == 404


# ----------------------------------------------------------------- adjuntos
async def test_adjunto_con_tipo_no_permitido(cliente, auth):
    r = await cliente.post(
        f"/solicitudes/adjuntos?solicitud_id={uuid.uuid4()}",
        headers=auth,
        files={"archivo": ("virus.exe", b"MZ" + b"\x00" * 100, "application/x-msdownload")},
    )
    assert r.status_code == 422


async def test_adjunto_demasiado_grande(cliente, auth):
    r = await cliente.post(
        f"/solicitudes/adjuntos?solicitud_id={uuid.uuid4()}",
        headers=auth,
        files={"archivo": ("enorme.pdf", b"%PDF" + b"\x00" * (11 * 1024 * 1024), "application/pdf")},
    )
    assert r.status_code == 413


async def test_adjunto_valido_devuelve_ruta_y_hash(cliente, auth, empleado):
    solicitud = uuid.uuid4()
    r = await cliente.post(
        f"/solicitudes/adjuntos?solicitud_id={solicitud}",
        headers=auth,
        files={"archivo": ("cita.pdf", b"%PDF-1.4 contenido de prueba", "application/pdf")},
    )
    assert r.status_code == 200
    datos = r.json()
    assert datos["storage_path"].startswith(f"{empleado['id']}/{solicitud}/")
    assert len(datos["hash_sha256"]) == 64
