"""El guion con el que se levanta el sistema para que lo prueben otros.

Lo que se comprueba aquí no es que arranque —eso no se puede probar sin
ocupar puertos—, sino lo que decide si la prueba sirve de algo: qué
direcciones se reparten, cuáles se rechazan y qué se avisa antes de
arrancar. Un enlace mal repartido se descubre con doce personas esperando.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
GUION = RAIZ / "scripts" / "compartir.py"


def _cargar():
    sys.path.insert(0, str(RAIZ / "scripts"))
    especificacion = importlib.util.spec_from_file_location("compartir", GUION)
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


compartir = _cargar()


@pytest.mark.parametrize(
    "ip",
    ["192.168.1.50", "192.168.0.1", "10.0.0.5", "10.255.255.254",
     "172.16.0.1", "172.31.255.254"],
)
def test_reconoce_las_direcciones_de_una_red_interna(ip):
    assert compartir.es_privada(ip), ip


@pytest.mark.parametrize(
    "ip",
    ["172.15.0.1",   # justo por debajo del rango privado
     "172.32.0.1",   # justo por encima
     "8.8.8.8",
     "200.93.1.10",  # una pública del Ecuador
     "no-es-una-ip", "192.168.1"],
)
def test_una_direccion_publica_no_se_reparte(ip):
    """Repartir una pública sería publicar el sistema sin querer."""
    assert not compartir.es_privada(ip), ip


def test_avisa_si_el_entorno_esta_en_produccion(tmp_path, monkeypatch):
    """En producción solo valen los orígenes de la lista, así que nadie entraría."""
    falso = tmp_path
    (falso / "backend").mkdir()
    (falso / "backend" / ".env").write_text("ENTORNO=produccion\n", encoding="utf-8")
    (falso / "frontend" / "vendor").mkdir(parents=True)
    (falso / "frontend" / "vendor" / "tailwind.css").write_text("", encoding="utf-8")
    monkeypatch.setattr(compartir, "RAIZ", falso)

    problemas = " ".join(compartir.comprobar_entorno())
    assert "produccion" in problemas.lower()
    assert "colaboradores" in problemas.lower()


def test_avisa_si_faltan_los_estilos_compilados(tmp_path, monkeypatch):
    """Sin el CSS la interfaz se ve en blanco y negro, y eso en una
    presentación parece que el sistema está roto."""
    falso = tmp_path
    (falso / "backend").mkdir()
    (falso / "backend" / ".env").write_text("ENTORNO=desarrollo\n", encoding="utf-8")
    monkeypatch.setattr(compartir, "RAIZ", falso)

    problemas = " ".join(compartir.comprobar_entorno())
    assert "tailwind.css" in problemas
    assert "npm" in problemas


def test_no_se_queja_cuando_todo_esta_en_su_sitio(tmp_path, monkeypatch):
    falso = tmp_path
    (falso / "backend").mkdir()
    (falso / "backend" / ".env").write_text("ENTORNO=desarrollo\n", encoding="utf-8")
    (falso / "frontend" / "vendor").mkdir(parents=True)
    (falso / "frontend" / "vendor" / "tailwind.css").write_text("x", encoding="utf-8")
    monkeypatch.setattr(compartir, "RAIZ", falso)

    assert compartir.comprobar_entorno() == []


def test_el_guion_fija_la_politica_de_bucle_de_windows():
    """Como todos los demás: psycopg no arranca sobre ProactorEventLoop."""
    assert "import _windows" in GUION.read_text(encoding="utf-8")
