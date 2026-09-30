#!/usr/bin/env python3
"""Arranca el backend. Úselo en lugar de invocar uvicorn directamente.

Existe por Windows. psycopg en modo asíncrono no funciona sobre
ProactorEventLoop, que es el bucle predeterminado de Python ahí, y uvicorn
solo cambia de bucle cuando arranca un subproceso —es decir, con `--reload`
o `--workers`—. Arrancar sin `--reload` dejaba el backend en pie pero
incapaz de conectarse a la base:

    Psycopg cannot use the 'ProactorEventLoop' to run in async mode

Aquí la política se fija antes de que exista cualquier bucle, así que da
igual cómo se arranque. En Linux y macOS no cambia nada.

    python scripts/servidor.py                    # desarrollo, con recarga
    python scripts/servidor.py --sin-recarga      # como en producción
    python scripts/servidor.py --puerto 8080
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# psycopg no arranca sobre el bucle de eventos que Windows usa por
# omisión. Ver scripts/_windows.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _windows  # noqa: F401,E402
import _cli  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Arranca el backend del sistema.")
    parser.add_argument("--host", default="",
                        help="Dirección concreta. Por omisión atiende 127.0.0.1 y ::1")
    parser.add_argument("--puerto", type=int, default=8000)
    parser.add_argument("--sin-recarga", action="store_true",
                        help="No vigilar cambios en el código (como en producción)")
    args = _cli.analizar(parser)

    try:
        import uvicorn
    except ImportError:
        print("Falta uvicorn.  pip install -r backend/requirements.txt", file=sys.stderr)
        return 1

    if not (RAIZ / "backend" / ".env").exists():
        print("No existe backend/.env.  Cópielo de backend/.env.example", file=sys.stderr)
        return 1

    recarga = not args.sin_recarga
    # `app_dir` solo lo entiende uvicorn.run(), no Config: por eso va aparte.
    # La carpeta ya está en sys.path desde el inicio de este script.
    carpeta = str(RAIZ / "backend")
    comunes: dict = {"reload": recarga, "port": args.puerto}
    if recarga:
        # Pasar reload_dirs sin recarga hace que uvicorn avise de una
        # configuración incoherente en cada arranque.
        comunes["reload_dirs"] = [carpeta]

    if args.host:                      # host explícito: se respeta tal cual
        print(f"Backend en http://{args.host}:{args.puerto}   (documentación en /docs)")
        print("Ctrl+C para detener.\n")
        uvicorn.run("app.main:app", host=args.host, app_dir=carpeta, **comunes)
        return 0

    # Sin --host: se escucha en las DOS direcciones de bucle local.
    #
    # En Windows «localhost» suele resolverse primero a ::1 (IPv6) y
    # «127.0.0.1» es IPv4. Son la misma máquina pero sockets distintos: un
    # backend atado solo a 127.0.0.1 rechaza al navegador que entró por
    # localhost, y la pantalla dice «No se pudo conectar con el servidor»
    # sin que el servidor registre nada. Atendiendo ambas, da igual cuál
    # escriba el usuario. Solo bucle local: no se expone en la red.
    print(f"Backend en http://127.0.0.1:{args.puerto} y http://localhost:{args.puerto}")
    print("Documentación interactiva en /docs.  Ctrl+C para detener.\n")

    sockets = _sockets_de_bucle_local(args.puerto)
    if len(sockets) < 2:
        for s in sockets:
            s.close()
        # Si algo impide abrir ambos, se sigue por el camino simple en vez
        # de no arrancar: es preferible un backend en IPv4 que ninguno.
        uvicorn.run("app.main:app", host="127.0.0.1", app_dir=carpeta, **comunes)
        return 0

    try:
        from uvicorn import Config, Server
        from uvicorn.supervisors import ChangeReload

        config = Config("app.main:app", **comunes)
        servidor = Server(config)
        if recarga:
            ChangeReload(config, target=servidor.run, sockets=sockets).run()
        else:
            servidor.run(sockets=sockets)
    except ImportError:
        # uvicorn cambió de estructura interna: mejor arrancar que fallar.
        for abierto in sockets:
            abierto.close()
        uvicorn.run("app.main:app", host="127.0.0.1", app_dir=carpeta, **comunes)
    return 0


def _sockets_de_bucle_local(puerto: int) -> list:
    """Un socket escuchando en 127.0.0.1 y otro en ::1, si el equipo lo admite."""
    import socket

    abiertos = []
    for familia, direccion in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            s = socket.socket(familia, socket.SOCK_STREAM)
            if familia == socket.AF_INET6 and hasattr(socket, "IPV6_V6ONLY"):
                # Cada socket atiende su propia familia: sin esto, en Linux el
                # de IPv6 reclamaría también el puerto IPv4 y el otro fallaría.
                s.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            s.bind((direccion, puerto))
            s.listen(2048)
            s.set_inheritable(True)
            abiertos.append(s)
        except OSError as exc:
            if familia == socket.AF_INET:
                print(f"No se pudo escuchar en 127.0.0.1:{puerto} — {exc}", file=sys.stderr)
                for a in abiertos:
                    a.close()
                return []
            # Un equipo sin IPv6 es perfectamente válido: se sigue con IPv4.
    return abiertos


if __name__ == "__main__":
    raise SystemExit(main())
