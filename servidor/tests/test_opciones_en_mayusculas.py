"""Que las mayúsculas de un indicador no detengan a nadie.

El sistema se opera desde PowerShell, donde nada distingue mayúsculas: los
comandos, las rutas y los nombres de archivo dan igual como se escriban.
`argparse` sí distingue, así que «--APLICAR» sale rechazado con un mensaje
que no explica por qué:

    error: unrecognized arguments: --APLICAR

Quien lo lee revisa la ortografía de la palabra, que está bien.

Lo que estas pruebas cuidan no es la comodidad, sino los dos límites: que
solo se toquen los indicadores y nunca los valores, y que no se inventen
indicadores que el guion no declara.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "scripts"))

import _cli  # noqa: E402


@pytest.fixture
def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="prueba")
    p.add_argument("archivo")
    p.add_argument("--aplicar", action="store_true")
    p.add_argument("--informe", default=None)
    return p


def test_el_indicador_en_mayusculas_se_entiende(parser):
    """El caso exacto que detuvo la carga del historial."""
    a = _cli.analizar(parser, ["HOJA.xlsx", "--APLICAR"])
    assert a.aplicar is True
    assert a.archivo == "HOJA.xlsx"


def test_y_con_mayusculas_a_medias(parser):
    assert _cli.analizar(parser, ["h.xlsx", "--Aplicar"]).aplicar is True


def test_tambien_cuando_lleva_valor_pegado(parser):
    a = _cli.analizar(parser, ["h.xlsx", "--INFORME=Cotejo.CSV"])
    assert a.informe == "Cotejo.CSV", "se corrigió también el valor"


def test_el_valor_no_se_toca_nunca(parser):
    """Una ruta puede depender de sus mayúsculas; en Linux depende siempre.

    Pasarla a minúsculas convertiría una molestia en un archivo que no
    existe, que es bastante peor.
    """
    a = _cli.analizar(parser, ["C:/Users/IMORETA/REGISTRO_DE_VACACIONE.xlsx",
                               "--INFORME", "Cotejo_2026.CSV"])
    assert a.archivo == "C:/Users/IMORETA/REGISTRO_DE_VACACIONE.xlsx"
    assert a.informe == "Cotejo_2026.CSV"


def test_un_indicador_que_no_existe_sigue_siendo_un_error(parser):
    """No se adivina: «--Aplicarr» está mal escrito y debe decirlo."""
    with pytest.raises(SystemExit):
        _cli.analizar(parser, ["h.xlsx", "--APLICARR"])


def test_despues_de_dos_guiones_todo_es_valor(parser):
    """Es la única forma de pasar un archivo que empiece por guion."""
    a = _cli.analizar(parser, ["--", "--RARO.xlsx"])
    assert a.archivo == "--RARO.xlsx"


def test_lo_que_ya_venia_bien_no_cambia(parser):
    a = _cli.analizar(parser, ["h.xlsx", "--aplicar", "--informe", "c.csv"])
    assert (a.archivo, a.aplicar, a.informe) == ("h.xlsx", True, "c.csv")


# ------------------------------------------------- y que los guiones lo usen

GUIONES = sorted((RAIZ / "scripts").glob("*.py"))


def _tiene_indicadores(guion: Path) -> bool:
    return "add_argument(\"--" in guion.read_text(encoding="utf-8")


@pytest.mark.parametrize("guion", [g for g in GUIONES if _tiene_indicadores(g)],
                         ids=lambda g: g.name)
def test_el_guion_analiza_sus_argumentos_por_el_ayudante(guion):
    fuente = guion.read_text(encoding="utf-8")
    assert "_cli.analizar(" in fuente, (
        f"{guion.name} tiene indicadores y llama a parse_args() directamente. "
        "En PowerShell, escribirlos en mayúsculas lo detendrá con un mensaje "
        "que no explica nada. Use _cli.analizar(p) en su lugar.")
    assert ".parse_args()" not in fuente, (
        f"{guion.name} conserva una llamada a parse_args() sin pasar por el "
        "ayudante.")


def test_hay_guiones_con_indicadores():
    """Si dejara de encontrarlos, las pruebas de arriba no probarían nada."""
    cuantos = [g.name for g in GUIONES if _tiene_indicadores(g)]
    assert len(cuantos) >= 4, f"solo se detectaron {cuantos}"
