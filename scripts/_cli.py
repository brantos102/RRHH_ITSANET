"""Que escribir «--APLICAR» sea lo mismo que escribir «--aplicar».

El sistema se opera desde PowerShell, donde nada distingue mayúsculas: los
comandos, las rutas y los nombres de archivo dan igual como se escriban. Pero
`argparse` sí distingue, así que `--APLICAR` no es un indicador desconocido
por una buena razón —lo es por una convención de Python que nadie tiene por
qué conocer— y el mensaje que sale no lo dice:

    error: unrecognized arguments: --APLICAR

Quien lo lee revisa la ortografía de la palabra, que está bien.

Solo se tocan los INDICADORES, nunca los valores. Una ruta puede depender de
sus mayúsculas —en Linux depende siempre— y pasarla a minúsculas convertiría
una molestia en un archivo que no existe.

Tampoco se inventa nada: un indicador solo se corrige si en minúsculas es uno
de los que el guion declara. `--Aplicarr` sigue siendo un error, y con razón.
"""
from __future__ import annotations

import argparse


def opciones_conocidas(parser: argparse.ArgumentParser) -> set[str]:
    """Los indicadores que el guion declara, tal como los declaró."""
    return {cadena for accion in parser._actions          # noqa: SLF001
            for cadena in accion.option_strings}


def normalizar(argv: list[str], parser: argparse.ArgumentParser) -> list[str]:
    """La misma línea de órdenes con los indicadores como el guion los espera.

    Se admite tanto `--APLICAR` como `--Aplicar`, y también `--INFORME=X`,
    donde solo cambia la parte de la izquierda del signo igual.
    """
    conocidas = opciones_conocidas(parser)
    if not conocidas:
        return argv

    en_minusculas = {o.lower(): o for o in conocidas}
    salida: list[str] = []
    solo_valores = False

    for pieza in argv:
        # Después de «--» todo es valor por convención, incluso si parece un
        # indicador. Respetarlo importa: es la única forma de pasar un archivo
        # que empiece por guion.
        if solo_valores or not pieza.startswith("-"):
            salida.append(pieza)
            continue
        if pieza == "--":
            solo_valores = True
            salida.append(pieza)
            continue

        nombre, igual, valor = pieza.partition("=")
        arreglado = en_minusculas.get(nombre.lower())
        salida.append(arreglado + igual + valor if arreglado else pieza)

    return salida


def analizar(parser: argparse.ArgumentParser, argv: list[str] | None = None):
    """`parse_args` sin sorpresas por las mayúsculas."""
    import sys
    return parser.parse_args(normalizar(list(argv if argv is not None else sys.argv[1:]),
                                        parser))
