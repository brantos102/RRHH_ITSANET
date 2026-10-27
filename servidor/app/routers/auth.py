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
from ..db import ejecutar, nuevo_id, obtener_todos, obtener_uno, transaccion
from ..errores import traducir
from ..reglas import acceso, ficha, periodos, personal, saldo
from ..deps import usuario_actual
from ..schemas import Perfil, RespuestaEnvio, Sesion, SolicitudToken, ValidacionToken
from ..security import comparar_hash, emitir_token, generar_otp, hash_otp

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
    #
    # Se cuenta lo pedido DESDE EL ÚLTIMO INGRESO, no desde hace una hora:
    # entrar deja la cuenta en cero. Un código que se pidió y se usó es un
    # ingreso normal, no un intento, y contarlo castiga justo a quien usa
    # bien el sistema: alguien que entra, cierra sesión y vuelve a entrar
    # —al probar, al cambiar de pantalla en el teléfono, al compartir el
    # equipo de garita— llegaba al tope en minutos y quedaba una hora fuera.
    #
    # Lo que la regla sigue frenando es lo que debe frenar: pedir códigos una
    # y otra vez sin usar ninguno, que es exactamente la forma del abuso.
    conteo = await acceso.codigos_sin_usar(datos.cedula, ip)
    if conteo and conteo["por_cedula"] >= settings.otp_max_envios_hora:
        await registrar(request, "otp_limite_cedula", cedula=datos.cedula)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Pidió varios códigos y no usó ninguno. Revise su correo —puede "
                   "haber llegado a la carpeta de no deseado— o comuníquese con "
                   "Talento Humano.",
        )
    if conteo and conteo["por_ip"] >= settings.otp_max_envios_hora * 4:
        await registrar(request, "otp_limite_ip", cedula=datos.cedula)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiadas solicitudes desde esta red.",
        )

    usuario = await obtener_uno(
        "SELECT id, nombre, email, activo FROM users WHERE cedula = %s",
        (datos.cedula,),
    )

    # Cédula no registrada, empleado inactivo, o sin correo donde enviar: la
    # misma respuesta para los tres, sin pistas. Quien no tiene correo llega
    # aquí desde que el campo admite nulo —antes traía una dirección
    # inventada—, y sin esta comprobación el registro del código intentaba
    # guardar un nulo y devolvía un 500 al que nadie le encuentra sentido. La
    # pantalla de acceso ya consulta `necesita-ficha` antes y ofrece el alta
    # guiada; esto es la red por debajo.
    if usuario is None or not usuario["activo"] or not usuario["email"]:
        await registrar(
            request, "otp_cedula_no_registrada", cedula=datos.cedula,
            detalle={"motivo": "sin_usuario" if usuario is None
                     else "inactivo" if not usuario["activo"] else "sin_correo"},
        )
        return RespuestaEnvio(
            enviado=True, mensaje=MENSAJE_GENERICO, correo=None,
            vigencia_minutos=settings.otp_vigencia_minutos,
        )

    codigo = generar_otp(settings.otp_longitud)

    # Un solo código vigente a la vez: se anulan los anteriores. ANULADO, no
    # consumido: nadie entró con ellos, y confundir las dos cosas es lo que
    # hacía que pedir un código de nuevo contara como haber entrado.
    await ejecutar(
        """UPDATE auth_otp SET anulado_en = NOW(6)
            WHERE cedula = %s AND consumido_en IS NULL AND anulado_en IS NULL
              AND expira_en > NOW(6)""",
        (datos.cedula,),
    )

    await ejecutar(
        """INSERT INTO auth_otp
             (cedula, user_id, email, code_hash, max_intentos, expira_en, ip, user_agent)
           VALUES (%(cedula)s, %(user_id)s, %(email)s, %(hash)s, %(max_intentos)s,
                   NOW(6) + INTERVAL %(minutos)s MINUTE, %(ip)s, %(agente)s)""",
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
    except Exception as exc:  # noqa: BLE001 - el detalle va al log, no al cliente
        log.exception("No se pudo enviar el código a %s", enmascarar(usuario["email"]))
        # Quien está entrando no puede arreglar el servidor de correo, así
        # que recibe un mensaje genérico con una referencia. Quien lee el
        # registro sí puede, y antes se quedaba con una traza de treinta
        # líneas: aquí queda escrito, bajo la MISMA referencia que ve la
        # pantalla, qué hay que corregir. Basta con
        #     python scripts/ver_logs.py --referencia <la de la pantalla>
        for linea in correo.por_que_no_sale(exc, settings):
            if linea:
                log.error("   %s", linea)
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
        """SELECT id, user_id, code_hash, intentos, max_intentos, expira_en
             FROM auth_otp
            WHERE cedula = %s AND consumido_en IS NULL AND anulado_en IS NULL
            ORDER BY created_at DESC LIMIT 1""",
        (datos.cedula,),
    )

    if registro is None:
        await registrar(request, "otp_validacion_sin_codigo", cedula=datos.cedula)
        raise error_credenciales

    if registro["intentos"] >= registro["max_intentos"]:
        # Anulado: se agotaron los intentos de teclearlo, nadie entró con él.
        await ejecutar("UPDATE auth_otp SET anulado_en = NOW(6) WHERE id = %s", (registro["id"],))
        await registrar(request, "otp_intentos_agotados", cedula=datos.cedula,
                        user_id=str(registro["user_id"]))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Superó el número de intentos. Solicite un código nuevo.",
        )

    # El intento se cuenta ANTES de comparar: un fallo del servidor no regala intentos.
    await ejecutar("UPDATE auth_otp SET intentos = intentos + 1 WHERE id = %s", (registro["id"],))

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
    await ejecutar("UPDATE auth_otp SET consumido_en = NOW(6) WHERE id = %s", (registro["id"],))

    usuario = await obtener_uno(
        """
        select u.id, u.cedula, u.nombre, u.email, u.rol, u.telefono, u.cargo,
               u.departamento, u.fecha_ingreso, u.dias_vacaciones, u.logros,
               anios_cumplidos(u.fecha_ingreso) as anios_servicio,
               j.nombre as jefe_nombre
        from users u
        left join users j on j.id = u.jefe_id
        where u.id = %s and u.activo
        """,
        (registro["user_id"],),
    )
    if usuario is None:
        raise error_credenciales

    # Los períodos se generan/actualizan al entrar: el saldo siempre está al día.
    await periodos.generar_periodos_vacaciones(usuario["id"])
    usuario = await obtener_uno(
        """
        select u.id, u.cedula, u.nombre, u.email, u.rol, u.telefono, u.cargo,
               u.departamento, u.fecha_ingreso, u.dias_vacaciones, u.logros,
               anios_cumplidos(u.fecha_ingreso) as anios_servicio,
               j.nombre as jefe_nombre
        from users u
        left join users j on j.id = u.jefe_id
        where u.id = %s
        """,
        (usuario["id"],),
    )

    token, expira = emitir_token(str(usuario["id"]), usuario["cedula"], usuario["rol"])

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
    return await saldo.explicar_saldo(usuario["id"])


@router.get("/mis-notificaciones")
async def mis_notificaciones(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    return await obtener_todos(
        """
        select n.id, n.tipo, n.severidad, n.titulo, n.mensaje, n.accion_url,
               n.leida_en, n.created_at,
               l.norma, l.articulo, l.titulo as articulo_titulo, l.texto as articulo_texto
        from notifications n
        left join v_legal_colaborador l on l.codigo = n.legal_ref
        where n.user_id = %s
        order by n.leida_en is not null, n.leida_en, n.created_at desc
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
    marcadas = await ejecutar(
        "UPDATE notifications SET leida_en = NOW(6) WHERE user_id = %s AND leida_en IS NULL",
        (usuario["id"],),
    )
    return {"marcadas": marcadas}


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

class ConfirmacionCorreo(BaseModel):
    token: uuid.UUID


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
    # Opcionales en la petición, NO en el resultado: lo que ya consta en el
    # expediente no se vuelve a pedir, y al terminar se comprueba que la
    # persona quede con teléfono y contacto de emergencia, vengan de donde
    # vengan. Pedirle de nuevo a alguien cuyo expediente ya está completo
    # todo lo que el sistema ya sabe es la forma más rápida de que decida
    # que el sistema no sabe nada.
    telefono: str | None = Field(None, min_length=7, max_length=20,
                                 description="Personal. Si ya consta, no hace falta repetirlo")
    emergencia_nombre: str | None = Field(None, min_length=3, max_length=120)
    # La base guarda el parentesco como enumerado: se acota aquí para que un
    # valor libre dé un mensaje claro y no un error interno.
    emergencia_parentesco: Literal[
        "conyuge", "conviviente", "hijo", "padre", "madre", "hermano",
        "abuelo", "nieto", "suegro", "cunado", "otro",
    ] | None = None
    emergencia_telefono: str | None = Field(None, min_length=7, max_length=20)
    direccion: str | None = Field(None, max_length=200)
    tipo_sangre: str | None = None
    # Confirmar el cargo y el jefe es parte del primer ingreso: la planilla
    # se cargó de una hoja de cálculo y nadie la verificó contra quien la
    # vive. Diez personas llegaron sin jefe asignado. Se pregunta aquí, que
    # es el único momento en que se tiene la atención de las 351.
    cargo_correcto: bool | None = None
    jefe_correcto: bool | None = None
    cargo_propuesto: str | None = Field(None, max_length=120)
    jefe_propuesto_id: uuid.UUID | None = None

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
    fila = await obtener_uno("SELECT puede_completar_ficha(%s) AS puede", (datos.cedula,))
    return {"necesita": bool(fila and fila["puede"])}


@router.post("/probar-identidad")
async def probar_identidad(datos: PruebaIdentidad, request: Request) -> dict:
    """Dos datos del expediente a cambio de un permiso de 30 minutos."""
    settings = get_settings()
    ip = ip_del_cliente(request)

    intentos = await obtener_uno(
        """SELECT COUNT(*) AS n FROM audit_logs
            WHERE accion = 'alta_identidad_fallida' AND ip = %s
              AND created_at > NOW(6) - INTERVAL 1 HOUR""",
        (ip,),
    )
    if intentos and intentos["n"] >= 10:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos desde esta red. Comuníquese con Talento Humano.",
        )

    usuario = await obtener_uno(
        """select u.id, u.nombre, u.cargo, u.departamento, u.fecha_ingreso,
                  j.nombre as jefe_nombre,
                  nullif(trim(coalesce(u.telefono, '')), '') as telefono,
                  nullif(trim(coalesce(u.direccion, '')), '') as direccion,
                  u.tipo_sangre,
                  (select c.nombre from emergency_contacts c
                    where c.user_id = u.id and c.es_principal limit 1) as emergencia
             from users u
             left join users j on j.id = u.jefe_id
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

    token_alta = nuevo_id()
    await ejecutar("INSERT INTO altas_pendientes (token, user_id, cedula, ip) VALUES (%s, %s, %s, %s)",
                   (token_alta, usuario["id"], datos.cedula, ip))
    alta = {"token": token_alta}
    await registrar(request, "alta_identidad_probada", user_id=str(usuario["id"]),
                    cedula=datos.cedula)

    return {
        "token": str(alta["token"]),
        "nombre": usuario["nombre"],
        # Lo que hay que confirmar. Se devuelve aquí, ya probada la
        # identidad, y no en la pantalla de acceso: el cargo y el área de
        # alguien no son datos que deba poder leer quien solo tecleó una
        # cédula, que en Ecuador es casi pública.
        "cargo": usuario["cargo"],
        "departamento": usuario["departamento"],
        "jefe": usuario["jefe_nombre"],
        "fecha_ingreso": usuario["fecha_ingreso"],
        # Qué consta ya en el expediente, para no volvérselo a pedir. Se
        # devuelven los valores de lo que la propia persona declaró —su
        # teléfono, su dirección— y solo el NOMBRE del contacto de
        # emergencia: basta para decirle «ya lo tenemos» sin exponer de más.
        "ya_consta": {
            "telefono": usuario["telefono"],
            "direccion": usuario["direccion"],
            "tipo_sangre": usuario["tipo_sangre"],
            "emergencia": usuario["emergencia"],
        },
        "minutos": 30,
    }


@router.get("/alta/jefaturas")
async def jefaturas_para_el_alta(token: uuid.UUID) -> list[dict]:
    """La lista para elegir jefe mientras se completa la ficha.

    Solo con un permiso de alta vivo, y solo nombre, cargo y área: quien
    llegó hasta aquí ya probó su identidad con dos datos del expediente, y
    aun así no ve ni cédulas ni correos de terceros (LOPDP, Art. 10).
    """
    alta = await obtener_uno(
        """SELECT 1 AS x FROM altas_pendientes
            WHERE token = %s AND usado_en IS NULL AND expira_en > NOW(6)""",
        (str(token),),
    )
    if alta is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"mensaje": "El permiso para completar sus datos venció."},
        )
    filas = await obtener_todos(
        "SELECT id, nombre, cargo, departamento FROM v_jefaturas"
    )
    return [{**f, "id": str(f["id"])} for f in filas]


@router.post("/confirmar-correo")
async def confirmar_correo(datos: ConfirmacionCorreo, request: Request,
                           tareas: BackgroundTasks) -> dict:
    """El enlace que llegó a la dirección nueva. Recién aquí empieza a regir.

    Es POST y no GET aunque venga de un enlace: los antivirus de correo y
    los previsualizadores abren los enlaces de los mensajes que analizan, y
    un GET con efecto los dejaría aplicar el cambio sin que la persona haya
    hecho nada. La página de confirmación hace el POST cuando alguien
    realmente la abre.
    """
    anterior = await obtener_uno(
        """select u.email, u.nombre
             from confirmaciones_correo c
             join users u on u.id = c.user_id
            where c.token = %s and c.confirmado_en is null""",
        (str(datos.token),),
    )

    resultado = await ficha.confirmar_correo(datos.token)

    if not resultado.get("confirmado"):
        await registrar(request, "correo_confirmacion_fallida")
        raise HTTPException(status_code=status.HTTP_410_GONE,
                            detail={"mensaje": resultado.get("motivo")})

    # Al buzón anterior: si el cambio no fue suyo, tiene que enterarse por
    # una vía que quien lo hizo no controla.
    if anterior and anterior["email"]:
        tareas.add_task(notificaciones.avisar_correo_confirmado,
                        anterior["email"], resultado["nombre"], resultado["email"])

    await registrar(request, "correo_confirmado", detalle={"correo": resultado["email"]})
    return {
        "confirmado": True,
        "nombre": resultado["nombre"],
        "email": resultado["email"],
        "mensaje": "Su correo quedó confirmado. Desde ahora recibirá ahí el "
                   "código de acceso y los avisos de sus solicitudes.",
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
             from altas_pendientes a
             join users u on u.id = a.user_id
            where a.token = %s and a.usado_en is null and a.expira_en > NOW(6)""",
        (str(datos.token),),
    )
    if alta is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={"mensaje": "El permiso para completar sus datos venció. "
                               "Vuelva a empezar desde la pantalla de acceso."},
        )

    # Opcional en la petición no significa opcional en el resultado: lo que
    # no llegó tiene que constar ya. Se comprueba contra el expediente, no
    # contra el formulario, que es lo que permite no repreguntar.
    ya = await obtener_uno(
        """select nullif(trim(coalesce(u.telefono, '')), '') as telefono,
                  (select 1 from emergency_contacts c
                    where c.user_id = u.id and c.es_principal limit 1) as emergencia
             from users u where u.id = %s""",
        (alta["user_id"],),
    ) or {}
    faltan = []
    if not (datos.telefono or ya.get("telefono")):
        faltan.append("su teléfono")
    if not ((datos.emergencia_nombre and datos.emergencia_telefono) or ya.get("emergencia")):
        faltan.append("un contacto de emergencia")
    if faltan:
        raise HTTPException(
            status_code=422,
            detail={"mensaje": f"Falta {' y '.join(faltan)}. Son los datos con los que "
                               "se le ubica si ocurre algo durante la jornada."},
        )

    ocupado = await obtener_uno(
        "SELECT 1 AS x FROM users WHERE email = %s AND id <> %s",
        (datos.email, alta["user_id"]),
    )
    if ocupado:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"mensaje": "Ese correo ya está registrado por otra persona. "
                               "Use su correo institucional o escriba a Talento Humano."},
        )

    try:
        async with transaccion():
            await ejecutar(
                """UPDATE users SET
                     email = %(email)s, correo_pendiente = FALSE,
                     telefono = COALESCE(%(telefono)s, telefono),
                     direccion = COALESCE(%(direccion)s, direccion),
                     tipo_sangre = COALESCE(%(sangre)s, tipo_sangre),
                     ficha_completa = TRUE, ficha_completada_en = NOW(6)
                   WHERE id = %(id)s""",
                {"email": datos.email, "telefono": datos.telefono,
                 "direccion": datos.direccion, "sangre": datos.tipo_sangre,
                 "id": alta["user_id"]},
            )
            # Se actualiza si ya había uno principal, en vez de insertar a
            # ciegas: Talento Humano puede reabrir un alta, y el segundo
            # intento chocaba con el índice único de «un principal por
            # persona» y moría con un «El registro ya existe» que no le dice
            # nada a nadie. Solo si la persona declaró uno nuevo: pisar con
            # nulos el que ya constaba borraría un dato para avisar a su familia.
            if datos.emergencia_nombre and datos.emergencia_telefono:
                await ejecutar(
                    """INSERT INTO emergency_contacts
                         (user_id, nombre, parentesco, telefono, es_principal)
                       VALUES (%s, %s, %s, %s, TRUE)
                       ON DUPLICATE KEY UPDATE nombre = VALUES(nombre),
                         parentesco = VALUES(parentesco), telefono = VALUES(telefono)""",
                    (alta["user_id"], datos.emergencia_nombre.strip(),
                     datos.emergencia_parentesco or "otro", datos.emergencia_telefono),
                )
            if datos.cargo_correcto:
                await ejecutar("UPDATE users SET cargo_confirmado_en = NOW(6) WHERE id = %s",
                               (alta["user_id"],))
            if datos.jefe_correcto:
                await ejecutar("UPDATE users SET jefe_confirmado_en = NOW(6) WHERE id = %s",
                               (alta["user_id"],))
            await ejecutar("UPDATE altas_pendientes SET usado_en = NOW(6) WHERE id = %s", (alta["id"],))
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    # Las correcciones van FUERA de la transacción de arriba y a propósito:
    # si la jefatura señalada resultara inválida, sería absurdo perder por eso
    # el correo y el teléfono que la persona acaba de escribir. Lo que no se
    # pueda registrar se devuelve como aviso, no como error.
    pedidos: list[tuple[str, str]] = []
    avisos: list[str] = []

    if datos.cargo_correcto is False and (datos.cargo_propuesto or "").strip():
        try:
            await ficha.solicitar_cambio_ficha(
                alta["user_id"], "cargo", datos.cargo_propuesto.strip(),
                "Corrección declarada al completar la ficha")
            pedidos.append(("Cargo que indica", datos.cargo_propuesto.strip()))
        except Exception:  # noqa: BLE001
            avisos.append("No se pudo registrar la corrección del cargo. "
                          "Puede volver a pedirla desde su ficha.")

    if datos.jefe_correcto is False and datos.jefe_propuesto_id:
        jefe = await obtener_uno(
            "SELECT nombre FROM v_jefaturas WHERE id = %s",
            (str(datos.jefe_propuesto_id),),
        )
        if jefe is None:
            avisos.append("La jefatura señalada no está en la lista vigente.")
        else:
            try:
                await ficha.solicitar_cambio_ficha(
                    alta["user_id"], "jefe_id", str(datos.jefe_propuesto_id),
                    "Corrección declarada al completar la ficha")
                pedidos.append(("Jefe que indica", jefe["nombre"]))
            except Exception:  # noqa: BLE001
                avisos.append("No se pudo registrar la corrección del jefe. "
                              "Puede volver a pedirla desde su ficha.")

    await registrar(request, "alta_ficha_completada", user_id=str(alta["user_id"]),
                    cedula=alta["cedula"],
                    detalle={"correo": datos.email, "correcciones": len(pedidos)})

    # Talento Humano de su región se entera: un correo que alguien declara de
    # sí mismo merece una mirada, aunque el sistema ya lo verifique de vuelta.
    destinos = [{"email": d["email"], "nombre": d["nombre"]}
                for d in await personal.rrhh_de_region(alta.get("region") or "sierra")]
    if destinos:
        tareas.add_task(notificaciones.avisar_alta_completada, destinos,
                        alta["nombre"], alta["cedula"], datos.email)
        if pedidos:
            tareas.add_task(notificaciones.avisar_correccion_de_ficha, destinos,
                            alta["nombre"], alta["cedula"], pedidos)

    return {
        "completado": True,
        "cedula": alta["cedula"],
        "en_revision": [etiqueta for etiqueta, _ in pedidos],
        "avisos": avisos,
        "mensaje": "Datos guardados. Le enviamos el código de acceso al correo "
                   "que acaba de registrar."
                   + (" Lo que indicó como incorrecto queda a la espera de que "
                      "Talento Humano lo confirme." if pedidos else ""),
    }
