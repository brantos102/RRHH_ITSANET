"""Pendientes de Talento Humano, por sede, con quién está atendiendo cada uno.

Antes lo que esperaba a Talento Humano estaba repartido —solicitudes en el
panel, cambios de ficha y firmas en Administración, consultas en el chat— y
dos personas podían ponerse con lo mismo sin saberlo. Aquí está todo junto:

  · filtrado por sede: «mi sede» por defecto (y las sedes que no tienen a
    nadie de Talento Humano, para que no queden huérfanas), Quito, Guayaquil
    o todas;
  · cada pendiente dice si alguien lo tomó («en revisión por María, hace 5
    min»). Tomarlo es un clic; caduca a las 4 horas si se olvida;
  · y abajo, lo atendido hoy y por quién.
"""
from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request

from ..audit import registrar
from ..db import ejecutar, obtener_todos, obtener_uno
from ..deps import exigir_rol

router = APIRouter(prefix="/rrhh/pendientes", tags=["Pendientes de Talento Humano"])
RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]
Tipo = Literal["cambio_ficha", "solicitud", "chat", "firma"]
VIGENCIA_HORAS = 4

SEDES = {"sierra": "Quito", "costa": "Guayaquil"}


def _filtro_sede(usuario: dict, sede: str) -> tuple[str, tuple]:
    """Condición sobre una columna `region` (alias `reg`)."""
    if sede in SEDES:
        return "reg = %s", (sede,)
    if sede == "todas":
        return "TRUE", ()
    propia = usuario.get("region") or "sierra"
    return ("(reg = %s OR reg NOT IN (SELECT DISTINCT region FROM v_rrhh_por_region))", (propia,))


SQL_PENDIENTES = """
SELECT * FROM (
  SELECT 'cambio_ficha' AS tipo, CAST(c.id AS CHAR) AS id, c.user_id AS persona_id, c.persona,
         c.region AS reg,
         CONCAT(c.etiqueta, ': ', COALESCE(c.nuevo_legible, c.valor_nuevo)) AS detalle,
         c.created_at AS desde, 'administracion.html#cambios-ficha' AS url
    FROM v_cambios_ficha_pendientes c
  UNION ALL
  SELECT 'solicitud', r.id, r.user_id, u.nombre, COALESCE(r.region, 'sierra'),
         CONCAT('N.º ', r.folio, ' · ', IF(r.tipo = 'vacacion', 'Vacaciones', 'Permiso'),
                ' del ', DATE_FORMAT(r.fecha_inicio, '%%d/%%m/%%Y'),
                ' al ', DATE_FORMAT(r.fecha_fin, '%%d/%%m/%%Y')),
         COALESCE(r.jefe_aprobado_en, r.created_at), 'dashboard.html#aprobaciones'
    FROM requests r JOIN users u ON u.id = r.user_id
   WHERE r.estado = 'pendiente_rrhh' OR (r.estado = 'pendiente_jefe' AND r.jefe_id IS NULL)
  UNION ALL
  SELECT 'chat', v.id, v.user_id, v.persona, v.region,
         CONCAT(COALESCE(v.asunto, 'Consulta'), ' · ', LEFT(COALESCE(v.ultimo_mensaje, ''), 90)),
         v.updated_at, 'mensajes.html'
    FROM v_conversaciones_bandeja v
   WHERE v.estado = 'abierta' AND v.sin_leer > 0
  UNION ALL
  SELECT 'firma', i.id, i.user_id, u.nombre, COALESCE(u.region, 'sierra'),
         CONCAT('Firmar solicitud N.º ', r.folio, ' · folio ', i.folio),
         COALESCE(r.rrhh_aprobado_en, i.emitido_en), 'administracion.html#papeles'
    FROM informes_firmados i
    JOIN requests r ON r.id = i.request_id AND r.estado = 'aprobado'
    JOIN users u ON u.id = i.user_id
   WHERE i.tipo = 'solicitud' AND i.firmado_en IS NULL
) p
"""

SQL_ATENDIDOS = """
SELECT * FROM (
  SELECT 'cambio_ficha' AS tipo, u.nombre AS persona, COALESCE(u.region, 'sierra') AS reg,
         CONCAT(f.etiqueta, ' · ', c.estado) AS detalle, q.nombre AS por, c.resuelto_en AS cuando
    FROM cambios_ficha c JOIN users u ON u.id = c.user_id
    JOIN campos_ficha f ON f.campo = c.campo LEFT JOIN users q ON q.id = c.resuelto_por
   WHERE c.resuelto_en >= CURRENT_DATE() AND c.resuelto_por IS NOT NULL
  UNION ALL
  SELECT 'solicitud', u.nombre, COALESCE(r.region, 'sierra'),
         CONCAT('N.º ', r.folio, ' · aprobada'), q.nombre, r.rrhh_aprobado_en
    FROM requests r JOIN users u ON u.id = r.user_id LEFT JOIN users q ON q.id = r.rrhh_aprobado_por
   WHERE r.rrhh_aprobado_en >= CURRENT_DATE()
  UNION ALL
  SELECT 'firma', u.nombre, COALESCE(u.region, 'sierra'), CONCAT('Firmó · folio ', i.folio),
         q.nombre, i.firmado_en
    FROM informes_firmados i JOIN users u ON u.id = i.user_id
    LEFT JOIN users q ON q.id = i.firmado_registrado_por
   WHERE i.firmado_en >= CURRENT_DATE()
) a
"""


@router.get("")
async def pendientes(usuario: RRHH, sede: str = "mia") -> dict:
    filtro, params = _filtro_sede(usuario, sede)
    filas = await obtener_todos(f"{SQL_PENDIENTES} WHERE {filtro} ORDER BY desde", params)
    tomados = {(t["tipo"], str(t["entidad_id"])): t for t in await obtener_todos(
        f"""SELECT a.tipo, a.entidad_id, a.user_id, a.tomado_en, u.nombre,
                   TIMESTAMPDIFF(MINUTE, a.tomado_en, NOW(6)) AS minutos
              FROM atenciones a JOIN users u ON u.id = a.user_id
             WHERE a.tomado_en > NOW(6) - INTERVAL {VIGENCIA_HORAS} HOUR""")}
    # Las consultas del chat ya dicen quién las atiende.
    chats = {str(c["id"]): c["atendida_por"] for c in await obtener_todos(
        "SELECT id, atendida_por FROM v_conversaciones_bandeja WHERE estado = 'abierta'")}
    items = []
    for f in filas:
        t = tomados.get((f["tipo"], str(f["id"])))
        atencion = ({"por": t["nombre"], "minutos": int(t["minutos"] or 0),
                     "propio": str(t["user_id"]) == str(usuario["id"])} if t else None)
        if atencion is None and f["tipo"] == "chat" and chats.get(str(f["id"])):
            atencion = {"por": chats[str(f["id"])], "minutos": None,
                        "propio": chats[str(f["id"])] == usuario.get("nombre")}
        items.append({"tipo": f["tipo"], "id": str(f["id"]), "persona": f["persona"],
                      "persona_id": str(f["persona_id"]), "region": f["reg"],
                      "sede": SEDES.get(f["reg"], f["reg"]), "detalle": f["detalle"],
                      "desde": f["desde"], "url": f["url"], "atencion": atencion})
    atendidos = await obtener_todos(f"{SQL_ATENDIDOS} WHERE {filtro} ORDER BY cuando DESC LIMIT 40",
                                    params)
    conteo: dict[str, int] = {}
    for i in items:
        conteo[i["tipo"]] = conteo.get(i["tipo"], 0) + 1
    return {"sede": sede, "items": items, "conteo": conteo,
            "atendidos_hoy": [{**a, "sede": SEDES.get(a["reg"], a["reg"])} for a in atendidos]}


@router.post("/{tipo}/{entidad_id}/tomar")
async def tomar(tipo: Tipo, entidad_id: str, request: Request, usuario: RRHH,
                forzar: bool = False) -> dict:
    """«Yo me encargo». Si ya lo tiene otra persona, se avisa; con `forzar`
    se lo queda quien pide (por ejemplo, si la otra persona salió)."""
    otro = await obtener_uno(
        f"""SELECT a.user_id, u.nombre FROM atenciones a JOIN users u ON u.id = a.user_id
             WHERE a.tipo = %s AND a.entidad_id = %s
               AND a.tomado_en > NOW(6) - INTERVAL {VIGENCIA_HORAS} HOUR""", (tipo, entidad_id))
    if otro and str(otro["user_id"]) != str(usuario["id"]) and not forzar:
        raise HTTPException(status_code=409, detail={
            "mensaje": f"{otro['nombre']} ya lo está revisando."})
    await ejecutar(
        """INSERT INTO atenciones (tipo, entidad_id, user_id) VALUES (%s, %s, %s)
           AS nuevo ON DUPLICATE KEY UPDATE user_id = nuevo.user_id, tomado_en = NOW(6)""",
        (tipo, entidad_id, str(usuario["id"])))
    await registrar(request, "pendiente_tomado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad=tipo, entidad_id=entidad_id,
                    detalle={"en_lugar_de": otro["nombre"] if otro and forzar else None})
    return {"mensaje": "Queda a su cargo. Los demás lo ven «en revisión»."}


@router.delete("/{tipo}/{entidad_id}/tomar")
async def soltar(tipo: Tipo, entidad_id: str, usuario: RRHH) -> dict:
    await ejecutar("DELETE FROM atenciones WHERE tipo = %s AND entidad_id = %s AND user_id = %s",
                   (tipo, entidad_id, str(usuario["id"])))
    return {"mensaje": "Lo dejó libre para otra persona."}
