"""Crea o repone el elenco de prueba: un operario, un jefe, Talento Humano…

    python scripts/personal_de_prueba.py            # dice qué haría
    python scripts/personal_de_prueba.py --aplicar  # lo hace
    python scripts/personal_de_prueba.py --quitar --aplicar

Para probar el sistema hace falta gente de cada rol, y crearla a mano por la
pantalla —cinco veces, con cédulas que pasen el dígito verificador— se hace
pesado y se acaba reutilizando a una persona real, que es justo lo que no hay
que hacer.

TODO LO QUE CREA VA MARCADO. Los correos usan el dominio `itsanet.test`, que
la RFC 2606 reserva para pruebas y que nunca resuelve a ningún servidor. Por
eso la pantalla de Depuración los señala: están bien señalados, son cuentas de
prueba. El día que sobren, `--quitar` se las lleva.

NO TOCA A NADIE MÁS. Solo crea o actualiza las cédulas de esta lista, y al
quitar solo borra las que él mismo creó. Una carga de prueba que roza la
planilla real no es una prueba, es un incidente.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _windows  # noqa: F401,E402
import _cli  # noqa: E402

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"

DOMINIO = "itsanet.test"

# Cédulas ecuatorianas válidas reservadas para esto: pasan el dígito
# verificador, que la base exige, y no pertenecen a nadie de la planilla —el
# guion lo comprueba antes de escribir—. Inventarlas a ojo no sirve: la
# primera tanda la rechazó la restricción `users_cedula_valida`, que es
# exactamente para lo que está.
ELENCO = [
    {"cedula": "1700000019", "nombre": "Prueba Admin Sistema",
     "rol": "admin", "cargo": "Administrador del sistema",
     "departamento": "TI", "ciudad": "Quito", "anios": 8},
    {"cedula": "1700000027", "nombre": "Prueba Talento Humano",
     "rol": "rrhh", "cargo": "Analista de Talento Humano",
     "departamento": "Talento Humano", "ciudad": "Quito", "anios": 6},
    {"cedula": "1700000035", "nombre": "Prueba Jefe Operaciones",
     "rol": "jefe", "cargo": "Jefe de Operaciones",
     "departamento": "Operaciones", "ciudad": "Quito", "anios": 7},
    {"cedula": "1700000043", "nombre": "Prueba Jefe Bodega Costa",
     "rol": "jefe", "cargo": "Jefe de Bodega",
     "departamento": "Bodega", "ciudad": "Guayaquil", "anios": 4},
    {"cedula": "1700000050", "nombre": "Prueba Guardia Garita",
     "rol": "guardia", "cargo": "Guardia de seguridad",
     "departamento": "Seguridad", "ciudad": "Quito", "anios": 2},
    # Operarios con antigüedades distintas a propósito: uno sin años cumplidos,
    # otro recién pasado el quinto —que es donde empiezan los días
    # adicionales— y otro con muchos, para ver el tope.
    {"cedula": "1700000068", "nombre": "Prueba Operario Nuevo",
     "rol": "empleado", "cargo": "Operativo", "departamento": "Operaciones",
     "ciudad": "Quito", "anios": 0, "jefe": "1700000035"},
    {"cedula": "1700000076", "nombre": "Prueba Operario Cinco Anos",
     "rol": "empleado", "cargo": "Operativo", "departamento": "Operaciones",
     "ciudad": "Quito", "anios": 5, "jefe": "1700000035"},
    {"cedula": "1700000084", "nombre": "Prueba Operario Antiguo",
     "rol": "empleado", "cargo": "Operador de Montacargas",
     "departamento": "Bodega", "ciudad": "Guayaquil", "anios": 16,
     "jefe": "1700000043"},
]


def correo(persona: dict) -> str:
    base = persona["nombre"].lower().replace("prueba ", "").replace(" ", ".")
    return f"{base}@{DOMINIO}"


async def principal(aplicar: bool, quitar: bool) -> int:
    from app.db import obtener_todos, obtener_uno

    cedulas = [p["cedula"] for p in ELENCO]

    # Que ninguna de estas cédulas sea de alguien real. Es lo único que puede
    # convertir esto en un problema, así que se comprueba siempre.
    ajenas = await obtener_todos(
        """select cedula, nombre, email::text as email from public.users
            where cedula = any(%s) and (email is null or email::text not like %s)""",
        (cedulas, f"%@{DOMINIO}"))
    if ajenas:
        print(f"{ROJO}Alguna cédula del elenco pertenece a una persona real:{FIN}")
        for a in ajenas:
            print(f"   {a['cedula']}  {a['nombre']}  {a['email'] or 'sin correo'}")
        print("   No se toca nada. Cambie esas cédulas en el guion.")
        return 2

    if quitar:
        existen = await obtener_todos(
            "select cedula, nombre from public.users where cedula = any(%s)", (cedulas,))
        print(f"Se quitarían {len(existen)} cuenta(s) de prueba:")
        for e in existen:
            print(f"   {e['cedula']}  {e['nombre']}")
        if not aplicar:
            print(f"\n{AMARILLO}Nada cambió.{FIN} Repita con --aplicar.")
            return 0
        # Se desactivan, no se borran: borrar arrastra en cascada todo su
        # expediente, y si alguien probó solicitudes con ellas conviene que
        # queden para mirarlas.
        await obtener_uno(
            """update public.users set activo = false
                where cedula = any(%s) returning 1 as x""", (cedulas,))
        print(f"\n{VERDE}Desactivadas.{FIN} Si de verdad quiere borrarlas, lea "
              "supabase/depuracion/03_eliminar.sql: arrastran su expediente.")
        return 0

    print(f"Elenco de prueba ({len(ELENCO)} cuentas), dominio {DOMINIO}:\n")
    for p in ELENCO:
        existe = await obtener_uno(
            "select nombre, activo from public.users where cedula = %s", (p["cedula"],))
        marca = f"{GRIS}ya existe{FIN}" if existe else f"{VERDE}nueva{FIN}"
        print(f"   {p['cedula']}  {p['nombre']:<28} {p['rol']:<9} "
              f"{p['anios']:>2} año(s)  {marca}")

    if not aplicar:
        print(f"\n{AMARILLO}Nada se escribió.{FIN} Repita con --aplicar para crearlas.")
        return 0

    creadas = actualizadas = 0
    for p in ELENCO:
        fila = await obtener_uno(
            """insert into public.users
                 (cedula, nombre, email, rol, cargo, departamento, ciudad,
                  fecha_ingreso, fecha_nacimiento, telefono, activo, ficha_completa)
               values (%(cedula)s, %(nombre)s, %(email)s, %(rol)s, %(cargo)s,
                       %(departamento)s, %(ciudad)s,
                       (current_date - make_interval(years => %(anios)s))::date,
                       '1990-01-15'::date, '0999000000', true, true)
               on conflict (cedula) do update
                 set nombre = excluded.nombre, email = excluded.email,
                     rol = excluded.rol, cargo = excluded.cargo,
                     departamento = excluded.departamento, ciudad = excluded.ciudad,
                     fecha_ingreso = excluded.fecha_ingreso, activo = true
               returning id, (xmax = 0) as es_nueva""",
            {**p, "email": correo(p)})
        creadas += 1 if fila["es_nueva"] else 0
        actualizadas += 0 if fila["es_nueva"] else 1
        await obtener_uno("select public.generar_periodos_vacaciones(%s) as n", (fila["id"],))

    # Los jefes, en una segunda pasada: al crear al primero el suyo todavía
    # no existía.
    for p in ELENCO:
        if p.get("jefe"):
            await obtener_uno(
                """update public.users set jefe_id =
                     (select id from public.users where cedula = %s)
                    where cedula = %s returning 1 as x""",
                (p["jefe"], p["cedula"]))

    await obtener_uno("select public.recalcular_saldos() as n")

    print(f"\n{VERDE}{creadas} creada(s) y {actualizadas} actualizada(s).{FIN}")
    print(f"{GRIS}Entran con su cédula. El código de acceso no llega por correo "
          f"—el dominio {DOMINIO} no existe—: se lee del registro con{FIN}")
    print("    python scripts/ver_logs.py --buscar \"Código de acceso\"")
    print(f"{GRIS}Aparecen en Administración → Depuración como cuentas de "
          f"prueba, que es lo que son.{FIN}")
    return 0


async def _con_cierre(aplicar: bool, quitar: bool) -> int:
    from app.db import cerrar_pool
    try:
        return await principal(aplicar, quitar)
    finally:
        await cerrar_pool()


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--aplicar", action="store_true", help="Escribir de verdad.")
    p.add_argument("--quitar", action="store_true", help="Desactivar el elenco.")
    a = _cli.analizar(p)
    raise SystemExit(asyncio.run(_con_cierre(a.aplicar, a.quitar)))
