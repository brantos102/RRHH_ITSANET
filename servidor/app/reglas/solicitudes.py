"""Crear una solicitud: las reglas que deciden si se acepta y por dónde va.

Reemplaza a los disparadores de PostgreSQL que actuaban al insertar
(tg_requests_before_insert, tg_requests_ruta_aprobacion,
tg_requests_validar_requisitos, tg_requests_informe_trazabilidad) y a
ausencia_solapada, sugerir_rango_con_fin_de_semana y previsualizar_solicitud.

Los mensajes son los mismos, palabra por palabra, y la pista para el
formulario va en ReglaDeNegocio.pista con el formato que tenía el HINT de
PostgreSQL. El orden de las comprobaciones también es el mismo: ante una
solicitud que incumple dos reglas, la persona ve el mismo mensaje que veía.

Lo que pasa DESPUÉS de insertar —la región, el aviso al jefe, la bitácora—
lo hacen los disparadores de MySQL (0005_solicitudes.sql).
"""
from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..db import ejecutar, obtener_uno, transaccion
from ..errores import ReglaDeNegocio
from . import papeles, periodos

_CENTESIMA = Decimal("0.01")
ESTADOS_QUE_OCUPAN = ("pendiente_jefe", "pendiente_rrhh", "pendiente_anulacion", "aprobado")


def _hora(valor) -> dt.time | None:
    """PyMySQL entrega TIME como timedelta; aquí se trabaja con time."""
    if valor is None or isinstance(valor, dt.time):
        return valor
    return (dt.datetime.min + valor).time()


async def ausencia_solapada(user_id, desde: dt.date, hasta: dt.date, hora_inicio=None,
                            hora_fin=None, excluir=None) -> dict[str, Any] | None:
    """La solicitud viva de la persona que pisa esas fechas, si hay una.

    Lo cancelado y lo rechazado libera las fechas; lo que espera decisión, no:
    pedir dos veces los mismos días es el error que se quiere frenar, y
    frenarlo al pedir es más barato que descubrirlo al aprobar.

    Única excepción: dos permisos por horas del mismo día cuyos horarios no
    se pisan. Salir a las 12:00 de uno y entrar a las 12:00 del otro no es
    un conflicto.
    """
    return await obtener_uno(
        """SELECT r.id AS request_id, r.folio, r.fecha_inicio, r.fecha_fin, r.estado,
                  (r.hora_inicio IS NOT NULL AND r.fecha_inicio = r.fecha_fin) AS por_horas
             FROM requests r
            WHERE r.user_id = %(u)s
              AND r.estado IN ('pendiente_jefe', 'pendiente_rrhh', 'pendiente_anulacion', 'aprobado')
              AND (%(excluir)s IS NULL OR r.id <> %(excluir)s)
              AND r.fecha_inicio <= %(hasta)s AND r.fecha_fin >= %(desde)s
              AND NOT (
                    %(hi)s IS NOT NULL AND %(hf)s IS NOT NULL AND %(desde)s = %(hasta)s
                AND r.hora_inicio IS NOT NULL AND r.hora_fin IS NOT NULL
                AND r.fecha_inicio = r.fecha_fin AND r.fecha_inicio = %(desde)s
                AND (%(hf)s <= r.hora_inicio OR %(hi)s >= r.hora_fin))
            ORDER BY r.fecha_inicio, r.folio
            LIMIT 1""",
        {"u": user_id, "excluir": excluir, "desde": desde, "hasta": hasta,
         "hi": hora_inicio, "hf": hora_fin})


def sugerir_rango_con_fin_de_semana(inicio: dt.date, fin: dt.date) -> tuple[dt.date, dt.date]:
    """Si termina viernes, hasta el domingo; si empieza lunes, desde el sábado."""
    if fin.isoweekday() == 5:
        return inicio, fin + dt.timedelta(days=2)
    if inicio.isoweekday() == 1:
        return inicio - dt.timedelta(days=2), fin
    return inicio, fin


def _texto(valor) -> str:
    """Un número como lo imprime PostgreSQL en un mensaje: «7», «1.00»."""
    return str(valor)


def _cuenta(valor) -> str:
    """Un conteo de días de calcular_dias como lo escribía PostgreSQL: «3».

    En PostgreSQL esa función devolvía un numeric sin decimales; la de MySQL
    devuelve DECIMAL(6,2), que se escribiría «3.00».
    """
    d = Decimal(valor)
    return str(int(d)) if d == d.to_integral_value() else str(d.normalize())


async def _config_numero(clave: str) -> Decimal | None:
    """coalesce(nullif(valor, '')::numeric, 0), o None si la clave no existe."""
    fila = await obtener_uno("SELECT valor FROM app_config WHERE clave = %s", (clave,))
    if fila is None:
        return None
    valor = (fila["valor"] or "").strip()
    return Decimal(valor) if valor else Decimal(0)


async def preparar_solicitud(s: dict[str, Any]) -> dict[str, Any]:
    """Valida y completa una solicitud antes de insertarla.

    Recibe lo que manda el formulario y devuelve la fila completa: días,
    saldo, adelanto, fines de semana, jefe, estado y ruta de aprobación. Si
    algo no se cumple, levanta ReglaDeNegocio con el mensaje para la persona.
    """
    s = dict(s)
    tipo = s["tipo"]
    inicio, fin = s["fecha_inicio"], s["fecha_fin"]
    hora_inicio, hora_fin = _hora(s.get("hora_inicio")), _hora(s.get("hora_fin"))
    excepcion = bool(s.get("bloque_menor_justificado") or False)

    # ------------------------------------------------- tg_requests_before_insert
    u = await obtener_uno("SELECT jefe_id, fecha_ingreso FROM users WHERE id = %s AND activo",
                          (s["user_id"],))
    if u is None or u["fecha_ingreso"] is None:
        raise ReglaDeNegocio(f"Usuario {s['user_id']} no existe o está inactivo")

    # Que la persona tenga sus períodos al día antes de mirar su saldo.
    await periodos.generar_periodos_vacaciones(s["user_id"])
    calc = await obtener_uno(
        """SELECT u.dias_vacaciones AS saldo, calcular_dias(%s, %s, %s) AS dias,
                  fines_de_semana_completos(%s, %s) AS fds,
                  fines_semana_pendientes(u.id) AS fds_pendientes
             FROM users u WHERE u.id = %s""",
        (tipo, inicio, fin, inicio, fin, s["user_id"]))
    saldo: Decimal = calc["saldo"]
    dias = Decimal(calc["dias"]).quantize(_CENTESIMA, ROUND_HALF_UP)

    s["dias_solicitados"] = dias
    s["saldo_al_solicitar"] = saldo
    s["jefe_id"] = s.get("jefe_id") or u["jefe_id"]
    s["estado"] = "pendiente_jefe"
    s["fines_semana"] = calc["fds"]
    s["horas_solicitadas"] = None
    if hora_inicio is not None and hora_fin is not None:
        segundos = (dt.datetime.combine(inicio, hora_fin) - dt.datetime.combine(inicio, hora_inicio)
                    ).total_seconds()
        s["horas_solicitadas"] = (Decimal(str(segundos)) / Decimal(3600)).quantize(_CENTESIMA, ROUND_HALF_UP)

    # UN PERMISO DE UN SOLO DÍA CUENTA AUNQUE EL DÍA NO SEA HÁBIL. Hay gente
    # trabajando el domingo (garita, operarios): quien pide un día concreto
    # pide ausentarse de un turno que SÍ está cubriendo. Un rango de varios
    # días no se toca: ahí descartar el fin de semana sigue siendo lo correcto.
    if s["dias_solicitados"] <= 0 and tipo != "vacacion" and inicio == fin:
        s["dias_solicitados"] = Decimal("1.00")

    if s["dias_solicitados"] <= 0:
        raise ReglaDeNegocio("El rango de fechas no genera días computables (feriados/fin de semana).")

    if tipo == "vacacion":
        s["es_adelanto"] = s["dias_solicitados"] > saldo
        # Una excepción al bloque mínimo queda fuera de la regla de fines de
        # semana: exigirle uno completo a quien pide dos días por una urgencia
        # es pedirle justo lo que la excepción existe para no exigir.
        if (calc["fds_pendientes"] > 0 and s["fines_semana"] == 0
                and not s.get("omitir_regla_fds") and not excepcion
                and (fin.isoweekday() == 5 or inicio.isoweekday() == 1)):
            sug = sugerir_rango_con_fin_de_semana(inicio, fin)
            raise ReglaDeNegocio(
                f"Le faltan {calc['fds_pendientes']} fin(es) de semana obligatorio(s) por consumir. "
                f"La solicitud debe incluir sábado y domingo: use {sug[0]} a {sug[1]}",
                pista=f"{sug[0]}|{sug[1]}")
    else:
        pt = await obtener_uno("SELECT * FROM permission_types WHERE id = %s AND activo",
                               (s.get("permission_type_id"),))
        if pt is None:
            raise ReglaDeNegocio("Tipo de permiso inválido o inactivo")
        s["es_adelanto"] = bool(pt["descuenta_vacaciones"]) and s["dias_solicitados"] > saldo
        if pt["requiere_justificacion"] and len((s.get("justificacion") or "").strip(" ")) < 10:
            raise ReglaDeNegocio(
                f'El permiso "{pt["nombre"]}" requiere justificación de al menos 10 caracteres')
        if pt["max_dias"] is not None and s["dias_solicitados"] > pt["max_dias"]:
            raise ReglaDeNegocio(
                f'El permiso "{pt["nombre"]}" admite un máximo de {_texto(pt["max_dias"])} día(s); '
                f'solicitó {_texto(s["dias_solicitados"])}')
        if (pt["max_horas"] is not None and s["horas_solicitadas"] is not None
                and s["horas_solicitadas"] > pt["max_horas"]):
            raise ReglaDeNegocio(
                f'El permiso "{pt["nombre"]}" admite un máximo de {_texto(pt["max_horas"])} hora(s); '
                f'solicitó {_texto(s["horas_solicitadas"])}')

    # ---------------------------------------------- tg_requests_ruta_aprobacion
    # Antes que cualquier regla de política: si la persona ya está ausente
    # esos días, lo demás no importa.
    choque = await ausencia_solapada(s["user_id"], inicio, fin, hora_inicio, hora_fin, s.get("id"))
    if choque is not None:
        folio = str(choque["folio"]) if choque["folio"] is not None else "sin folio"
        raise ReglaDeNegocio(
            f"Ya tiene una ausencia registrada del {choque['fecha_inicio']:%d/%m/%Y} al "
            f"{choque['fecha_fin']:%d/%m/%Y} (solicitud Nº {folio}, "
            f"{choque['estado'].replace('_', ' ')}). No se puede estar ausente dos veces los mismos "
            "días: anule esa solicitud o elija otras fechas.",
            pista="solape|" + (str(choque["folio"]) if choque["folio"] is not None else ""))

    s["ruta_aprobacion"] = "estandar"
    if tipo == "vacacion":
        minimo = await _config_numero("vacaciones_bloque_minimo")
        anticipacion = await _config_numero("vacaciones_anticipacion_dias")
        anticipacion = int(anticipacion) if anticipacion is not None else None
        hoy = (await obtener_uno("SELECT CURRENT_DATE() AS hoy"))["hoy"]
        # El mínimo se mide en días de AUSENCIA, no en los que se descuentan:
        # un feriado dentro del rango no acorta el descanso.
        calendario = (fin - inicio).days + 1
        aviso = (inicio - hoy).days

        if (anticipacion or 0) > 0 and aviso < anticipacion and not excepcion:
            raise ReglaDeNegocio(
                f"Las vacaciones se comunican con {anticipacion} días de anticipación y usted avisa "
                f"con {max(aviso, 0)} (Lineamiento 1 de Talento Humano). Su jefe necesita ese tiempo "
                "para organizar quién cubre el puesto. Si el caso no admite espera, márquelo como "
                "excepción y explíquelo.",
                pista=f"anticipacion|{anticipacion}")

        if (minimo or 0) > 0 and calendario < minimo:
            if not excepcion:
                raise ReglaDeNegocio(
                    f"Las vacaciones se toman en bloques de al menos {_texto(minimo)} días seguidos y "
                    f"usted pidió {calendario}. Si su caso lo amerita, márquelo como excepción, explique "
                    "el motivo y adjunte el respaldo: la autoriza Talento Humano, no su jefe.",
                    pista=f"bloque_minimo|{_texto(minimo)}")
            if len((s.get("justificacion") or "").strip(" ")) < 30:
                raise ReglaDeNegocio(
                    f"Para tomar menos de {_texto(minimo)} días debe justificarlo por escrito, con al "
                    "menos 30 caracteres: quien autoriza la excepción necesita entender por qué se "
                    "aparta de la política.")

        # Apartarse de la política y comprometer días que no existen son las
        # dos decisiones que no le corresponden a la jefatura inmediata.
        if excepcion or s["es_adelanto"]:
            s["ruta_aprobacion"] = "rrhh_primero"
            s["estado"] = "pendiente_rrhh"
    else:
        excepcion = False
    s["bloque_menor_justificado"] = excepcion
    return s


async def validar_requisitos(request_id) -> None:
    """Lo que solo se puede comprobar con los adjuntos ya subidos.

    Tomar menos del bloque mínimo es una excepción a la política: la
    autoriza Talento Humano y el documento que la sustenta es lo que queda
    en el expediente. Para un permiso, el respaldo se sugiere pero no se
    exige al enviar: el certificado de una cita médica se emite DESPUÉS.
    """
    r = await obtener_uno(
        """SELECT r.tipo, r.fecha_inicio, r.fecha_fin,
                  (SELECT COUNT(*) FROM request_attachments a WHERE a.request_id = r.id) AS adjuntos
             FROM requests r WHERE r.id = %s""", (request_id,))
    if r is None or r["tipo"] != "vacacion":
        return
    minimo = await _config_numero("vacaciones_bloque_minimo") or Decimal(0)
    if minimo > 0 and (r["fecha_fin"] - r["fecha_inicio"]).days + 1 < minimo and r["adjuntos"] == 0:
        raise ReglaDeNegocio(
            f"Para tomar menos de {_texto(minimo)} días debe adjuntar el documento que respalde la excepción.")


_COLUMNAS = ["id", "user_id", "tipo", "permission_type_id", "fecha_inicio", "fecha_fin", "hora_inicio",
             "hora_fin", "descripcion", "justificacion", "bloque_menor_justificado", "dias_solicitados",
             "saldo_al_solicitar", "jefe_id", "estado", "fines_semana", "horas_solicitadas", "es_adelanto",
             "ruta_aprobacion", "omitir_regla_fds", "reemplazo_id"]


async def crear_solicitud(datos: dict[str, Any], adjuntos: list[dict[str, Any]] = (),
                          subido_por=None) -> dict[str, Any]:
    """Valida, inserta, emite los documentos y registra los adjuntos. Todo o nada.

    Devuelve la fila creada, con su folio.
    """
    async with transaccion():
        s = await preparar_solicitud(datos)
        columnas = [c for c in _COLUMNAS if c in s and (s[c] is not None or c in datos)]
        await ejecutar(
            f"INSERT INTO requests ({', '.join(columnas)}) VALUES ({', '.join(['%s'] * len(columnas))})",
            tuple(s[c] for c in columnas))

        if s["tipo"] == "vacacion":
            await papeles.informe_trazabilidad_asegurar(s["user_id"])
            await papeles.informe_solicitud_asegurar(s["id"])

        for a in adjuntos:
            await ejecutar(
                """INSERT INTO request_attachments
                     (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes, hash_sha256, subido_por)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (s["id"], a["storage_path"], a["nombre_archivo"], a["mime_type"], a["tamano_bytes"],
                 a.get("hash_sha256"), subido_por))

        await validar_requisitos(s["id"])
        return await obtener_uno("SELECT * FROM requests WHERE id = %s", (s["id"],))


async def previsualizar_solicitud(user_id, tipo: str, inicio: dt.date, fin: dt.date,
                                  permission_type_id=None) -> dict[str, Any]:
    """Lo que la pantalla muestra antes de enviar: días, saldo después, avisos."""
    from .saldo import desglose_dias

    calc = await obtener_uno(
        """SELECT (SELECT dias_vacaciones FROM users WHERE id = %s) AS saldo,
                  calcular_dias(%s, %s, %s) AS dias, fines_de_semana_completos(%s, %s) AS fds,
                  fines_semana_pendientes(%s) AS fds_pendientes""",
        (user_id, tipo, inicio, fin, inicio, fin, user_id))
    saldo, dias = calc["saldo"], calc["dias"]
    fds, fds_pend = calc["fds"], calc["fds_pendientes"]
    sug = (inicio, fin)
    avisos: list[str] = []
    ok = True
    pt = None

    if dias <= 0:
        ok = False
        avisos.append("El rango seleccionado no genera días computables.")

    if tipo == "vacacion":
        if saldo is not None and dias > saldo:
            avisos.append(f"Supera su saldo ({saldo} días disponibles). Debe registrar una justificación: "
                          "se tomará como días adelantados.")
        if fds_pend > 0 and fds == 0 and (fin.isoweekday() == 5 or inicio.isoweekday() == 1):
            ok = False
            sug = sugerir_rango_con_fin_de_semana(inicio, fin)
            dias_sug = (await obtener_uno("SELECT calcular_dias(%s, %s, %s) AS d", (tipo, *sug)))["d"]
            avisos.append(f"Le faltan {fds_pend} fin(es) de semana obligatorio(s). La solicitud debe incluir "
                          f"sábado y domingo: {sug[0]} a {sug[1]} ({_cuenta(dias_sug)} días).")
    else:
        pt = await obtener_uno("SELECT * FROM permission_types WHERE id = %s AND activo", (permission_type_id,))
        if pt is None:
            ok = False
            avisos.append("Debe seleccionar un tipo de permiso válido.")
        else:
            if pt["requiere_adjunto"]:
                avisos.append(f'El permiso "{pt["nombre"]}" exige adjuntar respaldo.')
            if pt["requiere_firma"]:
                avisos.append("Debe firmar electrónicamente la solicitud.")
            if pt["max_dias"] is not None and dias > pt["max_dias"]:
                ok = False
                avisos.append(f"Máximo {pt['max_dias']} día(s) para este permiso.")
            if pt["descuenta_vacaciones"]:
                avisos.append("Este permiso se descuenta de su saldo de vacaciones.")

    adelanto = tipo == "vacacion" and saldo is not None and dias > saldo
    return {
        "valido": ok,
        "dias": dias,
        "saldo_actual": saldo,
        "saldo_despues": (saldo - dias if saldo is not None else None) if tipo == "vacacion" else saldo,
        "fines_semana_incluidos": fds,
        "fines_semana_pendientes": fds_pend,
        "requiere_justificacion": adelanto or bool(pt and pt["requiere_justificacion"]),
        "requiere_adjunto": bool(pt and pt["requiere_adjunto"]),
        "requiere_firma": bool(pt["requiere_firma"]) if pt else tipo == "permiso",
        "rango_sugerido": {"inicio": sug[0], "fin": sug[1]},
        "avisos": avisos,
        "desglose": await desglose_dias(tipo, inicio, fin),
    }
