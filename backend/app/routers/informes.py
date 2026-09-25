"""Informes con filtros combinables y descarga en CSV.

Cada filtro es opcional y se acumula con los demás. El número de solicitud
manda: si se indica, se ignoran los otros, que es lo que espera quien busca
un caso concreto.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from psycopg import sql

from ..audit import registrar
from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol
from fastapi import Request

router = APIRouter(prefix="/informes", tags=["Informes"])

Analista = Annotated[dict, Depends(exigir_rol("rrhh", "admin", "jefe"))]

CAMPO_FECHA = {
    "creado": "fecha_solicitud",
    "inicio": "fecha_inicio",
    "fin": "fecha_fin",
}

COLUMNAS_CSV = [
    ("folio", "Nº solicitud"), ("fecha_solicitud", "Fecha de solicitud"),
    ("solicitante", "Solicitante"), ("cedula", "Cédula"),
    ("departamento", "Departamento"), ("cargo", "Cargo"),
    ("tipo_detalle", "Tipo"), ("fecha_inicio", "Desde"), ("fecha_fin", "Hasta"),
    ("dias_solicitados", "Días"), ("estado", "Estado"),
    ("jefe", "Jefe"), ("rrhh", "Talento Humano"), ("reemplazo", "Reemplazo"),
    ("motivo_rechazo", "Motivo del rechazo"),
]


async def _consultar(
    usuario: dict,
    folio: int | None,
    campo_fecha: str,
    desde: date | None,
    hasta: date | None,
    estado: list[str] | None,
    tipo: list[str] | None,
    departamento: list[str] | None,
    cargo: list[str] | None,
    solicitante: list[str] | None,
    jefe: list[str] | None,
    cedula: str | None,
    limite: int,
) -> list[dict]:
    condiciones: list[str] = []
    parametros: dict = {}

    # Un jefe solo ve a su equipo; RRHH y administración ven todo
    if usuario["rol"] == "jefe":
        condiciones.append(
            "user_id in (select id from public.users where jefe_id = %(mi_equipo)s)")
        parametros["mi_equipo"] = usuario["id"]

    if folio:
        # Buscar un número concreto ignora el resto: es lo que se espera
        condiciones.append("folio = %(folio)s")
        parametros["folio"] = folio
    else:
        columna = CAMPO_FECHA.get(campo_fecha, "fecha_solicitud")
        if desde:
            condiciones.append(f"{columna} >= %(desde)s")
            parametros["desde"] = desde
        if hasta:
            condiciones.append(f"{columna} <= %(hasta)s")
            parametros["hasta"] = hasta

        for nombre, columna_sql, valores in [
            ("estado", "estado", estado), ("tipo", "tipo", tipo),
            ("departamento", "departamento", departamento), ("cargo", "cargo", cargo),
            ("solicitante", "solicitante", solicitante), ("jefe", "jefe", jefe),
        ]:
            if valores:
                condiciones.append(f"{columna_sql} = any(%({nombre})s)")
                parametros[nombre] = valores

        if cedula:
            condiciones.append("cedula like %(cedula)s")
            parametros["cedula"] = f"{cedula.strip()}%"

    parametros["limite"] = min(limite, 5000)
    donde = " and ".join(condiciones) if condiciones else "true"

    return await obtener_todos(
        f"""select * from public.v_informe_solicitudes
            where {donde} order by folio desc limit %(limite)s""",
        parametros,
    )


@router.get("/dimensiones")
async def dimensiones(usuario: Analista) -> dict:
    """Valores disponibles para cada filtro: se llenan desde los datos reales."""
    filas = await obtener_uno(
        """
        select
          (select coalesce(jsonb_agg(distinct departamento) filter (where departamento is not null), '[]')
             from public.users where activo) as departamentos,
          (select coalesce(jsonb_agg(distinct cargo) filter (where cargo is not null), '[]')
             from public.users where activo) as cargos,
          (select coalesce(jsonb_agg(jsonb_build_object('id', id, 'nombre', nombre) order by nombre), '[]')
             from public.users where activo) as personas,
          (select coalesce(jsonb_agg(jsonb_build_object('id', id, 'nombre', nombre) order by nombre), '[]')
             from public.users where activo and rol in ('jefe','rrhh','admin')) as jefes,
          (select coalesce(jsonb_agg(nombre order by orden), '[]')
             from public.permission_types where activo) as tipos_permiso
        """
    )
    return {
        **filas,
        "estados": ["pendiente_jefe", "pendiente_rrhh", "pendiente_anulacion",
                    "aprobado", "rechazado", "cancelado"],
        "tipos": ["vacacion", "permiso"],
        "campos_fecha": [{"valor": k, "etiqueta": e} for k, e in
                         [("creado", "Creado"), ("inicio", "Inicio de la ausencia"),
                          ("fin", "Fin de la ausencia")]],
    }


@router.get("/solicitudes")
async def informe_solicitudes(
    usuario: Analista,
    folio: int | None = None,
    campo_fecha: Literal["creado", "inicio", "fin"] = "creado",
    desde: date | None = None,
    hasta: date | None = None,
    estado: list[str] | None = Query(None),
    tipo: list[str] | None = Query(None),
    departamento: list[str] | None = Query(None),
    cargo: list[str] | None = Query(None),
    solicitante: list[str] | None = Query(None),
    jefe: list[str] | None = Query(None),
    cedula: str | None = None,
    limite: int = 500,
) -> dict:
    filas = await _consultar(usuario, folio, campo_fecha, desde, hasta, estado, tipo,
                             departamento, cargo, solicitante, jefe, cedula, limite)

    # Resumen que ahorra contar a mano
    resumen = {
        "total": len(filas),
        "aprobadas": sum(1 for f in filas if f["estado"] == "aprobado"),
        "rechazadas": sum(1 for f in filas if f["estado"] == "rechazado"),
        "en_tramite": sum(1 for f in filas if f["estado"].startswith("pendiente")),
        "dias_aprobados": float(sum(f["dias_solicitados"] for f in filas
                                    if f["estado"] == "aprobado")),
    }
    return {"resumen": resumen, "filas": [{**f, "solicitud_id": str(f["solicitud_id"]),
                                           "user_id": str(f["user_id"])} for f in filas]}


@router.get("/solicitudes.csv")
async def informe_csv(
    request: Request,
    usuario: Analista,
    folio: int | None = None,
    campo_fecha: Literal["creado", "inicio", "fin"] = "creado",
    desde: date | None = None,
    hasta: date | None = None,
    estado: list[str] | None = Query(None),
    tipo: list[str] | None = Query(None),
    departamento: list[str] | None = Query(None),
    cargo: list[str] | None = Query(None),
    solicitante: list[str] | None = Query(None),
    jefe: list[str] | None = Query(None),
    cedula: str | None = None,
) -> Response:
    """Mismo informe, listo para abrir en Excel."""
    filas = await _consultar(usuario, folio, campo_fecha, desde, hasta, estado, tipo,
                             departamento, cargo, solicitante, jefe, cedula, 5000)

    memoria = io.StringIO()
    # Punto y coma: es lo que Excel en español espera como separador
    escritor = csv.writer(memoria, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    escritor.writerow([etiqueta for _, etiqueta in COLUMNAS_CSV])
    for f in filas:
        escritor.writerow([f.get(clave) if f.get(clave) is not None else "" for clave, _ in COLUMNAS_CSV])

    await registrar(request, "informe_descargado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"filas": len(filas)})

    # BOM para que Excel reconozca los acentos
    contenido = "﻿" + memoria.getvalue()
    return Response(
        content=contenido.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition":
                 f'attachment; filename="solicitudes-{date.today():%Y-%m-%d}.csv"'},
    )


@router.get("/resumen-departamentos")
async def resumen_departamentos(usuario: Analista, anio: int | None = None) -> list[dict]:
    """Cuántos días se fueron por departamento y mes."""
    return await obtener_todos(
        """
        select coalesce(departamento, 'Sin departamento') as departamento,
               to_char(date_trunc('month', fecha_inicio), 'YYYY-MM') as mes,
               count(*) as solicitudes,
               count(*) filter (where estado = 'aprobado') as aprobadas,
               coalesce(sum(dias_solicitados) filter (where estado = 'aprobado'), 0) as dias
        from public.v_informe_solicitudes
        where extract(year from fecha_inicio) = coalesce(%s, extract(year from current_date))
        group by 1, 2
        order by 1, 2
        """,
        (anio,),
    )
