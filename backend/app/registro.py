"""Registro de actividad y errores, pensado para rastrear un caso concreto.

El problema que resuelve: alguien reporta «me salió un error» y no hay por
dónde empezar. Ahora cada petición lleva un identificador que aparece en
tres lugares a la vez —la pantalla del usuario, la cabecera de la respuesta
y cada línea del registro—, de modo que con ese código se llega al rastro
exacto: qué pidió, quién, desde dónde y qué falló.

Los registros van a archivo además de a la consola. Una terminal cerrada se
lleva consigo la única evidencia de lo que pasó anoche, y los incidentes
casi nunca se reportan mientras ocurren.
"""
from __future__ import annotations

import logging
import logging.handlers
import re
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path

# Viaja con la petición sin tener que pasarlo por parámetro a cada función.
peticion_actual: ContextVar[str] = ContextVar("peticion_actual", default="—")
usuario_actual_log: ContextVar[str] = ContextVar("usuario_actual_log", default="—")

CARPETA = Path(__file__).resolve().parents[1] / "logs"


class ContextoPeticion(logging.Filter):
    """Añade el identificador de petición y la cédula a cada línea."""

    def filter(self, registro: logging.LogRecord) -> bool:
        registro.peticion = peticion_actual.get()
        registro.quien = usuario_actual_log.get()
        return True


def nuevo_id() -> str:
    """Corto y legible: se dicta por teléfono sin equivocarse."""
    return uuid.uuid4().hex[:8]


_CODIGO = re.compile(r"^[A-Za-z0-9-]{4,32}$")


def codigo_aceptable(valor: str | None) -> str | None:
    """Filtra el código que propone el cliente antes de escribirlo.

    Se permite que el navegador imponga el suyo, porque así una operación se
    sigue de punta a punta. Pero lo que llega por una cabecera acaba en un
    archivo que sirve de evidencia: con un salto de línea se podrían fabricar
    entradas falsas, y con unos kilobytes, inflar el archivo. Solo pasan
    letras, dígitos y guiones, entre 4 y 32 caracteres; cualquier otra cosa
    se descarta en silencio y se genera un código propio.
    """
    if valor and _CODIGO.match(valor):
        return valor
    return None


def configurar(nivel: str = "INFO", a_archivo: bool = True) -> None:
    """Deja el registro listo. Se llama una sola vez, al arrancar."""
    formato = logging.Formatter(
        "%(asctime)s %(levelname)-7s [%(peticion)s] %(quien)s %(name)s :: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    filtro = ContextoPeticion()

    raiz = logging.getLogger()
    raiz.setLevel(getattr(logging, nivel.upper(), logging.INFO))

    # Se limpian los manejadores previos: uvicorn instala los suyos y sin
    # esto cada línea saldría dos veces.
    for viejo in list(raiz.handlers):
        raiz.removeHandler(viejo)

    consola = logging.StreamHandler(sys.stdout)
    consola.setFormatter(formato)
    consola.addFilter(filtro)
    raiz.addHandler(consola)

    if a_archivo:
        try:
            CARPETA.mkdir(parents=True, exist_ok=True)
            # Diez archivos de 5 MB: unas semanas de historia sin llenar el
            # disco de una máquina modesta.
            archivo = logging.handlers.RotatingFileHandler(
                CARPETA / "sistema.log", maxBytes=5_000_000, backupCount=10,
                encoding="utf-8",
            )
            archivo.setFormatter(formato)
            archivo.addFilter(filtro)
            raiz.addHandler(archivo)

            # Los errores, además, en su propio archivo: cuando algo se
            # rompe nadie quiere buscar entre miles de líneas de rutina.
            errores = logging.handlers.RotatingFileHandler(
                CARPETA / "errores.log", maxBytes=5_000_000, backupCount=10,
                encoding="utf-8",
            )
            errores.setLevel(logging.WARNING)
            errores.setFormatter(formato)
            errores.addFilter(filtro)
            raiz.addHandler(errores)
        except OSError as exc:
            # Sin permiso de escritura se sigue con la consola: un registro
            # a medias es mejor que un arranque fallido.
            raiz.warning("No se pudo escribir en %s (%s). Solo consola.", CARPETA, exc)

    # uvicorn y psycopg hablan de más en INFO; se les baja el volumen para
    # que lo propio del sistema no quede sepultado.
    for ruidoso in ("uvicorn.access", "httpx", "psycopg.pool"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)


def ruta_registros() -> str:
    return str(CARPETA)
