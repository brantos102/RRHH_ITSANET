"""El frontend no debe publicarse apuntando a un entorno de pruebas.

Esta prueba existe por un error concreto: durante el desarrollo se cambió
`frontend/config.js` a un puerto de pruebas y así quedó publicado. Quien
descargó el repositorio tenía la aplicación llamando a un puerto donde no
escuchaba nada, y la única pista era «No se pudo conectar con el servidor».
"""
from __future__ import annotations

import re
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "frontend" / "config.js"

PUERTOS_ESPERADOS = {"8000"}          # el único puerto de backend por omisión


def _valor(clave: str) -> str | None:
    texto = CONFIG.read_text(encoding="utf-8")
    encontrado = re.search(rf'{clave}\s*:\s*"([^"]*)"', texto)
    return encontrado.group(1) if encontrado else None


def test_el_config_no_fija_un_puerto_de_pruebas():
    api = _valor("API")
    assert api is not None, "config.js debe declarar API"
    if not api:
        return                        # vacío: se deduce del navegador, que es lo correcto

    puertos = set(re.findall(r":(\d{2,5})\b", api))
    assert puertos <= PUERTOS_ESPERADOS, (
        f"config.js apunta a {api}. Un puerto de pruebas publicado deja la "
        f"aplicación sin conectar en la máquina de cualquier otro."
    )


def test_el_puerto_del_backend_es_el_documentado():
    texto = CONFIG.read_text(encoding="utf-8")
    encontrado = re.search(r"PUERTO_API\s*:\s*(\d+)", texto)
    assert encontrado, "config.js debe declarar PUERTO_API"
    assert encontrado.group(1) in PUERTOS_ESPERADOS


def test_no_queda_rastro_del_cdn_de_tailwind():
    """Los estilos se compilan localmente: el CDN dejaba la app a merced de la red."""
    paginas = list((CONFIG.parent).glob("*.html"))
    assert paginas, "no se encontraron páginas"
    for pagina in paginas:
        texto = pagina.read_text(encoding="utf-8")
        assert "cdn.tailwindcss.com" not in texto, f"{pagina.name} sigue usando el CDN"
