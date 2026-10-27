"""Carga (o vuelve a cargar) personas desde un CSV, con su saldo de vacaciones.

    .venv/bin/python mysql/cargar_personas.py personas.csv             # revisa y muestra; no escribe
    .venv/bin/python mysql/cargar_personas.py personas.csv --aplicar   # carga
    .venv/bin/python mysql/cargar_personas.py personas.csv --quitar --aplicar
                                                                       # borra a ESAS personas

El CSV lo prepara Talento Humano EN EL SERVIDOR y no se sube nunca al
repositorio: son datos personales (LOPDP). Columnas, con encabezado, separadas
por punto y coma o por coma (el orden no importa; las de [ ] son opcionales):

    cedula; nombre; email; rol; fecha_ingreso; [jefe_cedula]; [saldo];
    [cargo]; [departamento]; [ciudad]; [telefono]; [fecha_nacimiento]

  email          la fila con el correo en blanco se omite (aún no se completó)
  rol            empleado, jefe, rrhh, guardia o admin
  fechas         2021-09-01 o 01/09/2021
  jefe_cedula    la cédula de su jefe inmediato (en el mismo archivo o ya cargado)
  saldo          los días que Talento Humano tiene conciliados. Si falta, el
                 saldo se calcula desde la fecha de ingreso como si no hubiera
                 gozado nada.

Las personas se identifican por cédula: si ya existe, se ACTUALIZAN sus datos
y su saldo; si no, se crea. Nada se escribe sin --aplicar, y todo va en una
sola transacción: o entra el archivo completo, o no entra nada.

--quitar borra de la base a las personas del archivo, CON TODO su expediente
(solicitudes, períodos, avisos…). Sirve para la fase de pruebas: cargar,
probar, quitar y volver a cargar. Con datos reales en uso, a nadie se lo
borra: se lo da de baja desde Administración.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "servidor"))

from app.cedula import es_cedula_valida, normalizar_cedula  # noqa: E402
from app.db import a_json, cerrar_pool, ejecutar, lista, nuevo_id, obtener_todos, obtener_uno, transaccion  # noqa: E402
from app.reglas import periodos  # noqa: E402

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"
ROLES = {"empleado", "jefe", "rrhh", "guardia", "admin"}
OBLIGATORIAS = ("cedula", "nombre", "email", "rol", "fecha_ingreso")
OPCIONALES = ("jefe_cedula", "saldo", "cargo", "departamento", "ciudad", "telefono", "fecha_nacimiento")
CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _fecha(texto: str) -> dt.date | None:
    texto = (texto or "").strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return dt.datetime.strptime(texto, formato).date()
        except ValueError:
            pass
    return None


def leer(archivo: Path) -> tuple[list[dict], list[str]]:
    """Las filas válidas y la lista de problemas. Una fila con problemas no se carga."""
    texto = archivo.read_text(encoding="utf-8-sig")
    dialecto = csv.Sniffer().sniff(texto.splitlines()[0], delimiters=";,")
    lector = csv.DictReader(texto.splitlines(), dialect=dialecto)
    columnas = {c.strip().lower(): c for c in (lector.fieldnames or [])}
    faltan = [c for c in OBLIGATORIAS if c not in columnas]
    if faltan:
        raise SystemExit(f"{ROJO}Al archivo le faltan columnas: {', '.join(faltan)}{FIN}")

    filas, problemas, vistas = [], [], set()
    sin_correo = 0
    for n, crudo in enumerate(lector, start=2):
        v = {c: (crudo.get(columnas[c]) or "").strip() for c in (*OBLIGATORIAS, *OPCIONALES) if c in columnas}
        # Una fila con el correo todavía en blanco no es un error: es alguien
        # que Talento Humano aún no completó (personas_completar.csv). Se omite.
        if not v["email"]:
            sin_correo += 1
            continue
        error = []
        cedula = normalizar_cedula(v["cedula"]).zfill(10)   # el Excel suele comerse el 0 inicial
        if not es_cedula_valida(cedula):
            error.append(f"cédula {v['cedula'] or '(vacía)'} no válida")
        elif cedula in vistas:
            error.append(f"cédula {cedula} repetida en el archivo")
        if len(v["nombre"]) < 3:
            error.append("falta el nombre")
        email = v["email"].lower()
        if not CORREO.match(email):
            error.append(f"correo «{v['email']}» no válido")
        rol = v["rol"].lower()
        if rol not in ROLES:
            error.append(f"rol «{v['rol']}» no es uno de {', '.join(sorted(ROLES))}")
        ingreso = _fecha(v["fecha_ingreso"])
        if ingreso is None:
            error.append(f"fecha de ingreso «{v['fecha_ingreso']}» no se entiende")
        nacimiento = _fecha(v.get("fecha_nacimiento", "")) if v.get("fecha_nacimiento") else None
        saldo = None
        if v.get("saldo"):
            try:
                saldo = Decimal(v["saldo"].replace(",", "."))
            except InvalidOperation:
                error.append(f"saldo «{v['saldo']}» no es un número")
        jefe = normalizar_cedula(v.get("jefe_cedula", "")).zfill(10) if v.get("jefe_cedula") else None
        if jefe == cedula:
            error.append("no puede ser su propio jefe")
        if error:
            problemas.append(f"fila {n}: " + "; ".join(error))
            continue
        vistas.add(cedula)
        filas.append({"fila": n, "cedula": cedula, "nombre": " ".join(v["nombre"].split()), "email": email,
                      "rol": rol, "fecha_ingreso": ingreso, "fecha_nacimiento": nacimiento,
                      "saldo": saldo, "jefe_cedula": jefe,
                      **{c: v.get(c) or None for c in ("cargo", "departamento", "ciudad", "telefono")}})
    if sin_correo:
        print(f"{GRIS}{sin_correo} fila(s) con el correo en blanco: se omiten hasta que se complete.{FIN}")
    return filas, problemas


async def cargar(filas: list[dict]) -> tuple[int, int]:
    nuevas = actualizadas = 0
    async with transaccion():
        ids: dict[str, str] = {}
        for f in filas:
            ya = await obtener_uno("SELECT id FROM users WHERE cedula = %s", (f["cedula"],))
            datos = {c: f[c] for c in ("nombre", "email", "rol", "fecha_ingreso", "fecha_nacimiento",
                                       "cargo", "departamento", "ciudad", "telefono")
                     if f[c] is not None}
            datos["correo_pendiente"] = False
            if ya is None:
                user_id = str(nuevo_id())
                columnas = ", ".join(["id", "cedula", *datos])
                marcas = ", ".join(["%s"] * (len(datos) + 2))
                await ejecutar(f"INSERT INTO users ({columnas}) VALUES ({marcas})",
                               (user_id, f["cedula"], *datos.values()))
                nuevas += 1
            else:
                user_id = str(ya["id"])
                asignaciones = ", ".join(f"{c} = %s" for c in datos)
                await ejecutar(f"UPDATE users SET {asignaciones}, activo = TRUE WHERE id = %s",
                               (*datos.values(), user_id))
                actualizadas += 1
            ids[f["cedula"]] = user_id

        # El jefe, en una segunda pasada: puede venir más abajo en el archivo.
        for f in filas:
            jefe_id = None
            if f["jefe_cedula"]:
                jefe_id = ids.get(f["jefe_cedula"])
                if jefe_id is None:
                    fila = await obtener_uno("SELECT id FROM users WHERE cedula = %s AND activo",
                                             (f["jefe_cedula"],))
                    jefe_id = str(fila["id"]) if fila else None
            await ejecutar("UPDATE users SET jefe_id = %s WHERE id = %s", (jefe_id, ids[f["cedula"]]))

        # El saldo: el conciliado si viene; si no, el que da la antigüedad.
        for f in filas:
            if f["saldo"] is not None:
                await periodos.cargar_saldo_inicial(ids[f["cedula"]], f["saldo"], 0)
            else:
                await periodos.generar_periodos_vacaciones(ids[f["cedula"]])

        await ejecutar(
            """INSERT INTO audit_logs (accion, entidad, detalle)
               VALUES ('personas_cargadas', 'users', %s)""",
            (a_json({"nuevas": nuevas, "actualizadas": actualizadas, "origen": "mysql/cargar_personas.py"}),))
    return nuevas, actualizadas


async def quitar(cedulas: list[str]) -> int:
    async with transaccion():
        ids = [str(f["id"]) for f in await obtener_todos(
            "SELECT id FROM users WHERE cedula IN %s", (lista(cedulas),))]
        if not ids:
            return 0
        # MySQL comprueba cada referencia fila por fila: se sueltan antes las
        # que apuntan a estas personas desde otras fichas.
        for columna in ("jefe_id", "salida_registrada_por"):
            await ejecutar(f"UPDATE users SET {columna} = NULL WHERE {columna} IN %s", (lista(ids),))
        await ejecutar("DELETE FROM request_adjustments WHERE ajustado_por IN %s", (lista(ids),))
        n = await ejecutar("DELETE FROM users WHERE id IN %s", (lista(ids),))
        await ejecutar(
            """INSERT INTO audit_logs (accion, entidad, detalle)
               VALUES ('personas_quitadas', 'users', %s)""",
            (a_json({"personas": n, "origen": "mysql/cargar_personas.py --quitar"}),))
    return n


async def principal(args) -> int:
    archivo = Path(args.archivo)
    if not archivo.exists():
        raise SystemExit(f"No existe {archivo}")
    filas, problemas = leer(archivo)
    print(f"{archivo.name}: {len(filas)} persona(s) correctas", end="")
    print(f", {ROJO}{len(problemas)} con problemas (no se cargan){FIN}" if problemas else "")
    for p in problemas:
        print(f"  {ROJO}{p}{FIN}")
    try:
        existentes = {f["cedula"] for f in await obtener_todos(
            "SELECT cedula FROM users WHERE cedula IN %s", (lista([f["cedula"] for f in filas]),))}

        if args.quitar:
            if not existentes:
                print("Ninguna de esas personas está en la base. No hay nada que quitar.")
                return 0
            cuenta = await obtener_uno(
                """SELECT (SELECT COUNT(*) FROM requests r JOIN users u ON u.id = r.user_id
                            WHERE u.cedula IN %s) AS solicitudes""", (lista(sorted(existentes)),))
            print(f"\nSe BORRARÍAN {len(existentes)} persona(s) con todo su expediente "
                  f"({cuenta['solicitudes']} solicitud(es) incluidas).")
            if not args.aplicar:
                print(f"{AMARILLO}Nada se borró.{FIN} Repita con --aplicar para hacerlo.")
                return 0
            n = await quitar(sorted(existentes))
            print(f"{VERDE}Borradas {n} persona(s).{FIN}")
            return 0

        for f in filas:
            accion = "actualiza" if f["cedula"] in existentes else "nueva"
            saldo = f"saldo {f['saldo']}" if f["saldo"] is not None else "saldo por antigüedad"
            jefe = f"jefe {f['jefe_cedula']}" if f["jefe_cedula"] else "sin jefe"
            print(f"  {GRIS}{accion:<9}{FIN} {f['cedula']}  {f['nombre'][:30]:<30} {f['rol']:<8} "
                  f"{f['email']:<32} {jefe:<16} {saldo}")
        sin_jefe = [f for f in filas if f["rol"] == "empleado" and not f["jefe_cedula"]]
        if sin_jefe:
            print(f"{AMARILLO}  {len(sin_jefe)} empleado(s) sin jefe: sus solicitudes irán directo a "
                  f"Talento Humano.{FIN}")
        if not args.aplicar:
            print(f"\n{AMARILLO}Nada se escribió.{FIN} Repita con --aplicar para cargarlo.")
            return 0
        if problemas and not args.con_problemas:
            print(f"\n{ROJO}Hay filas con problemas. Corríjalas, o repita con --con-problemas para "
                  f"cargar solo las correctas.{FIN}")
            return 1
        nuevas, actualizadas = await cargar(filas)
        print(f"\n{VERDE}Cargado: {nuevas} nueva(s), {actualizadas} actualizada(s).{FIN}")
        return 0
    finally:
        await cerrar_pool()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("archivo")
    parser.add_argument("--aplicar", action="store_true", help="escribir de verdad (si no, solo muestra)")
    parser.add_argument("--quitar", action="store_true", help="borrar a las personas del archivo")
    parser.add_argument("--con-problemas", action="store_true",
                        help="cargar las filas correctas aunque otras tengan problemas")
    sys.exit(asyncio.run(principal(parser.parse_args())))
