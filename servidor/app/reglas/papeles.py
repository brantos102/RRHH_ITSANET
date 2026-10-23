"""Los documentos que se imprimen y se firman: trazabilidad y solicitud.

Reemplaza a folio_informe, datos_informe_trazabilidad, datos_informe_solicitud,
informe_trazabilidad_asegurar, informe_solicitud_asegurar,
informe_trazabilidad_reemitir e informe_impreso.

El papel de trazabilidad se emite UNA vez por persona (un índice único lo
garantiza en la base). Una reemisión es un documento nuevo, con su folio y
con el nombre de quien la autorizó: el papel ya firmado no se toca.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from ..db import ejecutar, obtener_todos, obtener_uno, transaccion, nuevo_id
from ..errores import ReglaDeNegocio, es_unicidad, restriccion_de


async def folio_informe(tipo: str) -> str:
    """TRZ-2026-00573 o SOL-2026-00574. Un solo contador para los dos tipos,
    como en PostgreSQL.

    MySQL no tiene secuencias: el contador es una fila de `secuencias`.
    UPDATE ... LAST_INSERT_ID(valor + 1) incrementa y deja el valor nuevo
    a la vista de ESTA conexión sin que otra pueda colarse en medio; por eso
    tiene que correr dentro de una transacción, que fija la conexión.
    """
    async with transaccion():
        await ejecutar("UPDATE secuencias SET valor = LAST_INSERT_ID(valor + 1) "
                       "WHERE nombre = 'informes_firmados_folio'")
        fila = await obtener_uno("SELECT LAST_INSERT_ID() AS n, YEAR(CURRENT_DATE()) AS anio")
    prefijo = "TRZ-" if tipo == "trazabilidad" else "SOL-"
    # zfill y no un lpad que recorte: en PostgreSQL, el folio 100000 se
    # habría cortado a «10000» y chocado con uno ya emitido.
    return f"{prefijo}{fila['anio']}-{str(fila['n']).zfill(5)}"


async def _empresa() -> dict[str, Any]:
    f = await obtener_uno("SELECT cfg_texto('empresa_razon_social') AS razon_social, "
                          "cfg_texto('empresa_ruc') AS ruc, cfg_texto('empresa_ciudad') AS ciudad")
    return {"razon_social": f["razon_social"], "ruc": f["ruc"], "ciudad": f["ciudad"]}


async def datos_informe_trazabilidad(user_id) -> dict[str, Any] | None:
    u = await obtener_uno(
        """SELECT u.nombre, u.cedula, u.cargo, u.departamento, u.bodega, u.centro_costo,
                  u.fecha_ingreso, anios_cumplidos(u.fecha_ingreso) AS anios, u.dias_vacaciones,
                  (SELECT j.nombre FROM users j WHERE j.id = u.jefe_id) AS jefe
             FROM users u WHERE u.id = %s""", (user_id,))
    if u is None:
        return None
    por_anio = (await obtener_uno("SELECT dias_por_antiguedad(%s) AS d",
                                  (max(u["anios"] or 0, 0) + 1,)))["d"]
    historial = await obtener_todos(
        """SELECT fecha_inicio, fecha_fin, dias, procedencia, detalle, folio
             FROM v_historial_vacaciones WHERE user_id = %s
            ORDER BY fecha_inicio, procedencia, folio""", (user_id,))
    gozadas = [
        {"fecha_inicio": h["fecha_inicio"], "fecha_fin": h["fecha_fin"], "dias": h["dias"],
         "observacion": (h["detalle"] or "Registro del archivo de Talento Humano")
         if h["procedencia"] == "historico"
         else f"{h['detalle'] or 'Tramitada por el sistema'} · folio {h['folio']}"}
        for h in historial
    ]
    return {
        "empresa": await _empresa(),
        "colaborador": {
            "nombre": u["nombre"], "cedula": u["cedula"], "cargo": u["cargo"],
            "departamento": u["departamento"], "bodega": u["bodega"],
            "centro_costo": u["centro_costo"], "fecha_ingreso": u["fecha_ingreso"],
            "anios_servicio": u["anios"], "jefe": u["jefe"],
        },
        "saldo": {"dias_disponibles": u["dias_vacaciones"], "dias_por_periodo_en_curso": por_anio},
        "gozadas": gozadas,
        "totales": {
            "veces": len(historial),
            "dias": sum((h["dias"] for h in historial), start=0),
            "desde_la_hoja": sum(1 for h in historial if h["procedencia"] == "historico"),
            "en_el_sistema": sum(1 for h in historial if h["procedencia"] != "historico"),
        },
    }


async def datos_informe_solicitud(request_id) -> dict[str, Any] | None:
    r = await obtener_uno(
        """SELECT r.*, u.nombre AS u_nombre, u.cedula AS u_cedula, u.cargo AS u_cargo,
                  u.departamento AS u_departamento, u.bodega AS u_bodega,
                  u.centro_costo AS u_centro_costo, u.fecha_ingreso AS u_fecha_ingreso,
                  j.nombre AS jefe_nombre,
                  (SELECT x.nombre FROM users x WHERE x.id = r.reemplazo_id) AS reemplazo_nombre,
                  (SELECT a.nombre FROM users a WHERE a.id = r.jefe_aprobado_por) AS aprobo_jefe,
                  (SELECT a.nombre FROM users a WHERE a.id = r.rrhh_aprobado_por) AS aprobo_rrhh
             FROM requests r
             JOIN users u ON u.id = r.user_id
             LEFT JOIN users j ON j.id = r.jefe_id
            WHERE r.id = %s""", (request_id,))
    if r is None:
        return None
    return {
        "empresa": await _empresa(),
        "colaborador": {
            "nombre": r["u_nombre"], "cedula": r["u_cedula"], "cargo": r["u_cargo"],
            "departamento": r["u_departamento"], "bodega": r["u_bodega"],
            "centro_costo": r["u_centro_costo"], "fecha_ingreso": r["u_fecha_ingreso"],
            "jefe": r["jefe_nombre"],
        },
        "solicitud": {
            "folio": r["folio"],
            "solicitada_en": r["created_at"],
            "fecha_inicio": r["fecha_inicio"],
            "fecha_fin": r["fecha_fin"],
            "dias": r["dias_solicitados"],
            # El día en que se reincorpora: el siguiente al último de vacaciones.
            "reintegro": r["fecha_fin"] + dt.timedelta(days=1),
            "clase": "Adelantadas" if r["es_adelanto"] else "Ordinarias",
            "estado": r["estado"],
            "aprobada": r["estado"] == "aprobado",
            "saldo_al_solicitar": r["saldo_al_solicitar"],
            "descripcion": r["descripcion"],
            "reemplazo": r["reemplazo_nombre"],
        },
        "aprobaciones": {
            "jefe": {"nombre": r["aprobo_jefe"], "cuando": r["jefe_aprobado_en"]},
            "rrhh": {"nombre": r["aprobo_rrhh"], "cuando": r["rrhh_aprobado_en"]},
        },
    }


async def _informe(id_) -> dict[str, Any]:
    return await obtener_uno("SELECT * FROM informes_firmados WHERE id = %s", (id_,))


async def informe_trazabilidad_asegurar(user_id, emitido_por=None) -> dict[str, Any]:
    """El papel de trazabilidad vigente de la persona; lo emite si no tiene."""
    async with transaccion():
        actual = await obtener_uno(
            """SELECT id FROM informes_firmados WHERE user_id = %s AND tipo = 'trazabilidad'
                ORDER BY emitido_en DESC LIMIT 1""", (user_id,))
        if actual is not None:
            return await _informe(actual["id"])
        nuevo = nuevo_id()
        try:
            await ejecutar(
                """INSERT INTO informes_firmados (id, user_id, tipo, folio, emitido_por, datos)
                   VALUES (%s, %s, 'trazabilidad', %s, %s, %s)""",
                (nuevo, user_id, await folio_informe("trazabilidad"), emitido_por,
                 await datos_informe_trazabilidad(user_id)))
        except Exception as exc:
            # Dos solicitudes de la misma persona a la vez: la otra lo emitió
            # primero. El índice único impidió el duplicado; se usa el suyo.
            if es_unicidad(exc) and restriccion_de(exc) == "idx_trazabilidad_una_sola_vez":
                otra = await obtener_uno(
                    """SELECT id FROM informes_firmados WHERE user_id = %s AND tipo = 'trazabilidad'
                        ORDER BY emitido_en DESC LIMIT 1""", (user_id,))
                return await _informe(otra["id"])
            raise
        return await _informe(nuevo)


async def informe_solicitud_asegurar(request_id, emitido_por=None) -> dict[str, Any]:
    """El papel de una solicitud de vacaciones, con lo que diga HOY.

    A diferencia del de trazabilidad, se reimprime actualizado: acompaña una
    solicitud que todavía puede aprobarse o rechazarse, y un formulario que
    dijera «pendiente» cuando ya está aprobada no serviría en el mostrador.
    """
    async with transaccion():
        r = await obtener_uno("SELECT user_id, tipo FROM requests WHERE id = %s", (request_id,))
        if r is None:
            raise ReglaDeNegocio("Esa solicitud no existe.")
        if r["tipo"] != "vacacion":
            raise ReglaDeNegocio("Este informe es de vacaciones; esa solicitud es de otro tipo.")
        actual = await obtener_uno(
            "SELECT id FROM informes_firmados WHERE request_id = %s AND tipo = 'solicitud' LIMIT 1",
            (request_id,))
        if actual is not None:
            await ejecutar("UPDATE informes_firmados SET datos = %s WHERE id = %s",
                           (await datos_informe_solicitud(request_id), actual["id"]))
            return await _informe(actual["id"])
        nuevo = nuevo_id()
        await ejecutar(
            """INSERT INTO informes_firmados (id, user_id, tipo, request_id, folio, emitido_por, datos)
               VALUES (%s, %s, 'solicitud', %s, %s, %s, %s)""",
            (nuevo, r["user_id"], request_id, await folio_informe("solicitud"), emitido_por,
             await datos_informe_solicitud(request_id)))
        return await _informe(nuevo)


async def informe_trazabilidad_reemitir(user_id, autoriza, motivo: str | None) -> dict[str, Any]:
    """Un documento NUEVO con los datos de hoy y el nombre de quien autorizó."""
    motivo = (motivo or "").strip(" ")
    if not motivo:
        raise ReglaDeNegocio("Una reemisión necesita motivo: queda como constancia de quién la "
                             "autorizó y por qué.")
    async with transaccion():
        if await obtener_uno("SELECT 1 AS x FROM informes_firmados WHERE user_id = %s "
                             "AND tipo = 'trazabilidad' LIMIT 1", (user_id,)) is None:
            raise ReglaDeNegocio("Esa persona no tiene todavía un informe de trazabilidad que reemitir.")
        nuevo = nuevo_id()
        await ejecutar(
            """INSERT INTO informes_firmados (id, user_id, tipo, folio, autorizado_por, autorizado_en,
                                              autorizacion_motivo, emitido_por, datos)
               VALUES (%s, %s, 'trazabilidad', %s, %s, NOW(6), %s, %s, %s)""",
            (nuevo, user_id, await folio_informe("trazabilidad"), autoriza, motivo, autoriza,
             await datos_informe_trazabilidad(user_id)))
        return await _informe(nuevo)


async def informe_impreso(informe_id) -> None:
    await ejecutar("UPDATE informes_firmados SET impresiones = impresiones + 1, "
                   "ultima_impresion = NOW(6) WHERE id = %s", (informe_id,))
