"""Sistema Integrado de Permisos, Vacaciones y Control de Garita — API."""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import registro
from .config import get_settings
from .db import abrir_pool, cerrar_pool, obtener_uno
from .routers import (administracion, aprobaciones, auth, chat, ficha, firmas,
                      garita, informes, panel, personas, solicitudes,
                      temporal)

settings = get_settings()

# Antes de cualquier otra cosa: si algo falla durante el arranque, interesa
# que quede escrito.
registro.configurar(settings.nivel_log, a_archivo=settings.log_a_archivo)
log = logging.getLogger("rrhh")


@asynccontextmanager
async def ciclo_de_vida(app: FastAPI):
    await abrir_pool()
    log.info("Pool de base de datos abierto")
    log.info("Entorno: %s", settings.entorno)
    log.info(
        "CORS acepta: %s%s",
        ", ".join(settings.origenes_permitidos) or "(lista vacía)",
        "" if settings.es_produccion else " y cualquier http://localhost:PUERTO",
    )
    if settings.log_a_archivo:
        log.info("Registros en %s (sistema.log y errores.log)", registro.ruta_registros())
    yield
    await cerrar_pool()
    log.info("Pool cerrado")


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
    allow_origin_regex=settings.origen_regex,
    allow_credentials=True,
    # PUT no está, y es a propósito: en este sistema los cambios parciales
    # van por PATCH. Un PUT nuevo pasaría las pruebas de la API y fallaría
    # solo en el navegador, en el vuelo previo, que es de los fallos más
    # caros de encontrar.
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    # Sin esto el navegador oculta la cabecera a JavaScript cuando el frontend
    # y la API están en orígenes distintos, que es justo el caso en desarrollo.
    # `X-Peticion-Id` para poder leer el código de la petición desde las
    # herramientas del navegador aunque no haya habido error, y
    # `Content-Disposition` para que las descargas conserven el nombre que
    # pone el servidor: sin exponerla, el archivo bajaba como «cotejo.xlsx»
    # en vez de «cotejo-de-la-carga-inicial-2026-09-27.xlsx».
    expose_headers=["X-Peticion-Id", "Content-Disposition"],
    max_age=600,
)


@app.middleware("http")
async def diagnostico_de_origen(request: Request, call_next):
    """Un preflight rechazado devuelve 400 sin decir por qué. Aquí sí se dice.

    Es el error más frecuente al arrancar en una máquina nueva: el navegador
    envía un Origin que no está permitido, CORSMiddleware responde 400 y el
    usuario solo ve «No se pudo conectar con el servidor».
    """
    origen = request.headers.get("origin")
    if origen and not settings.origen_aceptado(origen):
        log.error(
            "CORS: origen rechazado %s (permitidos: %s). "
            "Agréguelo a CORS_ORIGINS en backend/.env y reinicie uvicorn. "
            "Si el origen es 'null', está abriendo el HTML con doble clic: "
            "sírvalo por HTTP (python -m http.server 5500 dentro de frontend/).",
            origen,
            ", ".join(settings.origenes_permitidos) or "ninguno",
        )
    return await call_next(request)


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


@app.middleware("http")
async def rastro_de_peticion(request: Request, call_next):
    """Marca cada petición con un código y mide cuánto tardó.

    El código sale por tres vías a la vez —la cabecera `X-Peticion-Id`, el
    mensaje de error en pantalla y cada línea del registro—, así que basta
    que alguien lo dicte por teléfono para encontrar su caso exacto entre
    miles de líneas.

    Se guarda también en `request.state` y no solo en la variable de
    contexto: el manejador de errores 500 corre por fuera de este
    middleware, en una copia distinta del contexto, y desde ahí la variable
    no se ve. `state` viaja en el scope de ASGI, que sí es el mismo objeto.
    """
    codigo = registro.codigo_aceptable(request.headers.get("x-peticion-id")) \
        or registro.nuevo_id()
    request.state.peticion = codigo
    testigo = registro.peticion_actual.set(codigo)
    inicio = time.perf_counter()
    try:
        try:
            respuesta = await call_next(request)
        except Exception:
            # El detalle lo escribe el manejador de abajo; aquí solo se deja
            # constancia de que la petición murió, con su duración.
            log.warning(
                "%s %s terminó en excepción tras %.0f ms",
                request.method, request.url.path,
                (time.perf_counter() - inicio) * 1000,
            )
            raise

        transcurrido = (time.perf_counter() - inicio) * 1000
        respuesta.headers["X-Peticion-Id"] = codigo
        # Se registra toda petición, no solo las que fallan. La pregunta que
        # más veces hubo que responder en este proyecto es «¿la petición llegó
        # al servidor?» —el preflight rechazado, el puerto equivocado, la
        # sesión caducada—, y para eso el silencio no sirve de nada. A este
        # tamaño (unos 350 empleados) el volumen es de cientos de KB al día,
        # que la rotación absorbe sin problema. Los OPTIONS sí se omiten: son
        # dos por cada petición real y no dicen nada que ella no diga.
        nivel = logging.WARNING if respuesta.status_code >= 500 or transcurrido > 3000 \
            else logging.INFO
        if request.method != "OPTIONS":
            # La cédula la fijó una dependencia, en otro contexto que no se ve
            # desde aquí; se recupera del scope.
            marca = registro.usuario_actual_log.set(getattr(request.state, "quien", "—"))
            try:
                log.log(
                    nivel, "%s %s → %s en %.0f ms",
                    request.method, request.url.path, respuesta.status_code, transcurrido,
                )
            finally:
                registro.usuario_actual_log.reset(marca)
    finally:
        # Al final de todo, no antes de la última línea: soltarlo demasiado
        # pronto dejaba la línea de cierre —la única que hay cuando la
        # petición sale bien— marcada con «—» en vez del código.
        registro.peticion_actual.reset(testigo)
    return respuesta


@app.exception_handler(Exception)
async def error_no_controlado(request: Request, exc: Exception):
    """Nunca se devuelve la traza al cliente: podría filtrar datos.

    Sí se devuelve el código de la petición. Sin él, «ocurrió un error
    inesperado» obliga a adivinar; con él, quien reporta el problema entrega
    la única pista que hace falta para llegar a la traza completa.
    """
    codigo = getattr(request.state, "peticion", None) or registro.nuevo_id()
    # Este manejador corre por fuera del middleware del rastro, donde la
    # variable de contexto ya se soltó: se vuelve a fijar solo para la línea
    # de la traza y se deja como estaba, o el código se pegaría a los
    # mensajes siguientes (se vio teñir al «Pool cerrado» del apagado).
    testigo = registro.peticion_actual.set(codigo)
    try:
        # El tipo y el mensaje van en la línea de cabecera, no solo en la
        # traza: la traza pasa por el middleware de Starlette y llega a
        # cuarenta líneas de sus entrañas antes de la causa real, así que
        # `--errores` debe poder decir qué pasó sin desplazarse.
        log.exception(
            "Error no controlado en %s %s → %s: %s",
            request.method, request.url.path, type(exc).__name__, exc,
        )
    finally:
        registro.peticion_actual.reset(testigo)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": (
                "Ocurrió un error inesperado. El incidente quedó registrado "
                f"con la referencia {codigo}; indíquela al reportarlo."
            ),
            "referencia": codigo,
        },
        headers={"X-Peticion-Id": codigo},
    )


app.include_router(auth.router)
app.include_router(solicitudes.router)
app.include_router(firmas.router)
app.include_router(aprobaciones.router)
app.include_router(garita.router)
app.include_router(informes.router)
app.include_router(administracion.router)
app.include_router(ficha.router)
app.include_router(chat.router)
app.include_router(temporal.router)
app.include_router(panel.router)
app.include_router(personas.router)


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
