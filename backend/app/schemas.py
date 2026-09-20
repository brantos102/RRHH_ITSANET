"""Contratos de entrada y salida de la API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from .cedula import es_cedula_valida, normalizar_cedula


class SolicitudToken(BaseModel):
    cedula: str = Field(..., description="Cédula ecuatoriana de 10 dígitos")

    @field_validator("cedula")
    @classmethod
    def validar(cls, v: str) -> str:
        limpia = normalizar_cedula(v)
        if not es_cedula_valida(limpia):
            raise ValueError("La cédula ingresada no es válida.")
        return limpia


class ValidacionToken(SolicitudToken):
    codigo: str = Field(..., min_length=4, max_length=10)

    @field_validator("codigo")
    @classmethod
    def solo_digitos(cls, v: str) -> str:
        limpio = "".join(c for c in v if c.isdigit())
        if not limpio:
            raise ValueError("El código debe ser numérico.")
        return limpio


class RespuestaEnvio(BaseModel):
    enviado: bool
    mensaje: str
    correo: str | None = None
    vigencia_minutos: int


class Perfil(BaseModel):
    id: str
    cedula: str
    nombre: str
    email: str
    rol: str
    cargo: str | None = None
    departamento: str | None = None
    telefono: str | None = None
    fecha_ingreso: date
    anios_servicio: int
    dias_vacaciones: float
    jefe_nombre: str | None = None
    logros: list[dict[str, Any]] = []


class Sesion(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expira_en: datetime
    perfil: Perfil
