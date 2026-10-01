"""Dice por qué no sale el correo, en castellano y con el remedio.

El sistema envía el código de acceso por correo. Si el envío falla, la
pantalla dice «No pudimos enviar el correo. Intente en unos minutos.» —y
tiene que decir eso, porque quien está entrando no es quien configura el
servidor—. El motivo de verdad queda en el registro, mezclado con una traza
de Python de treinta líneas.

Este guion hace el envío a propósito, atrapa el fallo y lo traduce:

    python scripts/probar_correo.py                  prueba y escribe a SMTP_USER
    python scripts/probar_correo.py usted@itsanet.com.ec
    python scripts/probar_correo.py --solo-revisar   no envía: solo revisa la configuración

No guarda nada ni toca la base de datos.
"""
from __future__ import annotations

import argparse
import asyncio
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _windows  # noqa: F401,E402
import _cli  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"


def diagnostico(error: Exception, settings) -> list[str]:
    """Traduce el fallo a lo que hay que hacer.

    El orden importa: se mira primero lo que el texto del error dice sin
    lugar a dudas, y solo al final se cae en los consejos generales.
    """
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


def revisar(settings) -> list[str]:
    """Lo que se ve mal sin necesidad de conectarse a ninguna parte."""
    avisos = []
    if settings.email_backend == "console":
        avisos.append(
            "EMAIL_BACKEND=console: el sistema NO envía correos, los imprime en la "
            "terminal del backend. Está bien para probar; para que la gente reciba "
            "su código hay que ponerlo en «smtp».")
    if not settings.smtp_user:
        avisos.append("SMTP_USER está vacío: casi ningún servidor acepta envíos sin autenticar.")
    if not settings.smtp_password:
        avisos.append("SMTP_PASSWORD está vacío.")
    elif settings.smtp_password.startswith("<") or "contrasena" in settings.smtp_password.lower():
        avisos.append("SMTP_PASSWORD sigue siendo el texto de ejemplo del archivo .env.")
    elif " " in settings.smtp_password:
        avisos.append(
            "SMTP_PASSWORD tiene espacios. Google muestra la contraseña de aplicación "
            "en cuatro grupos («abcd efgh ijkl mnop») pero se escribe SIN espacios.")
    if settings.smtp_port == 465 and settings.smtp_starttls:
        avisos.append(
            "SMTP_PORT=465 con SMTP_STARTTLS=true. El 465 nace cifrado y no lleva "
            "STARTTLS; se usará TLS implícito e ignorará esa línea, pero conviene "
            "corregirla para que el archivo diga la verdad.")
    if settings.smtp_port == 587 and not settings.smtp_starttls:
        avisos.append("SMTP_PORT=587 con SMTP_STARTTLS=false: el 587 exige STARTTLS.")
    if settings.smtp_user and settings.smtp_user not in settings.smtp_remitente:
        avisos.append(
            f"SMTP_REMITENTE no contiene a {settings.smtp_user}. Muchos servidores "
            "rechazan enviar en nombre de otra dirección.")
    return avisos


async def principal(destino: str | None, solo_revisar: bool) -> int:
    if not (RAIZ / "backend" / ".env").exists():
        print(f"{ROJO}✗{FIN} No existe backend/.env. Cópielo de backend/.env.example.")
        return 1

    from app.config import get_settings
    settings = get_settings()

    print("Configuración actual")
    print("────────────────────")
    print(f"  SMTP_HOST       {settings.smtp_host}")
    print(f"  SMTP_PORT       {settings.smtp_port}")
    print(f"  SMTP_USER       {settings.smtp_user or '(vacío)'}")
    print(f"  SMTP_PASSWORD   {'•' * 12 if settings.smtp_password else '(vacío)'}"
          f"  {GRIS}({len(settings.smtp_password)} caracteres){FIN}")
    print(f"  SMTP_STARTTLS   {str(settings.smtp_starttls).lower()}")
    print(f"  SMTP_REMITENTE  {settings.smtp_remitente}")
    print(f"  EMAIL_BACKEND   {settings.email_backend}")
    print()

    avisos = revisar(settings)
    for aviso in avisos:
        print(f"{AMARILLO}!{FIN} {aviso}\n")

    if solo_revisar:
        return 0 if not avisos else 1

    if settings.email_backend == "console":
        print(f"{GRIS}No se intenta enviar nada: con EMAIL_BACKEND=console no hay envío "
              f"que probar.{FIN}")
        return 1

    destinatario = destino or settings.smtp_user
    if not destinatario:
        print(f"{ROJO}✗{FIN} Indique a qué dirección escribir:")
        print("    python scripts/probar_correo.py usted@itsanet.com.ec")
        return 1

    print(f"Enviando una prueba a {destinatario}…")
    from app import correo
    try:
        await correo.enviar(
            destinatario,
            "Prueba de configuración · Permisos y Vacaciones",
            "Si está leyendo esto, el sistema ya puede enviar los códigos de acceso.\n\n"
            "Este mensaje lo generó scripts/probar_correo.py. Nadie más lo recibió.\n",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"\n{ROJO}✗ No se pudo enviar.{FIN}\n")
        print(f"{GRIS}{type(exc).__name__}: {exc}{FIN}\n")
        print("Qué significa")
        print("─────────────")
        for linea in diagnostico(exc, settings):
            print(f"  {linea}" if linea else "")
        return 1

    print(f"\n{VERDE}✓ Enviado.{FIN} Revise la bandeja de {destinatario} —y la carpeta de")
    print("  correo no deseado, que es donde suele caer el primero.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Comprueba que el sistema puede enviar los códigos de acceso.")
    p.add_argument("destino", nargs="?", help="A qué dirección escribir (por omisión, SMTP_USER).")
    p.add_argument("--solo-revisar", action="store_true",
                   help="Revisa la configuración sin enviar nada.")
    args = _cli.analizar(p)
    try:
        return asyncio.run(principal(args.destino, args.solo_revisar))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
