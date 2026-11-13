"""Adjuntos de las solicitudes en el disco del servidor.

Con Supabase los archivos iban a un bucket privado. En el servidor
corporativo van a una carpeta del propio servidor (ADJUNTOS_DIR), que tiene
que estar FUERA de la carpeta que publica Apache: un certificado médico no
puede quedar a una URL adivinable de distancia. Solo el backend los lee, y
solo después de comprobar quién los pide.

La ruta que se guarda en request_attachments.storage_path es relativa a esa
carpeta y tiene la misma forma que tenía en el bucket
(«<usuario>/<solicitud>/<archivo>»), así que las rutas trasladadas desde
Supabase siguen valiendo con solo copiar los archivos debajo de ADJUNTOS_DIR.

DOS PROTECCIONES QUE EL BUCKET NO NECESITABA Y EL DISCO SÍ:

  El nombre del archivo lo elige quien lo sube. En un bucket «../../x» era
  una clave rara; en un disco es una ruta que sale de la carpeta. Se limpia
  el nombre y, además, toda ruta se resuelve y se comprueba que siga dentro
  de ADJUNTOS_DIR antes de leer o escribir.

  Se escribe en un archivo temporal y se renombra al final. Si el servidor
  se cae a la mitad, no queda un certificado cortado con apariencia de
  bueno: o está entero o no está.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path

from fastapi import HTTPException, status

from .config import get_settings

log = logging.getLogger("rrhh.storage")

_NO_PERMITIDO = re.compile(r"[^A-Za-z0-9._-]+")


def nombre_seguro(nombre: str, largo: int = 60) -> str:
    """El nombre que puso el colaborador, sin nada que pueda leerse como ruta.

    «Certificado médico (1).pdf» -> «Certificado_medico_1_.pdf». Las
    tildes se pierden en el nombre en disco, no en la base: el nombre
    original se guarda aparte, en request_attachments.nombre_archivo.
    """
    import unicodedata
    plano = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode()
    limpio = _NO_PERMITIDO.sub("_", Path(plano).name).strip("._") or "archivo"
    return limpio[-largo:]


def _carpeta() -> Path:
    return Path(get_settings().adjuntos_dir).resolve()


def ruta_absoluta(ruta: str) -> Path:
    """Dónde está en disco un storage_path. Nunca fuera de ADJUNTOS_DIR."""
    base = _carpeta()
    destino = (base / ruta).resolve()
    if destino == base or base not in destino.parents:
        # No se dice en la respuesta por qué: a quien intenta salir de la
        # carpeta no se le explica cómo. Sí queda en el registro.
        log.warning("Ruta de adjunto fuera de la carpeta, rechazada: %r", ruta)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail={"mensaje": "Ruta de archivo no válida."})
    return destino


def _escribir(destino: Path, contenido: bytes) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    fd, temporal = tempfile.mkstemp(dir=destino.parent, prefix=".subiendo-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(temporal, 0o640)
        os.replace(temporal, destino)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise


async def subir_adjunto(ruta: str, contenido: bytes, mime: str) -> str:
    """Guarda el archivo y devuelve la ruta con que se registra en la base."""
    destino = ruta_absoluta(ruta)
    try:
        await asyncio.to_thread(_escribir, destino, contenido)
    except OSError as exc:
        # Quien adjunta un certificado no puede arreglar permisos de una
        # carpeta: recibe un mensaje neutro. Quien sí puede lee el registro.
        log.error("No se pudo guardar el adjunto en %s: %s", destino, exc)
        log.error("Qué revisar: que ADJUNTOS_DIR (%s) exista, que el usuario del servicio "
                  "pueda escribir en ella y que el disco tenga espacio.", _carpeta())
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"mensaje": "No se pudo guardar el archivo. Intente de nuevo."},
        ) from exc
    return ruta


async def leer_adjunto(ruta: str) -> bytes | None:
    """El contenido de un adjunto, o None si no está en disco.

    No comprueba QUIÉN lo pide: eso lo hace la ruta que lo use, antes de
    llamar aquí, igual que con cualquier otro dato de una solicitud.
    """
    destino = ruta_absoluta(ruta)
    try:
        return await asyncio.to_thread(destino.read_bytes)
    except FileNotFoundError:
        return None
