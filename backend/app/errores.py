"""Traducción de errores de PostgreSQL a respuestas útiles.

Las reglas de negocio viven en la base y sus mensajes ya están redactados
en español para el usuario final. Aquí se dejan pasar esos mensajes y se
convierte lo demás en un error genérico, sin filtrar detalles internos.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, status
from psycopg import errors as pg

log = logging.getLogger("rrhh.errores")

# Mensaje por restricción, cuando el nombre del CHECK no le dice nada al usuario
POR_RESTRICCION = {
    "requests_justificacion_obligatoria":
        "Los días solicitados superan su saldo: debe escribir una justificación de al menos 10 caracteres.",
    "requests_descripcion_max":
        "La descripción no puede superar los 200 caracteres.",
    "requests_descripcion_obligatoria":
        "Debe describir el motivo de su solicitud (mínimo 5 caracteres).",
    "requests_permiso_categorizado":
        "Debe seleccionar el tipo de permiso.",
    "requests_rango_fechas":
        "La fecha de fin no puede ser anterior a la de inicio.",
    "requests_rango_horas":
        "La hora de fin debe ser posterior a la de inicio.",
    "request_attachments_mime_permitido":
        "Solo se admiten imágenes (JPG, PNG, WebP, HEIC) o archivos PDF.",
    "request_attachments_tamano_bytes_check":
        "Cada archivo debe pesar menos de 10 MB.",
    "users_cedula_valida":
        "La cédula ingresada no es válida.",
    "family_cedula_valida":
        "La cédula del familiar no es válida.",
}


def traducir(exc: Exception) -> HTTPException:
    """Convierte un error de la base en HTTPException con mensaje legible."""
    # Excepciones levantadas a propósito por los triggers (RAISE EXCEPTION)
    if isinstance(exc, pg.RaiseException):
        mensaje = (exc.diag.message_primary or "").strip()
        detalle: dict = {"mensaje": mensaje}
        # El HINT transporta datos que el formulario necesita para ofrecer una
        # salida. Lleva etiqueta al inicio para no confundir un caso con otro:
        # "rango|2099-07-13|2099-07-19"  -> corrección del fin de semana
        # "bloque_minimo|7"              -> mínimo de días de vacaciones
        pista = exc.diag.message_hint or ""
        etiqueta, _, resto = pista.partition("|")
        if etiqueta == "bloque_minimo" and resto:
            detalle["bloque_minimo"] = resto
        elif pista and "|" in pista:
            # Formato histórico sin etiqueta: dos fechas.
            partes = [p for p in pista.split("|") if p]
            if etiqueta == "rango":
                partes = partes[1:]
            if len(partes) == 2:
                detalle["rango_sugerido"] = {"inicio": partes[0], "fin": partes[1]}
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detalle)

    if isinstance(exc, pg.CheckViolation):
        nombre = exc.diag.constraint_name or ""
        mensaje = POR_RESTRICCION.get(nombre, "Los datos enviados no cumplen una regla del sistema.")
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                             detail={"mensaje": mensaje, "restriccion": nombre})

    if isinstance(exc, pg.UniqueViolation):
        return HTTPException(status_code=status.HTTP_409_CONFLICT,
                             detail={"mensaje": "El registro ya existe."})

    if isinstance(exc, pg.InsufficientPrivilege):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                             detail={"mensaje": "No tiene permisos para esta operación."})

    log.exception("Error de base no contemplado")
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                         detail={"mensaje": "Ocurrió un error inesperado. El incidente quedó registrado."})
