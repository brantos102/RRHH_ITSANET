"""Administración › Actualizaciones: qué versión está instalada, si faltan
migraciones, y las notas de cada actualización para leerlas o descargarlas.

Solo lee: no actualiza nada desde la web. Actualizar el servidor es un acto
de TI en la terminal (`bash despliegue/actualizar.sh`), con respaldo previo;
una página web que ejecutara comandos en el servidor sería una puerta que no
debe existir.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from ..db import obtener_todos
from ..deps import exigir_rol

router = APIRouter(prefix="/admin/actualizaciones", tags=["Actualizaciones"])
ADMIN = Annotated[dict, Depends(exigir_rol("admin"))]

RAIZ = Path(__file__).resolve().parents[3]
NOTAS = RAIZ / "despliegue" / "actualizaciones"
MIGRACIONES = RAIZ / "mysql" / "migraciones"
NOMBRE_NOTA = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}_[0-9]{2}_[a-z0-9_]{1,60}\.md$")


def _version() -> dict:
    """La versión del código, leída de .git sin ejecutar comandos."""
    git = RAIZ / ".git"
    try:
        cabeza = (git / "HEAD").read_text().strip()
        if cabeza.startswith("ref: "):
            ref = cabeza[5:]
            archivo = git / ref
            if archivo.exists():
                sha = archivo.read_text().strip()
            else:   # referencias empaquetadas
                sha = next((l.split()[0] for l in (git / "packed-refs").read_text().splitlines()
                            if l.endswith(" " + ref)), "")
            return {"rama": ref.removeprefix("refs/heads/"), "commit": sha[:10]}
        return {"rama": None, "commit": cabeza[:10]}
    except OSError:
        return {"rama": None, "commit": None}


def _titulo(ruta: Path) -> str:
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if linea.startswith("# "):
            return linea[2:].strip()
    return ruta.stem


@router.get("")
async def estado(usuario: ADMIN) -> dict:
    aplicadas = {f["archivo"] for f in await obtener_todos("SELECT archivo FROM schema_migraciones")}
    disponibles = sorted(p.name for p in MIGRACIONES.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    notas = sorted((p for p in NOTAS.glob("*.md") if NOMBRE_NOTA.match(p.name)),
                   key=lambda p: p.name, reverse=True)
    return {
        "version": _version(),
        "migraciones": {"aplicadas": len(aplicadas & set(disponibles)), "disponibles": len(disponibles),
                        "faltan": [m for m in disponibles if m not in aplicadas]},
        "notas": [{"archivo": p.name, "titulo": _titulo(p), "fecha": p.name[:10]} for p in notas],
        "comando": "bash despliegue/actualizar.sh",
    }


@router.get("/{archivo}")
async def nota(archivo: str, usuario: ADMIN, descargar: bool = False) -> Response:
    """El texto de una nota. Solo nombres con la forma de las notas: nada de
    rutas, nada fuera de la carpeta."""
    if not NOMBRE_NOTA.match(archivo) or not (NOTAS / archivo).is_file():
        raise HTTPException(status_code=404, detail={"mensaje": "Esa nota no existe."})
    contenido = (NOTAS / archivo).read_text(encoding="utf-8")
    cabeceras = {"Cache-Control": "no-store"}
    if descargar:
        cabeceras["Content-Disposition"] = f'attachment; filename="{archivo}"'
    return Response(contenido, media_type="text/markdown; charset=utf-8", headers=cabeceras)
