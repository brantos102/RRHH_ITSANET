"""OTP, hashing y emisión de las sesiones (JWT)."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException, status

from .config import get_settings


# --------------------------------------------------------------------- OTP
def generar_otp(longitud: int) -> str:
    """Código numérico con entropía criptográfica (no `random`)."""
    maximo = 10**longitud
    return str(secrets.randbelow(maximo)).zfill(longitud)


def hash_otp(codigo: str, cedula: str) -> str:
    """SHA-256 del código ligado a la cédula.

    Ligarlo a la cédula evita que un hash filtrado sirva para otro usuario,
    y el código nunca se almacena en claro (LOPDP Art. 37).
    """
    return hashlib.sha256(f"{cedula}:{codigo}".encode()).hexdigest()


def comparar_hash(a: str, b: str) -> bool:
    """Comparación en tiempo constante: no filtra información por tiempo."""
    return hmac.compare_digest(a, b)


# --------------------------------------------------------------------- JWT
AUDIENCIA = "rrhh-itsanet"


def emitir_token(user_id: str, cedula: str, rol: str) -> tuple[str, datetime]:
    """Firma la sesión del colaborador.

    `sub` es el id de la ficha (users.id). Con Supabase era el id de
    auth.users, una tabla de Supabase que en MySQL no existe; el backend ya
    era quien verificaba cada permiso, así que la identidad sale de la ficha.

    La audiencia es propia del sistema: un token firmado para otra
    aplicación con el mismo secreto no abre una sesión aquí.
    """
    settings = get_settings()
    ahora = datetime.now(timezone.utc)
    expira = ahora + timedelta(hours=settings.jwt_expira_horas)

    payload: dict[str, Any] = {
        "sub": user_id,
        "aud": AUDIENCIA,
        "iat": int(ahora.timestamp()),
        "exp": int(expira.timestamp()),
        "cedula": cedula,
        "rol": rol,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256"), expira


def leer_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience=AUDIENCIA,
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Su sesión expiró. Vuelva a ingresar.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sesión inválida.",
        )
