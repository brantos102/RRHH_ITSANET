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
GUION = RAIZ / "scripts" / "_puerto.py"


def _cargar():
    sys.path.insert(0, str(RAIZ / "scripts"))
    especificacion = importlib.util.spec_from_file_location("puerto_local", GUION)
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


puertos = _cargar()


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
def _con(tmp_path, base: str, local: str | None = None):
    (tmp_path / "frontend").mkdir(exist_ok=True)
    (tmp_path / "frontend" / "config.js").write_text(base, encoding="utf-8")
    if local is not None:
        (tmp_path / "frontend" / "config.local.js").write_text(local, encoding="utf-8")
    return tmp_path


def test_se_lee_el_puerto_de_la_configuracion(tmp_path):
    raiz = _con(tmp_path, "window.RRHH_CONFIG = { API: '', PUERTO_API: 8000 };")
    assert puertos.de_la_interfaz(raiz) == 8000


def test_los_ajustes_locales_ganan(tmp_path):
    raiz = _con(tmp_path, "window.RRHH_CONFIG = { PUERTO_API: 8000 };",
                "Object.assign(window.RRHH_CONFIG, { PUERTO_API: 3000 });")
    assert puertos.de_la_interfaz(raiz) == 3000


def test_una_linea_comentada_no_cuenta(tmp_path):
    """El archivo de ejemplo trae todo comentado: copiarlo no debe fijar nada."""
    raiz = _con(tmp_path, "window.RRHH_CONFIG = { PUERTO_API: 8000 };",
                "Object.assign(window.RRHH_CONFIG, {\n  // PUERTO_API: 3000,\n});")
    assert puertos.de_la_interfaz(raiz) == 8000


def test_sin_configuracion_se_supone_el_8000(tmp_path):
    (tmp_path / "frontend").mkdir()
    assert puertos.de_la_interfaz(tmp_path) == 8000


# ------------------------- los dos puertos no pueden discrepar
def test_el_backend_arranca_donde_la_interfaz_lo_busca():
    """Es la discrepancia que cuesta una tarde: la pantalla dice «No se pudo
    conectar con el servidor» y el registro del backend está vacío, porque
    la petición nunca llegó a una ruta. El síntoma apunta al correo, al
    cortafuegos o a la base, que no tienen nada que ver."""
    fuente = (RAIZ / "scripts" / "servidor.py").read_text(encoding="utf-8")
    assert "_puerto.de_la_interfaz()" in fuente, "servidor.py debe leer el puerto de la interfaz"
    assert 'default=8000' not in fuente, "ya no debe suponer el 8000"


def test_los_guiones_leen_el_puerto_del_mismo_sitio():
    """Un segundo lugar donde esté el puerto es un segundo lugar donde se
    puede quedar desactualizado."""
    for guion in ("servidor.py", "compartir.py"):
        fuente = (RAIZ / "scripts" / guion).read_text(encoding="utf-8")
        assert "import _puerto" in fuente, guion
        assert "_puerto.de_la_interfaz()" in fuente, guion


def test_el_servidor_de_la_interfaz_no_devuelve_404_sin_ajustes_locales():
    """Un 404 rojo en la consola de cada pantalla parece un error y no lo es."""
    fuente = (RAIZ / "scripts" / "frontend.py").read_text(encoding="utf-8")
    assert "config.local.js" in fuente
    assert "send_response(200)" in fuente


def test_el_puerto_ya_no_esta_fijado_a_mano_en_el_cliente():
    """`api.js` es código del repositorio: el puerto de una máquina no va ahí."""
    fuente = (FRONTEND / "js" / "api.js").read_text(encoding="utf-8")
    assert "CFG.PUERTO_API" in fuente, "el puerto debe salir de la configuración"
