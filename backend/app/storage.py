"""Subida de archivos a Supabase Storage (buckets privados)."""
from __future__ import annotations

import logging

import httpx
from fastapi import HTTPException, status

from .config import get_settings

log = logging.getLogger("rrhh.storage")
BUCKET_SOLICITUDES = "solicitudes"


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
        log.error("Storage respondió %s al subir a «%s»: %s",
                  respuesta.status_code, bucket, respuesta.text[:300])
        # Quien está adjuntando un certificado médico no puede crear un
        # bucket ni revisar una clave, así que recibe un mensaje neutro. El
        # que sí puede lee el registro, y antes se quedaba con el código de
        # estado y un JSON de Supabase: aquí queda dicho qué hacer.
        log.error("Qué significa: %s", por_que_fallo(respuesta.status_code, respuesta.text))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"mensaje": "No se pudo guardar el archivo. Intente de nuevo."},
        )
    return ruta


def por_que_fallo(codigo: int, cuerpo: str) -> str:
    """Traduce la respuesta de Supabase Storage a lo que hay que hacer.

    Los tres fallos que ocurren de verdad al instalar el sistema, y que
    desde la pantalla son indistinguibles entre sí.
    """
    texto = (cuerpo or "").lower()

    if "bucket not found" in texto or "bucket_not_found" in texto:
        return ("El bucket no existe en este proyecto de Supabase. Créelo con:  "
                "python scripts/probar_adjuntos.py --crear")
    if codigo in (401, 403) or "invalid" in texto and "jwt" in texto \
            or "unauthorized" in texto or "signature" in texto:
        return ("Supabase rechazó la clave. SUPABASE_SERVICE_ROLE_KEY tiene que ser la "
                "clave «service_role» del proyecto, no la «anon»: la anon no puede "
                "escribir en un bucket privado. Está en Supabase › Project Settings › "
                "API Keys.")
    if "row-level security" in texto or "violates" in texto or "policy" in texto:
        return ("Una política de Storage bloqueó la escritura. Con la clave service_role "
                "no debería pasar: compruebe que SUPABASE_SERVICE_ROLE_KEY no sea la anon.")
    if "payload too large" in texto or codigo == 413:
        return ("El archivo supera el límite del bucket. Súbalo en Supabase › Storage › "
                "el bucket › Configuration, o reduzca TAMANO_MAXIMO en el backend.")
    if "mime" in texto or "content type" in texto:
        return ("El bucket no admite ese tipo de archivo. Revise «Allowed MIME types» en "
                "la configuración del bucket, o déjelo vacío para admitir todos.")
    if codigo >= 500:
        return "Supabase devolvió un error propio. Reintente; si persiste, revise su estado."
    return ("No reconozco este fallo. Para ver la configuración completa y probarla:  "
            "python scripts/probar_adjuntos.py")


async def subir_adjunto(ruta: str, contenido: bytes, mime: str) -> str:
    return await subir(BUCKET_SOLICITUDES, ruta, contenido, mime)


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
