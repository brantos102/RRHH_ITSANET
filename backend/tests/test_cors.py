"""El preflight es lo primero que toca el navegador: si falla, no hay sistema.

Un origen rechazado devuelve 400 en OPTIONS y la pantalla de acceso solo dice
«No se pudo conectar con el servidor», así que estas pruebas fijan qué
orígenes pasan en desarrollo y cuáles quedan fuera en producción.
"""
from __future__ import annotations

import pytest
from app.config import Settings


PREFLIGHT = {
    "Origin": "http://127.0.0.1:5500",
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "content-type",
}


@pytest.mark.anyio
@pytest.mark.parametrize(
    "origen",
    [
        "http://localhost:5500",     # el de la lista
        "http://127.0.0.1:5500",     # otro origen para el navegador, mismo equipo
        "http://127.0.0.1:5501",     # Live Server cuando 5500 está ocupado
        "http://localhost:8000",
    ],
)
async def test_preflight_aceptado_en_desarrollo(cliente, origen):
    r = await cliente.options("/auth/solicitar-token", headers={**PREFLIGHT, "Origin": origen})
    assert r.status_code == 200, r.text
    assert r.headers["access-control-allow-origin"] == origen


@pytest.mark.anyio
async def test_preflight_rechaza_origen_ajeno(cliente):
    r = await cliente.options(
        "/auth/solicitar-token",
        headers={**PREFLIGHT, "Origin": "https://sitio-de-un-tercero.com"},
    )
    assert "access-control-allow-origin" not in r.headers


def _config(**extra) -> Settings:
    base = dict(
        database_url="postgresql://x/y",
        supabase_jwt_secret="secreto-de-prueba-suficientemente-largo-1234",
    )
    return Settings(**{**base, **extra})  # type: ignore[arg-type]


def test_en_produccion_no_vale_localhost():
    cfg = _config(entorno="produccion", cors_origins="https://permisos.itsanet.com.ec")
    assert cfg.origen_regex is None
    assert cfg.origen_aceptado("https://permisos.itsanet.com.ec")
    assert not cfg.origen_aceptado("http://localhost:5500")


def test_barra_final_y_mayusculas_no_rompen_la_lista():
    cfg = _config(cors_origins="https://permisos.itsanet.com.ec/ , http://localhost:5500")
    assert cfg.origen_aceptado("https://permisos.itsanet.com.ec")
    assert cfg.origen_aceptado("http://localhost:5500/")


def test_un_dominio_que_solo_empieza_igual_no_pasa():
    cfg = _config(entorno="produccion", cors_origins="https://itsanet.com.ec")
    assert not cfg.origen_aceptado("https://itsanet.com.ec.atacante.net")
    assert not cfg.origen_aceptado("http://localhost.atacante.net:5500")
