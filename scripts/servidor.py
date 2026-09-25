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

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Arranca el backend del sistema.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--puerto", type=int, default=8000)
    parser.add_argument("--sin-recarga", action="store_true",
                        help="No vigilar cambios en el código (como en producción)")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        print("Falta uvicorn.  pip install -r backend/requirements.txt", file=sys.stderr)
        return 1

    if not (RAIZ / "backend" / ".env").exists():
        print("No existe backend/.env.  Cópielo de backend/.env.example", file=sys.stderr)
        return 1

    print(f"Backend en http://{args.host}:{args.puerto}   (documentación en /docs)")
    print("Ctrl+C para detener.\n")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.puerto,
        reload=not args.sin_recarga,
        reload_dirs=[str(RAIZ / "backend")],
        app_dir=str(RAIZ / "backend"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
