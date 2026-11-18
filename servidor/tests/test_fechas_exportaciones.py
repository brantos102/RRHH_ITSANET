"""Fecha al imprimir, escaneo como último paso, exportaciones con
trazabilidad, notas de actualización y orden de las tarjetas.

  · Un documento se imprime con la fecha de hoy; con una anterior, solo
    Talento Humano, con justificación, y hasta tres veces por documento.
  · El pendiente de firma sigue abierto hasta que se sube el escaneo.
  · Cada exportación pide motivo, lleva folio y deja su huella registrada.
  · Las notas de actualización se leen y descargan, sin salir de su carpeta.
"""
from __future__ import annotations

import hashlib
import io
from datetime import date, timedelta

import pytest
from openpyxl import load_workbook

from app.db import ejecutar, obtener_uno
from tests.test_panel_configurable import admin_auth  # noqa: F401
from tests.test_reglas_nuevas import (CEDULA_RRHH_R, auth, jefe_auth,  # noqa: F401
                                      lunes_sin_feriados, rrhh_auth)
from tests.test_sedes_ficha_escaneos import _papel_de_solicitud


@pytest.fixture(autouse=True)
async def _sin_papeles(empleado):
    await ejecutar("DELETE FROM informes_firmados WHERE user_id = %s", (empleado["id"],))
    yield
    await ejecutar("DELETE FROM informes_firmados WHERE user_id = %s", (empleado["id"],))
    await ejecutar("DELETE FROM exportaciones WHERE motivo LIKE %s", ("Prueba automática%",))


# ------------------------------------------------------- fecha al imprimir
async def test_fecha_anterior_con_justificacion_y_hasta_tres_veces(cliente, auth, rrhh_auth, empleado):
    papel = await _papel_de_solicitud(cliente, auth, empleado)
    ayer = (date.today() - timedelta(days=1)).isoformat()

    # Hoy: sin preguntas, y queda registrada como no retroactiva.
    r = await cliente.get(f"/papeles/{papel['id']}.pdf", headers=rrhh_auth)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")

    # El colaborador no puede poner una fecha anterior.
    r = await cliente.get(f"/papeles/{papel['id']}.pdf", headers=auth,
                          params={"fecha": ayer, "justificacion": "Vacaciones gozadas antes del sistema"})
    assert r.status_code == 403
    # Sin justificación, no.
    r = await cliente.get(f"/papeles/{papel['id']}.pdf", headers=rrhh_auth, params={"fecha": ayer})
    assert r.status_code == 422
    # Futura, nunca.
    r = await cliente.get(f"/papeles/{papel['id']}.pdf", headers=rrhh_auth,
                          params={"fecha": (date.today() + timedelta(days=2)).isoformat()})
    assert r.status_code == 422

    for _ in range(3):
        r = await cliente.get(f"/papeles/{papel['id']}.pdf", headers=rrhh_auth,
                              params={"fecha": ayer, "justificacion": "Vacaciones gozadas antes del sistema"})
        assert r.status_code == 200, r.text
    r = await cliente.get(f"/papeles/{papel['id']}.pdf", headers=rrhh_auth,
                          params={"fecha": ayer, "justificacion": "Vacaciones gozadas antes del sistema"})
    assert r.status_code == 409 and "máximo" in r.json()["detail"]["mensaje"]

    f = (await cliente.get(f"/papeles/{papel['id']}/fechas", headers=rrhh_auth)).json()
    assert f["usadas"] == 3 and f["restantes"] == 0
    assert sum(1 for h in f["historial"] if h["retroactiva"]) == 3
    # Y lo ve el colaborador al imprimir: hoy, siempre.
    assert (await cliente.get(f"/papeles/{papel['id']}.pdf", headers=auth)).status_code == 200


async def test_el_pdf_dice_la_fecha_consignada_y_la_real(cliente, auth, rrhh_auth, empleado):
    from pypdf import PdfReader
    papel = await _papel_de_solicitud(cliente, auth, empleado)
    anterior = date.today() - timedelta(days=10)
    r = await cliente.get(f"/papeles/{papel['id']}.pdf", headers=rrhh_auth,
                          params={"fecha": anterior.isoformat(),
                                  "justificacion": "Documento de vacaciones gozadas en octubre"})
    texto = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert f"{anterior:%d/%m/%Y}" in texto and f"{date.today():%d/%m/%Y}" in texto


# ------------------------------------------------- escaneo, último paso
async def test_el_pendiente_sigue_hasta_subir_el_escaneo(cliente, auth, rrhh_auth, empleado):
    await cliente.post("/papeles/trazabilidad", headers=auth)
    papel = await obtener_uno(
        "SELECT id FROM informes_firmados WHERE user_id = %s AND tipo = 'trazabilidad'", (empleado["id"],))
    assert papel, "la constancia debió emitirse"
    await cliente.get(f"/papeles/{papel['id']}.pdf", headers=rrhh_auth)

    def tiene(d):
        return any(i["tipo"] == "firma" and i["id"] == str(papel["id"]) for i in d["items"])

    assert tiene((await cliente.get("/rrhh/pendientes", headers=rrhh_auth, params={"sede": "todas"})).json())
    await cliente.post(f"/admin/papeles/{papel['id']}/firmado", headers=rrhh_auth)
    d = (await cliente.get("/rrhh/pendientes", headers=rrhh_auth, params={"sede": "todas"})).json()
    assert tiene(d), "firmado pero sin escaneo: sigue pendiente"
    assert any("falta subir el escaneo" in i["detalle"] for i in d["items"] if i["id"] == str(papel["id"]))

    r = await cliente.post(f"/admin/papeles/{papel['id']}/escaneo", headers=rrhh_auth,
                           files={"archivo": ("f.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf")})
    assert r.status_code == 200
    d = (await cliente.get("/rrhh/pendientes", headers=rrhh_auth, params={"sede": "todas"})).json()
    assert not tiene(d)
    assert any("Escaneo firmado subido" in a["detalle"] for a in d["atendidos_hoy"])


# ---------------------------------------------------------- exportaciones
async def test_exportar_pide_motivo_y_deja_folio_y_huella(cliente, auth, rrhh_auth, empleado):
    assert (await cliente.post("/admin/exportaciones", headers=auth, json={
        "tipo": "personas", "motivo": "Prueba automática de permisos"})).status_code == 403
    r = await cliente.post("/admin/exportaciones", headers=rrhh_auth, json={
        "tipo": "personas", "formato": "xlsx", "motivo": "corto"})
    assert r.status_code == 422

    previa = (await cliente.post("/admin/exportaciones/previa", headers=rrhh_auth, json={
        "tipo": "personas", "filtros": {"personas": [empleado["id"]]}})).json()
    assert previa["filas"] == 1

    r = await cliente.post("/admin/exportaciones", headers=rrhh_auth, json={
        "tipo": "personas", "formato": "xlsx", "filtros": {"personas": [empleado["id"]]},
        "motivo": "Prueba automática de exportación por persona"})
    assert r.status_code == 200, r.text
    folio = r.headers["x-folio"]
    assert folio.startswith(f"EXP-{date.today().year}-")
    assert r.headers["x-sha256"] == hashlib.sha256(r.content).hexdigest()
    hoja = load_workbook(io.BytesIO(r.content)).active
    celdas = " ".join(str(c.value) for fila in hoja.iter_rows() for c in fila if c.value)
    assert folio in celdas and "Prueba automática de exportación" in celdas and empleado["cedula"] in celdas
    # La fila de encabezados lleva el azul de la marca (antes se pintaba la de arriba).
    cabecera = next(f for f in hoja.iter_rows() if f[0].value == "Cédula")
    assert cabecera[0].fill.start_color.rgb.endswith("1C58D7")
    assert hoja._images, "el archivo lleva el logo"
    fila = await obtener_uno("SELECT filas, sha256 FROM exportaciones WHERE folio = %s", (folio,))
    assert fila["filas"] == 1 and fila["sha256"] == r.headers["x-sha256"]
    historial = (await cliente.get("/admin/exportaciones", headers=rrhh_auth)).json()
    assert any(h["folio"] == folio for h in historial)


@pytest.mark.parametrize("tipo", ["saldos", "solicitudes", "historial", "documentos"])
@pytest.mark.parametrize("formato", ["pdf", "csv"])
async def test_cada_informe_sale_en_cada_formato(cliente, auth, rrhh_auth, empleado, tipo, formato):
    await _papel_de_solicitud(cliente, auth, empleado)
    r = await cliente.post("/admin/exportaciones", headers=rrhh_auth, json={
        "tipo": tipo, "formato": formato, "filtros": {"personas": [empleado["id"]], "desde": "2000-01-01",
                                                      "hasta": (date.today() + timedelta(days=400)).isoformat()},
        "motivo": "Prueba automática de formatos"})
    if r.status_code == 422:      # sin datos de ese tipo para la persona de prueba
        assert "No hay datos" in r.json()["detail"]["mensaje"]
        return
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF" if formato == "pdf" else "﻿".encode())


# ---------------------------------------------------- notas de actualización
async def test_notas_de_actualizacion_solo_admin_y_sin_salir_de_la_carpeta(cliente, admin_auth, rrhh_auth):
    assert (await cliente.get("/admin/actualizaciones", headers=rrhh_auth)).status_code == 403
    d = (await cliente.get("/admin/actualizaciones", headers=admin_auth)).json()
    assert d["notas"] and d["comando"] == "bash despliegue/actualizar.sh"
    assert d["migraciones"]["faltan"] == []
    archivo = d["notas"][0]["archivo"]
    r = await cliente.get(f"/admin/actualizaciones/{archivo}", headers=admin_auth, params={"descargar": True})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "actualizar.sh" in r.text
    for malo in ("..%2F..%2Fservidor%2F.env", "LEEME.md", "2026-01-01_01_x.sql"):
        assert (await cliente.get(f"/admin/actualizaciones/{malo}", headers=admin_auth)).status_code == 404


# ------------------------------------------------------- orden por arrastre
async def test_ordenar_vistas_y_bloques(cliente, rrhh_auth):
    ids = []
    for nombre in ("Prueba orden A", "Prueba orden B"):
        r = await cliente.post("/tablero/vistas", headers=rrhh_auth, json={
            "nombre": nombre, "medida": "personas", "dimension": "sede", "grafico": "columnas", "ancho": 4})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])
    assert (await cliente.post("/tablero/vistas/orden", headers=rrhh_auth,
                               json={"ids": list(reversed(ids))})).status_code == 200
    vistas = [v for v in (await cliente.get("/tablero/vistas", headers=rrhh_auth)).json() if v["id"] in ids]
    assert [v["id"] for v in vistas] == list(reversed(ids))
    await ejecutar("DELETE FROM tablero_vistas WHERE nombre LIKE %s", ("Prueba orden%",))

    antes = (await cliente.get("/admin/tablero", headers=rrhh_auth)).json()
    claves = [b["clave"] for b in antes]
    r = await cliente.post("/admin/tablero/orden", headers=rrhh_auth, json={"claves": list(reversed(claves))})
    assert r.status_code == 200
    despues = [b["clave"] for b in (await cliente.get("/admin/tablero", headers=rrhh_auth)).json()]
    assert despues == list(reversed(claves))
    await cliente.post("/admin/tablero/orden", headers=rrhh_auth, json={"claves": claves})


async def test_cifra_con_comparacion_y_filtro_cruzado(cliente, rrhh_auth, empleado):
    r = await cliente.get("/tablero/explorar", headers=rrhh_auth, params={
        "medida": "altas", "dimension": "total", "comparar": True, "desde": "2025-01-01", "hasta": "2025-12-31"})
    assert r.status_code == 200 and r.json()["anterior"] is not None
    r = await cliente.get("/tablero/explorar", headers=rrhh_auth, params={
        "medida": "personas", "dimension": "area", "cargo": "cargo que no existe"})
    assert r.json()["datos"] == []
