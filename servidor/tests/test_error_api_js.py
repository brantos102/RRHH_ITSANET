"""La referencia solo debe acompañar a los errores inesperados.

Existe por un desliz concreto: el código de la petición viaja en la cabecera
de *todas* las respuestas, así que al incorporarlo al mensaje sin mirar el
estado, un «el código es incorrecto» acababa en «el código es incorrecto
(referencia a1b2c3d4)». No se notó en las pruebas de navegador porque entre
orígenes distintos el navegador oculta la cabecera a JavaScript; en un
despliegue de mismo origen habría salido en cada validación.

Se ejecuta la clase de verdad en Node en vez de buscar texto en el archivo:
lo que importa es qué mensaje ve el usuario.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

API_JS = Path(__file__).resolve().parents[2] / "frontend" / "js" / "api.js"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="requiere Node para ejecutar el módulo"
)


def _clase_error_api() -> str:
    """Aísla la clase: el módulo completo necesita navegador para cargarse."""
    texto = API_JS.read_text(encoding="utf-8")
    inicio = texto.index("export class ErrorApi")
    # Hasta el cierre de la clase, que está a nivel de columna cero.
    fin = texto.index("\n}\n", inicio) + len("\n}\n")
    return texto[inicio:fin].replace("export class", "class")


def _mensajes(casos: list[dict]) -> list[str]:
    guion = f"""
{_clase_error_api()}
const casos = {json.dumps(casos)};
console.log(JSON.stringify(casos.map(
  (c) => new ErrorApi(c.mensaje, c.estado, null, c.referencia).message
)));
"""
    salida = subprocess.run(
        ["node", "--input-type=module", "-e", guion],
        capture_output=True, text=True, check=True,
    )
    return json.loads(salida.stdout)


def test_un_error_del_servidor_lleva_la_referencia():
    (mensaje,) = _mensajes([
        {"mensaje": "Ocurrió un error inesperado.", "estado": 500, "referencia": "a1b2c3d4"},
    ])
    assert "a1b2c3d4" in mensaje


def test_una_validacion_no_lleva_la_referencia():
    mensajes = _mensajes([
        {"mensaje": "El código es incorrecto.", "estado": 401, "referencia": "a1b2c3d4"},
        {"mensaje": "Debe justificar el bloque menor.", "estado": 422, "referencia": "a1b2c3d4"},
        {"mensaje": "No tiene permisos para esta operación.", "estado": 403, "referencia": "a1b2c3d4"},
    ])
    for mensaje in mensajes:
        assert "referencia" not in mensaje, mensaje
        assert "a1b2c3d4" not in mensaje, mensaje


def test_no_se_repite_si_el_servidor_ya_la_puso_en_el_texto():
    """El texto de los 500 ya la trae; no debe salir dos veces."""
    (mensaje,) = _mensajes([
        {"mensaje": "Error inesperado, referencia a1b2c3d4.", "estado": 500,
         "referencia": "a1b2c3d4"},
    ])
    assert mensaje.count("a1b2c3d4") == 1, mensaje


def test_la_cabecera_se_expone_a_javascript():
    """Sin expose_headers el navegador la oculta entre orígenes distintos."""
    main = (Path(__file__).resolve().parents[1] / "app" / "main.py").read_text(encoding="utf-8")
    expuestas = re.search(r"expose_headers=\[([^\]]*)\]", main)
    assert expuestas, "CORSMiddleware debe exponer la cabecera del rastro"
    assert "X-Peticion-Id" in expuestas.group(1)
