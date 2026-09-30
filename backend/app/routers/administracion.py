"""Administración: personal, tipos de solicitud, días no laborables y parámetros.

Todo lo que aquí se cambia altera cómo se calculan derechos de la gente, así
que cada movimiento queda en la bitácora con quién lo hizo.
"""
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from ..audit import registrar
from ..cedula import es_cedula_valida, normalizar_cedula
from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol
from ..errores import traducir
from ..exportar import Informe, entregar

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
          and (%(q)s = ''
               or u.nombre ilike %(like)s
               or u.cargo ilike %(like)s
               or u.departamento ilike %(like)s
               or u.email ilike %(like)s
               -- Solo si la búsqueda trae dígitos. `normalizar_cedula` los
               -- deja en nada cuando se busca por texto, y el patrón quedaba
               -- siendo el comodín solo, que coincide con toda la planilla:
               -- buscar «zzzz» devolvía las trescientas cincuenta personas.
               -- (Sin el signo de porcentaje en este comentario a propósito:
               --  psycopg lo lee como marcador de parámetro y rompe la
               --  consulta aunque esté dentro de un comentario SQL.)
               or (%(cedula)s <> '' and u.cedula like %(cedula_patron)s))
        order by u.nombre
        limit 500
        """,
        {"inactivos": incluir_inactivos, "q": q.strip(),
         "like": f"%{q.strip()}%",
         "cedula": normalizar_cedula(q),
         "cedula_patron": f"{normalizar_cedula(q)}%"},
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

    # Bajarle el rol a una jefatura con gente a cargo la deja sin atribuciones
    # pero con sus colaboradores todavía apuntándole: piden permiso y el
    # pedido no le llega a nadie. Esa baja va por `/admin/jefaturas`, que
    # obliga a decir a quién pasan las personas y los pendientes.
    if campos.get("rol") is not None and campos["rol"] not in ("jefe", "rrhh", "admin"):
        cuenta = await obtener_uno(
            """select u.nombre, u.rol::text as rol,
                      (select count(*) from public.users s
                        where s.jefe_id = u.id and s.activo) as a_cargo
                 from public.users u where u.id = %s""",
            (user_id,),
        )
        if cuenta and cuenta["rol"] in ("jefe", "rrhh", "admin") and cuenta["a_cargo"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"mensaje": (
                    f"{cuenta['nombre']} tiene {cuenta['a_cargo']} persona(s) a cargo. "
                    "Quítele la jefatura desde Configuración › Jefaturas, que le pedirá "
                    "a qué jefatura pasan antes de hacerlo."),
                    "a_cargo": int(cuenta["a_cargo"])},
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


class NuevaJefatura(BaseModel):
    persona_id: uuid.UUID


class BajaJefatura(BaseModel):
    """A quién pasan las personas y con qué rol se queda quien deja el mando."""

    nuevo_jefe_id: uuid.UUID | None = None
    rol_destino: Literal["empleado", "guardia", "rrhh", "admin"] = "empleado"


@router.get("/admin/jefaturas")
async def listar_jefaturas(usuario: RRHH) -> list[dict]:
    """Quiénes tienen mando hoy, con cuánta gente y cuánto les está esperando."""
    filas = await obtener_todos("select * from public.v_jefaturas_admin")
    return [{**f, "id": str(f["id"]), "a_cargo": int(f["a_cargo"]),
             "esperando": int(f["esperando"])} for f in filas]


@router.post("/admin/jefaturas", status_code=status.HTTP_201_CREATED)
async def crear_jefatura(datos: NuevaJefatura, request: Request, usuario: RRHH) -> dict:
    try:
        fila = await obtener_uno("select public.jefatura_crear(%s, %s) as r",
                                 (datos.persona_id, usuario["id"]))
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    if fila["r"].get("cambio"):
        await registrar(request, "jefatura_creada", user_id=str(usuario["id"]),
                        cedula=usuario["cedula"], entidad="users",
                        entidad_id=str(datos.persona_id),
                        detalle={"rol_anterior": fila["r"].get("rol_anterior")})
    return fila["r"]


@router.post("/admin/jefaturas/{user_id}/quitar")
async def quitar_jefatura(user_id: uuid.UUID, datos: BajaJefatura,
                          request: Request, usuario: RRHH) -> dict:
    """Le quita el mando y, en el mismo movimiento, traslada a su gente.

    El traslado y el cambio de rol van en la misma llamada a propósito: si
    fueran dos pasos, entre uno y otro habría gente reportando a alguien que
    ya no puede aprobarle nada.
    """
    try:
        fila = await obtener_uno(
            "select public.jefatura_quitar(%s, %s, %s, %s) as r",
            (user_id, datos.nuevo_jefe_id, datos.rol_destino, usuario["id"]),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "jefatura_quitada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="users", entidad_id=str(user_id),
                    detalle={"nuevo_jefe": str(datos.nuevo_jefe_id or ""),
                             "rol_destino": datos.rol_destino,
                             "personas_movidas": fila["r"].get("personas_movidas"),
                             "solicitudes_movidas": fila["r"].get("solicitudes_movidas")})
    return fila["r"]


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


class CorreccionFDS(BaseModel):
    periodo: int = Field(..., ge=1, le=60)
    consumidos: int = Field(..., ge=0, le=10)
    motivo: str = Field(..., min_length=15, max_length=300)


@router.get("/admin/usuarios/{user_id}/periodos")
async def periodos_de(user_id: uuid.UUID, usuario: RRHH) -> list[dict]:
    """Los períodos de una persona, para revisarlos o corregirlos."""
    return await obtener_todos(
        """
        select periodo, fecha_desde, fecha_hasta, dias_asignados, dias_consumidos,
               dias_saldo, fines_semana_obligatorios, fines_semana_consumidos,
               vence_en, caducado, devengado
        from public.vacation_periods where user_id = %s order by periodo
        """,
        (user_id,),
    )


@router.post("/admin/usuarios/{user_id}/fines-semana")
async def corregir_fines_semana(
    user_id: uuid.UUID, datos: CorreccionFDS, request: Request, usuario: RRHH,
) -> dict:
    """Corrige los fines de semana obligatorios ya consumidos.

    El panel puede decir «le faltan 2 fines de semana» a alguien que ya los
    tomó antes de que existiera el sistema, y entonces la regla le impide
    pedir vacaciones normales por un dato que no refleja la realidad. Esto lo
    arregla, y solo desde aquí: el empleado no toca su propio contador.
    """
    try:
        await obtener_uno(
            "select public.corregir_fines_semana(%s, %s, %s, %s, %s) as p",
            (user_id, datos.periodo, datos.consumidos, datos.motivo, usuario["id"]),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "fines_semana_corregidos", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="vacation_periods",
                    entidad_id=str(user_id),
                    detalle={"periodo": datos.periodo, "consumidos": datos.consumidos})
    return {"mensaje": f"Período {datos.periodo}: quedan "
                       f"{datos.consumidos} fin(es) de semana consumido(s)."}


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


# ------------------------------------------------- cotejo con el archivo de origen
COLUMNAS_COTEJO = [
    ("cedula", "Cédula"), ("nombre", "Nombre"), ("email", "Correo"),
    ("rol", "Perfil"), ("cargo", "Cargo"), ("departamento", "Departamento"),
    ("bodega", "Bodega"), ("centro_costo", "Centro de costo"), ("cliente", "Cliente"),
    ("ciudad", "Ciudad"), ("region", "Región"), ("fecha_ingreso", "Fecha de ingreso"),
    ("anios_servicio", "Años"), ("jefe_nombre", "Jefe inmediato"),
    ("saldo_mostrado", "Saldo en el sistema"), ("dias_ganados", "Días ganados"),
    ("dias_en_curso", "Días del año en curso"), ("dias_caducados", "Días caducados"),
    ("periodos", "Períodos"), ("telefono", "Teléfono"),
    ("correo_pendiente", "Correo por completar"), ("activo", "Activo"),
]


@router.get("/admin/cotejo.{formato}")
async def exportar_cotejo(
    request: Request, usuario: RRHH, formato: Literal["csv", "xlsx", "pdf"],
    departamento: str | None = None,
    solo_revisar: bool = False,
) -> Response:
    """Lo que quedó cargado, para compararlo con el archivo de origen.

    Una carga masiva puede traer errores —una cédula mal tecleada, un jefe que
    no existe en la planilla, una fecha de ingreso distinta entre hojas— y
    revisarlos dentro del sistema, de uno en uno, no es viable con trescientas
    cincuenta personas. Esto baja la tabla completa para cotejarla contra el
    Excel del que salió.

    Con `solo_revisar` se acota a lo que ya se sabe que está incompleto: sin
    correo real, sin jefe, o con el saldo descuadrado.
    """
    condiciones = ["u.activo"]
    parametros: dict = {}
    if departamento:
        condiciones.append("u.departamento = %(depto)s")
        parametros["depto"] = departamento
    if solo_revisar:
        condiciones.append(
            "(u.correo_pendiente or u.jefe_id is null"
            " or u.dias_vacaciones is distinct from d.dias_ganados + d.dias_en_curso)")

    filas = await obtener_todos(
        f"""
        select u.cedula, u.nombre, u.email, u.rol::text as rol, u.cargo, u.departamento,
               u.bodega, u.centro_costo, u.cliente, u.ciudad, u.region::text as region,
               u.fecha_ingreso, public.anios_cumplidos(u.fecha_ingreso) as anios_servicio,
               j.nombre as jefe_nombre, u.telefono, u.correo_pendiente, u.activo,
               u.dias_vacaciones as saldo_mostrado,
               d.dias_ganados, d.dias_en_curso, d.dias_caducados,
               (select count(*) from public.vacation_periods p
                 where p.user_id = u.id and not p.caducado) as periodos
        from public.users u
        left join public.users j on j.id = u.jefe_id
        cross join lateral public.saldo_desglosado(u.id) d
        where {' and '.join(condiciones)}
        order by u.departamento nulls last, u.nombre
        """,
        parametros,
    )

    informe = Informe(
        titulo="Cotejo de la carga inicial",
        columnas=COLUMNAS_COTEJO,
        filas=filas,
        filtros=[("Alcance", departamento or "Toda la planilla activa"),
                 ("Filas", "Solo las que requieren revisión" if solo_revisar else "Todas")],
        generado_por=f"{usuario['nombre']} ({usuario['rol']})",
        nota=("Compare estas filas con el archivo del que salió la carga. «Saldo en el "
              "sistema» debe ser la suma de «Días ganados» y «Días del año en curso»; "
              "si no lo es, avise para recalcularlo."),
    )

    await registrar(request, "cotejo_exportado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"],
                    detalle={"filas": len(filas), "formato": formato,
                             "solo_revisar": solo_revisar})

    return entregar(informe, formato)


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
               -- Nulo mientras la caducidad esté apagada, que es lo normal:
               -- la empresa no extingue días y una fecha de vencimiento que
               -- no va a cumplirse asusta sin motivo.
               (select min(p.vence_en) from public.vacation_periods p
                 where p.user_id = u.id and not p.caducado and p.dias_saldo > 0) as proximo_vencimiento,
               public.caducidad_activa() as caducidad_activa,
               (select count(*) from public.requests r
                 where r.user_id = u.id and r.estado in ('pendiente_jefe','pendiente_rrhh')) as en_tramite
        from public.users u
        where {filtro} and u.activo
        order by u.nombre
        """,
        parametros,
    )


# --------------------------------------------------------------- lineamientos
# El recuadro «Antes de enviar, tenga presente» que ve quien pide vacaciones o
# un permiso estaba escrito dentro del HTML. Son reglas internas de la empresa
# —cuántos días de anticipación, si el período se toma entero— y cambian por
# una circular, no por una versión del sistema. Quien las decide es Talento
# Humano, así que quien las escribe también.


class Lineamiento(BaseModel):
    texto: str | None = Field(None, min_length=5, max_length=400)
    ambito: Literal["vacacion", "permiso", "ambos"] | None = None
    orden: int | None = Field(None, ge=0, le=999)
    activo: bool | None = None


@router.get("/rrhh/lineamientos")
async def lineamientos_listar(
    _: Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]
) -> list[dict]:
    return await obtener_todos("select * from public.v_lineamientos")


@router.post("/rrhh/lineamientos", status_code=status.HTTP_201_CREATED)
async def lineamiento_crear(
    datos: Lineamiento, request: Request,
    usuario: Annotated[dict, Depends(exigir_rol("rrhh", "admin"))],
) -> dict:
    try:
        fila = await obtener_uno(
            """select * from public.lineamiento_guardar(
                   null, %s, %s, %s, %s::smallint, %s)""",
            (usuario["id"], datos.texto, datos.ambito, datos.orden, datos.activo),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    await registrar(request, "lineamiento.crear", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="lineamientos_solicitud",
                    entidad_id=str(fila["id"]), detalle={"texto": datos.texto})
    return dict(fila)


@router.patch("/rrhh/lineamientos/{lineamiento_id}")
async def lineamiento_cambiar(
    lineamiento_id: int, datos: Lineamiento, request: Request,
    usuario: Annotated[dict, Depends(exigir_rol("rrhh", "admin"))],
) -> dict:
    try:
        fila = await obtener_uno(
            """select * from public.lineamiento_guardar(
                   %s, %s, %s, %s, %s::smallint, %s)""",
            (lineamiento_id, usuario["id"], datos.texto, datos.ambito,
             datos.orden, datos.activo),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    await registrar(request, "lineamiento.cambiar", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="lineamientos_solicitud",
                    entidad_id=str(lineamiento_id),
                    detalle=datos.model_dump(exclude_none=True))
    return dict(fila)


# ----------------------------------------------------------------- depuración
# Lo que hay que revisar a mano después de una carga inicial, sin abrir un
# cliente de base de datos. Es de solo lectura: señala, no corrige. Lo que se
# corrige se corrige por las pantallas de siempre, que dejan constancia.


@router.get("/admin/depuracion")
async def depuracion(_: Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]) -> dict:
    """Qué está mal en los datos, ordenado por lo que impide trabajar.

    Las cuentas de prueba van primero, y no por vanidad del orden: al probar
    esto sobre la planilla real aparecieron pegadas a personas de verdad, con
    un correo que no existe y con roles de mando que nadie les dio.
    """
    cuentas = await obtener_todos("""
        select cedula, nombre, email::text as email, rol, cargo, departamento,
               a_cargo, solicitudes, historicas, que_hacer, user_id::text as user_id
          from public.v_cuentas_de_prueba""")

    fichas = await obtener_todos("""
        select cedula, nombre, departamento, cargo, rol, lo_principal, huecos,
               sin_correo, sin_cargo, sin_departamento, sin_nacimiento,
               sin_telefono, sin_jefe, user_id::text as user_id
          from public.v_fichas_incompletas limit 400""")

    jerarquia = await obtener_todos("""
        select cedula, nombre, rol, cargo, departamento, jefe_nombre,
               jefe_activo, a_cargo, problema, user_id::text as user_id
          from public.v_jerarquia where problema is not null
          order by problema, nombre""")

    sin_entrada = await obtener_todos("""
        select cedula, nombre, departamento, motivo, que_hacer
          from public.v_sin_entrada
         where sin_fecha_nacimiento or sin_fecha_ingreso""")

    historicas = await obtener_todos("""
        select u.cedula, u.nombre, u.fecha_ingreso, h.id, h.fecha_inicio,
               h.fecha_fin, h.dias, h.fila_origen,
               case when h.fecha_inicio < u.fecha_ingreso then 'anterior a su ingreso'
                    when h.fecha_inicio > current_date    then 'con fecha futura'
                    when h.dias > (h.fecha_fin - h.fecha_inicio + 1) then 'más días que fechas'
                    else 'días cero o negativos' end as problema
          from public.vacaciones_historicas h
          join public.users u on u.id = h.user_id
         where h.fecha_inicio < u.fecha_ingreso
            or h.fecha_inicio > current_date
            or h.dias > (h.fecha_fin - h.fecha_inicio + 1)
            or h.dias <= 0
         order by u.nombre, h.fecha_inicio""")

    roles = await obtener_todos("""
        select rol::text as rol, count(*) as personas
          from public.users where activo group by rol order by 2 desc""")

    return {
        "cuentas_de_prueba": cuentas,
        "fichas_incompletas": fichas,
        "jerarquia": jerarquia,
        "sin_entrada": sin_entrada,
        "historicas_imposibles": [{**h, "id": int(h["id"])} for h in historicas],
        "roles": [{**r, "personas": int(r["personas"])} for r in roles],
        "resumen": {
            "cuentas_de_prueba": len(cuentas),
            "fichas_incompletas": len(fichas),
            "jerarquia": len(jerarquia),
            "sin_entrada": len(sin_entrada),
            "historicas_imposibles": len(historicas),
        },
    }
