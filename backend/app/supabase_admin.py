"""Alta del usuario en auth.users (necesario para que RLS lo reconozca).

`users.auth_user_id` referencia `auth.users(id)`. Supabase no permite
escribir esa tabla por SQL de forma soportada, así que se usa la Admin API.
En desarrollo, sin SUPABASE_URL configurado, se inserta directamente.
"""
from __future__ import annotations

import logging

import httpx

from .config import get_settings
from .db import obtener_uno

log = logging.getLogger("rrhh.auth")


async def asegurar_auth_user(user_id: str, email: str, cedula: str) -> str:
    """Devuelve el auth_user_id del empleado, creándolo la primera vez."""
    fila = await obtener_uno(
        "select auth_user_id from public.users where id = %s", (user_id,)
    )
    if fila and fila["auth_user_id"]:
        return str(fila["auth_user_id"])

    settings = get_settings()
    auth_user_id: str | None = None

    if settings.supabase_url and settings.supabase_service_role_key:
        cabeceras = {
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=15) as cliente:
            respuesta = await cliente.post(
                f"{settings.supabase_url}/auth/v1/admin/users",
                headers=cabeceras,
                json={
                    "email": email,
                    "email_confirm": True,
                    "app_metadata": {"provider": "cedula_otp"},
                    "user_metadata": {"cedula": cedula},
                },
            )
            if respuesta.status_code in (200, 201):
                auth_user_id = respuesta.json()["id"]
            elif respuesta.status_code in (409, 422):
                # Ya existe: se busca por correo
                listado = await cliente.get(
                    f"{settings.supabase_url}/auth/v1/admin/users",
                    headers=cabeceras,
                    params={"page": 1, "per_page": 1, "filter": email},
                )
                usuarios = listado.json().get("users", []) if listado.status_code == 200 else []
                if usuarios:
                    auth_user_id = usuarios[0]["id"]
            else:
                log.error("Admin API respondió %s: %s", respuesta.status_code, respuesta.text[:300])

    if auth_user_id is None:
        # Entorno local sin Supabase Auth
        fila = await obtener_uno(
            "insert into auth.users (id, email) values (gen_random_uuid(), %s) returning id",
            (email,),
        )
        auth_user_id = str(fila["id"])

    await obtener_uno(
        "update public.users set auth_user_id = %s where id = %s returning id",
        (auth_user_id, user_id),
    )
    return str(auth_user_id)
