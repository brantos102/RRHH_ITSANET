"""Qué hoja se carga, y qué archivo.

La carga del historial se ejecuta una vez por instalación, a mano, y si toma
la pestaña equivocada no da error: da los datos de otra. Eso no se nota
nunca, así que el guion prefiere negarse antes que adivinar.

El archivo real de Talento Humano tiene dos pestañas parecidas —«REGISTRO DE
VACACIONE», la buena, y «registro de vacaciones», hoy vacía— y por eso el
nombre exacto manda sobre el parecido.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ / "scripts"))

import cargar_historial as ch  # noqa: E402

ENCABEZADO = ["NOMBRE", "ESTADO", "FECHA INGRESO", "FECHA ACTUAL", "CIUDAD",
              "BODEGA", "MESES", "AÑOS", "DIAS BASE", "DIAS ADICIONALES",
              "TOTAL", "inicio", "fin", "DIAS GOZADOS", "DISPONIBLE"]


def _libro(tmp_path: Path, hojas: dict[str, bool], nombre="hoja.xlsx") -> Path:
    """Un libro con las pestañas pedidas; con datos las marcadas como True."""
    openpyxl = pytest.importorskip("openpyxl")
    libro = openpyxl.Workbook()
    libro.remove(libro.active)
    for titulo, con_datos in hojas.items():
        h = libro.create_sheet(titulo)
        if con_datos:
            h.append(ENCABEZADO)
            fila = [None] * 15
            fila[0], fila[1] = "PEREZ PEREZ JUAN", "ACTIVO"
            fila[11], fila[12] = dt.datetime(2024, 3, 4), dt.datetime(2024, 3, 8)
            fila[13] = 5
            h.append(fila)
    ruta = tmp_path / nombre
    libro.save(ruta)
    return ruta


def test_elige_la_pestana_por_su_nombre_exacto(tmp_path):
    """La buena y la parecida conviven en el archivo real de la empresa."""
    ruta = _libro(tmp_path, {"registro de vacaciones": False,
                             "REGISTRO DE VACACIONE": True})
    eventos, _ = ch.leer_hoja(ruta)
    assert len(eventos) == 1, "cargó la pestaña vacía en vez de la buena"


def test_acepta_que_alguien_corrija_la_errata_del_nombre(tmp_path):
    """«REGISTRO DE VACACIONE» es una errata y se va a corregir algún día.

    Si ese día la carga dejara de funcionar, nadie ataría los dos hechos.
    """
    ruta = _libro(tmp_path, {"REGISTRO DE VACACIONES": True})
    eventos, _ = ch.leer_hoja(ruta)
    assert len(eventos) == 1


def test_con_dos_parecidas_y_ninguna_exacta_se_niega(tmp_path):
    """Entre dos que podrían ser, elegir es adivinar."""
    ruta = _libro(tmp_path, {"REGISTRO DE VACACIONES": True,
                             "Registro de Vacaciones 2025": True})
    with pytest.raises(SystemExit) as salida:
        ch.leer_hoja(ruta)
    assert salida.value.code == 2


def test_sin_ninguna_pestana_parecida_se_niega(tmp_path):
    ruta = _libro(tmp_path, {"CONECEL": True, "PASIVOS": True})
    with pytest.raises(SystemExit) as salida:
        ch.leer_hoja(ruta)
    assert salida.value.code == 2


def test_una_columna_movida_detiene_la_carga(tmp_path):
    """Cargar por posición sin comprobar el encabezado mete fechas en los días."""
    openpyxl = pytest.importorskip("openpyxl")
    libro = openpyxl.Workbook()
    libro.remove(libro.active)
    h = libro.create_sheet("REGISTRO DE VACACIONE")
    movido = list(ENCABEZADO)
    movido[11], movido[12] = "fin", "inicio"       # las dos, del revés
    h.append(movido)
    ruta = tmp_path / "movida.xlsx"
    libro.save(ruta)

    with pytest.raises(SystemExit) as salida:
        ch.leer_hoja(ruta)
    assert salida.value.code == 2


def test_encuentra_el_archivo_en_la_carpeta_de_al_lado(tmp_path, monkeypatch):
    """El guion vive en el repositorio y la hoja al lado, un nivel arriba.

    Quien se para en uno y nombra la otra recibía «No existe», que es cierto
    y no ayuda: la hoja está, a un paso de donde se buscó.
    """
    vecina = tmp_path / "al_lado"
    vecina.mkdir()
    real = _libro(vecina, {"REGISTRO DE VACACIONE": True},
                  nombre="REGISTRO_DE_VACACIONES.xlsx")

    monkeypatch.setattr(ch, "DONDE_BUSCAR", (tmp_path, vecina))
    assert ch.localizar(Path("REGISTRO_DE_VACACIONES.xlsx")) == real


def test_si_de_verdad_no_esta_lo_dice_y_se_detiene(tmp_path, monkeypatch):
    monkeypatch.setattr(ch, "DONDE_BUSCAR", (tmp_path,))
    with pytest.raises(SystemExit) as salida:
        ch.localizar(Path("NO_EXISTE.xlsx"))
    assert salida.value.code == 2
