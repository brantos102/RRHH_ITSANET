"""Lector de registros. Pensado para Windows, donde no hay grep ni tail.

Uso habitual:

    python scripts\\ver_logs.py                      últimas 40 líneas
    python scripts\\ver_logs.py --errores            solo advertencias y errores
    python scripts\\ver_logs.py --referencia a1b2c3d4   el rastro de un caso
    python scripts\\ver_logs.py --buscar vacaciones  por texto
    python scripts\\ver_logs.py --seguir             en vivo, como tail -f

Cuando alguien reporta «me salió un error con la referencia a1b2c3d4», la
segunda forma devuelve todas las líneas de esa petición: qué ruta pidió, con
qué cédula y la traza completa si hubo excepción.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Su propia carpeta en la ruta de búsqueda, para los ayudantes compartidos.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _cli  # noqa: E402

CARPETA = Path(__file__).resolve().parents[1] / "backend" / "logs"
SISTEMA = CARPETA / "sistema.log"
ERRORES = CARPETA / "errores.log"


def archivos(solo_errores: bool) -> list[Path]:
    """El principal y sus rotados, del más viejo al más nuevo."""
    base = ERRORES if solo_errores else SISTEMA
    rotados = sorted(
        CARPETA.glob(base.name + ".*"),
        key=lambda p: int(p.suffix.lstrip(".") or 0),
        reverse=True,
    )
    return [p for p in [*rotados, base] if p.exists()]


def lineas(solo_errores: bool):
    for archivo in archivos(solo_errores):
        # errors="replace": un archivo rotado a medio escribir no debe
        # impedir leer el resto.
        with archivo.open("r", encoding="utf-8", errors="replace") as f:
            yield from f


def es_continuacion(linea: str) -> bool:
    """Las trazas de Python siguen a su línea de cabecera, indentadas."""
    return linea.startswith((" ", "\t", "Traceback")) or linea.startswith("  ")


def filtrar(criterio: str | None, solo_errores: bool) -> list[str]:
    """Devuelve las líneas que casan, arrastrando la traza que las sigue."""
    salida: list[str] = []
    arrastrando = False
    for linea in lineas(solo_errores):
        if criterio is None:
            salida.append(linea)
            continue
        if criterio.lower() in linea.lower():
            salida.append(linea)
            arrastrando = True
        elif arrastrando and es_continuacion(linea):
            # La traza no repite la referencia, pero es justo lo que se busca.
            salida.append(linea)
        else:
            arrastrando = False
    return salida


def seguir(solo_errores: bool) -> None:
    archivo = ERRORES if solo_errores else SISTEMA
    if not archivo.exists():
        print(f"Todavía no existe {archivo}. Arranque el backend primero.")
        return
    print(f"Siguiendo {archivo}. Ctrl+C para salir.\n")
    with archivo.open("r", encoding="utf-8", errors="replace") as f:
        f.seek(0, 2)
        try:
            while True:
                linea = f.readline()
                if linea:
                    sys.stdout.write(linea)
                    sys.stdout.flush()
                else:
                    time.sleep(0.4)
        except KeyboardInterrupt:
            print()


def main() -> int:
    p = argparse.ArgumentParser(description="Lee los registros del backend.")
    p.add_argument("--referencia", help="Código de una petición (cabecera X-Peticion-Id).")
    p.add_argument("--buscar", help="Texto libre: una cédula, una ruta, un mensaje.")
    p.add_argument("--errores", action="store_true", help="Solo advertencias y errores.")
    p.add_argument("--ultimas", type=int, default=40, help="Cuántas líneas mostrar (0 = todas).")
    p.add_argument("--seguir", action="store_true", help="Mostrar en vivo lo que vaya llegando.")
    args = _cli.analizar(p)

    if not CARPETA.exists():
        print(f"No hay registros en {CARPETA}.")
        print("Se crean al arrancar el backend (python scripts/servidor.py).")
        return 1

    if args.seguir:
        seguir(args.errores)
        return 0

    criterio = args.referencia or args.buscar
    encontradas = filtrar(criterio, args.errores)

    if not encontradas:
        que = f" que contengan «{criterio}»" if criterio else ""
        print(f"No hay líneas{que} en {'errores.log' if args.errores else 'sistema.log'}.")
        return 1

    # Con una referencia concreta se muestra todo: son pocas líneas y
    # recortarlas escondería justo la parte final de la traza.
    recorte = encontradas if (args.referencia or args.ultimas == 0) else encontradas[-args.ultimas:]
    omitidas = len(encontradas) - len(recorte)
    if omitidas > 0:
        print(f"… {omitidas} línea(s) anteriores omitidas (use --ultimas 0 para verlas)\n")
    sys.stdout.write("".join(recorte))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
