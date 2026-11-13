"""Los dos papeles que el colaborador firma y lleva a Talento Humano.

Reglas de emisión, que son lo que distingue un documento del otro:

  TRAZABILIDAD — el historial completo. Se emite UNA SOLA VEZ, al registrarse
  la primera solicitud de vacaciones. No se vuelve a emitir salvo que
  Administración o Talento Humano lo autoricen con un motivo; el parámetro
  `trazabilidad_reemision` puede abrirlo («libre») si la empresa prefiere que
  el colaborador lo reimprima cuando quiera. El ejemplar ya firmado nunca
  cambia: una reemisión es un documento nuevo con folio nuevo.

  SOLICITUD — solo lo pedido en esa sesión. Se emite SIEMPRE, con cada
  solicitud de vacaciones, y se puede reimprimir cuantas veces haga falta: un
  papel que se mojó en la bodega no es un incidente de seguridad. Cada
  impresión queda contada.

Quién puede verlos: el propio colaborador y Talento Humano. Nadie más, ni el
jefe inmediato —lleva el historial completo de vacaciones de la persona, y el
jefe no necesita eso para autorizar cinco días (LOPDP, Art. 10).
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..audit import registrar
from ..db import obtener_todos, obtener_uno
from ..errores import traducir
from ..deps import exigir_rol, usuario_actual
from ..documentos import armar

router = APIRouter(tags=["Papeles para firmar"])

Usuario = Annotated[dict, Depends(usuario_actual)]
RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]


class Reemision(BaseModel):
    motivo: str = Field(..., min_length=15, max_length=400)


CAMPOS = """i.id, i.user_id, i.tipo::text as tipo, i.request_id, i.folio,
            i.emitido_en, i.impresiones, i.ultima_impresion, i.datos,
            i.autorizado_en, i.autorizacion_motivo,
            i.autorizado_por is not null as es_reemision,
            a.nombre as autorizado_por"""


async def _buscar(informe_id: uuid.UUID) -> dict | None:
    return await obtener_uno(
        f"""select {CAMPOS}, u.nombre as de_quien, u.cedula
              from public.informes_firmados i
              join public.users u on u.id = i.user_id
              left join public.users a on a.id = i.autorizado_por
             where i.id = %s""",
        (str(informe_id),))


@router.get("/papeles/mios")
async def mis_papeles(usuario: Usuario) -> dict:
    """Lo que tengo emitido, para volver a imprimirlo."""
    filas = await obtener_todos(
        """select id, tipo::text as tipo, folio, request_id, emitido_en,
                  impresiones, ultima_impresion,
                  autorizado_por is not null as es_reemision
             from public.informes_firmados
            where user_id = %s
            order by emitido_en desc""",
        (usuario["id"],))
    reemision = await obtener_uno(
        "select public.cfg_texto('trazabilidad_reemision') as modo")
    return {
        "papeles": filas,
        # Para que la pantalla sepa si ofrecer el botón o explicar a quién
        # pedírselo, en vez de ofrecerlo y fallar después.
        "trazabilidad_reemision": reemision["modo"],
    }


@router.post("/papeles/trazabilidad")
async def asegurar_trazabilidad(request: Request, usuario: Usuario) -> dict:
    """Mi constancia de goce. Si no la tengo, se emite ahora; si la tengo, es esa.

    Hace falta para quienes ya habían pedido vacaciones antes de que el
    documento existiera: su primera solicitud no lo generó porque no había
    nada que generar.
    """
    fila = await obtener_uno(
        "select id, folio, emitido_en from public.informe_trazabilidad_asegurar(%s)",
        (usuario["id"],))
    await registrar(request, "papel_trazabilidad_emitido", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="informes_firmados",
                    entidad_id=str(fila["id"]))
    return dict(fila)


@router.get("/papeles/{informe_id}.html", response_class=Response)
async def imprimir(informe_id: uuid.UUID, request: Request, usuario: Usuario) -> Response:
    """El documento, listo para imprimir y firmar a mano."""
    informe = await _buscar(informe_id)
    if informe is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Ese documento no existe."})

    propio = str(informe["user_id"]) == str(usuario["id"])
    if not propio and usuario["rol"] not in ("rrhh", "admin"):
        # Ni el jefe inmediato: lleva el historial completo de la persona.
        raise HTTPException(status_code=403, detail={
            "mensaje": "Ese documento es del colaborador y de Talento Humano."})

    # Cada impresión se cuenta: es la diferencia entre «se emitió una vez» y
    # «se imprimió catorce veces», y la segunda es la que cuenta en una
    # auditoría.
    await obtener_uno("select public.informe_impreso(%s)", (str(informe_id),))
    await registrar(request, "papel_impreso", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="informes_firmados",
                    entidad_id=str(informe_id),
                    detalle={"tipo": informe["tipo"], "folio": informe["folio"],
                             "de": informe["de_quien"], "propio": propio})

    return Response(content=armar(informe), media_type="text/html; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


@router.get("/papeles/de-la-solicitud/{request_id}")
async def papel_de_la_solicitud(request_id: uuid.UUID, usuario: Usuario) -> dict:
    """El formulario de una solicitud concreta. Se emite si todavía no existía."""
    duena = await obtener_uno(
        "select user_id, tipo::text as tipo from public.requests where id = %s",
        (str(request_id),))
    if duena is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Esa solicitud no existe."})
    if str(duena["user_id"]) != str(usuario["id"]) and usuario["rol"] not in ("rrhh", "admin"):
        raise HTTPException(status_code=403, detail={
            "mensaje": "Esa solicitud no es suya."})
    if duena["tipo"] != "vacacion":
        raise HTTPException(status_code=422, detail={
            "mensaje": "Este formulario es de vacaciones; esa solicitud es de otro tipo."})

    fila = await obtener_uno(
        "select id, folio, emitido_en from public.informe_solicitud_asegurar(%s)",
        (str(request_id),))
    return dict(fila)


# -------------------------------------------------------- Talento Humano
@router.get("/admin/papeles")
async def listar_papeles(usuario: RRHH, q: str = "", tipo: str | None = None) -> list[dict]:
    """Quién tiene qué emitido, y cuántas veces lo imprimió."""
    condiciones, parametros = [], []
    if q:
        condiciones.append("(v.nombre ilike %s or v.cedula like %s or v.folio ilike %s)")
        parametros += [f"%{q}%", f"{q}%", f"%{q}%"]
    if tipo in ("trazabilidad", "solicitud"):
        condiciones.append("v.tipo = %s")
        parametros.append(tipo)
    donde = ("where " + " and ".join(condiciones)) if condiciones else ""
    return await obtener_todos(
        f"""select v.id, v.user_id, v.cedula, v.nombre, v.departamento, v.tipo, v.folio,
                   v.solicitud_folio, v.emitido_en, v.emitido_por, v.impresiones,
                   v.ultima_impresion, v.es_reemision, v.es_el_vigente,
                   v.autorizado_por, v.autorizacion_motivo
              from public.v_informes_firmados v
              {donde}
             order by v.emitido_en desc
             limit 200""",
        tuple(parametros))


@router.post("/admin/papeles/{user_id}/reemitir-trazabilidad")
async def reemitir(user_id: uuid.UUID, datos: Reemision,
                   request: Request, usuario: RRHH) -> dict:
    """Autoriza una nueva constancia de goce para esa persona.

    No se borra ni se corrige la anterior: está firmada y sigue siendo un
    documento válido. La nueva nace con su folio, con la fecha de hoy y con el
    nombre de quien la autorizó impreso en el pie, que es exactamente lo que
    hace falta para poder explicar en una auditoría por qué hay dos.
    """
    try:
        fila = await obtener_uno(
            "select id, folio from public.informe_trazabilidad_reemitir(%s, %s, %s)",
            (str(user_id), str(usuario["id"]), datos.motivo))
    except Exception as exc:  # la base es la que conoce las reglas
        raise traducir(exc) from exc

    persona = await obtener_uno("select nombre from public.users where id = %s",
                                (str(user_id),))
    await registrar(request, "papel_trazabilidad_reemitido", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="informes_firmados",
                    entidad_id=str(fila["id"]),
                    detalle={"de": persona["nombre"] if persona else None,
                             "folio": fila["folio"], "motivo": datos.motivo})
    return {"id": fila["id"], "folio": fila["folio"],
            "mensaje": f"Nueva constancia {fila['folio']} para "
                       f"{persona['nombre'] if persona else 'el colaborador'}. "
                       "La anterior sigue siendo válida."}
