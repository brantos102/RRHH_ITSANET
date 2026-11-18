"""El chat existía en el servidor y no en la pantalla.

Dos huecos distintos, los dos invisibles desde las pruebas de la API:

1. `montarChat()` solo se llamaba desde `dashboard.js`, así que la burbuja
   desaparecía en el calendario, los informes, colaboradores y
   administración. La API respondía perfectamente a algo que nadie podía
   pulsar.

2. `/chat/bandeja` se servía desde el primer día y ninguna pantalla lo
   consumía. Talento Humano —que entra como `rrhh` o `admin`— no tenía
   burbuja «porque usa su bandeja», y la bandeja no estaba construida: los
   mensajes llegaban y nadie podía leerlos.

Se comprueba sobre los archivos porque es justo lo que la prueba de la API
no puede ver: que la pantalla exista y esté enganchada.
"""
from __future__ import annotations

from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


def _leer(*partes: str) -> str:
    return FRONTEND.joinpath(*partes).read_text(encoding="utf-8")


def test_la_bandeja_de_talento_humano_existe():
    assert (FRONTEND / "mensajes.html").exists(), (
        "Falta frontend/mensajes.html: sin ella /chat/bandeja no lo consume nadie"
    )
    assert (FRONTEND / "js" / "mensajes.js").exists()


def test_la_bandeja_usa_los_tres_extremos_del_backend():
    js = _leer("js", "mensajes.js")
    for metodo in ("bandejaChat", "leerConversacion", "enviarMensaje", "cerrarConversacion"):
        assert metodo in js, f"la bandeja no usa api.{metodo}"


def test_la_bandeja_es_solo_de_talento_humano():
    js = _leer("js", "mensajes.js")
    assert 'if (!sesion.vigente) location.replace("index.html")' in js
    assert '["rrhh", "admin"].includes(sesion.perfil?.rol)' in js, (
        "cualquiera podría abrir la bandeja y leer consultas ajenas"
    )


def test_el_chat_se_monta_desde_la_barra_y_no_desde_una_sola_pantalla():
    """La barra está en todas las pantallas; el panel, solo en una."""
    navegacion = _leer("js", "navegacion.js")
    assert 'import("./chat.js")' in navegacion and "montarChat()" in navegacion

    dashboard = _leer("js", "dashboard.js")
    assert "montarChat" not in dashboard, (
        "el panel volvió a montar el chat por su cuenta: habría dos burbujas"
    )


def test_la_burbuja_no_se_duplica():
    chat = _leer("js", "chat.js")
    assert 'document.getElementById("chat-burbuja")' in chat, (
        "sin la guarda, montarChat() dos veces deja dos burbujas superpuestas"
    )


def test_talento_humano_tiene_atajo_a_su_bandeja():
    chat = _leer("js", "chat.js")
    assert "montarAtajoBandeja" in chat
    assert "mensajes.html" in chat, (
        "el rol rrhh/admin se quedaba sin chat visible de ninguna forma"
    )

    navegacion = _leer("js", "navegacion.js")
    assert 'href: "mensajes.html"' in navegacion, "la bandeja no está en el menú"


def test_la_bandeja_esta_en_el_modulo_de_talento_humano():
    """Y no en el de administrador: quien atiende es Talento Humano."""
    navegacion = _leer("js", "navegacion.js")
    bloque = navegacion.split('id: "rrhh"')[1].split('id: "informes"')[0]
    assert "mensajes.html" in bloque
