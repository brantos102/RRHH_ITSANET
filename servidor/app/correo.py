"""Envío de correo. Con Google Workspace basta SMTP con contraseña de aplicación."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

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
      <h1 style="margin:0 0 20px;font-size:20px;color:#06122B">Su código de acceso</h1>
      <p style="margin:0 0 16px;color:#334155;font-size:15px">Hola {nombre}:</p>
      <p style="margin:0 0 8px;color:#334155;font-size:15px">Use este código para ingresar al sistema:</p>
      <p style="margin:0 0 20px;font-size:34px;font-weight:700;letter-spacing:10px;
                color:#06122B;background:#F7F7F7;border:1px solid #D2DEF7;border-radius:10px;
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

    if "quota" in texto or "exceeded" in texto or "limit" in texto or "credit" in texto \
            or "too many" in texto:
        return [
            "El proveedor de correo no acepta más envíos por ahora: se alcanzó el",
            "límite de su plan (cuota diaria o mensual, o créditos agotados).",
            "",
            "Revise el panel del proveedor (envíos usados, créditos, bloqueos) y",
            "amplíe el plan o espere a que se renueve la cuota. Mientras tanto, nadie",
            "recibe el código de acceso.",
        ]

    if "timed out" in texto or "timeout" in texto:
        todos = puertos(settings)
        return [
            f"El servidor {host} no respondió a tiempo en "
            + ("el puerto " + str(todos[0]) if len(todos) == 1
               else "los puertos " + " ni ".join(map(str, todos))) + ".",
            "",
            "Casi siempre es el cortafuegos o la red, que bloquea la salida por ese",
            "puerto. Compruébelo en la terminal del servidor:",
            *[f"    timeout 5 bash -c '</dev/tcp/{host}/{p}' && echo ABIERTO || echo CERRADO" for p in todos],
            "",
            "Si sale CERRADO, pídale a Sistemas que abra la salida hacia ese servidor y",
            "puerto, o configure otro puerto del proveedor con",
            "    bash despliegue/configurar_correo.sh",
            "",
            "Solo para pruebas (nunca con usuarios reales, el código queda en el registro):",
            "    EMAIL_BACKEND=console   en servidor/.env",
        ]

    if "ssl" in texto or "wrong version number" in texto or "record layer" in texto:
        otro = 465 if puerto == 587 else 587
        return [
            "El cifrado no cuadra con el puerto.",
            "",
            "Hay dos formas y no se mezclan:",
            "    SMTP_PORT=587  →  SMTP_STARTTLS=true    (Google Workspace, Microsoft 365)",
            "    SMTP_PORT=587 o 2525  →  SMTP_STARTTLS=auto  (proveedores «sin SSL», como turboSMTP)",
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
        f"  1. SMTP_USER y SMTP_PASSWORD en servidor/.env (contraseña DE APLICACIÓN)",
        f"  2. Que el puerto salga:  timeout 5 bash -c '</dev/tcp/{host}/{puerto}' && echo ABIERTO",
        f"  3. Que el puerto y el cifrado cuadren (587+STARTTLS, o 465 sin él)",
        "",
        "Y para seguir probando el sistema sin correo:",
        "    EMAIL_BACKEND=console   en servidor/.env",
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
    intentos: int = 4,
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
    inicio = time.monotonic()

    if settings.email_backend == "console":
        log.info("=== CORREO (modo consola) ===\nPara: %s%s%s\nAsunto: %s\n%s",
                 destinatario,
                 f"\nCopia: {', '.join(copia)}" if copia else "",
                 f"\nResponder a: {responder_a}" if responder_a else "",
                 asunto, texto)
        await _anotar(destinatario, asunto, "consola", None, None, None, inicio)
        return

    mensaje = EmailMessage()
    mensaje["From"] = settings.smtp_remitente
    mensaje["To"] = destinatario
    # Date y Message-ID: sin ellos Gmail y otros rechazan el correo o lo
    # mandan a spam («Messages missing a valid Message-ID header are not
    # accepted»). Ni el sistema ni la librería de envío los ponían.
    mensaje["Date"] = formatdate(localtime=True)
    dominio = parseaddr(settings.smtp_remitente or "")[1].partition("@")[2] or None
    mensaje["Message-ID"] = make_msgid(domain=dominio)
    # Correo automático (RFC 3834): evita respuestas automáticas en bucle
    # («fuera de la oficina») contra el buzón del sistema.
    mensaje["Auto-Submitted"] = "auto-generated"
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

    try:
        puerto, intento = await _enviar_con_reintentos(mensaje, [destinatario, *(copia or [])], settings,
                                                       intentos=intentos)
    except Exception as exc:
        await _anotar(destinatario, asunto, "fallido", None, intentos, f"{type(exc).__name__}: {exc}", inicio)
        raise
    await _anotar(destinatario, asunto, "enviado", puerto, intento, None, inicio)


def enmascarar(email: str) -> str:
    usuario, _, dominio = (email or "").partition("@")
    return f"{usuario[:2]}***@{dominio}" if dominio else "***"


async def _anotar(destino: str, asunto: str, resultado: str, puerto, intentos, error, inicio: float) -> None:
    """Constancia de cada envío (sin contenido, destino enmascarado, sin
    códigos de acceso). Nunca hace fallar el envío: si la base no responde,
    solo queda en el registro del servidor."""
    try:
        from .db import ejecutar
        await asyncio.wait_for(ejecutar(
            """INSERT INTO correos_enviados (destino, destino_hash, asunto, resultado, puerto, intentos, error,
                                             duracion_ms)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (enmascarar(destino), hashlib.sha256((destino or "").strip().lower().encode()).hexdigest(),
             re.sub(r"\b\d{4,8}\b", "••••••", asunto or "")[:255], resultado, puerto, intentos,
             (error or None) and error[:300], int((time.monotonic() - inicio) * 1000))), timeout=3)
    except Exception:  # noqa: BLE001
        log.debug("No se pudo anotar el envío en correos_enviados", exc_info=True)


# Lo que conviene volver a intentar: el servidor cortó, tardó o pidió que se
# insista luego (respuestas 4xx: «421 inténtelo más tarde», «451 error
# temporal»). Gmail y Microsoft 365 devuelven 421 cuando reciben varias
# conexiones seguidas, y eso era el «intente en unos minutos» que veía la
# gente: el segundo intento, segundos después, casi siempre pasa.
#
# Lo que NO se reintenta: clave rechazada (535), remitente no permitido
# (550/553). Insistir no lo arregla y solo demora el aviso.
ESPERAS = (2, 5, 10)


def es_transitorio(error: Exception) -> bool:
    if isinstance(error, (aiosmtplib.SMTPServerDisconnected, aiosmtplib.SMTPConnectError,
                          aiosmtplib.SMTPTimeoutError, asyncio.TimeoutError,
                          ConnectionError, TimeoutError)):
        return True
    codigo = getattr(error, "code", None)
    if isinstance(codigo, int):
        return 400 <= codigo < 500
    return isinstance(error, OSError) and not isinstance(error, aiosmtplib.SMTPException)


def es_de_conexion(error: Exception) -> bool:
    """No se llegó a hablar con el servidor: puerto cerrado o bloqueado."""
    return isinstance(error, (aiosmtplib.SMTPConnectError, aiosmtplib.SMTPConnectTimeoutError,
                              asyncio.TimeoutError, TimeoutError, ConnectionError)) or (
        isinstance(error, OSError) and not isinstance(error, aiosmtplib.SMTPException))


def puertos(settings) -> list[int]:
    """El puerto principal y, si hay, el alterno (por ejemplo 587 y 2525)."""
    alterno = getattr(settings, "smtp_port_alterno", None)
    return [settings.smtp_port] + ([int(alterno)] if alterno and int(alterno) != settings.smtp_port else [])


# El último puerto por el que salió un correo, por servidor. Si el principal
# no conecta (cortafuegos) y el alterno sí, los envíos siguientes empiezan por
# el alterno: el código de acceso no hace esperar el plazo del puerto cerrado
# cada vez. Vive en memoria: tras reiniciar se vuelve a probar el principal.
_puerto_que_funciona: dict[tuple, int] = {}


async def _enviar_con_reintentos(mensaje: EmailMessage, destinatarios: list[str], settings,
                                 *, intentos: int) -> tuple[int, int]:
    lista = puertos(settings)
    clave = (settings.smtp_host, tuple(lista))
    preferido = _puerto_que_funciona.get(clave)
    indice = lista.index(preferido) if preferido in lista else 0
    for intento in range(1, intentos + 1):
        puerto = lista[indice]
        try:
            await aiosmtplib.send(mensaje, recipients=destinatarios, **parametros_smtp(settings, puerto))
            if intento > 1 or puerto != settings.smtp_port:
                log.info("Correo enviado en el intento %s de %s (puerto %s)", intento, intentos, puerto)
            _puerto_que_funciona[clave] = puerto
            return puerto, intento
        except Exception as exc:  # noqa: BLE001
            if intento >= intentos or not es_transitorio(exc):
                raise
            espera = ESPERAS[min(intento - 1, len(ESPERAS) - 1)]
            # Si el puerto no conecta, el siguiente intento va por el otro,
            # sin esperar: no es que el servidor esté ocupado, es que por ahí
            # no se llega.
            if len(lista) > 1 and es_de_conexion(exc):
                siguiente = (indice + 1) % len(lista)
                # Sin esperar la primera vez que se cambia de puerto; si ya se
                # probaron todos, sí (puede ser un corte momentáneo).
                espera = 0 if intento < len(lista) else espera
                indice = siguiente
            log.warning("El servidor de correo falló en el puerto %s (%s: %s). Reintento %s de %s "
                        "por el puerto %s en %s s", puerto, type(exc).__name__, exc, intento + 1,
                        intentos, lista[indice], espera)
            await asyncio.sleep(espera)


def modo_starttls(valor) -> bool | None:
    """SMTP_STARTTLS: true (exigirlo), false (nunca) o auto (si el servidor lo
    ofrece). auto es lo que conviene con proveedores que publican sus puertos
    587/2525 «sin SSL»: cifra igual cuando pueden y no falla cuando no."""
    t = str(valor).strip().lower()
    if t in ("true", "1", "si", "sí", "yes"):
        return True
    if t in ("false", "0", "no"):
        return False
    return None


def parametros_smtp(settings, puerto: int | None = None) -> dict:
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
    puerto = puerto or settings.smtp_port
    comun = {
        "hostname": settings.smtp_host,
        "port": puerto,
        "username": settings.smtp_user or None,
        "password": settings.smtp_password or None,
        # Por intento. El código de acceso se reintenta con 12 s para que la
        # pantalla no espere más de lo que Apache tolera (60 s en total).
        "timeout": getattr(settings, "smtp_timeout", 12),
    }
    if puerto == 465:
        return {**comun, "use_tls": True, "start_tls": False}
    return {**comun, "start_tls": modo_starttls(settings.smtp_starttls)}


async def enviar_otp(destinatario: str, nombre: str, codigo: str) -> None:
    settings = get_settings()
    texto, html = _plantilla_otp(nombre, codigo, settings.otp_vigencia_minutos, settings.app_nombre)
    # Tres intentos, cada uno con un plazo corto: quien espera su código está
    # mirando la pantalla, y Apache corta la petición a los 60 s.
    await enviar(destinatario, f"Código de acceso: {codigo}", texto, html, intentos=3)
