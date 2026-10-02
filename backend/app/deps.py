"""Dependencias de FastAPI: usuario autenticado y control de rol."""
from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import registro
from .db import obtener_uno
from .security import leer_token

esquema = HTTPBearer(auto_error=False)

SQL_PERFIL = """
    select u.id, u.cedula, u.nombre, u.email, u.rol, u.telefono, u.cargo,
           u.departamento, u.fecha_ingreso, u.dias_vacaciones, u.logros,
           u.jefe_id, u.activo, u.auth_user_id, u.region, u.ciudad, u.correo_pendiente,
           public.anios_cumplidos(u.fecha_ingreso) as anios_servicio,
           j.nombre as jefe_nombre
    from public.users u
    left join public.users j on j.id = u.jefe_id
    where u.auth_user_id = %s and u.activo
"""


async def usuario_actual(
    request: Request,
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(esquema)],
) -> dict:
    if credenciales is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Debe iniciar sesión.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    datos = leer_token(credenciales.credentials)
    perfil = await obtener_uno(SQL_PERFIL, (datos["sub"],))

    if perfil is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado o inactivo.",
        )

    # A partir de aquí cada línea del registro lleva la cédula. Sin esto, un
    # error solo dice qué ruta falló, y «a alguien le falla aprobar» no se
    # puede reproducir; con la cédula se sabe qué rol, qué región y qué
    # solicitudes tenía delante quien lo sufrió.
    registro.usuario_actual_log.set(perfil["cedula"])
    # También en el scope: la línea final de cada petición la escribe un
    # middleware que corre en otro contexto y no vería la variable.
    request.state.quien = perfil["cedula"]
    return perfil


def exigir_rol(*roles: str):
    """Restringe un endpoint a ciertos roles."""

    async def verificar(usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
        if usuario["rol"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para esta operación.",
            )
        return usuario

    return verificar
