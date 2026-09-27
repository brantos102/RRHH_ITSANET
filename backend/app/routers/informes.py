"""Informes con filtros combinables y descarga en CSV, Excel o PDF.

Cada filtro es opcional y se acumula con los demás. El número de solicitud
manda: si se indica, se ignoran los otros, que es lo que espera quien busca
un caso concreto.
"""
from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from psycopg import sql

from fastapi import Request

from ..audit import registrar
from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol
from ..exportar import Informe, entregar

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


def _describir_filtros(
    folio, campo_fecha, desde, hasta, estado, tipo, departamento, cargo,
    solicitante, jefe, cedula,
) -> list[tuple[str, str]]:
    """El filtro aplicado, en claro, para que vaya dentro del archivo.

    Un informe que no dice de qué está hablando no sustenta nada: dentro de
    tres meses, una tabla sin contexto no se puede defender ante nadie.
    """
    if folio:
        return [("Solicitud", f"Nº {folio}")]

    etiqueta_fecha = {"creado": "Fecha de solicitud", "inicio": "Fecha de inicio",
                      "fin": "Fecha de fin"}[campo_fecha]
    filtros: list[tuple[str, str]] = []
    if desde or hasta:
        filtros.append((etiqueta_fecha,
                        f"{desde:%d/%m/%Y} al {hasta:%d/%m/%Y}" if desde and hasta
                        else (f"desde {desde:%d/%m/%Y}" if desde else f"hasta {hasta:%d/%m/%Y}")))
    for titulo, valores in (("Estado", estado), ("Tipo", tipo),
                            ("Departamento", departamento), ("Cargo", cargo),
                            ("Solicitante", solicitante), ("Jefe", jefe)):
        if valores:
            filtros.append((titulo, ", ".join(valores)))
    if cedula:
        filtros.append(("Cédula", cedula))
    return filtros or [("Alcance", "Todas las solicitudes visibles")]


@router.get("/solicitudes.{formato}")
async def descargar_informe(
    request: Request,
    usuario: Analista,
    formato: Literal["csv", "xlsx", "pdf"],
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
    """El mismo informe que se ve en pantalla, en el formato que haga falta.

    CSV para seguir trabajándolo, Excel para entregarlo con formato, PDF para
    firmar o archivar. Lo que se descarga es exactamente lo filtrado: el
    alcance del rol ya lo aplica `_consultar`, así que un jefe se lleva solo a
    su equipo aunque manipule la dirección.
    """
    filas = await _consultar(usuario, folio, campo_fecha, desde, hasta, estado, tipo,
                             departamento, cargo, solicitante, jefe, cedula, 5000)

    informe = Informe(
        titulo="Solicitudes de permisos y vacaciones",
        columnas=COLUMNAS_CSV,
        filas=filas,
        filtros=_describir_filtros(folio, campo_fecha, desde, hasta, estado, tipo,
                                   departamento, cargo, solicitante, jefe, cedula),
        generado_por=f"{usuario['nombre']} ({usuario['rol']})",
    )

    # Queda en la bitácora quién se llevó qué: son datos personales saliendo
    # del sistema (LOPDP Art. 10), y eso se registra.
    await registrar(request, "informe_descargado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"],
                    detalle={"filas": len(filas), "formato": formato,
                             "filtros": dict(informe.filtros)})

    return entregar(informe, formato)


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
