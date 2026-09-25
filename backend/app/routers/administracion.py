"""Administración: personal, tipos de solicitud, días no laborables y parámetros.

Todo lo que aquí se cambia altera cómo se calculan derechos de la gente, así
que cada movimiento queda en la bitácora con quién lo hizo.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from ..audit import registrar
from ..cedula import es_cedula_valida, normalizar_cedula
from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol
from ..errores import traducir

router = APIRouter(tags=["Administración"])

RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]
Admin = Annotated[dict, Depends(exigir_rol("admin"))]

ROLES = ("admin", "rrhh", "jefe", "empleado", "guardia")


class NuevoUsuario(BaseModel):
    cedula: str
    nombre: str = Field(..., min_length=3, max_length=120)
    email: EmailStr
    telefono: str | None = None
    rol: Literal["admin", "rrhh", "jefe", "empleado", "guardia"] = "empleado"
    cargo: str | None = None
    departamento: str | None = None
    jefe_id: uuid.UUID | None = None
    fecha_ingreso: date
    saldo_inicial: float | None = Field(None, description="Días que RRHH tiene en planilla")

    @field_validator("cedula")
    @classmethod
    def validar(cls, v: str) -> str:
        limpia = normalizar_cedula(v)
        if not es_cedula_valida(limpia):
            raise ValueError("La cédula ingresada no es válida.")
        return limpia


class CambioUsuario(BaseModel):
    nombre: str | None = None
    email: EmailStr | None = None
    telefono: str | None = None
    rol: Literal["admin", "rrhh", "jefe", "empleado", "guardia"] | None = None
    cargo: str | None = None
    departamento: str | None = None
    jefe_id: uuid.UUID | None = None
    activo: bool | None = None
    fecha_salida: date | None = None


class CambioTipoPermiso(BaseModel):
    nombre: str | None = None
    requiere_adjunto: bool | None = None
    requiere_justificacion: bool | None = None
    requiere_firma: bool | None = None
    remunerado: bool | None = None
    descuenta_vacaciones: bool | None = None
    max_dias: float | None = None
    max_horas: float | None = None
    activo: bool | None = None


class NuevoFeriado(BaseModel):
    fecha: date
    nombre: str = Field(..., min_length=3, max_length=100)


class CambioParametro(BaseModel):
    valor: str = Field(..., max_length=100)


# ------------------------------------------------------------------ personal
@router.get("/admin/usuarios")
async def listar_usuarios(usuario: RRHH, q: str = "", incluir_inactivos: bool = False) -> list[dict]:
    return await obtener_todos(
        """
        select u.id, u.cedula, u.nombre, u.email, u.telefono, u.rol::text, u.cargo,
               u.departamento, u.fecha_ingreso, u.fecha_salida, u.activo,
               u.dias_vacaciones, public.anios_cumplidos(u.fecha_ingreso) as anios_servicio,
               j.nombre as jefe_nombre, u.jefe_id,
               (select count(*) from public.requests r where r.user_id = u.id) as solicitudes
        from public.users u
        left join public.users j on j.id = u.jefe_id
        where (%(inactivos)s or u.activo)
          and (%(q)s = '' or u.nombre ilike %(like)s or u.cedula like %(cedula)s)
        order by u.nombre
        limit 500
        """,
        {"inactivos": incluir_inactivos, "q": q.strip(),
         "like": f"%{q.strip()}%", "cedula": f"{normalizar_cedula(q)}%"},
    )


@router.post("/admin/usuarios", status_code=status.HTTP_201_CREATED)
async def crear_usuario(datos: NuevoUsuario, request: Request, usuario: RRHH) -> dict:
    try:
        creado = await obtener_uno(
            """
            insert into public.users
                (cedula, nombre, email, telefono, rol, cargo, departamento, jefe_id, fecha_ingreso)
            values (%(cedula)s, %(nombre)s, %(email)s, %(telefono)s, %(rol)s,
                    %(cargo)s, %(depto)s, %(jefe)s, %(ingreso)s)
            returning id, cedula, nombre
            """,
            {"cedula": datos.cedula, "nombre": datos.nombre.strip(), "email": str(datos.email),
             "telefono": datos.telefono, "rol": datos.rol, "cargo": datos.cargo,
             "depto": datos.departamento, "jefe": datos.jefe_id, "ingreso": datos.fecha_ingreso},
        )
        # El saldo se cuadra con lo que RRHH ya tiene registrado en planilla
        if datos.saldo_inicial is not None:
            await obtener_uno("select public.cargar_saldo_inicial(%s, %s::numeric, 0) as saldo",
                              (creado["id"], datos.saldo_inicial))
        else:
            await obtener_uno("select public.generar_periodos_vacaciones(%s) as ok", (creado["id"],))
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "usuario_creado", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="users", entidad_id=str(creado["id"]),
                    detalle={"cedula": datos.cedula, "rol": datos.rol})
    return {"id": str(creado["id"]), "mensaje": f"{creado['nombre']} quedó registrado."}


@router.patch("/admin/usuarios/{user_id}")
async def editar_usuario(user_id: uuid.UUID, cambios: CambioUsuario,
                         request: Request, usuario: RRHH) -> dict:
    campos = {k: v for k, v in cambios.model_dump(exclude_unset=True).items() if v is not None
              or k in ("fecha_salida", "jefe_id")}
    if not campos:
        raise HTTPException(status_code=422, detail={"mensaje": "No indicó ningún cambio."})

    # Nadie se quita a sí mismo la administración: dejaría el sistema sin dueño
    if str(user_id) == str(usuario["id"]) and campos.get("rol") not in (None, usuario["rol"]):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": "No puede cambiar su propio rol. Pídaselo a otro administrador."},
        )

    asignaciones = ", ".join(f"{k} = %({k})s" for k in campos)
    try:
        actualizado = await obtener_uno(
            f"update public.users set {asignaciones} where id = %(id)s returning id, nombre",
            {**campos, "id": user_id},
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    if actualizado is None:
        raise HTTPException(status_code=404, detail={"mensaje": "No se encontró a esa persona."})

    await registrar(request, "usuario_modificado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="users", entidad_id=str(user_id),
                    detalle={"cambios": list(campos)})
    return {"id": str(actualizado["id"]), "mensaje": f"Datos de {actualizado['nombre']} actualizados."}


@router.post("/admin/usuarios/{user_id}/saldo")
async def ajustar_saldo(user_id: uuid.UUID, saldo: float, request: Request, usuario: RRHH) -> dict:
    """Cuadra el saldo con el que Talento Humano tiene en planilla."""
    try:
        fila = await obtener_uno("select public.cargar_saldo_inicial(%s, %s::numeric, 0) as saldo",
                                 (user_id, saldo))
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "saldo_ajustado", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="users", entidad_id=str(user_id), detalle={"saldo": saldo})
    return {"saldo": float(fila["saldo"]), "mensaje": f"Saldo ajustado a {fila['saldo']} días."}


@router.get("/admin/antiguedades")
async def antiguedades(usuario: RRHH) -> list[dict]:
    """Cuántos días corresponden a cada persona según sus años de servicio."""
    return await obtener_todos(
        """
        select u.id, u.cedula, u.nombre, u.departamento, u.fecha_ingreso,
               public.anios_cumplidos(u.fecha_ingreso) as anios,
               public.dias_por_antiguedad(greatest(public.anios_cumplidos(u.fecha_ingreso), 1)) as dias_por_anio,
               u.dias_vacaciones as saldo,
               (select count(*) from public.vacation_periods p
                 where p.user_id = u.id and p.caducado and p.dias_saldo > 0) as periodos_caducados
        from public.users u
        where u.activo
        order by public.anios_cumplidos(u.fecha_ingreso) desc, u.nombre
        """
    )


# ------------------------------------------------------- tipos de solicitud
@router.get("/admin/tipos-permiso")
async def listar_tipos(usuario: RRHH) -> list[dict]:
    return await obtener_todos(
        """select pt.*, l.norma, l.articulo, l.titulo as articulo_titulo
           from public.permission_types pt
           left join public.legal_references l on l.codigo = pt.legal_ref
           order by pt.orden"""
    )


@router.patch("/admin/tipos-permiso/{tipo_id}")
async def editar_tipo(tipo_id: int, cambios: CambioTipoPermiso,
                      request: Request, usuario: RRHH) -> dict:
    campos = cambios.model_dump(exclude_unset=True)
    if not campos:
        raise HTTPException(status_code=422, detail={"mensaje": "No indicó ningún cambio."})

    asignaciones = ", ".join(f"{k} = %({k})s" for k in campos)
    try:
        fila = await obtener_uno(
            f"update public.permission_types set {asignaciones} where id = %(id)s returning nombre",
            {**campos, "id": tipo_id},
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    if fila is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Ese tipo de solicitud no existe."})

    await registrar(request, "tipo_permiso_modificado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="permission_types", entidad_id=str(tipo_id),
                    detalle={"cambios": campos})
    return {"mensaje": f"«{fila['nombre']}» actualizado."}


# ------------------------------------------------------ días no laborables
@router.get("/admin/feriados")
async def listar_feriados(usuario: RRHH, anio: int | None = None) -> list[dict]:
    return await obtener_todos(
        """select fecha, nombre, activo from public.feriados
           where extract(year from fecha) = coalesce(%s, extract(year from current_date))
           order by fecha""",
        (anio,),
    )


@router.post("/admin/feriados", status_code=status.HTTP_201_CREATED)
async def crear_feriado(datos: NuevoFeriado, request: Request, usuario: RRHH) -> dict:
    try:
        await obtener_uno(
            """insert into public.feriados (fecha, nombre) values (%s, %s)
               on conflict (fecha) do update set nombre = excluded.nombre, activo = true
               returning fecha""",
            (datos.fecha, datos.nombre.strip()),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "feriado_registrado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="feriados", entidad_id=str(datos.fecha),
                    detalle={"nombre": datos.nombre})
    return {"mensaje": f"{datos.nombre} quedó registrado como día no laborable."}


@router.delete("/admin/feriados/{fecha}")
async def quitar_feriado(fecha: date, request: Request, usuario: RRHH) -> dict:
    """Se desactiva en vez de borrarse: los cálculos pasados deben seguir cuadrando."""
    fila = await obtener_uno(
        "update public.feriados set activo = false where fecha = %s returning nombre", (fecha,)
    )
    if fila is None:
        raise HTTPException(status_code=404, detail={"mensaje": "No hay un feriado en esa fecha."})

    await registrar(request, "feriado_desactivado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="feriados", entidad_id=str(fecha))
    return {"mensaje": f"{fila['nombre']} ya no cuenta como día no laborable."}


# ----------------------------------------------------------- configuración
@router.get("/admin/configuracion")
async def configuracion(usuario: RRHH) -> list[dict]:
    return await obtener_todos(
        """select c.clave, c.valor, c.descripcion, c.updated_at,
                  l.norma, l.articulo, l.texto as articulo_texto
           from public.app_config c
           left join public.legal_references l on l.codigo = c.legal_ref
           order by c.clave"""
    )


@router.patch("/admin/configuracion/{clave}")
async def cambiar_parametro(clave: str, cambio: CambioParametro,
                            request: Request, usuario: Admin) -> dict:
    """Solo administración: estos valores deciden derechos de toda la plantilla."""
    anterior = await obtener_uno("select valor from public.app_config where clave = %s", (clave,))
    if anterior is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Ese parámetro no existe."})

    await obtener_uno(
        "update public.app_config set valor = %s where clave = %s returning clave",
        (cambio.valor.strip(), clave),
    )
    await registrar(request, "parametro_modificado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="app_config", entidad_id=clave,
                    detalle={"antes": anterior["valor"], "ahora": cambio.valor})
    return {"mensaje": f"«{clave}» pasó de {anterior['valor']} a {cambio.valor}."}


@router.get("/admin/bitacora")
async def bitacora(usuario: RRHH, limite: int = 100, accion: str | None = None) -> list[dict]:
    """Quién hizo qué. Es la evidencia ante una auditoría."""
    return await obtener_todos(
        """
        select a.id, a.accion, a.entidad, a.entidad_id, a.ip, a.detalle, a.created_at,
               coalesce(u.nombre, a.cedula, 'sistema') as quien
        from public.audit_logs a
        left join public.users u on u.id = a.user_id
        where (%(accion)s::text is null or a.accion like %(patron)s)
        order by a.created_at desc
        limit %(limite)s
        """,
        {"accion": accion, "patron": f"%{accion}%" if accion else None, "limite": min(limite, 500)},
    )


# ------------------------------------------------------------ colaboradores
@router.get("/rrhh/colaboradores")
async def colaboradores(usuario: Annotated[dict, Depends(exigir_rol("jefe", "rrhh", "admin"))]) -> list[dict]:
    """Los períodos de la gente a cargo: lo que un jefe necesita para planificar."""
    if usuario["rol"] == "jefe":
        filtro, parametros = "u.jefe_id = %(jefe)s", {"jefe": usuario["id"]}
    else:
        filtro, parametros = "u.activo", {}

    return await obtener_todos(
        f"""
        select u.id, u.cedula, u.nombre, u.cargo, u.departamento, u.fecha_ingreso,
               public.anios_cumplidos(u.fecha_ingreso) as anios,
               u.dias_vacaciones as saldo,
               public.fines_semana_pendientes(u.id) as fines_semana_pendientes,
               (select min(p.vence_en) from public.vacation_periods p
                 where p.user_id = u.id and not p.caducado and p.dias_saldo > 0) as proximo_vencimiento,
               (select count(*) from public.requests r
                 where r.user_id = u.id and r.estado in ('pendiente_jefe','pendiente_rrhh')) as en_tramite
        from public.users u
        where {filtro} and u.activo
        order by u.nombre
        """,
        parametros,
    )
