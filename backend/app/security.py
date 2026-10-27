"""OTP, hashing y emisión de JWT compatibles con Supabase."""
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
def emitir_token(auth_user_id: str, user_id: str, cedula: str, rol: str) -> tuple[str, datetime]:
    """Firma un JWT que Supabase acepta, para que RLS reconozca al usuario.

    El claim `sub` debe ser el id de auth.users: `auth.uid()` lo lee y las
    políticas lo resuelven contra `users.auth_user_id`.
    """
    settings = get_settings()
    ahora = datetime.now(timezone.utc)
    expira = ahora + timedelta(hours=settings.jwt_expira_horas)

    payload: dict[str, Any] = {
        "sub": auth_user_id,
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(ahora.timestamp()),
        "exp": int(expira.timestamp()),
        "app_metadata": {"provider": "cedula_otp"},
        "user_metadata": {"user_id": user_id, "cedula": cedula, "rol": rol},
    }
    return jwt.encode(payload, settings.supabase_jwt_secret, algorithm="HS256"), expira


def leer_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
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
