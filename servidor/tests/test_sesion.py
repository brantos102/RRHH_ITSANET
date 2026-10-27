"""La sesión sin Supabase.

Con Supabase el token llevaba el id de auth.users, una tabla de Supabase. En
MySQL no existe: el token lleva el id de la ficha, y es el backend quien lo
firma y lo verifica con su propio secreto.
"""
from __future__ import annotations

import jwt
import pytest
from fastapi import HTTPException

from app.config import get_settings
from app.security import AUDIENCIA, emitir_token, leer_token


def test_el_token_identifica_a_la_ficha():
    token, _ = emitir_token("0f8fad5b-d9cb-469f-a165-70867728950e", "1750000000", "empleado")
    datos = leer_token(token)
    assert datos["sub"] == "0f8fad5b-d9cb-469f-a165-70867728950e"
    assert datos["rol"] == "empleado" and datos["aud"] == AUDIENCIA


def test_un_token_de_otra_aplicacion_no_abre_sesion():
    """Mismo secreto, otra audiencia: no vale. Un token emitido para Supabase
    («authenticated») no sirve en el servidor corporativo."""
    falso = jwt.encode({"sub": "x", "aud": "authenticated", "exp": 9999999999},
                       get_settings().jwt_secret, algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        leer_token(falso)
    assert exc.value.status_code == 401


def test_un_token_firmado_con_otro_secreto_no_abre_sesion():
    falso = jwt.encode({"sub": "x", "aud": AUDIENCIA, "exp": 9999999999},
                       "otro-secreto-cualquiera-de-longitud-suficiente", algorithm="HS256")
    with pytest.raises(HTTPException) as exc:
        leer_token(falso)
    assert exc.value.status_code == 401


def test_el_token_no_lleva_datos_personales_de_mas():
    """El token viaja en cada petición y el navegador lo guarda: lleva lo
    justo para identificar la sesión, no el correo ni el nombre."""
    token, _ = emitir_token("0f8fad5b-d9cb-469f-a165-70867728950e", "1750000000", "jefe")
    datos = jwt.decode(token, options={"verify_signature": False})
    assert set(datos) == {"sub", "aud", "iat", "exp", "cedula", "rol"}
