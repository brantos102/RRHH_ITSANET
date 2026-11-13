"""Envía un correo de prueba con la configuración del servidor.

    .venv/bin/python despliegue/probar_correo.py destino@empresa.com

Usa la misma configuración (servidor/.env) y el mismo código de envío que el
sistema, e incrusta un código QR de muestra igual a los de salida por garita:
si este correo llega y el QR se ve, los del sistema también.

No toca la base de datos. Si el envío falla, dice en castellano por qué y
qué revisar.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "servidor"))

# La configuración del sistema exige la base y el secreto de sesión. Para
# probar solo el correo no hacen falta: si todavía no están, se usan valores
# que no conectan a nada.
os.environ.setdefault("MYSQL_URL", "mysql://sin-base@localhost/sin_base")
os.environ.setdefault("JWT_SECRET", "solo-para-probar-el-correo")

from app import correo, qr  # noqa: E402
from app.config import get_settings  # noqa: E402


async def principal(destino: str) -> int:
    ajustes = get_settings()
    print(f"Servidor: {ajustes.smtp_host}:{ajustes.smtp_port} "
          f"(STARTTLS {'sí' if ajustes.smtp_starttls else 'no'}) · usuario: {ajustes.smtp_user or '—'}")
    print(f"Remitente: {ajustes.smtp_remitente}")
    print(f"Destino:   {destino}\n")
    if ajustes.email_backend == "console":
        print("EMAIL_BACKEND=console: el sistema no envía, solo imprime. Ejecute "
              "despliegue/configurar_correo.sh")
        return 2

    muestra = str(uuid.uuid4())
    texto = ("Correo de prueba del Sistema de Permisos y Vacaciones.\n\n"
             "Si lo recibe, el servidor puede enviar los códigos de acceso, los avisos a "
             "jefaturas y a Talento Humano, y los códigos QR de salida.\n\n"
             f"Código QR de muestra (no autoriza ninguna salida): {muestra}")
    html = ("<p>Correo de prueba del <b>Sistema de Permisos y Vacaciones</b>.</p>"
            "<p>Si lo recibe, el servidor puede enviar los códigos de acceso, los avisos a "
            "jefaturas y a Talento Humano, y los códigos QR de salida.</p>"
            "<p>Código QR de muestra (no autoriza ninguna salida):</p>"
            '<p><img src="cid:qr" alt="Código QR de muestra" width="200" height="200"></p>')
    try:
        await correo.enviar(destino, "Prueba de correo del sistema de Talento Humano", texto, html,
                            imagenes={"qr": qr.png(muestra)})
    except Exception as exc:  # noqa: BLE001
        print(f"NO SE ENVIÓ: {type(exc).__name__}: {exc}\n")
        for linea in correo.por_que_no_sale(exc, ajustes):
            if linea:
                print(f"  {linea}")
        return 1
    print("Enviado. Revise la bandeja de entrada (y la de no deseado) de", destino)
    print("Debe verse el código QR dentro del mensaje.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or "@" not in sys.argv[1]:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(principal(sys.argv[1])))
