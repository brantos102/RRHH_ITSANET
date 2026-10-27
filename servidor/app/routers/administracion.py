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
from ..db import booleanos, ejecutar, nuevo_id, obtener_todos, obtener_uno, transaccion
from ..deps import exigir_rol
from ..errores import es_unicidad, restriccion_de, traducir
from ..exportar import Informe, entregar
from ..reglas import administracion as reglas_admin
from ..reglas import periodos
from ..reglas.saldo import saldo_desglosado

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


class CambioArticulo(BaseModel):
    """Cómo se le muestra un artículo al colaborador.

    `resumen` se guarda aunque el modo elegido sea otro: así Talento Humano
    puede redactarlo con calma y recién después decidir mostrarlo.
    """

    visibilidad: Literal["completo", "resumen", "oculto"] | None = None
    resumen: str | None = Field(None, max_length=600)


# ------------------------------------------------------------------ personal
@router.get("/admin/usuarios")
async def listar_usuarios(usuario: RRHH, q: str = "", incluir_inactivos: bool = False) -> list[dict]:
    return await obtener_todos(
        """
        select u.id, u.cedula, u.nombre, u.email, u.telefono, u.rol, u.cargo,
               u.departamento, u.fecha_ingreso, u.fecha_salida, u.activo,
               u.dias_vacaciones, anios_cumplidos(u.fecha_ingreso) as anios_servicio,
               j.nombre as jefe_nombre, u.jefe_id,
               (select count(*) from requests r where r.user_id = u.id) as solicitudes
        from users u
        left join users j on j.id = u.jefe_id
        where (%(inactivos)s or u.activo)
          and (%(q)s = ''
               or u.nombre like %(like)s
               or u.cargo like %(like)s
               or u.departamento like %(like)s
               or u.email like %(like)s
               -- Solo si la búsqueda trae dígitos. `normalizar_cedula` los
               -- deja en nada cuando se busca por texto, y el patrón quedaba
               -- siendo el comodín solo, que coincide con toda la planilla:
               -- buscar «zzzz» devolvía las trescientas cincuenta personas.
               -- (Sin el signo de porcentaje en este comentario a propósito:
               --  el cliente de la base lo lee como marcador de parámetro y rompe la
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


async def _choque_de_ficha(exc: Exception, email: str | None = None,
                           cedula: str | None = None) -> HTTPException:
    """Un choque de unicidad en `users`, dicho con nombre y apellido.

    «El registro ya existe» es cierto y no sirve: quien corrige el correo de
    un colaborador se queda probando a ciegas, porque la ficha con la que
    choca NO está en la pantalla —puede ser de otra área, o estar inactiva—.
    Esto busca al que lo tiene y lo nombra.

    Nombrarlo es seguro aquí: estas rutas son de Talento Humano y
    Administración, que ya ven la lista completa del personal. No se expone
    nada que quien pregunta no pudiera mirar por su cuenta.
    """
    if not es_unicidad(exc):
        return traducir(exc)

    restriccion = restriccion_de(exc)
    if restriccion == "users_email_key" and email:
        # `email` choca ignorando mayúsculas (citext en PostgreSQL, la
        # intercalación _ci en MySQL), así que la búsqueda
        # tiene que hacerlo igual o diría «no encuentro a nadie».
        duena = await obtener_uno(
            """select nombre, cedula, activo, departamento
                 from users where email = %s""", (email,))
        if duena:
            estado = "" if duena["activo"] else " (ficha inactiva)"
            area = f", {duena['departamento']}" if duena["departamento"] else ""
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
                "mensaje": (
                    f"Ese correo ya está registrado a nombre de {duena['nombre']} "
                    f"— cédula {duena['cedula']}{area}{estado}. "
                    "Un correo no puede estar en dos fichas: corrija primero esa."),
                "restriccion": restriccion,
                "lo_tiene": {"nombre": duena["nombre"], "cedula": duena["cedula"],
                             "activo": duena["activo"]}})

    if restriccion == "users_cedula_key" and cedula:
        duena = await obtener_uno(
            "select nombre, activo from users where cedula = %s", (cedula,))
        if duena:
            estado = "" if duena["activo"] else " Esa ficha está inactiva: puede reactivarla."
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail={
                "mensaje": (f"Ya hay una ficha con la cédula {cedula}, "
                            f"a nombre de {duena['nombre']}.{estado}"),
                "restriccion": restriccion})

    return traducir(exc)


@router.post("/admin/usuarios", status_code=status.HTTP_201_CREATED)
async def crear_usuario(datos: NuevoUsuario, request: Request, usuario: RRHH) -> dict:
    nuevo = nuevo_id()
    try:
        # La ficha y sus períodos van juntos: una persona creada sin períodos
        # vería saldo cero hasta que alguien lo notara.
        async with transaccion():
            await ejecutar(
                """
                insert into users
                    (id, cedula, nombre, email, telefono, rol, cargo, departamento, jefe_id, fecha_ingreso)
                values (%(id)s, %(cedula)s, %(nombre)s, %(email)s, %(telefono)s, %(rol)s,
                        %(cargo)s, %(depto)s, %(jefe)s, %(ingreso)s)
                """,
                {"id": nuevo, "cedula": datos.cedula, "nombre": datos.nombre.strip(),
                 "email": str(datos.email), "telefono": datos.telefono, "rol": datos.rol,
                 "cargo": datos.cargo, "depto": datos.departamento, "jefe": datos.jefe_id,
                 "ingreso": datos.fecha_ingreso},
            )
            # El saldo se cuadra con lo que RRHH ya tiene registrado en planilla
            if datos.saldo_inicial is not None:
                await periodos.cargar_saldo_inicial(nuevo, datos.saldo_inicial, 0)
            else:
                await periodos.generar_periodos_vacaciones(nuevo)
        creado = await obtener_uno("select id, cedula, nombre from users where id = %s", (nuevo,))
    except Exception as exc:  # noqa: BLE001
        raise await _choque_de_ficha(exc, email=str(datos.email), cedula=datos.cedula) from exc

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
            """select u.nombre, u.rol,
                      (select count(*) from users s
                        where s.jefe_id = u.id and s.activo) as a_cargo
                 from users u where u.id = %s""",
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
        await ejecutar(f"update users set {asignaciones} where id = %(id)s",
                       {**campos, "id": user_id})
        actualizado = await obtener_uno("select id, nombre from users where id = %s", (user_id,))
    except Exception as exc:  # noqa: BLE001
        raise await _choque_de_ficha(exc, email=campos.get("email")) from exc

    if actualizado is None:
        raise HTTPException(status_code=404, detail={"mensaje": "No se encontró a esa persona."})

    await registrar(request, "usuario_modificado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="users", entidad_id=str(user_id),
                    detalle={"cambios": list(campos)})
    return {"id": str(actualizado["id"]), "mensaje": f"Datos de {actualizado['nombre']} actualizados."}


class NuevoIntegranteRRHH(BaseModel):
    persona_id: uuid.UUID
    region: Literal["sierra", "costa"] = "sierra"


class BajaRRHH(BaseModel):
    rol_destino: Literal["empleado", "guardia", "jefe"] = "empleado"


class CorreoDepartamento(BaseModel):
    """El buzón del departamento, o vacío para no usar ninguno."""

    sierra: str = Field("", max_length=120)
    costa: str = Field("", max_length=120)

    @field_validator("sierra", "costa")
    @classmethod
    def validar(cls, v: str) -> str:
        v = v.strip()
        if not v:
            return ""
        # Sin EmailStr para poder admitir la cadena vacía, que es «ninguno».
        if v.count("@") != 1 or v.startswith("@") or v.endswith("@") or "." not in v.split("@")[1]:
            raise ValueError("Escriba una dirección de correo válida, o déjelo en blanco.")
        return v


@router.get("/admin/talento-humano")
async def listar_talento_humano(usuario: RRHH) -> dict:
    """Quiénes integran el departamento y a qué buzón llegan sus avisos."""
    gente = await obtener_todos("select * from v_talento_humano")
    correos = await obtener_todos(
        """select clave, valor from app_config
            where clave in ('rrhh_correo_sierra', 'rrhh_correo_costa')""")
    por_clave = {c["clave"]: (c["valor"] or "") for c in correos}
    return {
        "integrantes": [{**f, "id": str(f["id"]),
                         "esperando_en_su_region": int(f["esperando_en_su_region"])}
                        for f in booleanos(gente, "puede_recibir")],
        "correos": {"sierra": por_clave.get("rrhh_correo_sierra", ""),
                    "costa": por_clave.get("rrhh_correo_costa", "")},
    }


@router.post("/admin/talento-humano", status_code=status.HTTP_201_CREATED)
async def integrar_a_talento_humano(datos: NuevoIntegranteRRHH, request: Request,
                                    usuario: RRHH) -> dict:
    try:
        fila = {"r": await reglas_admin.rrhh_integrar(datos.persona_id, datos.region,
                                                      usuario["id"])}
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "rrhh_integrante_agregado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="users",
                    entidad_id=str(datos.persona_id), detalle={"region": datos.region})
    return fila["r"]


@router.post("/admin/talento-humano/{user_id}/retirar")
async def retirar_de_talento_humano(user_id: uuid.UUID, datos: BajaRRHH,
                                    request: Request, usuario: RRHH) -> dict:
    """Le quita el acceso a los expedientes de su región.

    Quien deja Talento Humano y conserva el rol sigue viendo las fichas y las
    solicitudes de toda su región. Es el permiso que nadie revisa hasta que
    hay un problema, así que la baja tiene que ser tan fácil como el alta.
    """
    try:
        fila = {"r": await reglas_admin.rrhh_retirar(user_id, datos.rol_destino, usuario["id"])}
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "rrhh_integrante_retirado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="users", entidad_id=str(user_id),
                    detalle={"rol_destino": datos.rol_destino})
    return fila["r"]


@router.patch("/admin/talento-humano/correos")
async def cambiar_correos_departamento(datos: CorreoDepartamento, request: Request,
                                       usuario: RRHH) -> dict:
    """El buzón del departamento, que recibe copia de todo lo que se le dirige.

    No reemplaza a los buzones personales: los suma. Un buzón compartido
    sobrevive a que alguien salga de vacaciones o deje la empresa, que es
    cuando los avisos se pierden sin que nadie se entere.
    """
    for region, valor in (("sierra", datos.sierra), ("costa", datos.costa)):
        await ejecutar("update app_config set valor = %s where clave = %s",
                       (valor, f"rrhh_correo_{region}"))

    await registrar(request, "rrhh_correo_departamento", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="app_config",
                    detalle={"sierra": datos.sierra, "costa": datos.costa})
    return {
        "correos": {"sierra": datos.sierra, "costa": datos.costa},
        "mensaje": ("Buzones del departamento actualizados."
                    if (datos.sierra or datos.costa)
                    else "Sin buzón del departamento: los avisos irán solo a los "
                         "correos personales de quienes lo integran."),
    }


MOTIVOS_SALIDA = (
    "renuncia", "despido_intempestivo", "visto_bueno_empleador",
    "visto_bueno_trabajador", "desahucio", "fin_de_contrato",
    "mutuo_acuerdo", "jubilacion", "fallecimiento", "otro",
)


class BajaColaborador(BaseModel):
    """Cómo terminó la relación laboral. Las causas son las del Código del Trabajo."""

    fecha_salida: date
    motivo: Literal[
        "renuncia", "despido_intempestivo", "visto_bueno_empleador",
        "visto_bueno_trabajador", "desahucio", "fin_de_contrato",
        "mutuo_acuerdo", "jubilacion", "fallecimiento", "otro",
    ]
    detalle: str | None = Field(None, max_length=400)


@router.get("/admin/motivos-salida")
async def motivos_de_salida(usuario: RRHH) -> list[dict]:
    """Las causas, con el artículo que las sustenta.

    Va aquí y no escrito en la pantalla porque de la causa depende lo que
    corresponde liquidar, y quien la elige tiene que ver el sustento en el
    momento de elegirla, no buscarlo después.
    """
    return [
        {"codigo": "renuncia", "nombre": "Renuncia voluntaria",
         "articulo": "Art. 169 núm. 2",
         "ayuda": "El trabajador decide terminar la relación."},
        {"codigo": "despido_intempestivo", "nombre": "Despido intempestivo",
         "articulo": "Art. 188",
         "ayuda": "Terminación unilateral del empleador sin causa legal. Genera indemnización."},
        {"codigo": "visto_bueno_empleador", "nombre": "Visto bueno pedido por la empresa",
         "articulo": "Art. 172",
         "ayuda": "Por causas imputables al trabajador, calificado por el Inspector del Trabajo."},
        {"codigo": "visto_bueno_trabajador", "nombre": "Visto bueno pedido por el trabajador",
         "articulo": "Art. 173",
         "ayuda": "Por causas imputables al empleador, calificado por el Inspector del Trabajo."},
        {"codigo": "desahucio", "nombre": "Desahucio",
         "articulo": "Art. 184",
         "ayuda": "Aviso de terminación al vencimiento del plazo. Genera bonificación."},
        {"codigo": "fin_de_contrato", "nombre": "Terminación del contrato",
         "articulo": "Art. 169 núm. 3",
         "ayuda": "Se cumplió el plazo o concluyó la obra para la que se contrató."},
        {"codigo": "mutuo_acuerdo", "nombre": "Mutuo acuerdo",
         "articulo": "Art. 169 núm. 2",
         "ayuda": "Las dos partes convienen en terminar la relación."},
        {"codigo": "jubilacion", "nombre": "Jubilación",
         "articulo": "Art. 188 y siguientes", "ayuda": "Por edad o por años de servicio."},
        {"codigo": "fallecimiento", "nombre": "Fallecimiento",
         "articulo": "Art. 169 núm. 1",
         "ayuda": "Lo pendiente se liquida con los derechohabientes."},
        {"codigo": "otro", "nombre": "Otra causa",
         "articulo": None, "ayuda": "Detállela: queda en el expediente."},
    ]


@router.post("/admin/usuarios/{user_id}/baja")
async def dar_de_baja(user_id: uuid.UUID, datos: BajaColaborador,
                      request: Request, usuario: RRHH) -> dict:
    """Da de baja con causa y dice qué queda abierto a su nombre.

    No se impide la baja por tener gente a cargo o solicitudes en trámite
    —la persona ya se fue y el expediente tiene que reflejarlo—, pero se
    devuelve para resolverlo ahora en vez de descubrirlo semanas después.
    """
    try:
        fila = {"r": await reglas_admin.dar_de_baja(
            user_id, datos.fecha_salida, datos.motivo, datos.detalle, usuario["id"])}
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "colaborador_dado_de_baja", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="users", entidad_id=str(user_id),
                    detalle={"motivo": datos.motivo,
                             "fecha_salida": str(datos.fecha_salida),
                             "dias_por_liquidar": fila["r"].get("dias_por_liquidar")})
    return fila["r"]


@router.get("/admin/salidas")
async def salidas(usuario: RRHH, limite: int = 200) -> list[dict]:
    """Quiénes salieron, cuándo, por qué y con cuántos días por liquidar."""
    filas = await obtener_todos(
        "select * from v_salidas limit %s", (min(limite, 1000),))
    return [{**f, "id": str(f["id"]),
             "dias_por_liquidar": float(f["dias_por_liquidar"] or 0)} for f in filas]


class NuevaJefatura(BaseModel):
    persona_id: uuid.UUID


class BajaJefatura(BaseModel):
    """A quién pasan las personas y con qué rol se queda quien deja el mando."""

    nuevo_jefe_id: uuid.UUID | None = None
    rol_destino: Literal["empleado", "guardia", "rrhh", "admin"] = "empleado"


@router.get("/admin/jefaturas")
async def listar_jefaturas(usuario: RRHH) -> list[dict]:
    """Quiénes tienen mando hoy, con cuánta gente y cuánto les está esperando."""
    filas = await obtener_todos("select * from v_jefaturas_admin")
    return [{**f, "id": str(f["id"]), "a_cargo": int(f["a_cargo"]),
             "esperando": int(f["esperando"])} for f in filas]


@router.post("/admin/jefaturas", status_code=status.HTTP_201_CREATED)
async def crear_jefatura(datos: NuevaJefatura, request: Request, usuario: RRHH) -> dict:
    try:
        fila = {"r": await reglas_admin.jefatura_crear(datos.persona_id, usuario["id"])}
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
        fila = {"r": await reglas_admin.jefatura_quitar(
            user_id, datos.nuevo_jefe_id, datos.rol_destino, usuario["id"])}
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
        fila = {"saldo": await periodos.cargar_saldo_inicial(str(user_id), saldo, 0)}
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
        from vacation_periods where user_id = %s order by periodo
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
        await periodos.corregir_fines_semana(str(user_id), datos.periodo, datos.consumidos,
                                             datos.motivo, usuario["id"])
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
               anios_cumplidos(u.fecha_ingreso) as anios,
               dias_por_antiguedad(greatest(anios_cumplidos(u.fecha_ingreso), 1)) as dias_por_anio,
               u.dias_vacaciones as saldo,
               (select count(*) from vacation_periods p
                 where p.user_id = u.id and p.caducado and p.dias_saldo > 0) as periodos_caducados
        from users u
        where u.activo
        order by anios_cumplidos(u.fecha_ingreso) desc, u.nombre
        """
    )


# ------------------------------------------------------- tipos de solicitud
@router.get("/admin/tipos-permiso")
async def listar_tipos(usuario: RRHH) -> list[dict]:
    return await obtener_todos(
        """select pt.*, l.norma, l.articulo, l.titulo as articulo_titulo
           from permission_types pt
           left join legal_references l on l.codigo = pt.legal_ref
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
        await ejecutar(f"update permission_types set {asignaciones} where id = %(id)s",
                       {**campos, "id": tipo_id})
        fila = await obtener_uno("select nombre from permission_types where id = %s", (tipo_id,))
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
        """select fecha, nombre, activo from feriados
           where year(fecha) = coalesce(%s, year(current_date()))
           order by fecha""",
        (anio,),
    )


@router.post("/admin/feriados", status_code=status.HTTP_201_CREATED)
async def crear_feriado(datos: NuevoFeriado, request: Request, usuario: RRHH) -> dict:
    try:
        await ejecutar(
            """insert into feriados (fecha, nombre) values (%s, %s)
               on duplicate key update nombre = values(nombre), activo = true""",
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
    fila = await obtener_uno("select nombre from feriados where fecha = %s", (fecha,))
    if fila is not None:
        await ejecutar("update feriados set activo = false where fecha = %s", (fecha,))
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
           from app_config c
           left join legal_references l on l.codigo = c.legal_ref
           order by c.clave"""
    )


@router.patch("/admin/configuracion/{clave}")
async def cambiar_parametro(clave: str, cambio: CambioParametro,
                            request: Request, usuario: Admin) -> dict:
    """Solo administración: estos valores deciden derechos de toda la plantilla."""
    anterior = await obtener_uno("select valor from app_config where clave = %s", (clave,))
    if anterior is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Ese parámetro no existe."})

    await ejecutar("update app_config set valor = %s where clave = %s",
                   (cambio.valor.strip(), clave))
    await registrar(request, "parametro_modificado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="app_config", entidad_id=clave,
                    detalle={"antes": anterior["valor"], "ahora": cambio.valor})
    return {"mensaje": f"«{clave}» pasó de {anterior['valor']} a {cambio.valor}."}


# ------------------------------------------------------------- base legal
# Citar la ley es obligación de la empresa, pero citarla SUELTA es lo que
# arma la discusión en el mostrador: el Art. 75 leído a secas parece una
# invitación a acumular, y el Art. 76 parece un derecho a cobrar en lugar de
# descansar. De ahí los tres modos. Lo que no se ofrece es borrar el
# artículo: los derechos laborales son irrenunciables (Constitución, Art. 326
# núm. 2) y ocultar la norma no quita el derecho, solo quita la prueba de que
# la empresa lo informó.
@router.get("/admin/base-legal")
async def listar_base_legal(usuario: RRHH, categoria: str | None = None) -> list[dict]:
    """Los artículos con su modo actual y quién lo cambió."""
    condicion = "where l.categoria = %s" if categoria else ""
    filas = await obtener_todos(
        f"""select l.codigo, l.norma, l.articulo, l.titulo, l.texto, l.categoria,
                   l.visibilidad, l.resumen, l.visibilidad_en,
                   q.nombre as visibilidad_por,
                   l.codigo in ('CT_ART_69','CT_ART_75','CT_ART_73','CT_ART_74')
                     as sale_en_el_panel
              from legal_references l
              left join users q on q.id = l.visibilidad_por
              {condicion}
             order by l.orden""",
        (categoria,) if categoria else (),
    )
    return booleanos(filas, "sale_en_el_panel")


@router.patch("/admin/base-legal/{codigo}")
async def cambiar_articulo(codigo: str, cambio: CambioArticulo,
                           request: Request, usuario: Admin) -> dict:
    """Solo administración: decide lo que trescientas cincuenta personas leen."""
    antes = await obtener_uno(
        "select articulo, visibilidad, resumen from legal_references where codigo = %s",
        (codigo,))
    if antes is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Ese artículo no existe."})

    resumen = cambio.resumen.strip() if cambio.resumen is not None else None
    modo = cambio.visibilidad or antes["visibilidad"]
    # El resumen vacío con el modo resumen dejaría el artículo en blanco, que
    # es peor que cualquiera de los tres modos. La base lo rechaza igual; aquí
    # se dice en castellano antes de llegar a ella.
    if modo == "resumen" and not (resumen or (antes["resumen"] or "").strip()):
        raise HTTPException(status_code=422, detail={
            "mensaje": f"Para mostrar {antes['articulo']} en resumen hay que escribir el resumen."})

    try:
        await ejecutar(
            """update legal_references
                  set visibilidad     = coalesce(%s, visibilidad),
                      resumen         = coalesce(%s, resumen),
                      visibilidad_en  = NOW(6),
                      visibilidad_por = %s
                where codigo = %s""",
            (cambio.visibilidad, resumen, str(usuario["id"]), codigo))
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    fila = await obtener_uno(
        "select articulo, visibilidad from legal_references where codigo = %s", (codigo,))

    await registrar(request, "base_legal_modificada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="legal_references", entidad_id=codigo,
                    detalle={"antes": {"visibilidad": antes["visibilidad"],
                                       "resumen": antes["resumen"]},
                             "ahora": {"visibilidad": fila["visibilidad"],
                                       "resumen": resumen if resumen is not None else antes["resumen"]}})
    dicho = {"completo": "con su texto completo",
             "resumen": "en resumen",
             "oculto": "oculto"}[fila["visibilidad"]]
    return {"mensaje": f"{fila['articulo']} queda {dicho} para el colaborador."}


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

    filas = await obtener_todos(
        f"""
        select u.id, u.cedula, u.nombre, u.email, u.rol, u.cargo, u.departamento,
               u.bodega, u.centro_costo, u.cliente, u.ciudad, u.region,
               u.fecha_ingreso, anios_cumplidos(u.fecha_ingreso) as anios_servicio,
               j.nombre as jefe_nombre, u.telefono, u.correo_pendiente, u.activo,
               u.dias_vacaciones as saldo_mostrado,
               (select count(*) from vacation_periods p
                 where p.user_id = u.id and not p.caducado) as periodos
        from users u
        left join users j on j.id = u.jefe_id
        where {' and '.join(condiciones)}
        order by u.departamento is null, u.departamento, u.nombre
        """,
        parametros,
    )
    # El desglose es una regla en Python (en PostgreSQL era un LATERAL sobre
    # una función): se calcula por persona. Son unas 350; no pesa.
    for fila in filas:
        d = await saldo_desglosado(fila.pop("id"))
        fila.update(dias_ganados=d["dias_ganados"], dias_en_curso=d["dias_en_curso"],
                    dias_caducados=d["dias_caducados"])
    if solo_revisar:
        filas = [f for f in filas
                 if f["correo_pendiente"] or f["jefe_nombre"] is None
                 or f["saldo_mostrado"] is None
                 or f["saldo_mostrado"] != f["dias_ganados"] + f["dias_en_curso"]]

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
        from audit_logs a
        left join users u on u.id = a.user_id
        where (%(accion)s is null or a.accion like %(patron)s)
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

    filas = await obtener_todos(
        f"""
        select u.id, u.cedula, u.nombre, u.cargo, u.departamento, u.fecha_ingreso,
               anios_cumplidos(u.fecha_ingreso) as anios,
               u.dias_vacaciones as saldo,
               fines_semana_pendientes(u.id) as fines_semana_pendientes,
               -- Nulo mientras la caducidad esté apagada, que es lo normal:
               -- la empresa no extingue días y una fecha de vencimiento que
               -- no va a cumplirse asusta sin motivo.
               (select min(p.vence_en) from vacation_periods p
                 where p.user_id = u.id and not p.caducado and p.dias_saldo > 0) as proximo_vencimiento,
               caducidad_activa() as caducidad_activa,
               (select count(*) from requests r
                 where r.user_id = u.id and r.estado in ('pendiente_jefe','pendiente_rrhh')) as en_tramite
        from users u
        where {filtro} and u.activo
        order by u.nombre
        """,
        parametros,
    )
    return booleanos(filas, "caducidad_activa")


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
    return await obtener_todos("select * from v_lineamientos")


@router.post("/rrhh/lineamientos", status_code=status.HTTP_201_CREATED)
async def lineamiento_crear(
    datos: Lineamiento, request: Request,
    usuario: Annotated[dict, Depends(exigir_rol("rrhh", "admin"))],
) -> dict:
    try:
        fila = await reglas_admin.lineamiento_guardar(
            None, usuario["id"], datos.texto, datos.ambito, datos.orden, datos.activo)
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
        fila = await reglas_admin.lineamiento_guardar(
            lineamiento_id, usuario["id"], datos.texto, datos.ambito, datos.orden, datos.activo)
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
        select cedula, nombre, email, rol, cargo, departamento,
               a_cargo, solicitudes, historicas, que_hacer, user_id
          from v_cuentas_de_prueba""")

    fichas = await obtener_todos("""
        select cedula, nombre, departamento, cargo, rol, lo_principal, huecos,
               sin_correo, sin_cargo, sin_departamento, sin_nacimiento,
               sin_telefono, sin_jefe, user_id
          from v_fichas_incompletas limit 400""")

    jerarquia = await obtener_todos("""
        select cedula, nombre, rol, cargo, departamento, jefe_nombre,
               jefe_activo, a_cargo, problema, user_id
          from v_jerarquia where problema is not null
          order by problema, nombre""")

    sin_entrada = await obtener_todos("""
        select cedula, nombre, departamento, motivo, que_hacer
          from v_sin_entrada
         where sin_fecha_nacimiento or sin_fecha_ingreso""")

    historicas = await obtener_todos("""
        select u.cedula, u.nombre, u.fecha_ingreso, h.id, h.fecha_inicio,
               h.fecha_fin, h.dias, h.fila_origen,
               case when h.fecha_inicio < u.fecha_ingreso then 'anterior a su ingreso'
                    when h.fecha_inicio > current_date()  then 'con fecha futura'
                    when h.dias > (datediff(h.fecha_fin, h.fecha_inicio) + 1) then 'más días que fechas'
                    else 'días cero o negativos' end as problema
          from vacaciones_historicas h
          join users u on u.id = h.user_id
         where h.fecha_inicio < u.fecha_ingreso
            or h.fecha_inicio > current_date()
            or h.dias > (datediff(h.fecha_fin, h.fecha_inicio) + 1)
            or h.dias <= 0
         order by u.nombre, h.fecha_inicio""")

    roles = await obtener_todos("""
        select rol, count(*) as personas
          from users where activo group by rol order by 2 desc""")

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
