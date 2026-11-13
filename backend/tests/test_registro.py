"""El rastro de cada petición: sin él, «me salió un error» no se investiga.

Lo que se fija aquí es la cadena completa: el servidor marca la petición, el
código sale por la cabecera y por el mensaje en pantalla, la línea del
registro lo lleva, y el lector lo encuentra junto con la traza.
"""
from __future__ import annotations

import logging

import httpx
import pytest
from app import registro
from app.main import app

REFERENCIA = "aabbccdd"


@pytest.fixture
async def cliente_simple():
    """Cliente sin empleado: estas pruebas no tocan la base."""
    transporte = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transporte, base_url="http://api") as c:
        yield c


@pytest.fixture
def lineas_registradas():
    """Captura las líneas ya formateadas, con el filtro de contexto puesto.

    No sirve aplicar el filtro después de la petición sobre lo que guarda
    `caplog`: la variable de contexto ya se soltó y el filtro sellaría un
    guión donde debía ir el código. El filtro tiene que correr en el momento
    de emitir, que es exactamente lo que hace el manejador de producción.
    """
    capturadas: list[str] = []

    class Espia(logging.Handler):
        def emit(self, registro_) -> None:
            capturadas.append(self.format(registro_))

    espia = Espia()
    espia.setFormatter(logging.Formatter("%(levelname)s [%(peticion)s] %(quien)s %(message)s"))
    espia.addFilter(registro.ContextoPeticion())
    raiz = logging.getLogger()
    nivel_previo = raiz.level
    raiz.addHandler(espia)
    raiz.setLevel(logging.INFO)
    try:
        yield capturadas
    finally:
        raiz.removeHandler(espia)
        raiz.setLevel(nivel_previo)


@pytest.fixture
def ruta_que_falla():
    """Una ruta que estalla, para ejercitar el camino del error 500."""

    @app.get("/_prueba_estalla")
    async def estalla() -> dict:  # pragma: no cover - se invoca por HTTP
        raise RuntimeError("fallo deliberado para la prueba")

    yield "/_prueba_estalla"
    app.router.routes = [
        r for r in app.router.routes
        if getattr(r, "path", None) != "/_prueba_estalla"
    ]


@pytest.mark.anyio
async def test_toda_respuesta_trae_su_codigo(cliente_simple):
    r = await cliente_simple.get("/glosario")
    codigo = r.headers.get("X-Peticion-Id")
    assert codigo and len(codigo) == 8, r.headers


@pytest.mark.anyio
async def test_dos_peticiones_tienen_codigos_distintos(cliente_simple):
    primera = await cliente_simple.get("/glosario")
    segunda = await cliente_simple.get("/glosario")
    assert primera.headers["X-Peticion-Id"] != segunda.headers["X-Peticion-Id"]


@pytest.mark.anyio
async def test_se_respeta_el_codigo_que_manda_el_cliente(cliente_simple):
    """Permite seguir una misma operación desde el navegador hasta el registro."""
    r = await cliente_simple.get("/glosario", headers={"X-Peticion-Id": REFERENCIA})
    assert r.headers["X-Peticion-Id"] == REFERENCIA


@pytest.mark.anyio
async def test_la_peticion_exitosa_tambien_queda_marcada(cliente_simple, lineas_registradas):
    """Se soltaba el contexto antes de escribir la línea, que salía con «—».

    Importa tanto como el caso del error: «¿la petición llegó al servidor?» es
    lo que hay que responder cuando el navegador no muestra nada, y una línea
    sin código no se puede cruzar con lo que reporta el usuario.
    """
    await cliente_simple.get("/glosario", headers={"X-Peticion-Id": REFERENCIA})

    cierres = [ln for ln in lineas_registradas if "/glosario" in ln]
    assert cierres, f"debía registrarse la petición atendida: {lineas_registradas}"
    assert all(f"[{REFERENCIA}]" in ln for ln in cierres), cierres


@pytest.mark.anyio
async def test_el_error_500_devuelve_la_referencia(cliente_simple, ruta_que_falla):
    # raise_app_exceptions=False: interesa la respuesta que vería el navegador,
    # no que la excepción suba hasta la prueba.
    transporte = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transporte, base_url="http://api") as c:
        r = await c.get(ruta_que_falla, headers={"X-Peticion-Id": REFERENCIA})

    assert r.status_code == 500
    cuerpo = r.json()
    assert cuerpo["referencia"] == REFERENCIA
    # El código va dentro del texto: las pantallas muestran `detail` y así lo
    # ve el usuario sin tener que abrir las herramientas del navegador.
    assert REFERENCIA in cuerpo["detail"]
    assert r.headers["X-Peticion-Id"] == REFERENCIA


@pytest.mark.anyio
async def test_el_error_500_no_filtra_la_traza(cliente_simple, ruta_que_falla):
    transporte = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transporte, base_url="http://api") as c:
        r = await c.get(ruta_que_falla)
    assert "fallo deliberado" not in r.text
    assert "RuntimeError" not in r.text
    assert "Traceback" not in r.text


@pytest.mark.anyio
async def test_la_referencia_queda_en_el_registro(ruta_que_falla, lineas_registradas):
    transporte = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transporte, base_url="http://api") as c:
        await c.get(ruta_que_falla, headers={"X-Peticion-Id": REFERENCIA})

    marcadas = [ln for ln in lineas_registradas if f"[{REFERENCIA}]" in ln]
    assert marcadas, f"la excepción debía quedar marcada: {lineas_registradas}"
    # La causa va en la propia línea de cabecera: `ver_logs.py --errores` debe
    # poder decir qué pasó sin desplegar cuarenta líneas de traza de Starlette.
    assert any("RuntimeError: fallo deliberado" in ln for ln in marcadas), marcadas


@pytest.mark.anyio
@pytest.mark.parametrize(
    "intruso",
    [
        "a1b2c3d4\n2026-01-01 00:00:00 ERROR [xxxx] falso :: entrada fabricada",
        "corto",           # menos de 4 no, pero este tiene 5: debe pasar
        "x" * 500,         # kilobytes de basura en cada línea
        "../../etc/passwd",
        "con espacios",
        "",
    ],
)
async def test_no_se_acepta_cualquier_codigo_del_cliente(cliente_simple, intruso):
    """El registro es evidencia: no debe poder fabricarse desde una cabecera."""
    r = await cliente_simple.get("/glosario", headers={"X-Peticion-Id": intruso})
    devuelto = r.headers["X-Peticion-Id"]
    if intruso == "corto":
        assert devuelto == "corto"          # inofensivo, se respeta
    else:
        assert devuelto != intruso
        assert len(devuelto) == 8
    assert "\n" not in devuelto and " " not in devuelto


def test_el_formato_no_estalla_sin_contexto():
    """Las líneas de arranque se emiten antes de que exista una petición."""
    registro.configurar("INFO", a_archivo=False)
    linea = logging.LogRecord("rrhh", logging.INFO, __file__, 1, "arranque", None, None)
    registro.ContextoPeticion().filter(linea)
    assert linea.peticion == "—"
    assert linea.quien == "—"
