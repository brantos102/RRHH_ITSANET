"""Las tareas programadas del sistema, para lanzarlas desde systemd o a mano.

    .venv/bin/python mysql/tareas.py diaria      # caducidad (si está activa) y avisos
    .venv/bin/python mysql/tareas.py retencion   # depura bitácoras vencidas (mensual)

En Supabase las programaba pg_cron. Aquí las lanza un temporizador de
systemd (despliegue/rrhh-tareas*.timer) con la misma conexión que el
sistema (servidor/.env). Correrlas dos veces no duplica avisos.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "servidor"))

from app.db import cerrar_pool  # noqa: E402
from app.reglas import tareas  # noqa: E402


async def principal(orden: str) -> int:
    try:
        if orden == "diaria":
            resultado = await tareas.tarea_diaria()
        elif orden == "retencion":
            resultado = await tareas.aplicar_retencion()
        else:
            print(__doc__)
            return 2
        print(json.dumps(resultado, ensure_ascii=False, default=str))
        return 0
    finally:
        await cerrar_pool()


if __name__ == "__main__":
    sys.exit(asyncio.run(principal(sys.argv[1] if len(sys.argv) > 1 else "")))
