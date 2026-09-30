"""Personal temporal: quién vino, cuánto estuvo y cuánto se le paga.

Es un sistema pequeño dentro del grande, y con otra lógica. El personal de
planta tiene expediente, vacaciones y jefe; el temporal viene por jornadas y
se le paga por lo que trabajó esa semana. Por eso no vive en `users`:
mezclarlos habría dado una persona con saldo de vacaciones que nadie le debe,
un jefe que no tiene y un acceso al sistema que no necesita.

De todo esto la empresa necesita una sola cosa, dicha por Talento Humano:
cuántas horas hizo cada operario esta semana. De ahí sale la regla que manda:
nadie puede quedar sin salida registrada. Una jornada sin cerrar no es un
hueco en la bitácora, es una jornada que se paga a ojo.

El sistema las señala y no las inventa. No hay salida automática a las seis
de la tarde: eso convertiría un dato que falta en un dato falso, que es peor
que no tenerlo.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from ..audit import registrar
from ..cedula import normalizar_cedula
from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol
from ..errores import traducir

router = APIRouter(prefix="/temporal", tags=["Personal temporal"])

# La garita registra las jornadas; Talento Humano administra a la gente y
# liquida la semana.
GARITA = Annotated[dict, Depends(exigir_rol("guardia", "rrhh", "admin"))]
RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]


class NuevoTemporal(BaseModel):
    cedula: str
    nombre: str = Field(..., min_length=3, max_length=120)
    labor: str | None = Field(None, max_length=120)
    proveedor: str | None = Field(None, max_length=120)
    telefono: str | None = Field(None, max_length=20)
    valor_hora: float | None = Field(None, ge=0)
    observacion: str | None = Field(None, max_length=300)

    @field_validator("cedula")
    @classmethod
    def validar(cls, v: str) -> str:
        return normalizar_cedula(v)


class CambioTemporal(BaseModel):
    nombre: str | None = Field(None, min_length=3, max_length=120)
    labor: str | None = Field(None, max_length=120)
    proveedor: str | None = Field(None, max_length=120)
    telefono: str | None = Field(None, max_length=20)
    valor_hora: float | None = Field(None, ge=0)
    activo: bool | None = None
    observacion: str | None = Field(None, max_length=300)


class Movimiento(BaseModel):
    temporal_id: str
    observacion: str | None = Field(None, max_length=300)


class CierreManual(BaseModel):
    salida: datetime
    motivo: str = Field(..., min_length=10, max_length=300)


# --------------------------------------------------------------- la gente
@router.get("")
async def listar(usuario: GARITA, buscar: str | None = None,
                 incluir_inactivos: bool = False) -> list[dict]:
    """Quiénes están registrados, con su jornada de hoy si la tienen."""
    filas = await obtener_todos(
        """
        select t.id, t.cedula, t.nombre, t.labor, t.proveedor, t.telefono,
               t.valor_hora, t.activo, t.observacion,
               j.id as jornada_hoy, j.entrada_en, j.salida_en, j.horas
          from public.personal_temporal t
          left join public.jornadas_temporales j
                 on j.temporal_id = t.id and j.fecha = current_date
         where (%(inactivos)s or t.activo)
           and (%(buscar)s::text is null
                or t.nombre ilike '%%' || %(buscar)s || '%%'
                or t.cedula like %(buscar)s || '%%'
                or coalesce(t.labor, '') ilike '%%' || %(buscar)s || '%%'
                or coalesce(t.proveedor, '') ilike '%%' || %(buscar)s || '%%')
         order by t.activo desc, t.nombre
        """,
        {"buscar": (buscar or "").strip() or None, "inactivos": incluir_inactivos},
    )
    return [
        {**f, "id": str(f["id"]),
         "jornada_hoy": str(f["jornada_hoy"]) if f["jornada_hoy"] else None,
         "valor_hora": float(f["valor_hora"]) if f["valor_hora"] is not None else None,
         "horas": float(f["horas"]) if f["horas"] is not None else None,
         # El estado de hoy, resuelto aquí: la pantalla no tiene por qué
         # deducirlo de tres campos que pueden estar nulos.
         "estado_hoy": ("dentro" if f["jornada_hoy"] and not f["salida_en"]
                        else "completo" if f["jornada_hoy"] else "sin_registrar")}
        for f in filas
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
async def registrar_persona(datos: NuevoTemporal, request: Request, usuario: RRHH) -> dict:
    try:
        fila = await obtener_uno(
            """insert into public.personal_temporal
                 (cedula, nombre, labor, proveedor, telefono, valor_hora, observacion)
               values (%(cedula)s, %(nombre)s, %(labor)s, %(proveedor)s,
                       %(telefono)s, %(valor_hora)s, %(observacion)s)
               returning id, nombre""",
            datos.model_dump(),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "temporal_registrado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="personal_temporal",
                    entidad_id=str(fila["id"]), detalle={"cedula": datos.cedula})
    return {"id": str(fila["id"]), "mensaje": f"{fila['nombre']} quedó registrado."}


@router.patch("/{temporal_id}")
async def editar_persona(temporal_id: str, cambios: CambioTemporal,
                         request: Request, usuario: RRHH) -> dict:
    campos = cambios.model_dump(exclude_unset=True)
    if not campos:
        raise HTTPException(status_code=422, detail={"mensaje": "No indicó ningún cambio."})

    asignaciones = ", ".join(f"{k} = %({k})s" for k in campos)
    try:
        fila = await obtener_uno(
            f"""update public.personal_temporal set {asignaciones}
                 where id = %(id)s returning nombre""",
            {**campos, "id": temporal_id},
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    if fila is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Ese operario no existe."})

    await registrar(request, "temporal_modificado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="personal_temporal",
                    entidad_id=temporal_id, detalle={"cambios": list(campos)})
    return {"mensaje": f"Datos de {fila['nombre']} actualizados."}


# ------------------------------------------------------------- la jornada
@router.post("/entrada")
async def entrada(datos: Movimiento, request: Request, usuario: GARITA) -> dict:
    try:
        fila = await obtener_uno(
            "select public.temporal_registrar_entrada(%s, %s, %s) as r",
            (datos.temporal_id, usuario["id"], datos.observacion),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    r = fila["r"]
    await registrar(request, "temporal_entrada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="jornadas_temporales",
                    entidad_id=str(r["jornada_id"]))
    return {**r, "mensaje": f"{r['nombre']} entró. Falta registrar su salida."}


@router.post("/salida")
async def salida(datos: Movimiento, request: Request, usuario: GARITA) -> dict:
    try:
        fila = await obtener_uno(
            "select public.temporal_registrar_salida(%s, %s, %s) as r",
            (datos.temporal_id, usuario["id"], datos.observacion),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    r = fila["r"]
    await registrar(request, "temporal_salida", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="jornadas_temporales",
                    entidad_id=str(r["jornada_id"]))
    return {**r, "mensaje": f"{r['nombre']} salió. Jornada de {r['horas']} horas."}


@router.get("/dentro")
async def dentro(usuario: GARITA) -> list[dict]:
    filas = await obtener_todos("select * from public.v_temporales_dentro")
    return [{**f, "jornada_id": str(f["jornada_id"]), "temporal_id": str(f["temporal_id"]),
             "horas_hasta_ahora": float(f["horas_hasta_ahora"])} for f in filas]


@router.get("/sin-cerrar")
async def sin_cerrar(usuario: GARITA) -> list[dict]:
    """Las jornadas de días pasados que nadie cerró.

    Es la lista que no puede tener nada antes de pagar la semana. Se muestra
    tanto a la garita como a Talento Humano: el guardia es quien puede
    recordar qué pasó ese día.
    """
    filas = await obtener_todos("select * from public.v_jornadas_sin_cerrar")
    return [{**f, "jornada_id": str(f["jornada_id"]),
             "temporal_id": str(f["temporal_id"])} for f in filas]


@router.post("/jornadas/{jornada_id}/cerrar")
async def cerrar(jornada_id: str, datos: CierreManual,
                 request: Request, usuario: RRHH) -> dict:
    try:
        fila = await obtener_uno(
            "select public.temporal_cerrar_jornada(%s, %s, %s, %s) as r",
            (jornada_id, datos.salida, usuario["id"], datos.motivo),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "temporal_jornada_cerrada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="jornadas_temporales",
                    entidad_id=jornada_id, detalle={"motivo": datos.motivo})
    return {**fila["r"], "mensaje": "Jornada cerrada. Queda constancia de quién y por qué."}


# --------------------------------------------------------------- la semana
@router.get("/semana")
async def semana(usuario: RRHH, desde: date | None = None,
                 hasta: date | None = None) -> dict:
    """Lo trabajado por cada operario, para pagarle.

    Mientras `sin_cerrar` no sea cero el total está incompleto, y eso se dice
    en la respuesta en vez de dejar que alguien sume una columna que no
    cuadra.
    """
    filas = await obtener_todos(
        "select * from public.temporal_semana(%s, %s)", (desde, hasta))

    def numero(v):
        return float(v) if v is not None else None

    gente = [
        {**f, "temporal_id": str(f["temporal_id"]), "dias": int(f["dias"]),
         "horas": numero(f["horas"]), "valor_hora": numero(f["valor_hora"]),
         "total": numero(f["total"]), "sin_cerrar": int(f["sin_cerrar"])}
        for f in filas
    ]
    abiertas = sum(p["sin_cerrar"] for p in gente)
    return {
        "desde": desde, "hasta": hasta,
        "personas": gente,
        "total_horas": round(sum(p["horas"] or 0 for p in gente), 2),
        "total_pagar": round(sum(p["total"] or 0 for p in gente), 2),
        "jornadas_sin_cerrar": abiertas,
        "aviso": ("Hay jornadas sin salida registrada: el total está incompleto "
                  "hasta que se cierren." if abiertas else None),
    }
