"""Revisión de la emisión de correos: cabeceras que piden Gmail y otros, y
constancia de cada envío (sin contenido ni códigos)."""
from __future__ import annotations

import aiosmtplib

from app import correo
from app.db import ejecutar, obtener_uno
from tests.test_reglas_nuevas import auth, rrhh_auth  # noqa: F401


class _Ajustes:
    email_backend = "smtp"
    smtp_host = "pro.turbo-smtp.com"
    smtp_port = 2525
    smtp_port_alterno = 587
    smtp_user = "u"
    smtp_password = "c"
    smtp_starttls = "auto"
    smtp_timeout = 1
    smtp_remitente = "Talento Humano ITSANET <notificaciones@flexnetecuador.com>"


async def test_el_correo_lleva_date_message_id_y_auto_submitted(monkeypatch):
    capturado = {}

    async def falso(mensaje, **k):
        capturado["m"] = mensaje
    monkeypatch.setattr(correo, "get_settings", lambda: _Ajustes())
    monkeypatch.setattr(aiosmtplib, "send", falso)
    await correo.enviar("persona@empresa.ec", "Código de acceso: 482913", "hola")
    m = capturado["m"]
    assert m["Date"] and m["Message-ID"].endswith("@flexnetecuador.com>")
    assert m["Auto-Submitted"] == "auto-generated"
    fila = await obtener_uno("SELECT destino, asunto, resultado, puerto FROM correos_enviados ORDER BY id DESC LIMIT 1")
    assert fila["resultado"] == "enviado" and fila["puerto"] == 2525
    assert fila["destino"] == "pe***@empresa.ec"
    assert "482913" not in fila["asunto"]          # nunca el código de acceso


async def test_el_fallo_queda_anotado(monkeypatch):
    async def falla(*a, **k):
        raise aiosmtplib.SMTPAuthenticationError(535, "Authentication failed")
    monkeypatch.setattr(correo, "get_settings", lambda: _Ajustes())
    monkeypatch.setattr(aiosmtplib, "send", falla)
    try:
        await correo.enviar("jefe@empresa.ec", "Recordatorio", "hola", intentos=1)
    except aiosmtplib.SMTPAuthenticationError:
        pass
    fila = await obtener_uno("SELECT resultado, error FROM correos_enviados ORDER BY id DESC LIMIT 1")
    assert fila["resultado"] == "fallido" and "535" in fila["error"]


async def test_el_panel_muestra_y_busca_por_correo(cliente, auth, rrhh_auth, empleado):
    await ejecutar("DELETE FROM correos_enviados")
    await correo.enviar(empleado["email"], "Aviso de prueba", "hola")
    assert (await cliente.get("/admin/correo", headers=auth)).status_code == 403
    d = (await cliente.get(f"/admin/correo?buscar={empleado['email']}", headers=rrhh_auth)).json()
    assert d["configuracion"]["clave"] in ("configurada", "FALTA")
    assert "clave" not in str(d["configuracion"]["usuario"]).lower()
    assert len(d["registros"]) == 1 and d["registros"][0]["asunto"] == "Aviso de prueba"
    r = (await cliente.post("/admin/correo/probar", headers=rrhh_auth)).json()
    assert "mensaje" in r
