"""Lectura del registro de vacaciones para la carga, con un libro inventado."""
from __future__ import annotations

import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(RAIZ / "mysql"), str(RAIZ / "servidor")]

import cargar_registro as cr  # noqa: E402
from app.cedula import es_cedula_valida  # noqa: E402


def _cedulas(n: int, desde: int = 1759900000) -> list[str]:
    salida = []
    while len(salida) < n:
        desde += 1
        if es_cedula_valida(str(desde).zfill(10)):
            salida.append(str(desde).zfill(10))
    return salida


@pytest.fixture
def libro(tmp_path) -> tuple[Path, list[str]]:
    openpyxl = pytest.importorskip("openpyxl")
    c = _cedulas(5)
    # Una cédula de provincia 09 que Excel guardó como número, sin el cero.
    con_cero = next(x for x in (str(n).zfill(10) for n in range(900000001, 900009999))
                    if es_cedula_valida(x))
    wb = openpyxl.Workbook()
    reg = wb.active
    reg.title = "REGISTRO DE VACACIONE"
    reg.append(["NOMBRE", "ESTADO", "FECHA INGRESO", "FECHA ACTUAL", "CIUDAD", "BODEGA", "", "", "", "",
                "", "inicio", "fin", "", "DISPONIBLE"])
    corte = dt.datetime(2026, 10, 26)
    filas = [
        ("PEREZ ANA", "ACTIVO", "GYE", 20),          # dos filas: vale la última
        ("PEREZ ANA", "ACTIVO", "GYE", 12.5),
        ("LOPEZ LUIS", "ACTIVO", "UIO", -1),         # adelanto: negativo
        ("CERO PROVINCIA", "ACTIVO", "UIO", 3),
        ("SIN CEDULA", "ACTIVO", "UIO", 5),
        ("SE FUE", "PASIVO", "UIO", 0),
        ("DOBLE UNO", "ACTIVO", "UIO", 1),           # misma cédula que DOBLE DOS
    ]
    for nombre, estado, ciudad, disp in filas:
        reg.append([nombre, estado, dt.datetime(2020, 1, 15), corte, ciudad, "B1", None, None, None, None,
                    None, None, None, None, disp])
    maestro = wb.create_sheet("FECHA DE INGRESO")
    maestro.append(["NOMBRE", "FECHA DE INGRESO", "CIUDAD ", "BODEGA ", "ESTADO", "CECO"])
    maestro.append(["PEREZ ANA", dt.datetime(2019, 3, 1), "GYE", "B9", "ACTIVO", "CC-1"])
    tot = wb.create_sheet("totales vacaciones")
    tot.append(["cedula", "nombres"])
    tot.append([int(c[0]), "Pérez  Ana"])                      # tildes y espacios no importan
    tot.append([int(c[1]), "LOPEZ LUIS"])
    tot.append([int(con_cero), "CERO PROVINCIA"])              # 9 dígitos en la celda
    tot.append([int(c[2]), "SE FUE"])
    tot.append([int(c[3]), "DOBLE UNO"])
    tot.append([int(c[3]), "DOBLE DOS"])
    ruta = tmp_path / "registro.xlsx"
    wb.save(ruta)
    return ruta, [*c, con_cero]


def test_solo_entran_los_activos_identificados(libro):
    ruta, c = libro
    personas, fuera, resumen = cr.leer(ruta)
    por_nombre = {p["nombre"]: p for p in personas}
    assert set(por_nombre) == {"PEREZ ANA", "LOPEZ LUIS", "CERO PROVINCIA"}
    motivos = {f["nombre"]: f["motivo"] for f in fuera}
    assert "sin cédula" in motivos["SIN CEDULA"]
    assert "PASIVO" in motivos["SE FUE"]
    assert "otro nombre" in motivos["DOBLE UNO"]


def test_la_ultima_fila_trae_el_saldo_y_el_maestro_manda(libro):
    ruta, c = libro
    ana = next(p for p in cr.leer(ruta)[0] if p["nombre"] == "PEREZ ANA")
    assert ana["disponible"] == Decimal("12.50")
    assert ana["ingreso"] == dt.date(2019, 3, 1)       # de FECHA DE INGRESO, no del registro
    assert ana["ceco"] == "CC-1" and ana["bodega"] == "B9"
    assert ana["cedula"] == c[0]
    assert ana["corte"] == dt.date(2026, 10, 26)


def test_el_codigo_de_sede_se_traduce_a_ciudad(libro):
    """Con el código, la región salía sierra para todos y Guayaquil iba a Quito."""
    ruta, _ = libro
    ciudades = {p["nombre"]: p["ciudad"] for p in cr.leer(ruta)[0]}
    assert ciudades["PEREZ ANA"] == "Guayaquil"
    assert ciudades["LOPEZ LUIS"] == "Quito"


def test_se_repone_el_cero_que_excel_se_come(libro):
    ruta, c = libro
    cero = next(p for p in cr.leer(ruta)[0] if p["nombre"] == "CERO PROVINCIA")
    assert cero["cedula"] == c[-1] and cero["cedula"].startswith("0")


def test_un_saldo_negativo_se_conserva(libro):
    ruta, _ = libro
    luis = next(p for p in cr.leer(ruta)[0] if p["nombre"] == "LOPEZ LUIS")
    assert luis["disponible"] == Decimal("-1.00")
