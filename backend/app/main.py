"""Sistema Integrado de Permisos, Vacaciones y Control de Garita — API."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .db import abrir_pool, cerrar_pool, obtener_uno
from .routers import (administracion, aprobaciones, auth, firmas, garita, informes,
                      solicitudes)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("rrhh")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    await abrir_pool()
    log.info("Pool de base de datos abierto")
    yield
    await cerrar_pool()
    log.info("Pool cerrado")


settings = get_settings()

app = FastAPI(
    title=settings.app_nombre,
    version="0.2.0",
    description=(
        "API de permisos, vacaciones y control de garita. "
        "Autenticación por cédula con código de un solo uso al correo institucional."
    ),
    lifespan=ciclo_de_vida,
    docs_url=None if settings.es_produccion else "/docs",
    redoc_url=None,
    openapi_url=None if settings.es_produccion else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origenes_permitidos,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


@app.middleware("http")
async def cabeceras_de_seguridad(request: Request, call_next):
    respuesta = await call_next(request)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["X-Frame-Options"] = "DENY"
    respuesta.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    respuesta.headers["Permissions-Policy"] = "camera=(self), geolocation=(), microphone=()"
    if settings.es_produccion:
        respuesta.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return respuesta


@app.exception_handler(Exception)
async def error_no_controlado(request: Request, exc: Exception):
    """Nunca se devuelve la traza al cliente: podría filtrar datos."""
    log.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Ocurrió un error inesperado. El incidente quedó registrado."},
    )


app.include_router(auth.router)
app.include_router(solicitudes.router)
app.include_router(firmas.router)
app.include_router(aprobaciones.router)
app.include_router(garita.router)
app.include_router(informes.router)
app.include_router(administracion.router)


@app.get("/salud", tags=["Sistema"])
async def salud() -> dict:
    try:
        await obtener_uno("select 1 as ok")
        return {"estado": "ok", "base_datos": "conectada"}
    except Exception:  # noqa: BLE001
        log.exception("Fallo de conexión a la base")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"estado": "degradado", "base_datos": "sin conexión"},
        )


@app.get("/glosario", tags=["Sistema"])
async def glosario(categoria: str | None = None) -> list[dict]:
    """Artículos que sustentan las reglas. Público: es normativa vigente."""
    from .db import obtener_todos

    if categoria:
        return await obtener_todos(
            """select codigo, norma, articulo, titulo, texto, categoria
               from public.legal_references where categoria = %s order by orden""",
            (categoria,),
        )
    return await obtener_todos(
        """select codigo, norma, articulo, titulo, texto, categoria
           from public.legal_references order by orden"""
    )
