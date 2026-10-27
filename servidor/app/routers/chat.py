"""Chat entre un colaborador y Talento Humano.

Las dudas cotidianas —cuántos días me quedan, por qué me rechazaron— no
justifican un correo ni una llamada, y hoy terminan en el WhatsApp personal
de alguien de Talento Humano: fuera de todo registro y obligando a la gente
a dar su número particular. Dentro del sistema queda constancia y la
consulta llega al equipo de la región, no a una persona que puede estar de
vacaciones.

Sobre llamadas y videollamadas: los botones abren una sala de Google Meet,
que la empresa ya tiene con Workspace. Montar WebRTC propio —servidor de
señalización, TURN para atravesar los cortafuegos de las bodegas, grabación
y su base legal— es un proyecto aparte, no un botón.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..audit import registrar
from ..db import ejecutar, insertar, nuevo_id, obtener_todos, obtener_uno, transaccion
from ..deps import exigir_rol, usuario_actual
from ..errores import traducir
from ..reglas.personal import rrhh_de_region

router = APIRouter(prefix="/chat", tags=["Chat con Talento Humano"])

RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]


class NuevoMensaje(BaseModel):
    texto: str = Field(..., min_length=1, max_length=2000)
    conversacion_id: str | None = None
    asunto: str | None = Field(None, max_length=120)
    # A qué sede va la consulta. Se toma la de la persona cuando no se dice,
    # que es lo que corresponde casi siempre; pero hay quien trabaja en una
    # región y tiene su expediente en la otra, y quien pregunta por algo que
    # resuelve la otra sede. Antes no había forma de decirlo y la consulta
    # aterrizaba en la bandeja equivocada, donde nadie la esperaba.
    region: Literal["sierra", "costa"] | None = None


def _es_rrhh(usuario: dict) -> bool:
    return usuario["rol"] in ("rrhh", "admin")


async def _puede_ver(usuario: dict, conversacion_id: str) -> dict:
    conversacion = await obtener_uno(
        "select id, user_id, region, estado from conversaciones where id = %s",
        (conversacion_id,),
    )
    if conversacion is None:
        raise HTTPException(status_code=404, detail={"mensaje": "La conversación no existe."})

    propia = str(conversacion["user_id"]) == str(usuario["id"])
    if not propia and not _es_rrhh(usuario):
        # Un jefe no lee lo que su gente consulta: si lo hiciera, nadie
        # volvería a preguntar nada.
        raise HTTPException(status_code=403, detail={"mensaje": "No puede ver esta conversación."})
    return conversacion


@router.get("/mis-conversaciones")
async def mis_conversaciones(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    filas = await obtener_todos(
        """select id, asunto, estado, updated_at, atendida_por, ultimo_mensaje,
                  (select count(*) from mensajes m
                    where m.conversacion_id = v.id and m.leido_en is null and m.es_rrhh)
                    as sin_leer
             from v_conversaciones_bandeja v
            where user_id = %s order by updated_at desc limit 20""",
        (usuario["id"],),
    )
    return [{**f, "id": str(f["id"]), "sin_leer": int(f["sin_leer"] or 0)} for f in filas]


@router.get("/bandeja")
async def bandeja(usuario: RRHH, estado: str = "abierta") -> list[dict]:
    """Lo que espera respuesta en la región de quien consulta."""
    if usuario["rol"] == "admin":
        filtro, parametros = "estado = %s", (estado,)
    else:
        filtro = "estado = %s and region = %s"
        parametros = (estado, usuario.get("region") or "sierra")

    filas = await obtener_todos(
        f"""select id, user_id, persona, cedula, cargo, departamento, ciudad,
                   region, asunto, estado, updated_at, atendida_por, sin_leer,
                   ultimo_mensaje
              from v_conversaciones_bandeja
             where {filtro} order by sin_leer desc, updated_at desc limit 50""",
        parametros,
    )
    return [{**f, "id": str(f["id"]), "user_id": str(f["user_id"]),
             "sin_leer": int(f["sin_leer"] or 0)} for f in filas]


@router.get("/conversaciones/{conversacion_id}")
async def leer(
    conversacion_id: str, usuario: Annotated[dict, Depends(usuario_actual)]
) -> dict:
    conversacion = await _puede_ver(usuario, conversacion_id)
    mensajes = await obtener_todos(
        """select m.id, m.texto, m.es_rrhh, m.created_at, u.nombre as autor
             from mensajes m join users u on u.id = m.autor_id
            where m.conversacion_id = %s order by m.created_at""",
        (conversacion_id,),
    )
    # Se marcan leídos los del otro lado, no los propios.
    await ejecutar(
        """update mensajes set leido_en = NOW(6)
            where conversacion_id = %s and leido_en is null and es_rrhh <> %s""",
        (conversacion_id, _es_rrhh(usuario)),
    )
    return {
        "id": str(conversacion["id"]),
        "estado": conversacion["estado"],
        "mensajes": [{**m, "id": int(m["id"])} for m in mensajes],
    }


@router.post("/mensajes", status_code=status.HTTP_201_CREATED)
async def escribir(
    datos: NuevoMensaje, request: Request,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    try:
        async with transaccion():
            if datos.conversacion_id:
                conversacion = await _puede_ver(usuario, datos.conversacion_id)
            elif _es_rrhh(usuario):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={"mensaje": "Talento Humano responde conversaciones, no las inicia."},
                )
            else:
                nueva = nuevo_id()
                await ejecutar(
                    """insert into conversaciones (id, user_id, region, asunto)
                       values (%s, %s, %s, %s)""",
                    (nueva, usuario["id"],
                     datos.region or usuario.get("region") or "sierra",
                     datos.asunto),
                )
                conversacion = await obtener_uno(
                    "select id, user_id, region, estado from conversaciones where id = %s", (nueva,))

            # Quien responde queda anotado: para el colaborador es saber con
            # quién habla, no un nombre genérico.
            if _es_rrhh(usuario):
                await ejecutar(
                    """update conversaciones set atendida_por = %s
                        where id = %s and atendida_por is null""",
                    (usuario["id"], conversacion["id"]),
                )

            mensaje_id = await insertar(
                """insert into mensajes (conversacion_id, autor_id, es_rrhh, texto)
                   values (%s, %s, %s, %s)""",
                (conversacion["id"], usuario["id"], _es_rrhh(usuario), datos.texto.strip()),
            )
            mensaje = await obtener_uno(
                "select id, texto, es_rrhh, created_at from mensajes where id = %s", (mensaje_id,))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "chat_mensaje", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="conversaciones",
                    entidad_id=str(conversacion["id"]))

    return {
        "conversacion_id": str(conversacion["id"]),
        "mensaje": {**mensaje, "id": int(mensaje["id"]), "autor": usuario["nombre"]},
    }


@router.post("/conversaciones/{conversacion_id}/cerrar")
async def cerrar(conversacion_id: str, usuario: RRHH) -> dict:
    await ejecutar(
        """update conversaciones
              set estado = 'cerrada', cerrada_en = NOW(6), atendida_por = coalesce(atendida_por, %s)
            where id = %s""",
        (usuario["id"], conversacion_id),
    )
    return {"mensaje": "Conversación cerrada. Si la persona escribe de nuevo, se reabre."}


@router.get("/contactos")
async def contactos(usuario: Annotated[dict, Depends(usuario_actual)],
                    region: Literal["sierra", "costa"] | None = None) -> dict:
    """Con quién se puede hablar, y a qué sedes se puede escribir.

    La sede propia viene marcada, pero se devuelven las dos: hay quien
    trabaja en una región y tiene su expediente en la otra. Del equipo se
    dan nombre y cargo, no el correo de cada persona: para eso está el chat,
    que además deja constancia.
    """
    propia = usuario.get("region") or "sierra"
    elegida = region or propia

    filas = [{"nombre": f["nombre"], "cargo": f["cargo"]} for f in await rrhh_de_region(elegida)]
    sedes = await obtener_todos(
        """select codigo, nombre, sede,
                  case sede when 'Quito' then 'UIO' when 'Guayaquil' then 'GYE'
                            else upper(left(sede, 3)) end as sigla
             from regiones where activo order by codigo""")

    datos = await obtener_uno(
        "select nombre, sede from regiones where codigo = %s", (elegida,))
    return {
        "region": datos["nombre"] if datos else "Sierra y Oriente",
        "sede": datos["sede"] if datos else "Quito",
        "codigo": elegida,
        "propia": propia,
        # La suya primero: es la que elige nueve de cada diez veces, y la
        # que está a la izquierda se pulsa sin leer.
        "sedes": sorted(({**s, "es_la_suya": s["codigo"] == propia} for s in sedes),
                        key=lambda s: (not s["es_la_suya"], s["codigo"])),
        "equipo": filas,
    }
