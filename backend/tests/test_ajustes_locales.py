"""El puerto del backend, y por qué no debe vivir en un archivo del repositorio.

Esto nació de un `git pull` abortado:

    error: Your local changes to the following files would be overwritten by merge:
            frontend/js/api.js

El backend de esa máquina escuchaba en un puerto distinto del 8000, se
cambió a mano en `frontend/js/api.js` —que es código del repositorio— y a
partir de ahí cada actualización chocaba con ese cambio. Peor: si alguien
descarta el cambio para poder actualizar, la pantalla de acceso vuelve a
decir «No se pudo conectar con el servidor» y el síntoma no apunta a nada.

`config.local.js` resuelve las dos cosas: no se versiona, así que sobrevive
a cada pull, y pisa a `config.js` igual que en el navegador.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
FRONTEND = RAIZ / "frontend"
GUION = RAIZ / "scripts" / "compartir.py"


def _cargar():
    sys.path.insert(0, str(RAIZ / "scripts"))
    especificacion = importlib.util.spec_from_file_location("compartir_local", GUION)
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


compartir = _cargar()


# ------------------------------------------------- lo que carga el navegador
def test_todas_las_paginas_cargan_los_ajustes_locales():
    """Si una página se lo salta, ahí el puerto vuelve a estar mal y solo
    falla esa pantalla: el peor de los errores, el intermitente."""
    faltan = []
    for pagina in sorted(FRONTEND.glob("*.html")):
        texto = pagina.read_text(encoding="utf-8")
        if 'src="config.js"' in texto and 'src="config.local.js"' not in texto:
            faltan.append(pagina.name)
    assert not faltan, f"sin config.local.js: {faltan}"


def test_los_ajustes_locales_se_cargan_despues_de_la_configuracion_base():
    """El orden es lo que hace que uno pise al otro."""
    for pagina in sorted(FRONTEND.glob("*.html")):
        texto = pagina.read_text(encoding="utf-8")
        if 'src="config.local.js"' not in texto:
            continue
        assert texto.index('src="config.js"') < texto.index('src="config.local.js"'), pagina.name


def test_el_archivo_de_ejemplo_existe_y_no_fija_nada():
    """Copiarlo tal cual no debe cambiar el comportamiento de nadie."""
    ejemplo = FRONTEND / "config.local.js.ejemplo"
    assert ejemplo.exists()
    texto = ejemplo.read_text(encoding="utf-8")
    activas = [l for l in texto.splitlines()
               if "PUERTO_API" in l or ("API:" in l and "PUERTO" not in l)]
    assert activas, "el ejemplo debe mostrar qué se puede ajustar"
    for linea in activas:
        assert linea.strip().startswith("//"), f"viene fijado y debería estar comentado: {linea}"


def test_los_ajustes_locales_no_se_versionan():
    gitignore = (RAIZ / ".gitignore").read_text(encoding="utf-8")
    assert "frontend/config.local.js" in gitignore


def test_el_archivo_real_no_esta_en_el_repositorio():
    """Si alguien lo sube, le impone su puerto a todo el equipo."""
    import subprocess
    salida = subprocess.run(
        ["git", "ls-files", "frontend/config.local.js"],
        cwd=RAIZ, capture_output=True, text=True).stdout.strip()
    assert salida == "", "config.local.js quedó versionado"


# --------------------------------------------- lo que leen los guiones
def test_el_guion_lee_el_puerto_de_la_configuracion(tmp_path, monkeypatch):
    falso = tmp_path
    (falso / "frontend").mkdir()
    (falso / "frontend" / "config.js").write_text(
        "window.RRHH_CONFIG = { API: '', PUERTO_API: 8000 };", encoding="utf-8")
    monkeypatch.setattr(compartir, "RAIZ", falso)
    assert compartir.puerto_de_la_interfaz() == 8000


def test_los_ajustes_locales_ganan(tmp_path, monkeypatch):
    falso = tmp_path
    (falso / "frontend").mkdir()
    (falso / "frontend" / "config.js").write_text(
        "window.RRHH_CONFIG = { PUERTO_API: 8000 };", encoding="utf-8")
    (falso / "frontend" / "config.local.js").write_text(
        "Object.assign(window.RRHH_CONFIG, { PUERTO_API: 3000 });", encoding="utf-8")
    monkeypatch.setattr(compartir, "RAIZ", falso)
    assert compartir.puerto_de_la_interfaz() == 3000


def test_una_linea_comentada_no_cuenta(tmp_path, monkeypatch):
    """El archivo de ejemplo trae todo comentado: copiarlo no debe fijar nada."""
    falso = tmp_path
    (falso / "frontend").mkdir()
    (falso / "frontend" / "config.js").write_text(
        "window.RRHH_CONFIG = { PUERTO_API: 8000 };", encoding="utf-8")
    (falso / "frontend" / "config.local.js").write_text(
        "Object.assign(window.RRHH_CONFIG, {\n  // PUERTO_API: 3000,\n});", encoding="utf-8")
    monkeypatch.setattr(compartir, "RAIZ", falso)
    assert compartir.puerto_de_la_interfaz() == 8000


def test_sin_configuracion_se_supone_el_8000(tmp_path, monkeypatch):
    falso = tmp_path
    (falso / "frontend").mkdir()
    monkeypatch.setattr(compartir, "RAIZ", falso)
    assert compartir.puerto_de_la_interfaz() == 8000


def test_el_servidor_de_la_interfaz_no_devuelve_404_sin_ajustes_locales():
    """Un 404 rojo en la consola de cada pantalla parece un error y no lo es."""
    fuente = (RAIZ / "scripts" / "frontend.py").read_text(encoding="utf-8")
    assert "config.local.js" in fuente
    assert "send_response(200)" in fuente


def test_el_puerto_ya_no_esta_fijado_a_mano_en_el_cliente():
    """`api.js` es código del repositorio: el puerto de una máquina no va ahí."""
    fuente = (FRONTEND / "js" / "api.js").read_text(encoding="utf-8")
    assert "CFG.PUERTO_API" in fuente, "el puerto debe salir de la configuración"
