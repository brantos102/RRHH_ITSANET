"""Autenticación por cédula + código de un solo uso enviado al correo.

Decisiones de seguridad:
  * No se revela si una cédula está registrada (evita enumeración de
    empleados, dato personal bajo LOPDP). La respuesta es siempre la misma.
  * El código se guarda solo como hash SHA-256 ligado a la cédula.
  * Límite de envíos por cédula y por IP, e intentos máximos por código.
  * Cada paso queda en `audit_logs` con IP, agente y marca de tiempo.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator

from .. import correo, notificaciones
from ..audit import ip_del_cliente, registrar
from ..cedula import normalizar_cedula
from ..config import get_settings
from ..db import conexion, obtener_todos, obtener_uno
from ..errores import traducir
from ..deps import usuario_actual
from ..schemas import Perfil, RespuestaEnvio, Sesion, SolicitudToken, ValidacionToken
from ..security import comparar_hash, emitir_token, generar_otp, hash_otp
from ..supabase_admin import asegurar_auth_user

log = logging.getLogger("rrhh.auth")
router = APIRouter(prefix="/auth", tags=["Autenticación"])

MENSAJE_GENERICO = (
    "Si la cédula está registrada, enviamos un código al correo institucional."
)


def enmascarar(email: str) -> str:
    """j***z@itsanet.com.ec — reconocible para su dueño, opaco para el resto.

    La máscara es de longitud fija a propósito: si tuviera tantos asteriscos
    como letras, revelaría el largo del correo a quien pruebe cédulas ajenas.
    """
    usuario, _, dominio = email.partition("@")
    if len(usuario) <= 2:
        visible = f"{usuario[:1]}***"
    else:
        visible = f"{usuario[0]}***{usuario[-1]}"
    return f"{visible}@{dominio}"


# --------------------------------------------------------------------------
@router.post("/solicitar-token", response_model=RespuestaEnvio)
async def solicitar_token(datos: SolicitudToken, request: Request) -> RespuestaEnvio:
    settings = get_settings()
    ip = ip_del_cliente(request)

    # --- Límite de envíos: por cédula y por IP ---
    conteo = await obtener_uno(
        """
        select
          count(*) filter (where cedula = %(cedula)s) as por_cedula,
          count(*) filter (where ip = %(ip)s)         as por_ip
        from public.auth_otp
        where created_at > now() - interval '1 hour'
        """,
        {"cedula": datos.cedula, "ip": ip},
    )
    if conteo and conteo["por_cedula"] >= settings.otp_max_envios_hora:
        await registrar(request, "otp_limite_cedula", cedula=datos.cedula)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espere una hora o comuníquese con Talento Humano.",
        )
    if conteo and conteo["por_ip"] >= settings.otp_max_envios_hora * 4:
        await registrar(request, "otp_limite_ip", cedula=datos.cedula)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas solicitudes desde esta red.",
        )

    usuario = await obtener_uno(
        "select id, nombre, email, activo from public.users where cedula = %s",
        (datos.cedula,),
    )

    # Cédula no registrada o empleado inactivo: misma respuesta, sin pistas.
    if usuario is None or not usuario["activo"]:
        await registrar(
            request, "otp_cedula_no_registrada", cedula=datos.cedula,
            detalle={"motivo": "sin_usuario" if usuario is None else "inactivo"},
        )
        return RespuestaEnvio(
            enviado=True, mensaje=MENSAJE_GENERICO, correo=None,
            vigencia_minutos=settings.otp_vigencia_minutos,
        )

    codigo = generar_otp(settings.otp_longitud)

    # Un solo código vigente a la vez: se anulan los anteriores.
    await obtener_uno(
        """
        update public.auth_otp set consumido_en = now()
         where cedula = %s and consumido_en is null and expira_en > now()
        returning id
        """,
        (datos.cedula,),
    )

    await obtener_uno(
        """
        insert into public.auth_otp
            (cedula, user_id, email, code_hash, max_intentos, expira_en, ip, user_agent)
        values (%(cedula)s, %(user_id)s, %(email)s, %(hash)s, %(max_intentos)s,
                now() + make_interval(mins => %(minutos)s), %(ip)s, %(agente)s)
        returning id
        """,
        {
            "cedula": datos.cedula,
            "user_id": usuario["id"],
            "email": usuario["email"],
            "hash": hash_otp(codigo, datos.cedula),
            "max_intentos": settings.otp_max_intentos,
            "minutos": settings.otp_vigencia_minutos,
            "ip": ip,
            "agente": (request.headers.get("user-agent") or "")[:500],
        },
    )

    try:
        await correo.enviar_otp(usuario["email"], usuario["nombre"], codigo)
    except Exception:  # noqa: BLE001 - el detalle va al log, no al cliente
        log.exception("No se pudo enviar el código a %s", enmascarar(usuario["email"]))
        await registrar(request, "otp_error_envio", user_id=usuario["id"], cedula=datos.cedula)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No pudimos enviar el correo. Intente en unos minutos.",
        )

    await registrar(request, "otp_enviado", user_id=usuario["id"], cedula=datos.cedula)

    return RespuestaEnvio(
        enviado=True,
        mensaje=MENSAJE_GENERICO,
        correo=enmascarar(usuario["email"]),
        vigencia_minutos=settings.otp_vigencia_minutos,
    )


# --------------------------------------------------------------------------
@router.post("/validar-token", response_model=Sesion)
async def validar_token(datos: ValidacionToken, request: Request) -> Sesion:
    error_credenciales = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Código incorrecto o expirado.",
    )

    registro = await obtener_uno(
        """
        select id, user_id, code_hash, intentos, max_intentos, expira_en
        from public.auth_otp
        where cedula = %s and consumido_en is null
        order by created_at desc limit 1
        """,
        (datos.cedula,),
    )

    if registro is None:
        await registrar(request, "otp_validacion_sin_codigo", cedula=datos.cedula)
        raise error_credenciales

    if registro["intentos"] >= registro["max_intentos"]:
        await obtener_uno(
            "update public.auth_otp set consumido_en = now() where id = %s returning id",
            (registro["id"],),
        )
        await registrar(request, "otp_intentos_agotados", cedula=datos.cedula,
                        user_id=str(registro["user_id"]))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Superó el número de intentos. Solicite un código nuevo.",
        )

    # El intento se cuenta ANTES de comparar: un fallo del servidor no regala intentos.
    await obtener_uno(
        "update public.auth_otp set intentos = intentos + 1 where id = %s returning id",
        (registro["id"],),
    )

    from datetime import datetime, timezone

    vencido = registro["expira_en"] < datetime.now(timezone.utc)
    if vencido or not comparar_hash(registro["code_hash"], hash_otp(datos.codigo, datos.cedula)):
        await registrar(
            request,
            "otp_codigo_invalido" if not vencido else "otp_codigo_vencido",
            cedula=datos.cedula, user_id=str(registro["user_id"]),
            detalle={"intento": registro["intentos"] + 1},
        )
        raise error_credenciales

    # --- Código correcto ---
    await obtener_uno(
        "update public.auth_otp set consumido_en = now() where id = %s returning id",
        (registro["id"],),
    )

    usuario = await obtener_uno(
        """
        select u.id, u.cedula, u.nombre, u.email, u.rol, u.telefono, u.cargo,
               u.departamento, u.fecha_ingreso, u.dias_vacaciones, u.logros,
               public.anios_cumplidos(u.fecha_ingreso) as anios_servicio,
               j.nombre as jefe_nombre
        from public.users u
        left join public.users j on j.id = u.jefe_id
        where u.id = %s and u.activo
        """,
        (registro["user_id"],),
    )
    if usuario is None:
        raise error_credenciales

    auth_user_id = await asegurar_auth_user(str(usuario["id"]), usuario["email"], usuario["cedula"])

    # Los períodos se generan/actualizan al entrar: el saldo siempre está al día.
    await obtener_uno(
        "select public.generar_periodos_vacaciones(%s) as ok", (usuario["id"],)
    )
    usuario = await obtener_uno(
        """
        select u.id, u.cedula, u.nombre, u.email, u.rol, u.telefono, u.cargo,
               u.departamento, u.fecha_ingreso, u.dias_vacaciones, u.logros,
               public.anios_cumplidos(u.fecha_ingreso) as anios_servicio,
               j.nombre as jefe_nombre
        from public.users u
        left join public.users j on j.id = u.jefe_id
        where u.id = %s
        """,
        (usuario["id"],),
    )

    token, expira = emitir_token(auth_user_id, str(usuario["id"]), usuario["cedula"], usuario["rol"])

    await registrar(request, "sesion_iniciada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"rol": usuario["rol"]})

    return Sesion(
        access_token=token,
        expira_en=expira,
        perfil=Perfil(
            id=str(usuario["id"]),
            cedula=usuario["cedula"],
            nombre=usuario["nombre"],
            email=usuario["email"],
            rol=usuario["rol"],
            cargo=usuario["cargo"],
            departamento=usuario["departamento"],
            telefono=usuario["telefono"],
            fecha_ingreso=usuario["fecha_ingreso"],
            anios_servicio=usuario["anios_servicio"],
            dias_vacaciones=float(usuario["dias_vacaciones"]),
            jefe_nombre=usuario["jefe_nombre"],
            logros=usuario["logros"] or [],
        ),
    )


# --------------------------------------------------------------------------
@router.get("/me", response_model=Perfil)
async def perfil(usuario: Annotated[dict, Depends(usuario_actual)]) -> Perfil:
    return Perfil(
        id=str(usuario["id"]),
        cedula=usuario["cedula"],
        nombre=usuario["nombre"],
        email=usuario["email"],
        rol=usuario["rol"],
        cargo=usuario["cargo"],
        departamento=usuario["departamento"],
        telefono=usuario["telefono"],
        fecha_ingreso=usuario["fecha_ingreso"],
        anios_servicio=usuario["anios_servicio"],
        dias_vacaciones=float(usuario["dias_vacaciones"]),
        jefe_nombre=usuario["jefe_nombre"],
        logros=usuario["logros"] or [],
    )


@router.get("/mi-saldo")
async def mi_saldo(usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    """Desglose del saldo con la explicación y los artículos que lo sustentan."""
    fila = await obtener_uno(
        "select public.explicar_saldo(%s) as detalle", (usuario["id"],)
    )
    return fila["detalle"] if fila else {}


@router.get("/mis-notificaciones")
async def mis_notificaciones(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    return await obtener_todos(
        """
        select n.id, n.tipo, n.severidad, n.titulo, n.mensaje, n.accion_url,
               n.leida_en, n.created_at,
               l.norma, l.articulo, l.titulo as articulo_titulo, l.texto as articulo_texto
        from public.notifications n
        left join public.legal_references l on l.codigo = n.legal_ref
        where n.user_id = %s
        order by n.leida_en nulls first, n.created_at desc
        limit 50
        """,
        (usuario["id"],),
    )


@router.post("/mis-notificaciones/leidas")
async def marcar_notificaciones_leidas(
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Marca como leídas las notificaciones propias.

    Solo las propias: el filtro por `user_id` no es una comodidad sino el
    control de acceso, porque el backend entra con credenciales de servicio y
    no pasa por las políticas de la base.
    """
    filas = await obtener_todos(
        """update public.notifications set leida_en = now()
            where user_id = %s and leida_en is null
        returning id""",
        (usuario["id"],),
    )
    return {"marcadas": len(filas)}


# `response_model=None` explícito: con `from __future__ import annotations`
# el `-> None` llega como la cadena "None", y al resolverla FastAPI obtiene
# NoneType —que es un tipo, no un None— y concluye que la respuesta lleva
# cuerpo, cosa que un 204 prohíbe. El módulo entero fallaba al importarse.
@router.post("/cerrar-sesion", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def cerrar_sesion(request: Request, usuario: Annotated[dict, Depends(usuario_actual)]) -> None:
    """El token es sin estado: el cliente lo descarta. Aquí queda el registro."""
    await registrar(request, "sesion_cerrada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"])


# ---------------------------------------------------------------- alta guiada
# 230 de las 351 personas de la planilla no tienen correo registrado, y el
# acceso es por código al correo. No se les puede avisar en la pantalla de
# acceso sin revelar qué cédulas existen, así que la salida es que completen
# su ficha ellas mismas.
#
# El riesgo es evidente: la cédula es un dato casi público en Ecuador. Si
# bastara con conocerla para fijar un correo, cualquiera se apropiaría de una
# cuenta. Por eso hay tres barreras:
#
#   1. Solo alcanza a quien NO tiene correo real. Quien ya lo tiene queda
#      fuera de este camino, de modo que no sirve para secuestrar cuentas.
#   2. Hay que probar la identidad con dos datos del expediente que Talento
#      Humano ya tiene: fecha de nacimiento y fecha de ingreso.
#   3. El correo se verifica de vuelta: para entrar hay que recibir el código
#      en la dirección declarada. Y Talento Humano recibe aviso de cada alta.

class PruebaIdentidad(BaseModel):
    cedula: str
    fecha_nacimiento: date
    fecha_ingreso: date

    @field_validator("cedula")
    @classmethod
    def validar(cls, v: str) -> str:
        return normalizar_cedula(v)


class FichaInicial(BaseModel):
    token: uuid.UUID
    email: EmailStr
    telefono: str = Field(..., min_length=7, max_length=20,
                          description="Personal. Obligatorio: es como se ubica a la persona")
    emergencia_nombre: str = Field(..., min_length=3, max_length=120)
    # La base guarda el parentesco como enumerado: se acota aquí para que un
    # valor libre dé un mensaje claro y no un error interno.
    emergencia_parentesco: Literal[
        "conyuge", "conviviente", "hijo", "padre", "madre", "hermano",
        "abuelo", "nieto", "suegro", "cunado", "otro",
    ] | None = None
    emergencia_telefono: str = Field(..., min_length=7, max_length=20)
    direccion: str | None = Field(None, max_length=200)
    tipo_sangre: str | None = None

    @field_validator("telefono", "emergencia_telefono")
    @classmethod
    def solo_digitos(cls, v: str | None) -> str | None:
        if v is None:
            return None
        limpio = re.sub(r"\D", "", v)
        if len(limpio) < 7:
            raise ValueError("El teléfono debe tener al menos 7 dígitos")
        return limpio


@router.post("/necesita-ficha")
async def necesita_ficha(datos: SolicitudToken, request: Request) -> dict:
    """¿Esta cédula debe completar su ficha antes de poder entrar?

    Responde lo mismo —falso— tanto si la cédula no existe como si ya tiene
    correo: quien pregunta no aprende nada que no supiera.
    """
    fila = await obtener_uno(
        "select public.puede_completar_ficha(%s) as puede", (datos.cedula,)
    )
    return {"necesita": bool(fila and fila["puede"])}


@router.post("/probar-identidad")
async def probar_identidad(datos: PruebaIdentidad, request: Request) -> dict:
    """Dos datos del expediente a cambio de un permiso de 30 minutos."""
    settings = get_settings()
    ip = ip_del_cliente(request)

    intentos = await obtener_uno(
        """select count(*) as n from public.audit_logs
            where accion = 'alta_identidad_fallida' and ip = %s
              and created_at > now() - interval '1 hour'""",
        (ip,),
    )
    if intentos and intentos["n"] >= 10:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos desde esta red. Comuníquese con Talento Humano.",
        )

    usuario = await obtener_uno(
        """select u.id, u.nombre from public.users u
            where u.cedula = %(cedula)s and u.activo
              and u.correo_pendiente and not u.ficha_completa
              and u.fecha_nacimiento = %(nacimiento)s
              and u.fecha_ingreso = %(ingreso)s""",
        {"cedula": datos.cedula, "nacimiento": datos.fecha_nacimiento,
         "ingreso": datos.fecha_ingreso},
    )

    if usuario is None:
        await registrar(request, "alta_identidad_fallida", cedula=datos.cedula)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"mensaje": "Los datos no coinciden con ningún expediente. "
                               "Verifíquelos o comuníquese con Talento Humano."},
        )

    alta = await obtener_uno(
        """insert into public.altas_pendientes (user_id, cedula, ip)
           values (%s, %s, %s) returning token, expira_en""",
        (usuario["id"], datos.cedula, ip),
    )
    await registrar(request, "alta_identidad_probada", user_id=str(usuario["id"]),
                    cedula=datos.cedula)

    return {
        "token": str(alta["token"]),
        "nombre": usuario["nombre"],
        "minutos": 30,
    }


@router.post("/completar-ficha")
async def completar_ficha(
    datos: FichaInicial, request: Request, tareas: BackgroundTasks
) -> dict:
    """Guarda los datos y deja a la persona en condiciones de entrar.

    El correo declarado NO se da por bueno: para entrar hay que recibir el
    código en esa dirección. Si alguien intentara poner un correo ajeno, no
    podría pasar de aquí, y Talento Humano ve el aviso igual.
    """
    ip = ip_del_cliente(request)
    alta = await obtener_uno(
        """select a.id, a.user_id, a.cedula, u.nombre, u.region
             from public.altas_pendientes a
             join public.users u on u.id = a.user_id
            where a.token = %s and a.usado_en is null and a.expira_en > now()""",
        (datos.token,),
    )
    if alta is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"mensaje": "El permiso para completar sus datos venció. "
                               "Vuelva a empezar desde la pantalla de acceso."},
        )

    ocupado = await obtener_uno(
        "select 1 as x from public.users where email = %s and id <> %s",
        (datos.email, alta["user_id"]),
    )
    if ocupado:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": "Ese correo ya está registrado por otra persona. "
                               "Use su correo institucional o escriba a Talento Humano."},
        )

    try:
        async with conexion() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    update public.users set
                      email = %(email)s, correo_pendiente = false,
                      telefono = %(telefono)s,
                      direccion = coalesce(%(direccion)s, direccion),
                      tipo_sangre = coalesce(%(sangre)s, tipo_sangre),
                      ficha_completa = true, ficha_completada_en = now()
                    where id = %(id)s
                    """,
                    {"email": datos.email, "telefono": datos.telefono,
                     "direccion": datos.direccion, "sangre": datos.tipo_sangre,
                     "id": alta["user_id"]},
                )
                await cur.execute(
                    """
                    insert into public.emergency_contacts
                        (user_id, nombre, parentesco, telefono, es_principal)
                    values (%s, %s, %s::parentesco, %s, true)
                    """,
                    (alta["user_id"], datos.emergencia_nombre.strip(),
                     datos.emergencia_parentesco or "otro", datos.emergencia_telefono),
                )
                await cur.execute(
                    "update public.altas_pendientes set usado_en = now() where id = %s",
                    (alta["id"],),
                )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "alta_ficha_completada", user_id=str(alta["user_id"]),
                    cedula=alta["cedula"], detalle={"correo": datos.email})

    # Talento Humano de su región se entera: un correo que alguien declara de
    # sí mismo merece una mirada, aunque el sistema ya lo verifique de vuelta.
    destinos = await obtener_todos(
        "select email, nombre from public.rrhh_de_region(%s)",
        (alta.get("region") or "sierra",),
    )
    if destinos:
        tareas.add_task(notificaciones.avisar_alta_completada, destinos,
                        alta["nombre"], alta["cedula"], datos.email)

    return {
        "completado": True,
        "cedula": alta["cedula"],
        "mensaje": "Datos guardados. Le enviamos el código de acceso al correo "
                   "que acaba de registrar.",
    }
