"""Garita, anulaciones, informes y administración."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA

CEDULA_GUARDIA = "0900000001"
CEDULA_RRHH = "1100000007"
CEDULA_VISITA = "1713175071"


async def lunes_limpio(semanas: int = 6) -> date:
    feriados = {f["fecha"] for f in await obtener_todos(
        "select fecha from public.feriados where activo and fecha >= current_date")}
    base = date.today() + timedelta(weeks=semanas)
    c = base - timedelta(days=base.weekday())
    for _ in range(60):
        if not ({c + timedelta(days=i) for i in range(7)} & feriados):
            return c
        c += timedelta(weeks=1)
    raise AssertionError("sin semana libre")


@pytest.fixture
async def equipo(empleado):
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s,'API Guardia','guardia@api.test','guardia', current_date - 500) returning id""",
        (CEDULA_GUARDIA,))
    rrhh = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s,'API RRHH','rrhh@api.test','rrhh', current_date - 900) returning id""",
        (CEDULA_RRHH,))
    await ejecutar(
        """update public.vacation_periods set fines_semana_consumidos = fines_semana_obligatorios
           where user_id = %s and not caducado""", (empleado["id"],))
    return {"rrhh": str(rrhh["id"])}


async def _entrar(cliente, codigos, cedula) -> dict:
    await cliente.post("/auth/solicitar-token", json={"cedula": cedula})
    r = await cliente.post("/auth/validar-token", json={"cedula": cedula, "codigo": codigos[-1]})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def aprobada(cliente, codigos, equipo, empleado):
    """Una solicitud aprobada, con su QR emitido."""
    emp = await _entrar(cliente, codigos, CEDULA_PRUEBA)
    lunes = await lunes_limpio()
    creada = await cliente.post("/solicitudes", headers=emp, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=6)),
        "descripcion": "Solicitud para garita", "firmar": False})
    assert creada.status_code == 201, creada.text
    solicitud_id = creada.json()["id"]

    # Vigente hoy, que es lo que la garita valida. Se ajusta ANTES de aprobar:
    # el sistema no deja mover fechas de una solicitud ya aprobada.
    await ejecutar(
        "update public.requests set fecha_inicio=current_date, fecha_fin=current_date+2 where id=%s",
        (solicitud_id,))
    await ejecutar("update public.requests set estado='pendiente_rrhh' where id=%s", (solicitud_id,))
    await ejecutar("update public.requests set estado='aprobado' where id=%s", (solicitud_id,))
    fila = await obtener_uno("select qr_hash, folio from public.requests where id=%s", (solicitud_id,))
    return {"id": solicitud_id, "qr": str(fila["qr_hash"]), "folio": fila["folio"]}


# ------------------------------------------------------------------ garita
async def test_un_empleado_no_entra_a_la_garita(cliente, codigos, equipo):
    emp = await _entrar(cliente, codigos, CEDULA_PRUEBA)
    assert (await cliente.get("/garita/hoy", headers=emp)).status_code == 403


async def test_qr_valido_autoriza_la_salida(cliente, codigos, aprobada):
    g = await _entrar(cliente, codigos, CEDULA_GUARDIA)
    r = await cliente.post("/garita/validar-qr", headers=g, json={"codigo": aprobada["qr"]})
    assert r.status_code == 200
    datos = r.json()
    assert datos["autorizado"] is True
    assert datos["folio"] == aprobada["folio"]
    assert datos["nombre"] == "API Empleado"


async def test_qr_inexistente_se_deniega_y_queda_registrado(cliente, codigos, equipo):
    g = await _entrar(cliente, codigos, CEDULA_GUARDIA)
    r = await cliente.post("/garita/validar-qr", headers=g, json={"codigo": str(uuid.uuid4())})
    assert r.json()["autorizado"] is False

    fila = await obtener_uno(
        "select count(*) as n from public.access_logs where tipo_acceso='acceso_denegado'")
    assert fila["n"] >= 1, "un intento denegado debe quedar en la bitácora"


async def test_codigo_ilegible_no_rompe_nada(cliente, codigos, equipo):
    g = await _entrar(cliente, codigos, CEDULA_GUARDIA)
    r = await cliente.post("/garita/validar-qr", headers=g, json={"codigo": "no-es-un-uuid"})
    assert r.status_code == 200 and r.json()["autorizado"] is False


async def test_fuera_de_fecha_se_deniega(cliente, codigos, aprobada, empleado):
    """Una autorización aprobada pero cuyo período aún no empieza no deja salir."""
    # Toda solicitud nace pendiente: el trigger lo impone aunque se inserte
    # directamente. Hay que recorrer el flujo para llegar a «aprobado».
    creada = await obtener_uno(
        """insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
           values (%s, 'vacacion', current_date + 20, current_date + 25,
                   'Autorizacion de fecha futura')
           returning id""",
        (empleado["id"],))
    await ejecutar("update public.requests set estado='pendiente_rrhh' where id=%s", (creada["id"],))
    await ejecutar("update public.requests set estado='aprobado' where id=%s", (creada["id"],))
    futura = await obtener_uno("select qr_hash from public.requests where id=%s", (creada["id"],))

    g = await _entrar(cliente, codigos, CEDULA_GUARDIA)
    r = await cliente.post("/garita/validar-qr", headers=g, json={"codigo": str(futura["qr_hash"])})
    assert r.json()["autorizado"] is False
    assert "Fuera de fecha" in r.json()["motivo"]


async def test_el_panel_del_dia_separa_autorizados_de_en_tramite(cliente, codigos, aprobada):
    g = await _entrar(cliente, codigos, CEDULA_GUARDIA)
    datos = (await cliente.get("/garita/hoy", headers=g)).json()
    assert any(p["folio"] == aprobada["folio"] for p in datos["aprobadas"])
    assert "en_tramite" in datos


async def test_registro_y_salida_de_visita(cliente, codigos, equipo):
    g = await _entrar(cliente, codigos, CEDULA_GUARDIA)
    r = await cliente.post("/garita/visitantes", headers=g, json={
        "cedula": CEDULA_VISITA, "nombre": "Proveedor de prueba", "empresa": "ACME",
        "motivo_visita": "Entrega de equipos", "a_quien_visita_texto": "Bodega"})
    assert r.status_code == 201
    visita = r.json()["id"]

    dentro = (await cliente.get("/garita/visitantes/dentro", headers=g)).json()
    assert any(v["id"] == visita for v in dentro)

    salida = await cliente.post(f"/garita/visitantes/{visita}/salida", headers=g)
    assert salida.status_code == 200 and "min dentro" in salida.json()["mensaje"]

    assert (await cliente.post(f"/garita/visitantes/{visita}/salida", headers=g)).status_code == 404


async def test_visitante_con_cedula_invalida(cliente, codigos, equipo):
    g = await _entrar(cliente, codigos, CEDULA_GUARDIA)
    r = await cliente.post("/garita/visitantes", headers=g, json={
        "cedula": "1234567890", "nombre": "Nadie", "motivo_visita": "Probar"})
    assert r.status_code == 422


# -------------------------------------------------------------- anulaciones
async def test_anular_aprobada_necesita_motivo_y_pasa_a_rrhh(cliente, codigos, aprobada):
    emp = await _entrar(cliente, codigos, CEDULA_PRUEBA)
    sin_motivo = await cliente.post(f"/solicitudes/{aprobada['id']}/cancelar", headers=emp, json={})
    assert sin_motivo.status_code == 422

    con_motivo = await cliente.post(f"/solicitudes/{aprobada['id']}/cancelar", headers=emp,
                                    json={"motivo": "Se adelantó una auditoría"})
    assert con_motivo.status_code == 200
    assert con_motivo.json()["estado"] == "pendiente_anulacion"


async def test_solo_rrhh_resuelve_anulaciones(cliente, codigos, aprobada):
    emp = await _entrar(cliente, codigos, CEDULA_PRUEBA)
    await cliente.post(f"/solicitudes/{aprobada['id']}/cancelar", headers=emp,
                       json={"motivo": "Cambio de planes familiares"})
    assert (await cliente.get("/aprobaciones/anulaciones", headers=emp)).status_code == 403

    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    pendientes = (await cliente.get("/aprobaciones/anulaciones", headers=rrhh)).json()
    assert any(a["id"] == aprobada["id"] for a in pendientes)


async def test_autorizar_anulacion_devuelve_los_dias(cliente, codigos, aprobada, empleado):
    antes = (await obtener_uno("select dias_vacaciones from public.users where id=%s",
                               (empleado["id"],)))["dias_vacaciones"]
    emp = await _entrar(cliente, codigos, CEDULA_PRUEBA)
    await cliente.post(f"/solicitudes/{aprobada['id']}/cancelar", headers=emp,
                       json={"motivo": "Se suspendió el viaje"})

    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    r = await cliente.post(f"/aprobaciones/{aprobada['id']}/anulacion", headers=rrhh,
                           json={"accion": "aprobar"})
    assert r.status_code == 200 and r.json()["estado"] == "cancelado"

    despues = (await obtener_uno("select dias_vacaciones from public.users where id=%s",
                                 (empleado["id"],)))["dias_vacaciones"]
    assert despues > antes, "autorizar la anulación devuelve los días"


async def test_anulacion_denegada_deja_la_solicitud_vigente(cliente, codigos, aprobada):
    emp = await _entrar(cliente, codigos, CEDULA_PRUEBA)
    await cliente.post(f"/solicitudes/{aprobada['id']}/cancelar", headers=emp,
                       json={"motivo": "Prefiero otras fechas"})
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)

    sin_motivo = await cliente.post(f"/aprobaciones/{aprobada['id']}/anulacion", headers=rrhh,
                                    json={"accion": "rechazar"})
    assert sin_motivo.status_code == 422

    r = await cliente.post(f"/aprobaciones/{aprobada['id']}/anulacion", headers=rrhh,
                           json={"accion": "rechazar", "motivo": "El reemplazo ya fue coordinado"})
    assert r.status_code == 200 and r.json()["estado"] == "aprobado"


async def test_el_qr_anulado_deja_de_servir(cliente, codigos, aprobada):
    emp = await _entrar(cliente, codigos, CEDULA_PRUEBA)
    await cliente.post(f"/solicitudes/{aprobada['id']}/cancelar", headers=emp,
                       json={"motivo": "Se suspendió el viaje"})
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    await cliente.post(f"/aprobaciones/{aprobada['id']}/anulacion", headers=rrhh,
                       json={"accion": "aprobar"})

    g = await _entrar(cliente, codigos, CEDULA_GUARDIA)
    r = await cliente.post("/garita/validar-qr", headers=g, json={"codigo": aprobada["qr"]})
    assert r.json()["autorizado"] is False
    assert "anulada" in r.json()["motivo"]


# ----------------------------------------------------------------- informes
async def test_el_informe_filtra_por_numero(cliente, codigos, aprobada):
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    r = await cliente.get(f"/informes/solicitudes?folio={aprobada['folio']}", headers=rrhh)
    assert r.status_code == 200
    filas = r.json()["filas"]
    assert len(filas) == 1 and filas[0]["folio"] == aprobada["folio"]


async def test_el_informe_resume(cliente, codigos, aprobada):
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    r = await cliente.get("/informes/solicitudes", headers=rrhh)
    resumen = r.json()["resumen"]
    assert resumen["total"] >= 1 and "dias_aprobados" in resumen


async def test_el_csv_trae_encabezados_en_espanol(cliente, codigos, aprobada):
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    r = await cliente.get("/informes/solicitudes.csv", headers=rrhh)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    texto = r.content.decode("utf-8")
    assert texto.startswith("﻿"), "el BOM permite que Excel lea los acentos"
    assert "Nº solicitud;Fecha de solicitud;Solicitante" in texto


async def test_las_dimensiones_vienen_de_los_datos(cliente, codigos, equipo):
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    d = (await cliente.get("/informes/dimensiones", headers=rrhh)).json()
    assert "pendiente_anulacion" in d["estados"]
    assert any(p["nombre"] == "API Empleado" for p in d["personas"])


async def test_un_empleado_no_ve_informes(cliente, codigos, equipo):
    emp = await _entrar(cliente, codigos, CEDULA_PRUEBA)
    assert (await cliente.get("/informes/solicitudes", headers=emp)).status_code == 403


# ------------------------------------------------------------ administración
async def test_crear_usuario_con_saldo_de_planilla(cliente, codigos, equipo):
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    r = await cliente.post("/admin/usuarios", headers=rrhh, json={
        "cedula": "1200000006", "nombre": "Nuevo Ingreso", "email": "nuevo@empresa-prueba.com",
        "rol": "empleado", "fecha_ingreso": str(date.today() - timedelta(days=1200)),
        "saldo_inicial": 7.5})
    assert r.status_code == 201, r.text

    fila = await obtener_uno(
        "select dias_vacaciones from public.users where cedula = '1200000006'")
    assert float(fila["dias_vacaciones"]) == 7.5
    await ejecutar("delete from public.users where cedula = '1200000006'")


async def test_cedula_invalida_al_crear_usuario(cliente, codigos, equipo):
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    r = await cliente.post("/admin/usuarios", headers=rrhh, json={
        "cedula": "1234567890", "nombre": "Imposible", "email": "x@empresa-prueba.com",
        "rol": "empleado", "fecha_ingreso": str(date.today())})
    assert r.status_code == 422


async def test_nadie_se_quita_a_si_mismo_la_administracion(cliente, codigos, equipo):
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    yo = (await cliente.get("/auth/me", headers=rrhh)).json()
    r = await cliente.patch(f"/admin/usuarios/{yo['id']}", headers=rrhh, json={"rol": "empleado"})
    assert r.status_code == 409


async def test_solo_administracion_cambia_los_parametros(cliente, codigos, equipo):
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    # RRHH los consulta…
    assert (await cliente.get("/admin/configuracion", headers=rrhh)).status_code == 200
    # …pero no los cambia: deciden derechos de toda la plantilla
    r = await cliente.patch("/admin/configuracion/vacaciones_dias_base", headers=rrhh,
                            json={"valor": "20"})
    assert r.status_code == 403


async def test_feriado_se_desactiva_no_se_borra(cliente, codigos, equipo):
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    fecha_prueba = "2099-06-15"
    await cliente.post("/admin/feriados", headers=rrhh,
                       json={"fecha": fecha_prueba, "nombre": "Feriado de prueba"})
    await cliente.delete(f"/admin/feriados/{fecha_prueba}", headers=rrhh)

    fila = await obtener_uno("select activo from public.feriados where fecha = %s", (fecha_prueba,))
    assert fila is not None, "no debe borrarse: los cálculos pasados deben seguir cuadrando"
    assert fila["activo"] is False
    await ejecutar("delete from public.feriados where fecha = %s", (fecha_prueba,))


async def test_antiguedades_calcula_los_dias_por_anio(cliente, codigos, equipo):
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    gente = (await cliente.get("/admin/antiguedades", headers=rrhh)).json()
    empleado = next(p for p in gente if p["nombre"] == "API Empleado")
    assert empleado["anios"] == 7
    assert float(empleado["dias_por_anio"]) == 17      # Art. 69: 15 + 2


async def test_la_bitacora_registra_quien_administra(cliente, codigos, equipo):
    rrhh = await _entrar(cliente, codigos, CEDULA_RRHH)
    await cliente.post("/admin/feriados", headers=rrhh,
                       json={"fecha": "2099-07-20", "nombre": "Otro feriado"})
    registros = (await cliente.get("/admin/bitacora?limite=20", headers=rrhh)).json()
    assert any(r["accion"] == "feriado_registrado" and r["quien"] == "API RRHH" for r in registros)
    await ejecutar("delete from public.feriados where fecha = '2099-07-20'")
