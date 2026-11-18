"""El verificador no debe bloquear el arranque por una librería de pruebas.

`pypdf` solo se usa para leer un PDF dentro de una prueba. Estaba en el mismo
`requirements.txt` que lo demás y el verificador exigía la lista entera, así
que no tenerla impedía usar el sistema —que funciona perfectamente sin ella—.
Lo que hace falta para EJECUTAR y lo que solo hace falta para PROBAR se
separan por el encabezado «# desarrollo».
"""
from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
REQUISITOS = RAIZ / "backend" / "requirements.txt"
VERIFICADOR = RAIZ / "scripts" / "verificar.py"


def _paquetes() -> tuple[set[str], set[str]]:
    """Los de ejecución y los de pruebas, tal como los separa el verificador."""
    ejecucion: set[str] = set()
    pruebas: set[str] = set()
    destino = ejecucion
    for linea in REQUISITOS.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea.lower().startswith("# desarrollo"):
            destino = pruebas
            continue
        if "==" in linea and not linea.startswith("#"):
            destino.add(linea.split("==", 1)[0].split("[")[0])
    return ejecucion, pruebas


def test_las_de_pruebas_estan_separadas():
    ejecucion, pruebas = _paquetes()
    assert "pytest" in pruebas, "pytest no hace falta para usar el sistema"
    assert "pypdf" in pruebas, "pypdf solo lee el PDF dentro de una prueba"
    assert not (ejecucion & pruebas), "un paquete no puede estar en los dos grupos"


def test_lo_que_el_sistema_necesita_de_verdad_esta_del_lado_de_ejecucion():
    """Si alguna de estas cae al grupo equivocado, el arranque dejaría de avisar."""
    ejecucion, pruebas = _paquetes()
    for paquete in ("fastapi", "uvicorn", "psycopg", "pydantic",
                    "reportlab", "openpyxl", "qrcode", "pillow"):
        assert paquete in ejecucion, f"{paquete} hace falta para ejecutar"
        assert paquete not in pruebas


def test_el_verificador_respeta_esa_separacion():
    """Se comprueba en el código: es lo que decide si el arranque se bloquea."""
    codigo = VERIFICADOR.read_text(encoding="utf-8")
    assert "# desarrollo" in codigo, \
        "el verificador debe reconocer el encabezado que separa los dos grupos"
    # El bloqueo solo puede mirar la lista de ejecución.
    bloqueo = re.search(r"if faltantes:\s*\n\s*fallo\(", codigo)
    assert bloqueo, "debe seguir bloqueando cuando falta algo de ejecución"
    assert "faltan_pruebas and not faltantes" in codigo, \
        "las de pruebas se avisan, no bloquean"
