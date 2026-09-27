"""Sirve la interfaz web, sin importar desde qué carpeta se ejecute.

Existe por un tropiezo concreto y fácil de repetir: estando ya dentro de
`frontend`, ejecutar `python -m http.server 5500 --directory frontend` sirve
`frontend\\frontend`, que no existe, y el navegador solo dice «Error code: 404
– File not found». El servidor arranca, la terminal no se queja, y nada indica
que el problema es la carpeta.

Aquí la carpeta se deduce de la ubicación de este archivo, así que da igual
desde dónde se lance. Y si algo falta, lo dice antes de levantar nada.

    python scripts/frontend.py                # en el 5500
    python scripts/frontend.py --puerto 5501  # si el 5500 está ocupado
"""
from __future__ import annotations

import argparse
import http.server
import socket
import socketserver
import sys
from pathlib import Path

CARPETA = Path(__file__).resolve().parents[1] / "frontend"
IMPRESCINDIBLES = ("index.html", "dashboard.html", "config.js")


class Servidor(socketserver.ThreadingTCPServer):
    """Acepta IPv4 e IPv6 a la vez.

    En Windows `localhost` resuelve muchas veces a `::1` y `127.0.0.1` es
    IPv4: atender solo una de las dos deja media aplicación inalcanzable
    según qué escriba cada quien en la barra de direcciones.
    """

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, puerto: int, manejador):
        if socket.has_dualstack_ipv6():
            try:
                self.address_family = socket.AF_INET6
                super().__init__(("::", puerto), manejador, bind_and_activate=False)
                self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                self.server_bind()
                self.server_activate()
                return
            except OSError as exc:
                # Con red de seguridad a propósito: esta rama no se puede
                # probar en un entorno sin IPv6, y quedarse sin interfaz por
                # una pila mal configurada sería peor que atender solo IPv4.
                # Si el puerto está ocupado, el intento de abajo lo dirá igual.
                try:
                    self.socket.close()
                except Exception:  # noqa: BLE001
                    pass
                print(f"  (IPv6 no disponible: {exc}; se atiende solo IPv4)")

        self.address_family = socket.AF_INET
        super().__init__(("0.0.0.0", puerto), manejador)


class Manejador(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(CARPETA), **kwargs)

    def log_message(self, formato: str, *args) -> None:
        # El registro por omisión imprime cada archivo estático. Solo interesa
        # lo que falla: un 404 aquí suele ser un enlace roto o una ruta mal
        # escrita, y con doscientas líneas de 200 OK no se ve.
        codigo = str(args[1]) if len(args) > 1 else ""
        if codigo.startswith(("4", "5")):
            sys.stderr.write(f"  {self.address_string()} → {formato % args}\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Sirve la interfaz web del sistema.")
    p.add_argument("--puerto", type=int, default=5500)
    argumentos = p.parse_args()

    if not CARPETA.is_dir():
        print(f"No encuentro la carpeta de la interfaz en {CARPETA}.")
        print("¿Está ejecutando esto dentro del repositorio descargado?")
        return 1

    faltan = [a for a in IMPRESCINDIBLES if not (CARPETA / a).exists()]
    if faltan:
        print(f"La carpeta {CARPETA} existe pero le faltan: {', '.join(faltan)}.")
        print("Actualice el repositorio con:  git pull")
        return 1

    try:
        servidor = Servidor(argumentos.puerto, Manejador)
    except OSError as exc:
        print(f"No pude escuchar en el puerto {argumentos.puerto}: {exc}")
        print(f"Si ya hay algo ahí, use otro:  python scripts/frontend.py --puerto {argumentos.puerto + 1}")
        return 1

    print(f"Interfaz servida desde {CARPETA}")
    print(f"Abra  http://127.0.0.1:{argumentos.puerto}   (o http://localhost:{argumentos.puerto})")
    print("Solo se muestran aquí los errores. Ctrl+C para detener.\n")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nInterfaz detenida.")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
