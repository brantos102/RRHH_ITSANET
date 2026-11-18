"""Historial de vacaciones por año, su descarga en Excel y PDF, y la
revisión (refutación) de un registro con evidencia.

  · Cualquier persona ve y descarga SU historial.
  · Talento Humano y administración ven y descargan el de cualquiera (queda
    en la bitácora: son datos personales de otra persona).
  · Refutar un registro exige evidencia (un correo exportado a PDF, una
    captura, un documento). El pedido llega por correo al departamento de
    Talento Humano con la evidencia adjunta, y a la bandeja del sistema.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, Response,
                     UploadFile)
from pydantic import BaseModel, Field

from .. import historial_archivos, notificaciones
from ..audit import registrar
from ..db import ejecutar, insertar, obtener_todos, obtener_uno
from ..deps import exigir_rol, usuario_actual
from ..reglas import historial as reglas_historial
from ..reglas import personal
from ..storage import leer_adjunto, nombre_seguro, subir_adjunto

log = logging.getLogger("rrhh.historial")
router = APIRouter(tags=["Historial de vacaciones"])
Usuario = Annotated[dict, Depends(usuario_actual)]
TH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]

# La evidencia suele ser un correo: exportado a PDF, una captura, o el
# propio archivo del correo (.eml de Outlook web/Gmail, .msg de Outlook).
EXTENSIONES = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
               ".webp": "image/webp", ".heic": "image/heic", ".eml": "message/rfc822",
               ".msg": "application/vnd.ms-outlook"}
TAMANO_MAXIMO = 10 * 1024 * 1024
ADJUNTAR_HASTA = 8 * 1024 * 1024   # más que eso no se adjunta al correo: se ve en el sistema


# ---------------------------------------------------------------- consulta
@router.get("/mi-historial/anual")
async def mi_historial_anual(usuario: Usuario) -> dict:
    return await reglas_historial.construir(usuario["id"])


@router.get("/mi-historial/{formato}", response_class=Response)
async def descargar_mi_historial(formato: Literal["excel", "pdf"], request: Request, usuario: Usuario) -> Response:
    datos = await reglas_historial.construir(usuario["id"])
    await registrar(request, "historial_descargado", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    detalle={"formato": formato, "propio": True})
    entregar = historial_archivos.a_excel if formato == "excel" else historial_archivos.a_pdf
    return entregar(datos, usuario["nombre"])


@router.get("/rrhh/personas/{user_id}/historial")
async def historial_de(user_id: uuid.UUID, request: Request, usuario: TH) -> dict:
    datos = await reglas_historial.construir(str(user_id))
    if not datos:
        raise HTTPException(status_code=404, detail={"mensaje": "No se encontró a esa persona."})
    await registrar(request, "historial_consultado", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="users", entidad_id=str(user_id))
    return datos


@router.get("/rrhh/personas/{user_id}/historial/{formato}", response_class=Response)
async def descargar_historial_de(user_id: uuid.UUID, formato: Literal["excel", "pdf"], request: Request,
                                 usuario: TH) -> Response:
    datos = await reglas_historial.construir(str(user_id))
    if not datos:
        raise HTTPException(status_code=404, detail={"mensaje": "No se encontró a esa persona."})
    await registrar(request, "historial_descargado", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="users", entidad_id=str(user_id), detalle={"formato": formato, "propio": False})
    entregar = historial_archivos.a_excel if formato == "excel" else historial_archivos.a_pdf
    return entregar(datos, usuario["nombre"])


# ---------------------------------------------------- refutar un registro
async def _registro_propio(user_id, origen: str, ref: str) -> dict:
    if origen == "historico":
        fila = await obtener_uno(
            "SELECT id, fecha_inicio, fecha_fin, dias FROM vacaciones_historicas WHERE id = %s AND user_id = %s",
            (ref, str(user_id))) if ref.isdigit() else None
        texto = "Registro de Talento Humano (antes del sistema)"
    else:
        fila = await obtener_uno(
            """SELECT id, folio, fecha_inicio, fecha_fin, dias_solicitados AS dias FROM requests
                WHERE id = %s AND user_id = %s AND estado IN ('aprobado', 'pendiente_anulacion')""",
            (ref, str(user_id)))
        texto = f"Solicitud Nº {fila['folio']}" if fila else ""
    if fila is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Ese registro no está en su historial."})
    return {**fila, "origen_texto": texto}


@router.post("/mi-historial/revisar")
async def refutar(request: Request, tareas: BackgroundTasks, usuario: Usuario,
                  origen: Literal["historico", "solicitud"] = Form(...), ref: str = Form(..., max_length=40),
                  motivo: str = Form(..., max_length=2000),
                  archivos: list[UploadFile] = File(default=[])) -> dict:
    """«No tomé esos días.» Con evidencia, siempre: sin ella Talento Humano
    no tiene con qué revisar, y el pedido solo generaría idas y vueltas."""
    motivo = " ".join(motivo.split())
    if len(motivo) < 15:
        raise HTTPException(status_code=422, detail={
            "mensaje": "Explique qué no corresponde, con al menos 15 caracteres."})
    archivos = [a for a in archivos if a and a.filename]
    if not archivos:
        raise HTTPException(status_code=422, detail={
            "mensaje": "Adjunte la evidencia: el correo (exportado a PDF o el archivo .eml/.msg), una captura "
                       "o el documento que muestra que no tomó esos días."})
    if len(archivos) > 5:
        raise HTTPException(status_code=422, detail={"mensaje": "Hasta 5 archivos por revisión."})
    registro = await _registro_propio(usuario["id"], origen, ref)
    if await obtener_uno(
            """SELECT 1 AS x FROM refutaciones_historial WHERE user_id = %s AND origen = %s AND estado = 'pendiente'
                  AND COALESCE(historico_id, request_id) = %s""", (str(usuario["id"]), origen, ref)):
        raise HTTPException(status_code=409, detail={
            "mensaje": "Ya pidió revisar ese registro y Talento Humano todavía no responde."})

    leidos = []
    for a in archivos:
        ext = Path(a.filename or "").suffix.lower()
        if ext not in EXTENSIONES:
            raise HTTPException(status_code=422, detail={
                "mensaje": f"«{a.filename}»: se aceptan PDF, imágenes (JPG, PNG, WebP, HEIC) o correos (.eml, .msg)."})
        contenido = await a.read()
        if not contenido:
            raise HTTPException(status_code=422, detail={"mensaje": f"«{a.filename}» está vacío."})
        if len(contenido) > TAMANO_MAXIMO:
            raise HTTPException(status_code=413, detail={"mensaje": f"«{a.filename}» pesa más de 10 MB."})
        leidos.append((a.filename, contenido, EXTENSIONES[ext]))

    rid = await insertar(
        """INSERT INTO refutaciones_historial (user_id, origen, historico_id, request_id, fecha_inicio, fecha_fin,
                                              dias, motivo)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (str(usuario["id"]), origen, int(ref) if origen == "historico" else None,
         ref if origen == "solicitud" else None, registro["fecha_inicio"], registro["fecha_fin"],
         registro["dias"], motivo))
    for nombre, contenido, mime in leidos:
        ruta = f"{usuario['id']}/revisiones/{rid}/{uuid.uuid4().hex}-{nombre_seguro(nombre)}"
        await subir_adjunto(ruta, contenido, mime)
        await ejecutar(
            """INSERT INTO refutacion_evidencias (refutacion_id, storage_path, nombre_archivo, mime_type,
                                                 tamano_bytes, hash_sha256)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (rid, ruta, nombre, mime, len(contenido), hashlib.sha256(contenido).hexdigest()))

    persona = await obtener_uno("SELECT nombre, cedula, email, region FROM users WHERE id = %s", (usuario["id"],))
    equipo = await personal.rrhh_de_region(persona["region"])
    for p in equipo:
        await ejecutar(
            """INSERT INTO notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
               VALUES (%s, 'solicitud_pendiente', 'advertencia', %s, %s, 'refutaciones_historial', %s,
                       '/administracion.html#pendientes')""",
            (str(p["id"]), f"Revisión del historial: {persona['nombre']}",
             f"Refuta {float(registro['dias']):g} día(s) del {registro['fecha_inicio']:%d/%m/%Y}.", str(rid)))
    adjuntos = leidos if sum(len(c) for _, c, _ in leidos) <= ADJUNTAR_HASTA else []
    tareas.add_task(notificaciones.avisar_revision_historial,
                    [{"email": p["email"], "nombre": p["nombre"]} for p in equipo], persona["region"],
                    persona, registro, motivo, rid, adjuntos, persona["email"])
    await registrar(request, "historial_refutado", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="refutaciones_historial", entidad_id=str(rid),
                    detalle={"origen": origen, "ref": ref, "archivos": [n for n, _, _ in leidos]})
    return {"id": rid, "mensaje": f"Enviado a Talento Humano (Nº R-{rid}), con la evidencia. "
                                  "Le responderán por correo y lo verá en su historial."}


# --------------------------------------------- bandeja de Talento Humano
@router.get("/rrhh/revisiones-historial")
async def revisiones(usuario: TH, estado: Literal["pendiente", "aceptada", "rechazada", "todas"] = "pendiente") -> list:
    filtro_region = ("TRUE" if usuario["rol"] == "admin" else
                     "(COALESCE(u.region, 'sierra') = %(r)s OR COALESCE(u.region, 'sierra') NOT IN "
                     "(SELECT DISTINCT region FROM v_rrhh_por_region))")
    filas = await obtener_todos(
        f"""SELECT f.id, f.origen, f.historico_id, f.request_id, f.fecha_inicio, f.fecha_fin, f.dias, f.motivo,
                   f.estado, f.respuesta, f.created_at, f.resuelto_en, u.id AS user_id, u.nombre, u.cedula,
                   u.departamento, q.nombre AS resuelto_por, r.folio
              FROM refutaciones_historial f
              JOIN users u ON u.id = f.user_id
              LEFT JOIN users q ON q.id = f.resuelto_por
              LEFT JOIN requests r ON r.id = f.request_id
             WHERE {filtro_region} AND (%(e)s = 'todas' OR f.estado = %(e)s)
             ORDER BY f.created_at DESC LIMIT 200""",
        {"r": usuario.get("region") or "sierra", "e": estado})
    for f in filas:
        f["user_id"] = str(f["user_id"])
        f["dias"] = float(f["dias"])
        f["evidencias"] = await obtener_todos(
            "SELECT id, nombre_archivo, mime_type, tamano_bytes FROM refutacion_evidencias WHERE refutacion_id = %s",
            (f["id"],))
    return filas


class Resolucion(BaseModel):
    accion: Literal["aceptar", "rechazar"]
    respuesta: str = Field(..., max_length=2000)


@router.post("/rrhh/revisiones-historial/{rid}")
async def resolver(rid: int, datos: Resolucion, request: Request, tareas: BackgroundTasks, usuario: TH) -> dict:
    """Aceptar NO cambia el saldo por sí solo: Talento Humano corrige el
    registro o el saldo con sus herramientas, que dejan su propia bitácora.
    La respuesta le llega a la persona por correo y en su historial."""
    respuesta = " ".join(datos.respuesta.split())
    if len(respuesta) < 10:
        raise HTTPException(status_code=422, detail={"mensaje": "Escriba la respuesta (mínimo 10 caracteres): "
                                                                "la persona la recibe por correo."})
    f = await obtener_uno(
        """SELECT f.*, u.nombre, u.email FROM refutaciones_historial f JOIN users u ON u.id = f.user_id
            WHERE f.id = %s""", (rid,))
    if f is None:
        raise HTTPException(status_code=404, detail={"mensaje": "Revisión no encontrada."})
    if f["estado"] != "pendiente":
        raise HTTPException(status_code=409, detail={"mensaje": "Esa revisión ya fue respondida."})
    aceptada = datos.accion == "aceptar"
    await ejecutar(
        """UPDATE refutaciones_historial SET estado = %s, respuesta = %s, resuelto_por = %s, resuelto_en = NOW(6)
            WHERE id = %s AND estado = 'pendiente'""",
        ("aceptada" if aceptada else "rechazada", respuesta, str(usuario["id"]), rid))
    await ejecutar(
        """INSERT INTO notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
           VALUES (%s, 'informativo', 'info', %s, %s, 'refutaciones_historial', %s, '/dashboard.html')""",
        (str(f["user_id"]), "Talento Humano respondió la revisión de su historial", respuesta, str(rid)))
    if f["email"]:
        tareas.add_task(notificaciones.avisar_revision_resuelta, f["email"], f["nombre"], f, aceptada,
                        respuesta, usuario["nombre"])
    await registrar(request, f"revision_historial_{'aceptada' if aceptada else 'rechazada'}",
                    user_id=str(usuario["id"]), cedula=usuario["cedula"], entidad="refutaciones_historial",
                    entidad_id=str(rid), detalle={"respuesta": respuesta})
    return {"mensaje": ("Revisión aceptada y respondida. Recuerde corregir el registro o el saldo en la ficha "
                        "de la persona." if aceptada else "Respuesta enviada a la persona.")}


@router.get("/revisiones-historial/{rid}/evidencias/{eid}", response_class=Response)
async def ver_evidencia(rid: int, eid: int, request: Request, usuario: Usuario) -> Response:
    """La evidencia la ven la persona que la subió y Talento Humano."""
    fila = await obtener_uno(
        """SELECT e.storage_path, e.nombre_archivo, e.mime_type, f.user_id FROM refutacion_evidencias e
             JOIN refutaciones_historial f ON f.id = e.refutacion_id
            WHERE e.id = %s AND e.refutacion_id = %s""", (eid, rid))
    if fila is None or not (usuario["rol"] in ("rrhh", "admin") or str(fila["user_id"]) == str(usuario["id"])):
        raise HTTPException(status_code=404, detail={"mensaje": "Evidencia no encontrada."})
    contenido = await leer_adjunto(fila["storage_path"])
    if contenido is None:
        raise HTTPException(status_code=404, detail={"mensaje": "El archivo no está en el servidor."})
    await registrar(request, "evidencia_vista", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="refutacion_evidencias", entidad_id=str(eid))
    # .eml y .msg se descargan; PDF e imágenes se abren en el navegador.
    disposicion = "attachment" if fila["mime_type"] in ("message/rfc822", "application/vnd.ms-outlook") else "inline"
    return Response(contenido, media_type=fila["mime_type"],
                    headers={"Content-Disposition": f'{disposicion}; filename="{nombre_seguro(fila["nombre_archivo"])}"',
                             "Cache-Control": "private, no-store"})
