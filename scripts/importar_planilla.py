#!/usr/bin/env python3
"""Convierte la planilla de Talento Humano en SQL listo para Supabase.

    python scripts/importar_planilla.py BD_inicial_RRHH.xlsx

Genera `supabase/carga_inicial.sql`, que se pega en el SQL Editor. No
escribe en la base: así se puede revisar antes de aplicar, y volver a
generarlo cuantas veces haga falta.

Qué hace con cada hoja
----------------------
ACTIVOS 2026        Personas, cargo, área, bodega, centro de costo, cliente,
                    ciudad, jefe inmediato, fechas de ingreso y de fin de
                    contrato, nacimiento, género, correo y teléfono.
REGISTRO DE VACACIONES
                    El saldo real. La hoja lleva un saldo corriente: cada
                    fila descuenta lo gozado de la anterior, de modo que la
                    ÚLTIMA fila de cada persona tiene el disponible vigente.
                    Ese es el número que se carga, no uno recalculado: la
                    empresa ya lo tiene conciliado.

Decisiones que conviene conocer
-------------------------------
* Las cédulas vienen como número y perdieron el cero inicial. Se rellenan
  a 10 dígitos y se validan con el módulo 10; las que no pasan se reportan
  y NO se cargan, porque una cédula errada es un acceso que nunca funciona.
* El jefe inmediato viene como nombre suelto. Se resuelve contra la misma
  planilla; a quien no se resuelve se lo reporta y queda sin jefe asignado.
* Quien no tiene correo recibe una dirección marcadora y queda señalado en
  `correo_pendiente`. Sin correo real no puede recibir su código: aparece
  en la vista `v_sin_correo` para que Talento Humano lo complete.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"

DOMINIO_MARCADOR = "pendiente.itsanet.local"


def sin_tildes(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(t.upper().split())


def comilla(valor) -> str:
    """Literal SQL. None y cadena vacía son NULL; las comillas se duplican."""
    if valor is None:
        return "null"
    if isinstance(valor, (dt.datetime, dt.date)):
        return f"'{valor.date() if isinstance(valor, dt.datetime) else valor}'"
    texto = str(valor).strip()
    if not texto:
        return "null"
    return "'" + texto.replace("'", "''") + "'"


def titulo_nombre(texto: str) -> str:
    """LOPEZ PEREZ JUAN -> López Perez Juan, respetando las partículas."""
    menores = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "DA", "DI"}
    palabras = str(texto or "").split()
    salida = []
    for i, p in enumerate(palabras):
        salida.append(p.lower() if p.upper() in menores and i else p.capitalize())
    return " ".join(salida)


def leer(ruta: Path):
    try:
        import openpyxl
    except ImportError:
        print(f"{ROJO}Falta openpyxl.{FIN}  pip install openpyxl", file=sys.stderr)
        raise SystemExit(1)
    return openpyxl.load_workbook(ruta, data_only=True)


# --------------------------------------------------------------- lectura
def leer_personas(wb) -> tuple[list[dict], list[str]]:
    """Hoja ACTIVOS: una fila por persona. Los encabezados están en la fila 5."""
    from app.cedula import es_cedula_valida

    hoja = next((h for h in wb.sheetnames if sin_tildes(h).startswith("ACTIVOS")), None)
    if hoja is None:
        raise SystemExit(f"{ROJO}No se encontró la hoja de personas activas.{FIN}")

    C = {"cedula": 1, "nombre": 2, "estado": 3, "cargo": 5, "ciudad": 6,
         "ceco": 8, "area": 9, "bodega": 10, "cliente": 12, "jefe": 13,
         "ingreso": 14, "contrato_fin": 15, "nacimiento": 18, "genero": 21,
         "correo": 22, "telefono": 23}

    personas, avisos = [], []
    for fila in wb[hoja].iter_rows(min_row=6, values_only=True):
        if not fila[C["cedula"]]:
            continue
        cedula = str(fila[C["cedula"]]).strip().split(".")[0].zfill(10)
        nombre = str(fila[C["nombre"]] or "").strip()

        if not es_cedula_valida(cedula):
            avisos.append(f"cédula inválida, no se carga: {cedula} — {nombre}")
            continue
        if not isinstance(fila[C["ingreso"]], (dt.datetime, dt.date)):
            avisos.append(f"sin fecha de ingreso, no se carga: {cedula} — {nombre}")
            continue

        personas.append({
            "cedula": cedula,
            "nombre": titulo_nombre(nombre),
            "nombre_clave": sin_tildes(nombre),
            "cargo": str(fila[C["cargo"]] or "").strip() or None,
            "ciudad": {"GYE": "Guayaquil", "UIO": "Quito"}.get(
                str(fila[C["ciudad"]] or "").strip().upper(),
                str(fila[C["ciudad"]] or "").strip() or None),
            "centro_costo": str(fila[C["ceco"]] or "").strip() or None,
            "departamento": str(fila[C["area"]] or "").strip() or None,
            "bodega": str(fila[C["bodega"]] or "").strip() or None,
            "cliente": str(fila[C["cliente"]] or "").strip() or None,
            "jefe_nombre": sin_tildes(fila[C["jefe"]]) or None,
            "fecha_ingreso": fila[C["ingreso"]],
            "contrato_fin": fila[C["contrato_fin"]]
                if isinstance(fila[C["contrato_fin"]], (dt.datetime, dt.date)) else None,
            "fecha_nacimiento": fila[C["nacimiento"]]
                if isinstance(fila[C["nacimiento"]], (dt.datetime, dt.date)) else None,
            "genero": str(fila[C["genero"]] or "").strip().capitalize() or None,
            "correo": (str(fila[C["correo"]] or "").strip().lower() or None),
            "telefono": re.sub(r"\D", "", str(fila[C["telefono"]] or "")) or None,
        })
    return personas, avisos


def cotejar_ingresos(wb, personas: list[dict]) -> list[str]:
    """Las dos hojas traen la fecha de ingreso: cuando discrepan, alguien
    tiene mal el saldo. Vale más señalarlo que elegir una en silencio."""
    hoja = next((h for h in wb.sheetnames if sin_tildes(h).startswith("REGISTRO")), None)
    if hoja is None:
        return []

    por_nombre = {p["nombre_clave"]: p for p in personas}
    vistos, avisos = set(), []
    for fila in wb[hoja].iter_rows(min_row=2, values_only=True):
        clave = sin_tildes(fila[0]) if fila[0] else None
        if not clave or clave in vistos:
            continue
        vistos.add(clave)
        persona = por_nombre.get(clave)
        if not persona or not isinstance(fila[2], (dt.datetime, dt.date)):
            continue
        del_registro = fila[2].date() if isinstance(fila[2], dt.datetime) else fila[2]
        de_activos = persona["fecha_ingreso"]
        de_activos = de_activos.date() if isinstance(de_activos, dt.datetime) else de_activos
        if del_registro != de_activos:
            avisos.append(
                f"fecha de ingreso distinta entre hojas: {persona['nombre']} — "
                f"registro {del_registro}, activos {de_activos}. Se usa la de ACTIVOS; "
                f"si la buena es la otra, corrija la planilla antes de cargar.")
    return avisos


def leer_saldos(wb) -> tuple[dict[str, float], list[str]]:
    """Hoja REGISTRO: saldo corriente; la última fila de cada persona manda."""
    hoja = next((h for h in wb.sheetnames if sin_tildes(h).startswith("REGISTRO")), None)
    if hoja is None:
        return {}, ["No se encontró la hoja de registro de vacaciones."]

    C_NOMBRE, C_DISPONIBLE = 0, 14
    ultimo: dict[str, float] = {}
    avisos: list[str] = []
    for fila in wb[hoja].iter_rows(min_row=2, values_only=True):
        if not fila[C_NOMBRE]:
            continue
        clave = sin_tildes(fila[C_NOMBRE])
        try:
            ultimo[clave] = round(float(fila[C_DISPONIBLE]), 2)
        except (TypeError, ValueError):
            if clave not in ultimo:
                avisos.append(f"saldo ilegible: {fila[C_NOMBRE]}")
    return ultimo, avisos


def resolver_jefes(personas: list[dict]) -> list[str]:
    """El jefe viene como nombre suelto; se busca por coincidencia de partes."""
    por_nombre = {p["nombre_clave"]: p["cedula"] for p in personas}
    sin_resolver: dict[str, int] = {}

    for p in personas:
        p["jefe_cedula"] = None
        if not p["jefe_nombre"]:
            continue
        partes = p["jefe_nombre"].split()
        candidatas = [ced for nom, ced in por_nombre.items()
                      if all(parte in nom.split() for parte in partes)]
        if len(candidatas) == 1 and candidatas[0] != p["cedula"]:
            p["jefe_cedula"] = candidatas[0]
        else:
            sin_resolver[p["jefe_nombre"]] = sin_resolver.get(p["jefe_nombre"], 0) + 1

    return [f"jefe no encontrado en la planilla: {n} ({c} persona(s) a su cargo))"
            for n, c in sorted(sin_resolver.items(), key=lambda x: -x[1])]


# ------------------------------------------------------------ generación
ENCABEZADO = """\
-- ---------------------------------------------------------------------------
-- Carga inicial de la planilla de ITSANET
--
-- Generado por scripts/importar_planilla.py el {fecha}.
-- NO editar a mano: vuelva a generarlo desde la planilla.
--
--   Personas .................. {total}
--   Con correo real ........... {con_correo}
--   Sin correo (no acceden) ... {sin_correo}
--   Con saldo de la planilla .. {con_saldo}
--
-- Es idempotente: volver a ejecutarlo actualiza los datos de quien ya
-- existe y no duplica a nadie. El saldo se recarga desde la planilla, así
-- que NO lo ejecute de nuevo una vez que el sistema empiece a descontar
-- vacaciones: sobreescribiría los movimientos hechos en el sistema.
-- ---------------------------------------------------------------------------

begin;

create temporary table planilla (
  cedula            text primary key,
  nombre            text,
  email             text,
  correo_pendiente  boolean,
  telefono          text,
  cargo             text,
  departamento      text,
  bodega            text,
  centro_costo      text,
  cliente           text,
  ciudad            text,
  genero            text,
  fecha_ingreso     date,
  contrato_fin      date,
  fecha_nacimiento  date,
  jefe_cedula       text,
  saldo             numeric(6,2)
) on commit drop;

insert into planilla values
"""

CIERRE = """;

-- 1. Personas: se insertan las nuevas y se actualizan las existentes.
--    El rol NO se toca: si Talento Humano ya nombró a alguien jefe o
--    administrador en el sistema, la planilla no debe degradarlo.
insert into public.users
  (cedula, nombre, email, correo_pendiente, telefono, cargo, departamento,
   bodega, centro_costo, cliente, ciudad, genero, fecha_ingreso, contrato_fin,
   fecha_nacimiento, rol, activo)
select p.cedula, p.nombre, p.email::citext, p.correo_pendiente, p.telefono,
       p.cargo, p.departamento, p.bodega, p.centro_costo, p.cliente, p.ciudad,
       p.genero, p.fecha_ingreso, p.contrato_fin, p.fecha_nacimiento,
       'empleado'::user_role, true
  from planilla p
on conflict (cedula) do update set
  nombre           = excluded.nombre,
  telefono         = coalesce(excluded.telefono, public.users.telefono),
  cargo            = excluded.cargo,
  departamento     = excluded.departamento,
  bodega           = excluded.bodega,
  centro_costo     = excluded.centro_costo,
  cliente          = excluded.cliente,
  ciudad           = excluded.ciudad,
  genero           = excluded.genero,
  fecha_ingreso    = excluded.fecha_ingreso,
  contrato_fin     = excluded.contrato_fin,
  fecha_nacimiento = excluded.fecha_nacimiento,
  activo           = true,
  -- El correo real de la planilla reemplaza a un marcador, nunca al revés:
  -- si alguien ya entró al sistema, su dirección buena se respeta.
  email            = case when excluded.correo_pendiente then public.users.email
                          else excluded.email::citext end,
  correo_pendiente = case when excluded.correo_pendiente then public.users.correo_pendiente
                          else false end;

-- 2. Jefaturas: en un segundo paso, porque un jefe puede aparecer en la
--    planilla después que su gente.
update public.users u
   set jefe_id = j.id
  from planilla p
  join public.users j on j.cedula = p.jefe_cedula
 where u.cedula = p.cedula and j.id <> u.id;

-- 3. Quien tiene gente a cargo es jefe en el sistema, salvo que ya tenga
--    un perfil superior (Talento Humano o administración).
update public.users
   set rol = 'jefe'::user_role
 where rol = 'empleado'::user_role
   and id in (select distinct jefe_id from public.users where jefe_id is not null);

-- 4. Saldo de vacaciones: el conciliado por Talento Humano, no uno
--    recalculado. `cargar_saldo_inicial` genera los períodos y deja la
--    trazabilidad de dónde salió el número.
create temporary table saldos_no_cargados (
  cedula text, nombre text, saldo_planilla numeric, motivo text
) on commit drop;

do $carga$
declare r record;
begin
  for r in select u.id, u.cedula, u.nombre, p.saldo
             from planilla p join public.users u on u.cedula = p.cedula
            where p.saldo is not null
  loop
    -- Persona por persona: un dato inconsistente en la planilla no puede
    -- tumbar la carga de los otros trescientos. El caso se reporta al final
    -- para que Talento Humano lo revise y lo cargue a mano.
    begin
      perform public.cargar_saldo_inicial(r.id, r.saldo, 0);
    exception when others then
      insert into saldos_no_cargados values (r.cedula, r.nombre, r.saldo, sqlerrm);
    end;
  end loop;
end
$carga$;

-- Saldos que quedaron sin cargar, si los hubo. Estas personas entran con el
-- saldo que calcula el sistema por su fecha de ingreso; revise el motivo.
select cedula, nombre, saldo_planilla, motivo from saldos_no_cargados;

commit;

-- ---------------------------------------------------------------------------
-- Comprobación posterior
-- ---------------------------------------------------------------------------
select count(*)                             as personas_activas,
       count(*) filter (where correo_pendiente) as sin_correo,
       count(*) filter (where jefe_id is not null) as con_jefe,
       count(*) filter (where rol = 'jefe')  as jefaturas,
       round(avg(dias_vacaciones), 2)        as saldo_promedio
  from public.users where activo;
"""


def generar(personas: list[dict], saldos: dict[str, float], destino: Path) -> dict:
    filas, con_correo, con_saldo = [], 0, 0
    for p in personas:
        correo = p["correo"]
        pendiente = not correo
        if pendiente:
            correo = f"{p['cedula']}@{DOMINIO_MARCADOR}"
        else:
            con_correo += 1
        saldo = saldos.get(p["nombre_clave"])
        if saldo is not None:
            con_saldo += 1

        filas.append(
            "  (" + ", ".join([
                comilla(p["cedula"]), comilla(p["nombre"]), comilla(correo),
                "true" if pendiente else "false",
                comilla(p["telefono"]), comilla(p["cargo"]), comilla(p["departamento"]),
                comilla(p["bodega"]), comilla(p["centro_costo"]), comilla(p["cliente"]),
                comilla(p["ciudad"]), comilla(p["genero"]),
                comilla(p["fecha_ingreso"]), comilla(p["contrato_fin"]),
                comilla(p["fecha_nacimiento"]), comilla(p["jefe_cedula"]),
                "null" if saldo is None else f"{saldo:.2f}",
            ]) + ")"
        )

    cuerpo = ENCABEZADO.format(
        fecha=dt.date.today().isoformat(), total=len(personas),
        con_correo=con_correo, sin_correo=len(personas) - con_correo, con_saldo=con_saldo,
    ) + ",\n".join(filas) + CIERRE

    destino.write_text(cuerpo, encoding="utf-8")
    return {"total": len(personas), "con_correo": con_correo,
            "sin_correo": len(personas) - con_correo, "con_saldo": con_saldo}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    origen = Path(sys.argv[1]).expanduser()
    if not origen.exists():
        print(f"{ROJO}No existe el archivo:{FIN} {origen}", file=sys.stderr)
        return 1

    print(f"Leyendo {origen.name}…\n")
    wb = leer(origen)

    personas, avisos = leer_personas(wb)
    saldos, avisos_saldo = leer_saldos(wb)
    avisos += avisos_saldo
    avisos += cotejar_ingresos(wb, personas)
    avisos += resolver_jefes(personas)

    destino = RAIZ / "supabase" / "carga_inicial.sql"
    resumen = generar(personas, saldos, destino)

    sin_saldo = [p["nombre"] for p in personas if p["nombre_clave"] not in saldos]

    print(f"  {VERDE}✓{FIN} {resumen['total']} persona(s) listas para cargar")
    print(f"  {VERDE}✓{FIN} {resumen['con_saldo']} con saldo tomado de la planilla")
    print(f"  {VERDE}✓{FIN} {sum(1 for p in personas if p['jefe_cedula'])} con jefe inmediato resuelto")

    if resumen["sin_correo"]:
        print(f"\n  {AMARILLO}!{FIN} {resumen['sin_correo']} persona(s) SIN correo registrado.")
        print(f"    {GRIS}No podrán recibir su código de acceso. Quedan cargadas y marcadas;{FIN}")
        print(f"    {GRIS}revíselas con:  select * from public.v_sin_correo;{FIN}")

    if sin_saldo:
        print(f"\n  {AMARILLO}!{FIN} {len(sin_saldo)} persona(s) sin saldo en el registro de vacaciones.")
        print(f"    {GRIS}Entran con el saldo que calcule el sistema por su fecha de ingreso.{FIN}")
        for n in sin_saldo[:5]:
            print(f"    {GRIS}· {n}{FIN}")
        if len(sin_saldo) > 5:
            print(f"    {GRIS}… y {len(sin_saldo) - 5} más{FIN}")

    if avisos:
        print(f"\n  {AMARILLO}!{FIN} {len(avisos)} punto(s) que conviene revisar:")
        for a in avisos[:12]:
            print(f"    {GRIS}· {a}{FIN}")
        if len(avisos) > 12:
            print(f"    {GRIS}… y {len(avisos) - 12} más{FIN}")

    print(f"\n{VERDE}Generado:{FIN} {destino.relative_to(RAIZ)}")
    print(f"{GRIS}Ábralo, revíselo y péguelo en el SQL Editor de Supabase.{FIN}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
