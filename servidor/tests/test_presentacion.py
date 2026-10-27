"""La demostración que se presenta en Talento Humano.

Dos cosas tienen que seguir siendo ciertas de este archivo, y las dos se
rompen sin que nadie lo note al editarlo:

  1. **No contiene datos de ninguna persona.** Es un documento que circula,
     se proyecta en una sala y se reenvía por correo. Una sola cédula o un
     solo nombre de la planilla lo convierte en un tratamiento de datos
     personales sin finalidad declarada (LOPDP, Art. 10).
  2. **Se abre sin internet.** Se presenta en una sala de reuniones; una
     presentación que depende de la red falla justo ahí.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ARCHIVO = Path(__file__).resolve().parents[2] / "presentacion" / "demo_sistema_rrhh.html"


@pytest.fixture(scope="module")
def html() -> str:
    assert ARCHIVO.exists(), f"falta {ARCHIVO}"
    return ARCHIVO.read_text(encoding="utf-8")


# ------------------------------------------------------- protección de datos
def test_no_lleva_ninguna_cedula(html):
    """Diez dígitos seguidos son una cédula ecuatoriana."""
    # Se excluye lo que va dentro del logo incrustado, que es base64.
    sin_base64 = re.sub(r"data:image/[^\"']+", "", html)
    sospechosas = re.findall(r"(?<!\d)\d{10}(?!\d)", sin_base64)
    assert not sospechosas, f"parecen cédulas: {sospechosas[:5]}"


def test_no_nombra_a_nadie_de_la_planilla(html):
    """Los apellidos que aparecieron en los hallazgos no van en un documento
    que se reenvía: el hallazgo se cuenta por el número, no por la persona."""
    for apellido in ("Gonzalez", "González", "Aguirre", "Sanchez", "Sánchez",
                     "Cedeño", "Vera Rosales", "Soledispa", "Abad Flores",
                     "Vanegas", "Quiroz", "Tonato", "Hernandez Oñate"):
        assert apellido not in html, f"aparece «{apellido}»"


def test_no_lleva_correos_de_personas(html):
    correos = re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", html)
    assert not correos, f"direcciones encontradas: {correos[:5]}"


def test_lo_dice_en_el_propio_documento(html):
    assert "No contiene datos de ninguna persona" in html


# --------------------------------------------------------- se abre sin red
def test_no_pide_nada_por_la_red(html):
    """Ni CDN, ni fuentes, ni imágenes remotas."""
    remotos = re.findall(r'(?:src|href)\s*=\s*["\'](https?:)?//[^"\']+', html)
    assert not remotos, f"recursos remotos: {remotos[:5]}"


def test_el_logo_va_incrustado(html):
    assert "data:image/png;base64," in html


def test_es_un_solo_archivo(html):
    """Sin hojas de estilo ni guiones aparte: se envía por correo tal cual."""
    assert '<link rel="stylesheet"' not in html
    assert not re.search(r"<script[^>]+\ssrc\s*=", html)


# ------------------------------------------------------------- el contenido
def test_estan_las_doce_secciones(html):
    for ancla in ("que-es", "antes", "flujo", "calculo", "cotejo", "fines-semana",
                  "permisos", "garita", "temporal", "datos", "hallazgos", "estado"):
        assert f'id="{ancla}"' in html, f"falta la sección {ancla}"


def test_el_indice_no_lleva_a_ninguna_parte_rota(html):
    anclas = set(re.findall(r'<section id="([^"]+)"', html))
    enlaces = set(re.findall(r'<a href="#([^"]+)"', html))
    assert enlaces <= anclas, f"enlaces sin destino: {enlaces - anclas}"


def test_cita_los_articulos_que_sustentan_el_calculo(html):
    """Sin el artículo, una cifra es una afirmación; con él, un sustento."""
    for articulo in ("Art. 69", "Art. 71", "Art. 75", "Art. 76", "Art. 326"):
        assert articulo in html, f"no cita el {articulo}"


def test_explica_el_devengo_mensual(html):
    assert "1,25" in html, "falta la parte diaria del devengo"
    assert "meses completos" in html


def test_dice_que_las_vacaciones_no_gozadas_se_pagan(html):
    """Decir que se pierden sería falso y contrario al Art. 326 núm. 2."""
    assert "se pagan" in html
    assert "se pierden" not in html.replace("No se pierden", "").replace("no se pierden", "")
