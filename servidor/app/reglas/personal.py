"""Quién es quién: Talento Humano por región, jefaturas y bajas.

Reemplaza a rrhh_de_region (y, a medida que se trasladan, a jefatura_crear,
jefatura_quitar, rrhh_integrar, rrhh_retirar y dar_de_baja).
"""
from __future__ import annotations

from typing import Any

from ..db import obtener_todos


async def rrhh_de_region(region: str | None) -> list[dict[str, Any]]:
    """Talento Humano de la región; si no hay nadie, todo el equipo.

    Si la región no tiene a nadie —vacaciones, una sede nueva— responde todo
    el equipo: es preferible que un aviso llegue de más a que no llegue.
    """
    region = region or "sierra"
    filas = await obtener_todos("SELECT * FROM v_rrhh_por_region WHERE region = %s", (region,))
    if filas:
        return filas
    return await obtener_todos("SELECT * FROM v_rrhh_por_region")
