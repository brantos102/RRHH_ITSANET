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


def por_que_no_sale(error: Exception, settings=None) -> list[str]:
    """Traduce el fallo del envío a lo que hay que hacer.

    Vive aquí y no en el guion de diagnóstico porque quien ve el fallo de
    verdad es el servidor, al intentar enviar el código de acceso. Quien
    está entrando recibe un mensaje neutro —no puede arreglar un servidor
    de correo—, pero quien lee el registro sí puede, y antes se quedaba con
    una traza de treinta líneas sin saber qué hacer con ella.

    El orden importa: se mira primero lo que el texto del error dice sin
    lugar a dudas, y solo al final se cae en los consejos generales.
    """
    settings = settings or get_settings()
    texto = f"{type(error).__name__}: {error}".lower()
    host, puerto = settings.smtp_host, settings.smtp_port

    if "535" in texto or "username and password not accepted" in texto \
            or "authentication" in texto or "auth" in texto and "fail" in texto:
        return [
            "El servidor rechazó el usuario o la contraseña.",
            "",
            "Con Google Workspace NO sirve la contraseña normal de la cuenta:",
            "hace falta una CONTRASEÑA DE APLICACIÓN de 16 letras, que se genera en",
            "    https://myaccount.google.com/apppasswords",
            "y exige tener la verificación en dos pasos activada en esa cuenta.",
            "",
            "Péguela en SMTP_PASSWORD, sin espacios y sin comillas.",
            "Si la copió con espacios («abcd efgh ijkl mnop»), quítelos.",
        ]

    if "timed out" in texto or "timeout" in texto:
        return [
            f"El servidor {host}:{puerto} no respondió a tiempo.",
            "",
            "Casi siempre es el cortafuegos o la red de la oficina, que bloquea",
            "la salida por ese puerto. Compruébelo desde PowerShell:",
            f"    Test-NetConnection {host} -Port {puerto}",
            "",
            "Si «TcpTestSucceeded» sale en False, el puerto está cerrado: pídale a",
            "Sistemas que abra la salida, o pruebe el otro puerto de este servidor",
            f"    SMTP_PORT={'465' if puerto == 587 else '587'}",
            "",
            "Mientras tanto, para no quedarse sin probar el sistema:",
            "    EMAIL_BACKEND=console   en backend/.env",
            "El código aparece en la terminal del backend en vez de por correo.",
        ]

    if "ssl" in texto or "wrong version number" in texto or "record layer" in texto:
        otro = 465 if puerto == 587 else 587
        return [
            "El cifrado no cuadra con el puerto.",
            "",
            "Hay dos formas y no se mezclan:",
            "    SMTP_PORT=587  →  SMTP_STARTTLS=true    (Google Workspace, Microsoft 365)",
            "    SMTP_PORT=465  →  SMTP_STARTTLS=false   (la conexión ya nace cifrada)",
            "",
            f"Ahora tiene el puerto {puerto} con STARTTLS={str(settings.smtp_starttls).lower()}.",
            f"Pruebe con el puerto {otro}.",
        ]

    if "name or service not known" in texto or "getaddrinfo" in texto \
            or "nodename nor servname" in texto:
        return [
            f"No se pudo resolver el nombre «{host}».",
            "",
            "Revise que SMTP_HOST esté bien escrito (smtp.gmail.com para Google",
            "Workspace, smtp.office365.com para Microsoft 365) y que el equipo",
            "tenga salida a internet.",
        ]

    if "connection refused" in texto or "actively refused" in texto:
        return [
            f"El servidor {host} rechazó la conexión en el puerto {puerto}.",
            "",
            "El nombre resuelve pero ese puerto no atiende. Revise SMTP_PORT:",
            "587 con STARTTLS, o 465 con la conexión ya cifrada.",
        ]

    if "relay" in texto or "not allowed" in texto or "553" in texto or "550" in texto:
        return [
            "El servidor aceptó la conexión pero no quiso enviar el mensaje.",
            "",
            f"Suele ser que SMTP_REMITENTE ({settings.smtp_remitente}) no coincide",
            f"con la cuenta autenticada ({settings.smtp_user}). Muchos servidores",
            "exigen que el remitente sea esa misma cuenta o un alias suyo.",
        ]

    return [
        "No reconozco este fallo. El texto completo está arriba.",
        "",
        "Lo que conviene revisar, en este orden:",
        f"  1. SMTP_USER y SMTP_PASSWORD en backend/.env (contraseña DE APLICACIÓN)",
        f"  2. Que el puerto salga:  Test-NetConnection {host} -Port {puerto}",
        f"  3. Que el puerto y el cifrado cuadren (587+STARTTLS, o 465 sin él)",
        "",
        "Y para seguir probando el sistema sin correo:",
        "    EMAIL_BACKEND=console   en backend/.env",
    ]


async def enviar(
    destinatario: str,
    asunto: str,
    texto: str,
    html: str | None = None,
    *,
    imagenes: dict[str, bytes] | None = None,
    adjuntos: list[tuple[str, bytes, str]] | None = None,
    responder_a: str | None = None,
    copia: list[str] | None = None,
) -> None:
    """Envía un correo.

    `imagenes` son imágenes incrustadas por Content-ID: {"qr": b"...png"} se
    referencia en el HTML como <img src="cid:qr">. Los clientes de correo
    bloquean las data URI, pero muestran las imágenes incrustadas así.
    `adjuntos` es una lista de (nombre, contenido, mime).

    `responder_a` pone la dirección del empleado en Reply-To: cuando Talento
    Humano contesta un aviso del sistema, la respuesta debe llegarle a la
    persona y no a un buzón que nadie lee. `copia` deja constancia en el
    correo de quien pidió algo, que es lo que le permite darle seguimiento
    desde su propia bandeja.
    """
    settings = get_settings()

    if settings.email_backend == "console":
        log.info("=== CORREO (modo consola) ===\nPara: %s%s%s\nAsunto: %s\n%s",
                 destinatario,
                 f"\nCopia: {', '.join(copia)}" if copia else "",
                 f"\nResponder a: {responder_a}" if responder_a else "",
                 asunto, texto)
        return

    mensaje = EmailMessage()
    mensaje["From"] = settings.smtp_remitente
    mensaje["To"] = destinatario
    if copia:
        mensaje["Cc"] = ", ".join(copia)
    if responder_a:
        mensaje["Reply-To"] = responder_a
    mensaje["Subject"] = asunto
    mensaje.set_content(texto)
    if html:
        mensaje.add_alternative(html, subtype="html")

        for cid, contenido in (imagenes or {}).items():
            mensaje.get_payload()[-1].add_related(
                contenido, maintype="image", subtype="png", cid=f"<{cid}>"
            )

    for nombre, contenido, mime in adjuntos or []:
        principal, _, secundario = mime.partition("/")
        mensaje.add_attachment(contenido, maintype=principal, subtype=secundario, filename=nombre)

    await aiosmtplib.send(mensaje, recipients=[destinatario, *(copia or [])],
                          **parametros_smtp(settings))


def parametros_smtp(settings) -> dict:
    """Cómo se conecta al servidor de correo, según el puerto.

    Hay dos formas de cifrar SMTP y confundirlas deja el envío colgado hasta
    que vence el plazo, sin decir por qué:

      · Puerto 587 (STARTTLS): se abre la conexión en claro y se sube a TLS
        con un comando. Es lo que usan Google Workspace y Microsoft 365.
      · Puerto 465 (TLS implícito): la conexión nace cifrada. Aquí NO va
        STARTTLS; pedirlo sobre una conexión ya cifrada es un error.

    El puerto manda sobre lo que diga SMTP_STARTTLS, porque el puerto es el
    dato que no se puede equivocar: 465 solo existe para TLS implícito.
    """
    comun = {
        "hostname": settings.smtp_host,
        "port": settings.smtp_port,
        "username": settings.smtp_user or None,
        "password": settings.smtp_password or None,
        "timeout": 20,
    }
    if settings.smtp_port == 465:
        return {**comun, "use_tls": True, "start_tls": False}
    return {**comun, "start_tls": settings.smtp_starttls}


async def enviar_otp(destinatario: str, nombre: str, codigo: str) -> None:
    settings = get_settings()
    texto, html = _plantilla_otp(nombre, codigo, settings.otp_vigencia_minutos, settings.app_nombre)
    await enviar(destinatario, f"Código de acceso: {codigo}", texto, html)
