"""Envío de correo. Con Google Workspace basta SMTP con contraseña de aplicación."""
from __future__ import annotations

import logging
from email.message import EmailMessage

import aiosmtplib

from .config import get_settings

log = logging.getLogger("rrhh.correo")


def _plantilla_otp(nombre: str, codigo: str, minutos: int, app: str) -> tuple[str, str]:
    texto = (
        f"Hola {nombre}:\n\n"
        f"Su código de acceso es: {codigo}\n\n"
        f"Vence en {minutos} minutos y solo puede usarse una vez.\n"
        f"Si usted no solicitó este código, ignore este mensaje y avise a Talento Humano.\n\n"
        f"{app}\n"
    )
    html = f"""<!doctype html>
<html lang="es"><body style="margin:0;padding:24px;background:#f1f5f9;font-family:system-ui,-apple-system,'Segoe UI',sans-serif">
  <table role="presentation" style="max-width:480px;margin:0 auto;background:#fff;border-radius:12px;padding:32px">
    <tr><td>
      <p style="margin:0 0 4px;color:#64748b;font-size:13px">{app}</p>
      <h1 style="margin:0 0 20px;font-size:20px;color:#0f172a">Su código de acceso</h1>
      <p style="margin:0 0 16px;color:#334155;font-size:15px">Hola {nombre}:</p>
      <p style="margin:0 0 8px;color:#334155;font-size:15px">Use este código para ingresar al sistema:</p>
      <p style="margin:0 0 20px;font-size:34px;font-weight:700;letter-spacing:10px;
                color:#0f172a;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;
                padding:16px;text-align:center">{codigo}</p>
      <p style="margin:0 0 16px;color:#64748b;font-size:13px">
        Vence en {minutos} minutos y solo puede usarse una vez.</p>
      <p style="margin:0;color:#64748b;font-size:13px">
        Si usted no solicitó este código, ignore este mensaje y avise a Talento Humano.</p>
    </td></tr>
  </table>
</body></html>"""
    return texto, html


async def enviar(destinatario: str, asunto: str, texto: str, html: str | None = None) -> None:
    settings = get_settings()

    if settings.email_backend == "console":
        log.info("=== CORREO (modo consola) ===\nPara: %s\nAsunto: %s\n%s",
                 destinatario, asunto, texto)
        return

    mensaje = EmailMessage()
    mensaje["From"] = settings.smtp_remitente
    mensaje["To"] = destinatario
    mensaje["Subject"] = asunto
    mensaje.set_content(texto)
    if html:
        mensaje.add_alternative(html, subtype="html")

    await aiosmtplib.send(
        mensaje,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=settings.smtp_starttls,
        timeout=20,
    )


async def enviar_otp(destinatario: str, nombre: str, codigo: str) -> None:
    settings = get_settings()
    texto, html = _plantilla_otp(nombre, codigo, settings.otp_vigencia_minutos, settings.app_nombre)
    await enviar(destinatario, f"Código de acceso: {codigo}", texto, html)
