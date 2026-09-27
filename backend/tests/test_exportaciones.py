"""Descargas oficiales: CSV, Excel y PDF, y el cotejo de la carga.

Lo que se exporta son datos personales saliendo del sistema, así que se
comprueban tres cosas: que el archivo sea del formato que dice ser, que lleve
dentro el filtro con el que se obtuvo —sin eso no sustenta nada— y que el
alcance del rol se respete también al descargar.
"""
from __future__ import annotations

import io
import zipfile
from datetime import timedelta

import pytest

from app.db import obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, lunes_sin_feriados,
                                      rrhh_auth)

FIRMAS = {
    "csv": b"\xef\xbb\xbf",          # BOM: Excel en Windows lo necesita
    "xlsx": b"PK\x03\x04",           # es un zip
    "pdf": b"%PDF",
}


@pytest.mark.parametrize("formato", ["csv", "xlsx", "pdf"])
async def test_el_informe_se_descarga_en_los_tres_formatos(cliente, rrhh_auth, formato):
    r = await cliente.get(f"/informes/solicitudes.{formato}", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    assert r.content.startswith(FIRMAS[formato]), f"{formato}: no parece un {formato}"
    assert "attachment" in r.headers["content-disposition"]
    assert f".{formato}" in r.headers["content-disposition"]


@pytest.mark.parametrize("formato", ["csv", "xlsx", "pdf"])
async def test_el_archivo_dice_con_que_filtro_se_hizo(cliente, rrhh_auth, formato):
    """Una tabla sin contexto no se puede defender tres meses después."""
    r = await cliente.get(
        f"/informes/solicitudes.{formato}?estado=aprobado&departamento=Operaciones",
        headers=rrhh_auth)
    assert r.status_code == 200, r.text

    texto = _texto_del_archivo(r.content, formato)
    assert "aprobado" in texto, f"{formato}: falta el estado filtrado"
    assert "Operaciones" in texto, f"{formato}: falta el departamento filtrado"


def _texto_del_archivo(contenido: bytes, formato: str) -> str:
    """Saca el texto legible de cualquiera de los tres formatos."""
    if formato == "csv":
        return contenido.decode("utf-8")
    if formato == "xlsx":
        # Un .xlsx es un zip; las cadenas viven en este XML.
        with zipfile.ZipFile(io.BytesIO(contenido)) as z:
            nombres = [n for n in z.namelist() if "sharedStrings" in n or "sheet1" in n]
            return " ".join(z.read(n).decode("utf-8", "replace") for n in nombres)
    # El PDF va comprimido: se lee con un lector de verdad. Rascar las
    # secuencias con expresiones regulares devolvía cadenas vacías, y la
    # prueba habría pasado sin comprobar nada.
    from pypdf import PdfReader
    lector = PdfReader(io.BytesIO(contenido))
    return " ".join(pagina.extract_text() or "" for pagina in lector.pages)


async def test_el_pdf_lleva_el_aviso_de_proteccion_de_datos(cliente, rrhh_auth):
    """Sale del sistema con nombres y cédulas: debe decirlo en el documento."""
    r = await cliente.get("/informes/solicitudes.pdf", headers=rrhh_auth)
    texto = _texto_del_archivo(r.content, "pdf")
    assert "Protecci" in texto and "Datos Personales" in texto


async def test_un_jefe_solo_descarga_a_su_equipo(cliente, auth, jefe_auth, empleado):
    """El alcance del rol vale también al descargar, no solo en pantalla."""
    lunes = await lunes_sin_feriados()
    creada = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Ocho dias del colaborador del jefe", "firmar": False})
    assert creada.status_code == 201, creada.text

    r = await cliente.get("/informes/solicitudes.csv", headers=jefe_auth)
    assert r.status_code == 200
    texto = r.content.decode("utf-8")
    assert CEDULA_PRUEBA in texto, "el jefe debe ver a su propio colaborador"


async def test_el_navegador_puede_leer_el_nombre_del_archivo(cliente, rrhh_auth):
    """Sin exponer la cabecera, la descarga pierde el nombre que pone el servidor.

    El frontend y la API están en orígenes distintos, y el navegador oculta a
    JavaScript toda cabecera que no se exponga a propósito. El archivo bajaba
    como «cotejo.xlsx» —el respaldo del código— en vez del nombre real con su
    fecha, y el fallo pasaba inadvertido justo por existir ese respaldo.
    """
    from app.main import app

    expuestas: list[str] = []
    for capa in app.user_middleware:
        valores = getattr(capa, "kwargs", {}).get("expose_headers")
        if valores:
            expuestas = list(valores)
    assert "Content-Disposition" in expuestas, (
        "CORS debe exponer Content-Disposition o las descargas pierden su nombre")


async def test_un_empleado_no_descarga_informes(cliente, auth):
    for formato in ("csv", "xlsx", "pdf"):
        r = await cliente.get(f"/informes/solicitudes.{formato}", headers=auth)
        assert r.status_code == 403, f"{formato}: {r.status_code}"


async def test_un_formato_inventado_se_rechaza(cliente, rrhh_auth):
    r = await cliente.get("/informes/solicitudes.exe", headers=rrhh_auth)
    assert r.status_code == 422


# ------------------------------------------------------- cotejo de la carga
@pytest.mark.parametrize("formato", ["csv", "xlsx", "pdf"])
async def test_el_cotejo_se_descarga(cliente, rrhh_auth, empleado, formato):
    r = await cliente.get(f"/admin/cotejo.{formato}", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    assert r.content.startswith(FIRMAS[formato])


async def test_el_cotejo_trae_lo_que_hace_falta_para_comparar(cliente, rrhh_auth, empleado):
    """Sin el saldo desglosado no se puede saber si la carga quedó bien."""
    r = await cliente.get("/admin/cotejo.csv", headers=rrhh_auth)
    texto = r.content.decode("utf-8")
    for columna in ("Cédula", "Fecha de ingreso", "Jefe inmediato",
                    "Saldo en el sistema", "Días ganados", "Días del año en curso"):
        assert columna in texto, f"falta la columna «{columna}»"
    assert CEDULA_PRUEBA in texto


async def test_el_cotejo_acota_a_lo_que_hay_que_revisar(cliente, rrhh_auth, empleado):
    """Con trescientas personas, mirar solo lo incompleto es la diferencia."""
    todas = await cliente.get("/admin/cotejo.csv", headers=rrhh_auth)
    revisar = await cliente.get("/admin/cotejo.csv?solo_revisar=true", headers=rrhh_auth)
    assert todas.status_code == revisar.status_code == 200

    filas_todas = todas.content.decode("utf-8").count("\n")
    filas_revisar = revisar.content.decode("utf-8").count("\n")
    assert filas_revisar <= filas_todas
    assert "Solo las que requieren revisión" in revisar.content.decode("utf-8")


async def test_un_empleado_no_puede_bajar_la_planilla(cliente, auth):
    """Es la nómina entera: nombres, cédulas y saldos de todo el mundo."""
    r = await cliente.get("/admin/cotejo.xlsx", headers=auth)
    assert r.status_code == 403
