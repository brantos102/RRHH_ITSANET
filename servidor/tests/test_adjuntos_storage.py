"""Adjuntos en el disco del servidor.

Con Supabase los certificados iban a un bucket privado. En el servidor
corporativo van a una carpeta, y una carpeta tiene riesgos que un bucket no
tenía: el nombre que elige quien sube el archivo puede leerse como ruta, y
un corte de luz a mitad de escritura puede dejar un archivo cortado. Estas
pruebas fijan que ninguna de las dos cosas pase.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import storage
from app.config import get_settings


@pytest.fixture
def carpeta(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("ADJUNTOS_DIR", str(tmp_path / "adjuntos"))
    get_settings.cache_clear()
    yield tmp_path / "adjuntos"
    get_settings.cache_clear()


# ------------------------------------------------------- nombre del archivo
@pytest.mark.parametrize("nombre", [
    "../../etc/passwd",
    "..\\..\\Windows\\win.ini",
    "/etc/shadow",
    "certificado/../../../fuera.pdf",
])
def test_el_nombre_no_puede_salir_de_la_carpeta(nombre):
    limpio = storage.nombre_seguro(nombre)
    assert "/" not in limpio and "\\" not in limpio and ".." not in limpio


def test_un_nombre_con_tildes_y_espacios_queda_legible():
    assert storage.nombre_seguro("Certificado médico (1).pdf") == "Certificado_medico_1_.pdf"


def test_un_nombre_vacio_o_de_solo_puntos_tiene_nombre():
    assert storage.nombre_seguro("") == "archivo"
    assert storage.nombre_seguro("...") == "archivo"


def test_un_nombre_largo_conserva_la_extension():
    assert storage.nombre_seguro("a" * 200 + ".pdf").endswith(".pdf")


# ---------------------------------------------------------------- la ruta
@pytest.mark.parametrize("ruta", [
    "../fuera.pdf",
    "usuario/../../fuera.pdf",
    "/etc/passwd",
    "",
    ".",
])
def test_ninguna_ruta_se_resuelve_fuera_de_la_carpeta(carpeta, ruta):
    """Aunque el nombre ya venga limpio, la ruta se comprueba otra vez: la
    que se lee sale de la base, y una fila trasladada o editada a mano no
    pasó por nombre_seguro."""
    with pytest.raises(HTTPException) as exc:
        storage.ruta_absoluta(ruta)
    assert exc.value.status_code == 400


def test_un_enlace_simbolico_no_saca_de_la_carpeta(carpeta, tmp_path):
    (carpeta / "u").mkdir(parents=True)
    (tmp_path / "secreto.txt").write_text("no")
    (carpeta / "u" / "atajo").symlink_to(tmp_path / "secreto.txt")
    with pytest.raises(HTTPException):
        storage.ruta_absoluta("u/atajo")


# --------------------------------------------------------- guardar y leer
async def test_guarda_y_lee_el_mismo_contenido(carpeta):
    ruta = "usuario/solicitud/abc-certificado.pdf"
    contenido = b"%PDF-1.4 contenido de prueba"
    assert await storage.subir_adjunto(ruta, contenido, "application/pdf") == ruta
    assert await storage.leer_adjunto(ruta) == contenido
    assert (carpeta / ruta).read_bytes() == contenido


async def test_el_archivo_no_queda_legible_para_otros_usuarios_del_servidor(carpeta):
    ruta = "u/s/a.pdf"
    await storage.subir_adjunto(ruta, b"x", "application/pdf")
    assert os.stat(carpeta / ruta).st_mode & 0o007 == 0


async def test_no_quedan_temporales_despues_de_guardar(carpeta):
    await storage.subir_adjunto("u/s/a.pdf", b"x", "application/pdf")
    assert [p.name for p in (carpeta / "u" / "s").iterdir()] == ["a.pdf"]


async def test_un_fallo_a_mitad_no_deja_un_archivo_cortado(carpeta, monkeypatch):
    """Se escribe en un temporal y se renombra al final: si algo falla antes
    del renombre, el archivo definitivo no existe —ni entero ni a medias—."""
    def falla(*_):
        raise OSError("disco lleno")
    monkeypatch.setattr(storage.os, "replace", falla)
    with pytest.raises(HTTPException) as exc:
        await storage.subir_adjunto("u/s/a.pdf", b"x" * 1000, "application/pdf")
    assert exc.value.status_code == 503
    assert not (carpeta / "u" / "s" / "a.pdf").exists()
    assert list((carpeta / "u" / "s").iterdir()) == []


async def test_el_colaborador_nunca_ve_el_detalle_tecnico(carpeta, monkeypatch):
    """Quien adjunta un certificado no puede arreglar una carpeta: el mensaje
    de la pantalla no nombra rutas ni permisos. El detalle va al registro."""
    def falla(*_):
        raise PermissionError(13, "Permission denied", "/var/lib/rrhh/adjuntos/u")
    monkeypatch.setattr(storage, "_escribir", falla)
    with pytest.raises(HTTPException) as exc:
        await storage.subir_adjunto("u/s/a.pdf", b"x", "application/pdf")
    mensaje = exc.value.detail["mensaje"]
    assert "/var" not in mensaje and "ermission" not in mensaje and "ADJUNTOS" not in mensaje


async def test_un_adjunto_que_no_esta_devuelve_none(carpeta):
    assert await storage.leer_adjunto("u/s/no-existe.pdf") is None
