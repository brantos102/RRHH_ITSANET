"""Lo que se le explica a la persona sobre su saldo.

UNA DIFERENCIA A PROPÓSITO con PostgreSQL. «El próximo período en vencer»
se elegía ordenando por fecha de vencimiento. Con la caducidad apagada —como
está en producción— ningún período tiene esa fecha, todos empatan, y
PostgreSQL devolvía uno cualquiera: el que encontrara primero en disco, que
puede cambiar de una consulta a otra. Aquí, ante un empate, se elige el más
antiguo, que es el que vencería primero si la caducidad se encendiera.
Ninguna pantalla mostraba ese dato, así que nadie vio nunca la diferencia.

Reemplaza a explicar_saldo, explicar_saldo_base, saldo_desglosado,
desglose_dias y base_legal_visible.

Los textos se arman con los mismos números y el mismo formato que en
PostgreSQL —«15.00 días base», fechas «31/12/2026»—: la persona lee lo mismo
antes y después del cambio de servidor.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ..db import obtener_todos, obtener_uno, lista

_CODIGOS_SALDO = ["CT_ART_69", "CT_ART_75", "CT_ART_73", "CT_ART_74"]


async def base_legal_visible(codigos: list[str]) -> list[dict[str, Any]]:
    """Los artículos que se pueden mostrar, como Talento Humano los dejó:
    el resumen si está en modo resumen, nada si está oculto."""
    return await obtener_todos(
        """SELECT codigo, norma, articulo, titulo,
                  CASE WHEN visibilidad = 'resumen' THEN resumen ELSE texto END AS texto,
                  visibilidad AS modo
             FROM legal_references
            WHERE codigo IN %s AND visibilidad <> 'oculto'
            ORDER BY orden""", (lista(codigos),))


async def saldo_desglosado(user_id) -> dict[str, Any]:
    """El saldo partido: lo ganado, lo que corre, lo caducado, y si la ficha
    muestra lo mismo que suman los períodos."""
    fila = await obtener_uno(
        """SELECT
             COALESCE(SUM(CASE WHEN p.devengado AND NOT p.caducado THEN p.dias_saldo END), 0) AS dias_ganados,
             COALESCE(SUM(CASE WHEN NOT p.devengado AND NOT p.caducado THEN p.dias_saldo END), 0) AS dias_en_curso,
             COALESCE(SUM(CASE WHEN p.caducado THEN p.dias_saldo END), 0) AS dias_caducados,
             COALESCE(SUM(CASE WHEN NOT p.caducado THEN p.dias_saldo END), 0) AS vigente,
             COUNT(CASE WHEN p.devengado AND NOT p.caducado AND p.dias_saldo > 0 THEN 1 END) AS periodos_ganados
           FROM vacation_periods p WHERE p.user_id = %s""", (user_id,))
    ficha = await obtener_uno("SELECT dias_vacaciones FROM users WHERE id = %s", (user_id,))
    proximo = await obtener_uno(
        """SELECT vence_en, dias_saldo FROM vacation_periods
            WHERE user_id = %s AND devengado AND NOT caducado AND dias_saldo > 0
            ORDER BY vence_en IS NULL, vence_en, periodo LIMIT 1""", (user_id,))
    cacheado = (ficha["dias_vacaciones"] if ficha and ficha["dias_vacaciones"] is not None
                else Decimal(0))
    return {
        "dias_ganados": fila["dias_ganados"],
        "dias_en_curso": fila["dias_en_curso"],
        "dias_caducados": fila["dias_caducados"],
        "saldo_cacheado": cacheado,
        "desalineado": cacheado != fila["vigente"],
        "periodos_ganados": int(fila["periodos_ganados"]),
        "proximo_vence_en": proximo["vence_en"] if proximo else None,
        "proximo_dias": proximo["dias_saldo"] if proximo else None,
    }


async def explicar_saldo_base(user_id) -> dict[str, Any]:
    u = await obtener_uno(
        """SELECT id, nombre, fecha_ingreso, dias_vacaciones,
                  anios_cumplidos(fecha_ingreso) AS anios,
                  puede_citar('CT_ART_69') AS cita_69, puede_citar('CT_ART_75') AS cita_75,
                  cfg_int('acumulacion_max_anios') AS acumulacion,
                  cfg_int('vacaciones_anio_dia_extra') AS anio_extra,
                  cfg_int('vacaciones_dias_base') AS base,
                  cfg_int('vacaciones_dias_extra_max') AS extra_max,
                  cfg_int('fines_semana_obligatorios') AS fds,
                  fines_semana_pendientes(id) AS fds_pendientes
             FROM users WHERE id = %s""", (user_id,))
    if u is None:
        return {"error": "Usuario no encontrado"}

    anios = u["anios"]
    # La cita del artículo se resuelve una vez y se pega donde hace falta. Si
    # Talento Humano ocultó el artículo, queda en blanco: el hecho se sigue
    # diciendo, la cita no.
    cita_69 = " (Art. 69 CT)" if u["cita_69"] else ""
    cita_75 = " (Art. 75 CT)" if u["cita_75"] else ""

    def explicacion(p) -> str:
        if not p["devengado"]:
            return "Período en curso: aún no cumple el año de servicio."
        if p["caducado"]:
            return (f"Caducó el {_ddmmyyyy(p['vence_en'])} por acumulación mayor a "
                    f"{u['acumulacion']} años{cita_75}.")
        if u["anio_extra"] is not None and p["periodo"] < u["anio_extra"]:
            return f"Año {p['periodo']} de servicio: {p['dias_asignados']} días base{cita_69}."
        return (f"Año {p['periodo']} de servicio: {u['base']} días base + "
                f"{p['dias_asignados'] - u['base']} día(s) por antigüedad{cita_69}.")

    periodos = [
        {"periodo": p["periodo"], "desde": p["fecha_desde"], "hasta": p["fecha_hasta"],
         "asignados": p["dias_asignados"], "consumidos": p["dias_consumidos"],
         "saldo": p["dias_saldo"], "vence_en": p["vence_en"], "caducado": p["caducado"],
         "devengado": p["devengado"], "explicacion": explicacion(p)}
        for p in await obtener_todos(
            "SELECT * FROM vacation_periods WHERE user_id = %s ORDER BY periodo", (user_id,))
    ]

    prox = await obtener_uno(
        """SELECT periodo, vence_en, dias_saldo FROM vacation_periods
            WHERE user_id = %s AND NOT caducado AND dias_saldo > 0
            ORDER BY vence_en IS NULL, vence_en, periodo LIMIT 1""", (user_id,))

    por_anio = (await obtener_uno("SELECT dias_por_antiguedad(%s) AS d",
                                  (max(anios or 0, 0) + 1,)))["d"]
    return {
        "empleado": u["nombre"],
        "fecha_ingreso": u["fecha_ingreso"],
        "anios_servicio": anios,
        "saldo_total": u["dias_vacaciones"],
        # El PERÍODO EN CURSO, no los años ya cumplidos: quien lleva 7 años
        # cumplidos cursa su período 8, que vale 18 días y no 17.
        "dias_por_anio_actual": por_anio,
        "fines_semana_pendientes": u["fds_pendientes"],
        "regla_antiguedad": (
            f"{u['base']} días por año cumplido. Desde el año {u['anio_extra']} se suma 1 día por "
            f"cada año de servicio, hasta un máximo de {u['extra_max']} días adicionales "
            f"({u['base'] + u['extra_max']} días en total)."),
        "regla_fines_semana": (
            f"De los {u['base']} días del período, {u['fds'] * 2} deben corresponder a "
            f"{u['fds']} fines de semana completos."),
        "proximo_vencimiento": None if prox is None else {
            "periodo": prox["periodo"], "vence_en": prox["vence_en"], "dias_en_riesgo": prox["dias_saldo"]},
        "periodos": periodos,
        "citar": {"art_69": cita_69 != "", "art_75": cita_75 != ""},
        "base_legal": await base_legal_visible(_CODIGOS_SALDO),
    }


async def explicar_saldo(user_id) -> dict[str, Any]:
    base = await explicar_saldo_base(user_id)
    if "error" in base:
        return base
    d = await saldo_desglosado(user_id)
    return {
        **base,
        "dias_ganados": d["dias_ganados"],
        "dias_en_curso": d["dias_en_curso"],
        "dias_caducados": d["dias_caducados"],
        "periodos_ganados": d["periodos_ganados"],
        "proximo_vence_en": d["proximo_vence_en"],
        "proximo_dias": d["proximo_dias"],
        "saldo_desalineado": d["desalineado"],
    }


async def desglose_dias(tipo: str, inicio: dt.date, fin: dt.date) -> dict[str, Any]:
    """Cuántos días tiene el rango y por qué se descuentan los que se descuentan."""
    feriados = {
        f["fecha"]: f["nombre"] for f in await obtener_todos(
            "SELECT fecha, nombre FROM feriados WHERE activo AND fecha BETWEEN %s AND %s",
            (inicio, fin))
    }
    dias = [inicio + dt.timedelta(days=i) for i in range(max((fin - inicio).days + 1, 0))]
    fin_de_semana = [d for d in dias if d.isoweekday() >= 6]
    descontar = (await obtener_uno("SELECT calcular_dias(%s, %s, %s) AS d", (tipo, inicio, fin)))["d"]
    return {
        "total_calendario": len(dias),
        "dias_descontar": descontar,
        "dias_no_laborables": sum(1 for d in dias
                                  if d in feriados or (tipo == "permiso" and d.isoweekday() >= 6)),
        "fines_de_semana": len(fin_de_semana),
        "feriados": [{"fecha": d, "nombre": feriados[d]} for d in dias if d in feriados],
    }


def _ddmmyyyy(fecha: dt.date | None) -> str:
    return fecha.strftime("%d/%m/%Y") if fecha else ""
