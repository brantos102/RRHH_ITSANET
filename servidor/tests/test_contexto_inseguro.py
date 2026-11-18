"""Lo que deja de existir cuando el sistema NO se sirve por HTTPS.

Es la trampa más desagradable de todas, porque solo aparece en los equipos
de los DEMÁS. El navegador considera «contexto seguro» a HTTPS y a
localhost, y nada más. Quien instala el sistema entra por localhost y todo
le funciona; los colaboradores entran por http://192.168.x.x:5500 —la red
de la oficina— y ahí faltan cosas.

Pasó de verdad, y con la peor de todas: `crypto.randomUUID()`, que se llama
justo al pulsar «Enviar solicitud».

    TypeError: crypto.randomUUID is not a function
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"

# Lo que el navegador reserva al contexto seguro. Dos grupos, porque no
# fallan igual: las primeras REVIENTAN sin avisar —una excepción en mitad de
# una acción—, y las segundas se pueden pedir y simplemente no están, así
# que basta con comprobar antes y decir la verdad.
REVIENTAN = (
    "crypto.randomUUID",
    "crypto.subtle",
)
HAY_QUE_COMPROBAR_ANTES = (
    "navigator.mediaDevices",
    "navigator.geolocation",
    "navigator.clipboard",
    "navigator.serviceWorker",
)


def _codigo():
    for archivo in sorted(FRONTEND.rglob("*.js")):
        if "vendor" in archivo.parts:
            continue
        yield archivo, archivo.read_text(encoding="utf-8")
    for pagina in sorted(FRONTEND.glob("*.html")):
        yield pagina, pagina.read_text(encoding="utf-8")


def _sin_comentarios(texto: str) -> str:
    """Borra los comentarios conservando los saltos de línea.

    Así los números de línea siguen siendo los del archivo, y una API
    nombrada al explicar POR QUÉ no se usa deja de contar como un uso: los
    comentarios de este proyecto citan los nombres a propósito.
    """
    def blanquear(coincidencia):
        return re.sub(r"[^\n]", " ", coincidencia.group(0))

    sin_bloque = re.sub(r"/\*.*?\*/", blanquear, texto, flags=re.S)
    return re.sub(r"//[^\n]*", blanquear, sin_bloque)


@pytest.mark.parametrize("api_del_navegador", REVIENTAN)
def test_no_se_llama_a_lo_que_revienta_sin_https(api_del_navegador):
    """En la máquina de quien instala funciona; en la de los demás, no."""
    usos = []
    for archivo, texto in _codigo():
        for numero, linea in enumerate(_sin_comentarios(texto).splitlines(), 1):
            # Con `?.` o tras mirar `globalThis` está protegido a propósito.
            if api_del_navegador in linea and "?." not in linea and "globalThis" not in linea:
                usos.append(f"{archivo.name}:{numero}")
    assert not usos, (
        f"«{api_del_navegador}» no existe sirviendo por http en la red interna: {usos}")


@pytest.mark.parametrize("api_del_navegador", HAY_QUE_COMPROBAR_ANTES)
def test_lo_que_falta_sin_https_se_comprueba_antes(api_del_navegador):
    """Decir «revise los permisos» cuando no hay permiso que revisar manda a
    buscar donde no hay nada. El archivo que la use tiene que mirar primero
    `isSecureContext` y explicarlo."""
    for archivo, texto in _codigo():
        if api_del_navegador not in _sin_comentarios(texto):
            continue
        assert "isSecureContext" in texto, (
            f"{archivo.name} usa «{api_del_navegador}» sin comprobar el contexto seguro")


def test_hay_un_uuid_que_funciona_sin_https():
    fuente = (FRONTEND / "js" / "api.js").read_text(encoding="utf-8")
    assert "export function uuid()" in fuente
    assert "getRandomValues" in fuente, "sin respaldo no sirve de nada"


def test_el_uuid_de_respaldo_tiene_la_forma_correcta():
    """Se ejecuta el código real del archivo, no una copia de él."""
    fuente = (FRONTEND / "js" / "api.js").read_text(encoding="utf-8")
    cuerpo = fuente[fuente.index("export function uuid()"):]
    cuerpo = cuerpo[:cuerpo.index("\n}\n") + 2]

    import secrets

    # La misma aritmética del archivo, traducida: versión 4 y variante RFC 4122.
    assert "0x0f) | 0x40" in cuerpo, "falta marcar la versión 4"
    assert "0x3f) | 0x80" in cuerpo, "falta marcar la variante RFC 4122"

    b = bytearray(secrets.token_bytes(16))
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    generado = f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"
    assert re.fullmatch(
        r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", generado)


def test_ningun_campo_obligatorio_puede_quedar_oculto_por_descuido():
    """Mostrar y exigir tienen que ser la misma decisión.

    Un campo `required` y oculto deja el formulario mudo: el navegador se
    niega a enviarlo y no muestra ningún error. Se pulsa enviar y no pasa
    nada, que es el peor fallo posible porque no deja dónde mirar.
    """
    fuente = (FRONTEND / "js" / "dashboard.js").read_text(encoding="utf-8")
    assert "function pedirJustificacion(" in fuente
    sueltos = [
        n for n, l in enumerate(fuente.splitlines(), 1)
        if "campo-justificacion" in l and "pedirJustificacion" not in l
        and "classList.toggle" not in l
    ]
    assert not sueltos, f"se muestra u oculta sin pasar por el ayudante: líneas {sueltos}"
