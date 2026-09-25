"""Firma electrónica del empleado: dibujada, imagen subida o certificado."""
from __future__ import annotations

import base64
import hashlib
import re
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from ..audit import registrar
from ..db import conexion, obtener_uno
from ..deps import usuario_actual
from ..errores import traducir
from ..storage import subir_firma

router = APIRouter(prefix="/firmas", tags=["Firmas"])

TAMANO_MAXIMO_FIRMA = 1024 * 1024          # 1 MB
# Sin SVG: un SVG puede incrustar <script>, y esta imagen se muestra luego
# en el panel de aprobación y en la pantalla de garita.
MIMES_FIRMA = {"image/png", "image/jpeg", "application/pdf"}
PATRON_DATA_URI = re.compile(r"^data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)$")
FIRMAS_MAGICAS = ((b"\x89PNG\r\n\x1a\n", "PNG"), (b"\xff\xd8\xff", "JPEG"))


def _es_imagen_real(crudo: bytes) -> bool:
    """El tipo declarado no basta: se comprueban los bytes iniciales."""
    return any(crudo.startswith(magico) for magico, _ in FIRMAS_MAGICAS)


class FirmaDibujada(BaseModel):
    contenido: str = Field(..., description="Data URI PNG o SVG del trazo")


async def _guardar(user_id: str, tipo: str, contenido: str | None,
                   storage_path: str | None, hash_sha256: str) -> dict:
    """Desactiva la firma anterior y registra la nueva, en una transacción.

    Las solicitudes ya firmadas no se alteran: guardan una copia del hash.
    """
    async with conexion() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "update public.signatures set activa = false where user_id = %s and activa",
                (user_id,),
            )
            await cur.execute(
                """
                insert into public.signatures (user_id, tipo, contenido, storage_path, hash_sha256)
                values (%s, %s, %s, %s, %s)
                returning id, tipo, hash_sha256, created_at
                """,
                (user_id, tipo, contenido, storage_path, hash_sha256),
            )
            return await cur.fetchone()


@router.get("/mia")
async def mi_firma(usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    fila = await obtener_uno(
        """select id, tipo, contenido, storage_path, hash_sha256, created_at
           from public.signatures where user_id = %s and activa""",
        (usuario["id"],),
    )
    if fila is None:
        return {"registrada": False}
    return {
        "registrada": True,
        "id": str(fila["id"]),
        "tipo": fila["tipo"],
        "contenido": fila["contenido"],
        "hash_sha256": fila["hash_sha256"],
        "created_at": fila["created_at"],
    }


@router.post("/dibujada", status_code=status.HTTP_201_CREATED)
async def registrar_dibujada(
    datos: FirmaDibujada, request: Request, usuario: Annotated[dict, Depends(usuario_actual)]
) -> dict:
    """Firma trazada con el mouse o el dedo, enviada como data URI."""
    coincidencia = PATRON_DATA_URI.match(datos.contenido.strip())
    if not coincidencia:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": "El formato de la firma no es válido."},
        )

    try:
        crudo = base64.b64decode(coincidencia.group(2), validate=True)
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=422, detail={"mensaje": "La firma está dañada."})

    if len(crudo) > TAMANO_MAXIMO_FIRMA:
        raise HTTPException(status_code=413, detail={"mensaje": "La firma no puede superar 1 MB."})
    if len(crudo) < 200:
        raise HTTPException(status_code=422,
                            detail={"mensaje": "El trazo está vacío: dibuje su firma antes de guardar."})
    if not _es_imagen_real(crudo):
        raise HTTPException(status_code=422,
                            detail={"mensaje": "El contenido enviado no es una imagen válida."})

    hash_firma = hashlib.sha256(crudo).hexdigest()

    try:
        fila = await _guardar(str(usuario["id"]), "dibujada", datos.contenido, None, hash_firma)
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "firma_registrada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="signatures", entidad_id=str(fila["id"]),
                    detalle={"tipo": "dibujada"})

    return {"id": str(fila["id"]), "tipo": "dibujada", "hash_sha256": hash_firma,
            "mensaje": "Firma registrada. Se usará en sus próximas solicitudes."}


@router.post("/archivo", status_code=status.HTTP_201_CREATED)
async def registrar_archivo(
    request: Request,
    usuario: Annotated[dict, Depends(usuario_actual)],
    archivo: UploadFile = File(...),
    tipo: Literal["imagen", "certificado"] = "imagen",
) -> dict:
    """Firma escaneada o certificado de firma electrónica oficial."""
    contenido = await archivo.read()

    if not contenido:
        raise HTTPException(status_code=422, detail={"mensaje": "El archivo está vacío."})
    if len(contenido) > TAMANO_MAXIMO_FIRMA:
        raise HTTPException(status_code=413, detail={"mensaje": "La firma no puede superar 1 MB."})
    if archivo.content_type not in MIMES_FIRMA:
        raise HTTPException(status_code=422,
                            detail={"mensaje": "Solo se admite PNG, JPG o PDF."})
    if archivo.content_type != "application/pdf" and not _es_imagen_real(contenido):
        raise HTTPException(status_code=422,
                            detail={"mensaje": "El archivo no es una imagen válida."})

    ruta = f"{usuario['id']}/{uuid.uuid4().hex}-{archivo.filename[:60]}"
    await subir_firma(ruta, contenido, archivo.content_type)
    hash_firma = hashlib.sha256(contenido).hexdigest()

    try:
        fila = await _guardar(str(usuario["id"]), tipo, None, ruta, hash_firma)
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "firma_registrada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="signatures", entidad_id=str(fila["id"]),
                    detalle={"tipo": tipo, "archivo": archivo.filename})

    return {"id": str(fila["id"]), "tipo": tipo, "hash_sha256": hash_firma,
            "mensaje": "Firma registrada. Se usará en sus próximas solicitudes."}
