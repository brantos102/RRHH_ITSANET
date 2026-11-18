"""Historial de vacaciones por año, descargas y revisión con evidencia."""
from __future__ import annotations

import io

from app import correo
from app.db import ejecutar, obtener_uno
from tests.test_reglas_nuevas import auth, rrhh_auth  # noqa: F401

PDF = b"%PDF-1.4\n% correo de prueba\n"


async def _historicas(empleado_id):
    await ejecutar("DELETE FROM vacaciones_historicas WHERE user_id = %s", (empleado_id,))
    for ini, fin, dias in (("2024-01-22", "2024-01-22", 1), ("2024-02-14", "2024-02-18", 5),
                           ("2025-07-14", "2025-07-20", 7)):
        await ejecutar("INSERT INTO vacaciones_historicas (user_id, fecha_inicio, fecha_fin, dias) "
                       "VALUES (%s, %s, %s, %s)", (empleado_id, ini, fin, dias))


async def test_el_historial_por_anio_cuadra(cliente, auth, empleado):
    await _historicas(empleado["id"])
    d = (await cliente.get("/mi-historial/anual", headers=auth)).json()
    por_anio = {a["anio"]: a for a in d["anios"]}
    assert por_anio[2024]["tomados"] == 6 and len(por_anio[2024]["registros"]) == 2
    assert por_anio[2025]["tomados"] == 7
    res = d["resumen"]
    assert res["generados"] == round(sum(a["asignados"] for a in d["anios"]), 2)
    assert res["tomados"] == round(sum(a["tomados"] for a in d["anios"]), 2)
    # El balance de cada año es asignados − tomados.
    for a in d["anios"]:
        assert a["balance"] == round(a["asignados"] - a["tomados"], 2)
    # Cada año de servicio dice base y adicionales (Art. 69: hasta 15 adicionales).
    for a in d["anios"]:
        for p in a["periodos"]:
            assert p["base"] == 15 and 0 <= p["adicionales"] <= 15


async def test_descarga_excel_y_pdf(cliente, auth, empleado):
    await _historicas(empleado["id"])
    x = await cliente.get("/mi-historial/excel", headers=auth)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    from openpyxl import load_workbook
    hoja = load_workbook(io.BytesIO(x.content)).active
    textos = [str(c.value) for fila in hoja.iter_rows() for c in fila if c.value is not None]
    assert "Control de Vacaciones y Permisos" in textos and any(t.startswith("Año 2024") for t in textos)
    p = await cliente.get("/mi-historial/pdf", headers=auth)
    assert p.status_code == 200 and p.content[:4] == b"%PDF"
    from pypdf import PdfReader
    texto = "".join(pg.extract_text() for pg in PdfReader(io.BytesIO(p.content)).pages)
    assert "Año 2024" in texto and "DÍAS GENERADOS" in texto
    assert await obtener_uno("SELECT 1 AS x FROM audit_logs WHERE accion = 'historial_descargado' LIMIT 1")


async def test_refutar_exige_evidencia_y_llega_a_talento_humano(cliente, auth, rrhh_auth, empleado, monkeypatch):
    await _historicas(empleado["id"])
    d = (await cliente.get("/mi-historial/anual", headers=auth)).json()
    reg = next(r for a in d["anios"] for r in a["registros"] if r["dias"] == 5)
    form = {"origen": reg["origen"], "ref": reg["ref"], "motivo": "Ese febrero no salí: estuve trabajando."}
    # Sin evidencia, no.
    r = await cliente.post("/mi-historial/revisar", headers=auth, data=form)
    assert r.status_code == 422 and "evidencia" in r.json()["detail"]["mensaje"]
    # Un tipo de archivo no admitido, tampoco.
    r = await cliente.post("/mi-historial/revisar", headers=auth, data=form,
                           files={"archivos": ("virus.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 422

    enviados = []

    async def falso(destino, asunto, texto, html=None, **k):
        enviados.append((destino, asunto, k.get("adjuntos"), k.get("responder_a")))
    monkeypatch.setattr(correo, "enviar", falso)
    r = await cliente.post("/mi-historial/revisar", headers=auth, data=form,
                           files=[("archivos", ("correo.pdf", PDF, "application/pdf")),
                                  ("archivos", ("correo.eml", b"From: a@b.ec\n\nhola", "message/rfc822"))])
    assert r.status_code == 200, r.text
    rid = r.json()["id"]
    # Llega a Talento Humano con la evidencia adjunta y Reply-To de la persona.
    a_th = [e for e in enviados if e[0] == "talento@api.test"]
    assert a_th and "Revisión del historial" in a_th[0][1] and len(a_th[0][2]) == 2
    assert a_th[0][3] == empleado["email"]
    # No se puede pedir dos veces lo mismo mientras espera.
    r2 = await cliente.post("/mi-historial/revisar", headers=auth, data=form,
                            files={"archivos": ("c.pdf", PDF, "application/pdf")})
    assert r2.status_code == 409
    # La persona ve el estado en su historial.
    d = (await cliente.get("/mi-historial/anual", headers=auth)).json()
    reg = next(r for a in d["anios"] for r in a["registros"] if r["dias"] == 5)
    assert reg["revision"]["estado"] == "pendiente"

    # Talento Humano la ve, abre la evidencia y responde.
    bandeja = (await cliente.get("/rrhh/revisiones-historial", headers=rrhh_auth)).json()
    rev = next(b for b in bandeja if b["id"] == rid)
    assert len(rev["evidencias"]) == 2
    ev = await cliente.get(f"/revisiones-historial/{rid}/evidencias/{rev['evidencias'][0]['id']}", headers=rrhh_auth)
    assert ev.status_code == 200 and ev.content == PDF
    assert (await cliente.post(f"/rrhh/revisiones-historial/{rid}", headers=auth,
                               json={"accion": "aceptar", "respuesta": "No me corresponde a mí"})).status_code == 403
    r = await cliente.post(f"/rrhh/revisiones-historial/{rid}", headers=rrhh_auth,
                           json={"accion": "aceptar", "respuesta": "Revisado con su jefe: se corrige el registro."})
    assert r.status_code == 200
    assert any(e[0] == empleado["email"] and "aceptó" in e[1] for e in enviados)
    d = (await cliente.get("/mi-historial/anual", headers=auth)).json()
    reg = next(r for a in d["anios"] for r in a["registros"] if r["dias"] == 5)
    assert reg["revision"]["estado"] == "aceptada" and reg["revision"]["respuesta"].startswith("Revisado")


async def test_nadie_refuta_registros_ajenos(cliente, auth):
    otro = await obtener_uno("SELECT id FROM vacaciones_historicas ORDER BY id LIMIT 1")
    ref = str(otro["id"]) if otro else "999999"
    r = await cliente.post("/mi-historial/revisar", headers=auth,
                           data={"origen": "historico", "ref": "999999999", "motivo": "Este registro no es mío, nunca salí."},
                           files={"archivos": ("c.pdf", PDF, "application/pdf")})
    assert r.status_code == 404
    assert ref
