"""Subida de archivos a Supabase Storage (buckets privados)."""
from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException, status

from .config import get_settings

log = logging.getLogger("rrhh.storage")
BUCKET_SOLICITUDES = "solicitudes"
BUCKET_FIRMAS = "firmas"


async def subir(bucket: str, ruta: str, contenido: bytes, mime: str) -> str:
    settings = get_settings()

    if not (settings.supabase_url and settings.supabase_service_role_key):
        log.warning("Storage no configurado: se omite la subida de %s", ruta)
        return ruta  # entorno de desarrollo sin Supabase

    async with httpx.AsyncClient(timeout=30) as cliente:
        respuesta = await cliente.post(
            f"{settings.supabase_url}/storage/v1/object/{bucket}/{ruta}",
            headers={
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "Content-Type": mime,
                "x-upsert": "true",
            },
            content=contenido,
        )
    if respuesta.status_code not in (200, 201):
        log.error("Storage respondió %s: %s", respuesta.status_code, respuesta.text[:300])
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"mensaje": "No se pudo guardar el archivo. Intente de nuevo."},
        )
    return ruta


async def subir_adjunto(ruta: str, contenido: bytes, mime: str) -> str:
    return await subir(BUCKET_SOLICITUDES, ruta, contenido, mime)


async def subir_firma(ruta: str, contenido: bytes, mime: str) -> str:
    return await subir(BUCKET_FIRMAS, ruta, contenido, mime)


async def url_firmada(bucket: str, ruta: str, segundos: int = 300) -> str | None:
    """Enlace temporal para que el navegador vea un archivo privado."""
    settings = get_settings()
    if not (settings.supabase_url and settings.supabase_service_role_key):
        return None

    async with httpx.AsyncClient(timeout=15) as cliente:
        respuesta = await cliente.post(
            f"{settings.supabase_url}/storage/v1/object/sign/{bucket}/{ruta}",
            headers={"Authorization": f"Bearer {settings.supabase_service_role_key}"},
            json={"expiresIn": segundos},
        )
    if respuesta.status_code != 200:
        return None
    return f"{settings.supabase_url}/storage/v1{respuesta.json()['signedURL']}"
