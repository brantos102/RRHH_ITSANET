"""Ficha personal: lo que cada quien corrige y lo que Talento Humano valida.

Un teléfono cambia, una dirección cambia, el contacto de emergencia cambia.
Obligar a que Talento Humano teclee cada uno de esos datos para 351 personas
es un cuello de botella sin ningún beneficio: nadie conoce mejor su propio
número. Pero el nombre, el correo o el estado civil sí deben validarse,
porque de ahí salen documentos.

Los cuatro niveles —libre, confirmado, revisado y bloqueado— viven en la
tabla `campos_ficha`, y quien decide es la base: una comprobación que solo
esté en este archivo la puede saltar cualquier cliente alterado.

«Confirmado» es el nivel del correo: lo cambia la propia persona, sin que
nadie apruebe nada, pero no rige hasta que abre el enlace que llega a la
dirección nueva. No hace falta que Talento Humano valide un buzón —nadie
conoce mejor el suyo—; hace falta comprobar que el buzón existe y es suyo,
y eso lo comprueba el buzón mismo.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from .. import notificaciones
from ..audit import ip_del_cliente, registrar
from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol, usuario_actual
from ..errores import traducir

router = APIRouter(tags=["Ficha personal"])

RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]


class CambiosLibres(BaseModel):
    """Solo campos de nivel «libre». La base rechaza cualquier otro."""
    telefono: str | None = Field(None, max_length=20)
    telefono_alternativo: str | None = Field(None, max_length=20)
    direccion: str | None = Field(None, max_length=200)
    tipo_sangre: str | None = Field(None, max_length=3)
    foto_url: str | None = Field(None, max_length=500)


class SolicitudCambio(BaseModel):
    campo: str = Field(..., max_length=40)
    valor: str = Field(..., min_length=1, max_length=200)
    motivo: str | None = Field(None, max_length=300)


class DecisionCambio(BaseModel):
    accion: Literal["aprobar", "rechazar"]
    motivo: str | None = Field(None, max_length=300)


class CorreoNuevo(BaseModel):
    email: EmailStr


class ConfirmacionDatos(BaseModel):
    """Lo que la persona responde sobre su cargo y su jefe.

    Confirmar es tan informativo como corregir: saber que alguien miró su
    cargo y dijo «es este» separa lo verificado de lo que nadie revisó desde
    que se cargó la planilla.
    """
    cargo_correcto: bool
    jefe_correcto: bool
    cargo_propuesto: str | None = Field(None, max_length=120)
    jefe_propuesto_id: str | None = Field(None, max_length=40)


@router.get("/mi-ficha")
async def mi_ficha(usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    """La ficha completa, con qué se puede tocar y qué no, y por qué."""
    persona = await obtener_uno(
        """select u.cedula, u.nombre, u.email::text as email, u.telefono,
                  u.telefono_alternativo, u.direccion, u.ciudad, u.provincia,
                  u.tipo_sangre, u.foto_url, u.fecha_nacimiento, u.estado_civil::text
                    as estado_civil,
                  u.fecha_ingreso, u.cargo, u.departamento, u.bodega, u.cliente,
                  u.centro_costo, u.dias_vacaciones, u.tiene_discapacidad,
                  u.porcentaje_discapacidad, coalesce(u.region, 'sierra') as region,
                  r.nombre as region_nombre, r.sede as region_sede,
                  j.nombre as jefe_nombre, u.jefe_id,
                  u.cargo_confirmado_en, u.jefe_confirmado_en, u.correo_pendiente,
                  (select c.email from public.confirmaciones_correo c
                    where c.user_id = u.id and c.confirmado_en is null
                      and c.expira_en > now()
                    order by c.created_at desc limit 1) as correo_por_confirmar
             from public.users u
             left join public.regiones r on r.codigo = coalesce(u.region, 'sierra')
             left join public.users j on j.id = u.jefe_id
            where u.id = %s""",
        (usuario["id"],),
    )
    campos = await obtener_todos(
        "select campo, etiqueta, nivel, ayuda from public.campos_ficha order by orden"
    )
    contactos = await obtener_todos(
        """select id, nombre, parentesco::text as parentesco, telefono, es_principal
             from public.emergency_contacts where user_id = %s order by es_principal desc""",
        (usuario["id"],),
    )
    pendientes = await obtener_todos(
        """select c.id, c.campo, f.etiqueta, c.valor_anterior, c.valor_nuevo,
                  c.estado, c.motivo_rechazo, c.created_at
             from public.cambios_ficha c
             join public.campos_ficha f on f.campo = c.campo
            where c.user_id = %s order by c.created_at desc limit 20""",
        (usuario["id"],),
    )
    return {
        "persona": {**persona,
                    "dias_vacaciones": float(persona["dias_vacaciones"] or 0),
                    "jefe_id": str(persona["jefe_id"]) if persona["jefe_id"] else None},
        "campos": campos,
        "contactos_emergencia": [{**c, "id": str(c["id"])} for c in contactos],
        "cambios": [{**c, "id": int(c["id"])} for c in pendientes],
    }


@router.patch("/mi-ficha")
async def corregir_ficha(
    datos: CambiosLibres, request: Request,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Los datos que la persona corrige sola, sin esperar a nadie."""
    cambios = {k: v for k, v in datos.model_dump().items() if v is not None}
    if not cambios:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": "No hay nada que cambiar."},
        )

    try:
        await obtener_uno(
            "select public.actualizar_ficha_libre(%s, %s::jsonb) is not null as ok",
            (usuario["id"], json.dumps(cambios)),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "ficha_actualizada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"campos": list(cambios)})
    return {"mensaje": "Sus datos quedaron actualizados."}


@router.post("/mi-ficha/cambios", status_code=status.HTTP_201_CREATED)
async def pedir_cambio(
    datos: SolicitudCambio, request: Request,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Lo que Talento Humano debe validar antes de que rija."""
    try:
        fila = await obtener_uno(
            "select public.solicitar_cambio_ficha(%s, %s, %s, %s) as id",
            (usuario["id"], datos.campo, datos.valor, datos.motivo),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "ficha_cambio_solicitado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"campo": datos.campo})
    return {
        "id": int(fila["id"]),
        "mensaje": "Su solicitud quedó registrada. Talento Humano la revisará; "
                   "mientras tanto sigue vigente el dato anterior.",
    }


@router.post("/mi-ficha/correo", status_code=status.HTTP_202_ACCEPTED)
async def cambiar_correo(
    datos: CorreoNuevo, request: Request, tareas: BackgroundTasks,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Declara una dirección nueva. Rige cuando se abre el enlace, no antes.

    Que el correo anterior siga vigente mientras tanto no es un detalle: si
    se aplicara de inmediato y la dirección tuviera un dedazo, la persona se
    quedaría sin poder recibir ni el código de acceso ni el de confirmación,
    y haría falta que Talento Humano la rescatara a mano.
    """
    try:
        fila = await obtener_uno(
            "select (public.pedir_confirmacion_correo(%s, %s, %s)).token as token",
            (usuario["id"], datos.email, ip_del_cliente(request)),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    tareas.add_task(notificaciones.confirmar_direccion,
                    str(datos.email), usuario["nombre"], str(fila["token"]))

    await registrar(request, "correo_confirmacion_pedida", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"correo": str(datos.email)})
    return {
        "mensaje": f"Le enviamos un enlace a {datos.email}. Ábralo dentro de las "
                   "próximas 24 horas para que la dirección empiece a regir. "
                   "Mientras tanto sigue vigente la anterior.",
    }


@router.post("/mi-ficha/confirmar")
async def confirmar_cargo_y_jefe(
    datos: ConfirmacionDatos, request: Request, tareas: BackgroundTasks,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """«Mi cargo es este y mi jefe es este» —o cuál debería ser.

    Lo que se confirma se marca y se acabó. Lo que se corrige NO se aplica:
    de quién depende cada persona decide a dónde va su solicitud a
    autorizarse, así que lo confirma Talento Humano. La persona señala, la
    empresa resuelve.
    """
    pedidos: list[tuple[str, str]] = []
    errores: list[str] = []

    if datos.cargo_correcto:
        await obtener_uno(
            "update public.users set cargo_confirmado_en = now() where id = %s returning id",
            (usuario["id"],),
        )
    elif datos.cargo_propuesto and datos.cargo_propuesto.strip():
        try:
            await obtener_uno(
                "select public.solicitar_cambio_ficha(%s, 'cargo', %s, %s) as id",
                (usuario["id"], datos.cargo_propuesto.strip(),
                 "Corrección declarada al confirmar los datos"),
            )
            pedidos.append(("Cargo que indica", datos.cargo_propuesto.strip()))
        except Exception as exc:  # noqa: BLE001
            errores.append(str(getattr(traducir(exc), "detail", exc)))
    else:
        errores.append("Indique cuál es su cargo si el registrado no corresponde.")

    if datos.jefe_correcto:
        await obtener_uno(
            "update public.users set jefe_confirmado_en = now() where id = %s returning id",
            (usuario["id"],),
        )
    elif datos.jefe_propuesto_id:
        jefe = await obtener_uno(
            "select nombre from public.v_jefaturas where id = %s", (datos.jefe_propuesto_id,)
        )
        if jefe is None:
            errores.append("La jefatura señalada no está en la lista.")
        else:
            try:
                await obtener_uno(
                    "select public.solicitar_cambio_ficha(%s, 'jefe_id', %s, %s) as id",
                    (usuario["id"], datos.jefe_propuesto_id,
                     "Corrección declarada al confirmar los datos"),
                )
                pedidos.append(("Jefe que indica", jefe["nombre"]))
            except Exception as exc:  # noqa: BLE001
                errores.append(str(getattr(traducir(exc), "detail", exc)))
    else:
        errores.append("Elija quién es su jefe inmediato si el registrado no corresponde.")

    if errores and not pedidos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": " ".join(errores)},
        )

    if pedidos:
        destinos = await obtener_todos(
            "select email, nombre from public.rrhh_de_region(%s)",
            (usuario.get("region") or "sierra",),
        )
        tareas.add_task(notificaciones.avisar_correccion_de_ficha, destinos,
                        usuario["nombre"], usuario["cedula"], pedidos)

    await registrar(request, "ficha_datos_confirmados", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"],
                    detalle={"cargo_ok": datos.cargo_correcto,
                             "jefe_ok": datos.jefe_correcto,
                             "correcciones": len(pedidos)})

    return {
        "mensaje": ("Gracias. Talento Humano revisará lo que indicó; mientras "
                    "tanto sigue vigente el dato anterior."
                    if pedidos else "Sus datos quedaron confirmados."),
        "en_revision": [e for e, _ in pedidos],
        "avisos": errores,
    }


@router.get("/catalogos/jefaturas")
async def jefaturas(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    """Nombre, cargo y área. Nada más: es lo justo para elegir en una lista.

    Ni cédula ni correo ni teléfono de terceros —LOPDP, Art. 10: no se
    recaba ni se expone más de lo que la finalidad exige—.
    """
    filas = await obtener_todos(
        """select id, nombre, cargo, departamento, a_cargo
             from public.v_jefaturas where id <> %s""",
        (usuario["id"],),
    )
    return [{**f, "id": str(f["id"]), "a_cargo": int(f["a_cargo"] or 0)} for f in filas]


@router.get("/rrhh/cambios-ficha")
async def cambios_pendientes(usuario: RRHH) -> list[dict]:
    """Bandeja de Talento Humano, acotada a su región."""
    if usuario["rol"] == "admin":
        filtro, parametros = "true", ()
    else:
        filtro, parametros = "region = %s", (usuario.get("region") or "sierra",)

    filas = await obtener_todos(
        f"""select id, user_id, cedula, persona, departamento, ciudad, region,
                   campo, etiqueta, valor_anterior, valor_nuevo, motivo, created_at,
                   anterior_legible, nuevo_legible
              from public.v_cambios_ficha_pendientes where {filtro}""",
        parametros,
    )
    return [{**f, "id": int(f["id"]), "user_id": str(f["user_id"])} for f in filas]


@router.post("/rrhh/cambios-ficha/{cambio_id}")
async def resolver_cambio(
    cambio_id: int, datos: DecisionCambio, request: Request, usuario: RRHH,
) -> dict:
    if datos.accion == "rechazar" and len((datos.motivo or "").strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": "Indique por qué se rechaza: la persona debe saber qué corregir."},
        )
    try:
        fila = await obtener_uno(
            "select (public.resolver_cambio_ficha(%s, %s, %s, %s)).campo as campo",
            (cambio_id, datos.accion == "aprobar", usuario["id"], datos.motivo),
        )
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "ficha_cambio_resuelto", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"],
                    detalle={"cambio": cambio_id, "accion": datos.accion})
    return {
        "mensaje": ("Cambio aplicado." if datos.accion == "aprobar"
                    else "Cambio rechazado. Se le avisó a la persona."),
        "campo": fila["campo"],
    }
