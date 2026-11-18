"""Foto de perfil.

La foto es un dato personal (LOPDP): no se publica en la web. Se guarda en
ADJUNTOS_DIR/fotos/, fuera de la carpeta que sirve Apache, y solo la
entregan estas rutas a quien puede verla: la propia persona, su jefe y
Talento Humano.

Lo que sube la persona no se guarda tal cual. Se abre con Pillow, se gira
según la orientación de la cámara, se recorta cuadrada, se reduce a 512 px y
se vuelve a codificar como JPEG. Así:
  · no quedan metadatos (EXIF con la ubicación GPS donde se tomó, el
    modelo del teléfono…);
  · un archivo que dice ser imagen y no lo es, no pasa;
  · ninguna foto pesa más de unos 80 KB.
"""
from __future__ import annotations

import io
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response

from ..audit import registrar
from ..db import ejecutar, obtener_uno
from ..deps import usuario_actual
from ..storage import leer_adjunto, ruta_absoluta, subir_adjunto

router = APIRouter(tags=["Foto de perfil"])
Usuario = Annotated[dict, Depends(usuario_actual)]

MAXIMO = 8 * 1024 * 1024
LADO = 512
MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}


def _procesar(contenido: bytes) -> bytes:
    from PIL import Image, ImageOps, UnidentifiedImageError

    Image.MAX_IMAGE_PIXELS = 40_000_000   # una foto de teléfono; no una bomba de píxeles
    try:
        with Image.open(io.BytesIO(contenido)) as img:
            img.load()
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")
            img = ImageOps.fit(img, (LADO, LADO), method=Image.Resampling.LANCZOS)
            salida = io.BytesIO()
            img.save(salida, "JPEG", quality=85, optimize=True)   # sin exif=: no lleva metadatos
            return salida.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status_code=422, detail={
            "mensaje": "No se pudo leer la imagen. Use una foto JPG o PNG."}) from exc


@router.post("/mi-ficha/foto")
async def subir_foto(request: Request, usuario: Usuario, archivo: UploadFile = File(...)) -> dict:
    contenido = await archivo.read()
    if not contenido:
        raise HTTPException(status_code=422, detail={"mensaje": "El archivo está vacío."})
    if len(contenido) > MAXIMO:
        raise HTTPException(status_code=413, detail={"mensaje": "La foto debe pesar menos de 8 MB."})
    if archivo.content_type not in MIMES:
        raise HTTPException(status_code=422, detail={"mensaje": "Use una foto JPG, PNG o WebP."})
    import asyncio
    jpeg = await asyncio.to_thread(_procesar, contenido)
    ruta = f"fotos/{usuario['id']}.jpg"
    await subir_adjunto(ruta, jpeg, "image/jpeg")
    await ejecutar("UPDATE users SET foto_url = %s WHERE id = %s", (ruta, str(usuario["id"])))
    await registrar(request, "foto_actualizada", user_id=str(usuario["id"]), cedula=usuario["cedula"])
    return {"mensaje": "Foto actualizada."}


@router.delete("/mi-ficha/foto")
async def quitar_foto(request: Request, usuario: Usuario) -> dict:
    fila = await obtener_uno("SELECT foto_url FROM users WHERE id = %s", (str(usuario["id"]),))
    if fila and fila["foto_url"] and fila["foto_url"].startswith("fotos/"):
        ruta_absoluta(fila["foto_url"]).unlink(missing_ok=True)
    await ejecutar("UPDATE users SET foto_url = NULL WHERE id = %s", (str(usuario["id"]),))
    await registrar(request, "foto_quitada", user_id=str(usuario["id"]), cedula=usuario["cedula"])
    return {"mensaje": "Foto quitada."}


async def _foto(user_id: str) -> Response:
    fila = await obtener_uno("SELECT foto_url FROM users WHERE id = %s", (user_id,))
    ruta = (fila or {}).get("foto_url") or ""
    # Solo rutas que puso este sistema: un valor antiguo o escrito a mano en la
    # base (una URL externa) no se sigue.
    contenido = await leer_adjunto(ruta) if ruta.startswith("fotos/") else None
    if contenido is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Sin foto."})
    return Response(contenido, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=300"})


@router.get("/mi-ficha/foto")
async def mi_foto(usuario: Usuario) -> Response:
    return await _foto(str(usuario["id"]))


@router.get("/personas/{user_id}/foto")
async def foto_de(user_id: str, usuario: Usuario) -> Response:
    """La propia, la de su gente (jefe) o la de cualquiera (Talento Humano)."""
    if str(usuario["id"]) != user_id and usuario["rol"] not in ("rrhh", "admin"):
        es_su_gente = await obtener_uno(
            "SELECT 1 AS x FROM users WHERE id = %s AND jefe_id = %s", (user_id, str(usuario["id"])))
        if not es_su_gente:
            raise HTTPException(status_code=404, detail={"mensaje": "Sin foto."})
    return await _foto(user_id)
