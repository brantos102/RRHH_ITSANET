"""Bitácora de auditoría: todo movimiento deja rastro (ISO 27001 A.8.15)."""
from __future__ import annotations

import json
from typing import Any

from fastapi import Request

from .db import ejecutar

SQL_INSERT = """
    insert into public.audit_logs
        (user_id, cedula, accion, entidad, entidad_id, ip, user_agent, detalle)
    values (%(user_id)s, %(cedula)s, %(accion)s, %(entidad)s, %(entidad_id)s,
            %(ip)s, %(user_agent)s, %(detalle)s)
"""


def ip_del_cliente(request: Request) -> str | None:
    """IP real detrás del proxy de Vercel/Fly/Nginx."""
    for cabecera in ("x-forwarded-for", "x-real-ip"):
        valor = request.headers.get(cabecera)
        if valor:
            return valor.split(",")[0].strip()
    return request.client.host if request.client else None


async def registrar(
    request: Request,
    accion: str,
    *,
    user_id: str | None = None,
    cedula: str | None = None,
    entidad: str | None = None,
    entidad_id: str | None = None,
    detalle: dict[str, Any] | None = None,
) -> None:
    await ejecutar(
        SQL_INSERT,
        {
            "user_id": user_id,
            "cedula": cedula,
            "accion": accion,
            "entidad": entidad,
            "entidad_id": entidad_id,
            "ip": ip_del_cliente(request),
            "user_agent": (request.headers.get("user-agent") or "")[:500],
            "detalle": json.dumps(detalle or {}, default=str, ensure_ascii=False),
        },
    )
