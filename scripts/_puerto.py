"""El puerto del backend, en un solo lugar: el que la interfaz va a llamar.

Existe porque la discrepancia entre los dos puertos cuesta una tarde y el
síntoma apunta a cualquier otra parte. Si el backend atiende en el 3000 y la
interfaz llama al 8000, la pantalla de acceso dice «No se pudo conectar con
el servidor» y el registro del backend está vacío: la petición nunca llegó a
una ruta, así que no hay nada que leer. Buscando el fallo se termina
revisando el correo, el cortafuegos o la base de datos —ninguno de los tres
tiene nada que ver—.

La interfaz es quien manda, porque es la que el navegador obedece. El
backend arranca donde ella va a buscarlo, y así no pueden discrepar.

`config.local.js` —que no se versiona— pisa a `config.js`, exactamente como
en el navegador.
"""
from __future__ import annotations

import re
from pathlib import Path

PREDETERMINADO = 8000
RAIZ = Path(__file__).resolve().parents[1]


def de_la_interfaz(raiz: Path | None = None) -> int:
    """El puerto que la interfaz tiene configurado para el backend."""
    base = (raiz or RAIZ) / "frontend"
    puerto = PREDETERMINADO
    for nombre in ("config.js", "config.local.js"):
        archivo = base / nombre
        if not archivo.exists():
            continue
        texto = archivo.read_text(encoding="utf-8", errors="replace")
        # Sin las líneas comentadas: el archivo de ejemplo las trae todas, y
        # copiarlo tal cual no debe cambiarle el puerto a nadie.
        util = "\n".join(l for l in texto.splitlines() if not l.strip().startswith("//"))
        encontrado = re.search(r"PUERTO_API\s*:\s*(\d{2,5})", util)
        if encontrado:
            puerto = int(encontrado.group(1))
    return puerto


def donde_lo_busca_el_navegador(puerto: int) -> str:
    """Una línea para decirle a quien arranca dónde va a quedar el backend."""
    cual = "config.local.js" if (RAIZ / "frontend" / "config.local.js").exists() else "config.js"
    return f"La interfaz lo busca en el puerto {puerto} (según frontend/{cual})."
