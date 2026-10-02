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
    # Un servidor de correo en esta misma máquina es casi siempre un
    # «cazador» de correos para desarrollo (MailHog, Mailpit, MailDev): no
    # entrega nada, los retiene en una bandeja local. Sirve para que usted
    # vea el código, pero si convoca a colaboradores a probar, ellos no
    # recibirán el suyo y no sabrán por qué.
    if settings.smtp_host.lower() in ("localhost", "127.0.0.1", "::1", "[::1]"):
        avisos.append(
            f"SMTP_HOST es «{settings.smtp_host}»: el correo sale a un servidor de ESTA "
            "máquina. Si es un cazador de correos de desarrollo, los mensajes se quedan "
            "ahí y nadie los recibe en su bandeja real. Compruébelo enviando una prueba "
            "a una dirección suya de verdad antes de convocar a nadie.")
    elif settings.smtp_port not in (25, 465, 587, 2525):
        avisos.append(
            f"SMTP_PORT={settings.smtp_port} no es un puerto de correo habitual "
            "(25, 465, 587 o 2525). Si es el relé de la empresa, está bien; si apunta "
            "a otro programa suyo, el envío puede «funcionar» sin que el mensaje salga "
            "de aquí. Envíe una prueba a una dirección externa para confirmarlo.")

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
    from app.correo import por_que_no_sale
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
        for linea in por_que_no_sale(exc, settings):
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
