"""Que ningún guion se caiga en Windows por el bucle de eventos.

psycopg en modo asíncrono no funciona sobre `ProactorEventLoop`, que es el
predeterminado de Python en Windows. Sin fijar la otra política, cualquier
guion que toque la base muere con un mensaje que no dice qué hacer:

    Psycopg cannot use the 'ProactorEventLoop' to run in async mode

Y muere tarde: primero lee el archivo, informa de que encontró 3.339 filas y
solo entonces se cae, de modo que parece un problema de los datos.

La protección estaba copiada a mano en dos de los seis guiones que la
necesitan. Los otros cuatro fallaban en Windows, cada uno el día que a
alguien le tocaba usarlo. Una protección que hay que acordarse de copiar es
una protección que falta, así que aquí se comprueba sola.

Esta prueba no necesita Windows para servir: lee el código, no lo ejecuta.
Es lo único que la hace útil, porque el equipo desarrolla en Linux y el
sistema se opera desde Windows.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

GUIONES = sorted((Path(__file__).resolve().parents[2] / "scripts").glob("*.py"))

# Lo que delata que un guion habla con la base y abre su propio bucle.
SENALES_BD = ("from app.db", "import app.db", "obtener_uno", "obtener_todos")


def _fuente(guion: Path) -> str:
    return guion.read_text(encoding="utf-8")


def _necesita_guarda(guion: Path) -> bool:
    fuente = _fuente(guion)
    return "asyncio.run(" in fuente and any(s in fuente for s in SENALES_BD)


def _importa_la_guarda(guion: Path) -> int | None:
    """La línea donde se importa «_windows», o nada.

    Por el árbol de sintaxis y no buscando el texto: una línea comentada
    —«# import _windows»— contiene la misma cadena y daría la prueba por
    superada justo cuando la protección ya no está.
    """
    for nodo in ast.walk(ast.parse(_fuente(guion))):
        if isinstance(nodo, ast.Import):
            for alias in nodo.names:
                if alias.name == "_windows":
                    return nodo.lineno
    return None


@pytest.mark.parametrize("guion", [g for g in GUIONES if _necesita_guarda(g)],
                         ids=lambda g: g.name)
def test_el_guion_fija_la_politica_de_windows(guion):
    assert _importa_la_guarda(guion) is not None, (
        f"{guion.name} abre un bucle de eventos y toca la base, pero no importa "
        "«_windows». En Windows morirá con «Psycopg cannot use the "
        "'ProactorEventLoop'» después de haber hecho medio trabajo. "
        "Añada, junto a los demás sys.path:\n"
        "    sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
        "    import _windows  # noqa: F401,E402")


@pytest.mark.parametrize("guion", [g for g in GUIONES if _necesita_guarda(g)],
                         ids=lambda g: g.name)
def test_la_politica_se_fija_antes_de_usar_la_base(guion):
    """El orden importa: después de crear un bucle ya no sirve de nada."""
    linea_guarda = _importa_la_guarda(guion)
    linea_bd = None
    for nodo in ast.walk(ast.parse(_fuente(guion))):
        if isinstance(nodo, ast.ImportFrom) and (nodo.module or "").startswith("app."):
            if linea_bd is None or nodo.lineno < linea_bd:
                linea_bd = nodo.lineno

    assert linea_guarda is not None, f"{guion.name} no importa «_windows»"
    if linea_bd is not None:
        assert linea_guarda < linea_bd, (
            f"{guion.name} importa «app.*» en la línea {linea_bd}, antes de fijar "
            f"la política en la {linea_guarda}. Tiene que ir primero.")


def test_hay_guiones_que_la_necesitan():
    """Si esta prueba deja de encontrar guiones, las de arriba no prueban nada."""
    cuantos = [g.name for g in GUIONES if _necesita_guarda(g)]
    assert len(cuantos) >= 4, f"solo se detectaron {cuantos}"


def test_el_modulo_compartido_existe_y_solo_hace_eso():
    """Sin funciones que haya que acordarse de llamar: hace su trabajo al
    importarse, que es el único momento en que sirve."""
    modulo = Path(__file__).resolve().parents[2] / "scripts" / "_windows.py"
    assert modulo.exists()
    fuente = modulo.read_text(encoding="utf-8")
    assert "WindowsSelectorEventLoopPolicy" in fuente
    assert 'sys.platform == "win32"' in fuente, (
        "la política se fijaría también fuera de Windows")
