"""Períodos de vacaciones: generarlos, caducarlos y cuadrar el saldo.

Reemplaza a generar_periodos_vacaciones, cargar_saldo_inicial,
caducar_periodos_de, caducar_periodos_vencidos, recalcular_saldos,
refrescar_saldo_vacaciones y corregir_fines_semana.

Los cálculos de antigüedad y de días devengados NO se reescriben aquí: se
usan las funciones de MySQL (anios_cumplidos, dias_por_antiguedad,
dias_devengados_en_curso), que ya se comprobaron iguales a las de PostgreSQL
en más de cien mil casos. Rehacerlas en Python sería una tercera versión que
probar.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from ..db import ejecutar, obtener_todos, obtener_uno, transaccion
from ..errores import ReglaDeNegocio


def mas_anios(fecha: dt.date, anios: int) -> dt.date:
    """Suma años como PostgreSQL y MySQL: el 29 de febrero cae en el 28.

    `fecha + make_interval(years => n)` en PostgreSQL y `DATE_ADD(fecha,
    INTERVAL n YEAR)` en MySQL hacen lo mismo. Alguien que entró un 29 de
    febrero cumple sus períodos el 28 en los años que no son bisiestos.
    """
    try:
        return fecha.replace(year=fecha.year + anios)
    except ValueError:
        return fecha.replace(year=fecha.year + anios, day=28)


async def refrescar_saldo_vacaciones(user_id) -> Decimal:
    """La ficha muestra la suma de los saldos de sus períodos no caducados.

    Un disparador de MySQL ya la mantiene al día con cada cambio de un
    período; esto la recalcula a pedido, igual que la función original.
    """
    async with transaccion():
        await ejecutar(_SQL_REFRESCAR + " WHERE u.id = %s", (user_id,))
        fila = await obtener_uno("SELECT dias_vacaciones FROM users WHERE id = %s", (user_id,))
    return fila["dias_vacaciones"] if fila else Decimal(0)


_SQL_REFRESCAR = """
    UPDATE users u
       SET u.dias_vacaciones = (SELECT COALESCE(SUM(p.dias_saldo), 0)
                                  FROM vacation_periods p
                                 WHERE p.user_id = u.id AND NOT p.caducado)
"""


async def generar_periodos_vacaciones(user_id) -> int:
    """Crea los períodos que le faltan a la persona según su fecha de ingreso.

    Uno por cada año cumplido, devengado, con los días que le corresponden
    por antigüedad; y el del año en curso, con lo devengado hasta hoy. Los
    períodos ya devengados no se tocan: si Talento Humano los ajustó, el
    ajuste se respeta. Devuelve cuántos años cumplidos tiene.
    """
    async with transaccion():
        u = await obtener_uno(
            """SELECT fecha_ingreso, anios_cumplidos(fecha_ingreso) AS anios,
                      cfg_int('fines_semana_obligatorios') AS fds,
                      cfg_int('acumulacion_max_anios') AS acumulacion,
                      caducidad_activa() AS caduca, CURRENT_DATE() AS hoy
                 FROM users WHERE id = %s FOR UPDATE""",
            (user_id,))
        if u is None or u["fecha_ingreso"] is None:
            raise ReglaDeNegocio(f"Usuario {user_id} no existe")

        ingreso: dt.date = u["fecha_ingreso"]
        anios = max(u["anios"] or 0, 0)
        caduca = bool(u["caduca"])

        def vence(hasta: dt.date) -> dt.date | None:
            # Apagada la caducidad no se calcula fecha de vencimiento alguna:
            # una fecha que no va a cumplirse es peor que ninguna fecha.
            return mas_anios(hasta, u["acumulacion"]) if caduca else None

        existentes = {
            f["periodo"]: f for f in await obtener_todos(
                """SELECT periodo, devengado, dias_asignados FROM vacation_periods
                    WHERE user_id = %s FOR UPDATE""", (user_id,))
        }

        for k in range(1, anios + 1):
            desde = mas_anios(ingreso, k - 1)
            hasta = mas_anios(ingreso, k) - dt.timedelta(days=1)
            dias = (await obtener_uno("SELECT dias_por_antiguedad(%s) AS d", (k,)))["d"]
            vence_en = vence(hasta)
            previo = existentes.get(k)
            if previo is None:
                await ejecutar(
                    """INSERT INTO vacation_periods
                         (user_id, periodo, fecha_desde, fecha_hasta, dias_asignados,
                          fines_semana_obligatorios, devengado, vence_en, caducado)
                       VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, %s)""",
                    (user_id, k, desde, hasta, dias, u["fds"], vence_en,
                     vence_en is not None and vence_en < u["hoy"]))
            elif not previo["devengado"]:
                # Era el período en curso y ya se cumplió el año: pasa a
                # devengado con los días completos.
                await ejecutar(
                    """UPDATE vacation_periods
                          SET dias_asignados = %s, devengado = TRUE, vence_en = %s
                        WHERE user_id = %s AND periodo = %s""",
                    (dias, vence_en, user_id, k))

        k = anios + 1
        desde = mas_anios(ingreso, k - 1)
        hasta = mas_anios(ingreso, k) - dt.timedelta(days=1)
        parcial = (await obtener_uno("SELECT dias_devengados_en_curso(%s, %s) AS d",
                                     (ingreso, k)))["d"]
        previo = existentes.get(k)
        if previo is None:
            await ejecutar(
                """INSERT INTO vacation_periods
                     (user_id, periodo, fecha_desde, fecha_hasta, dias_asignados,
                      fines_semana_obligatorios, devengado, vence_en)
                   VALUES (%s, %s, %s, %s, %s, %s, FALSE, %s)""",
                (user_id, k, desde, hasta, parcial, u["fds"], vence(hasta)))
        elif not previo["devengado"]:
            # Lo devengado en curso solo crece: un ajuste a mano hacia
            # arriba no se pisa con el cálculo.
            await ejecutar(
                """UPDATE vacation_periods SET dias_asignados = GREATEST(dias_asignados, %s)
                    WHERE user_id = %s AND periodo = %s""",
                (parcial, user_id, k))

        await refrescar_saldo_vacaciones(user_id)
    return anios


async def caducar_periodos_de(user_id) -> int:
    """Marca como caducados los períodos vencidos de una persona."""
    async with transaccion():
        if not await _caducidad_activa():
            # Apagada: no se extingue nada. Marcar días como perdidos no es un
            # detalle de presentación, es una afirmación sobre un pasivo laboral.
            return 0
        n = await ejecutar(
            """UPDATE vacation_periods SET caducado = TRUE
                WHERE user_id = %s AND NOT caducado
                  AND vence_en < CURRENT_DATE() AND dias_saldo > 0""", (user_id,))
        await refrescar_saldo_vacaciones(user_id)
    return n


async def caducar_periodos_vencidos() -> int:
    """Lo mismo para toda la planilla. Lo ejecuta la tarea diaria."""
    async with transaccion():
        if not await _caducidad_activa():
            return 0
        n = await ejecutar(
            """UPDATE vacation_periods SET caducado = TRUE
                WHERE NOT caducado AND vence_en < CURRENT_DATE() AND dias_saldo > 0""")
        await ejecutar(_SQL_REFRESCAR + " WHERE u.activo")
    return n


async def recalcular_saldos(user_id=None) -> int:
    """Recalcula el saldo de la ficha de una persona activa, o de todas."""
    async with transaccion():
        if user_id is None:
            n = (await obtener_uno("SELECT COUNT(*) AS n FROM users WHERE activo"))["n"]
            await ejecutar(_SQL_REFRESCAR + " WHERE u.activo")
        else:
            n = (await obtener_uno("SELECT COUNT(*) AS n FROM users WHERE activo AND id = %s",
                                   (user_id,)))["n"]
            await ejecutar(_SQL_REFRESCAR + " WHERE u.activo AND u.id = %s", (user_id,))
    return n


async def cargar_saldo_inicial(user_id, saldo_real, fds_ya_consumidos: int = 0) -> Decimal:
    """Cuadra el saldo con el que Talento Humano tiene en planilla.

    Genera los períodos y descuenta la diferencia —los días que la persona ya
    tomó antes del sistema— de los más antiguos a los más nuevos. Lo que no
    alcanza queda como adelanto en el último período, en negativo, como está
    en la planilla, en vez de perderse.
    """
    saldo_real = Decimal(str(saldo_real))
    async with transaccion():
        await generar_periodos_vacaciones(user_id)
        await caducar_periodos_de(user_id)

        asignado = (await obtener_uno(
            """SELECT COALESCE(SUM(dias_asignados), 0) AS s FROM vacation_periods
                WHERE user_id = %s AND NOT caducado""", (user_id,)))["s"]
        ajuste = asignado - saldo_real   # días ya tomados históricamente
        if ajuste < 0:
            raise ReglaDeNegocio(
                f"El saldo indicado ({saldo_real}) supera lo devengado no caducado ({asignado})")

        await ejecutar("UPDATE vacation_periods SET dias_consumidos = 0 "
                       "WHERE user_id = %s AND NOT caducado", (user_id,))

        restante = ajuste
        for p in await obtener_todos(
                """SELECT id, dias_asignados FROM vacation_periods
                    WHERE user_id = %s AND NOT caducado AND dias_asignados > 0
                    ORDER BY periodo""", (user_id,)):
            if restante <= 0:
                break
            toma = min(p["dias_asignados"], restante)
            await ejecutar("UPDATE vacation_periods SET dias_consumidos = %s WHERE id = %s",
                           (toma, p["id"]))
            restante -= toma

        if restante > 0:
            ultimo = await obtener_uno(
                """SELECT id FROM vacation_periods WHERE user_id = %s AND NOT caducado
                    ORDER BY periodo DESC LIMIT 1""", (user_id,))
            if ultimo is not None:
                await ejecutar("UPDATE vacation_periods SET dias_consumidos = dias_consumidos + %s "
                               "WHERE id = %s", (restante, ultimo["id"]))

        primero = await obtener_uno(
            """SELECT id FROM vacation_periods WHERE user_id = %s AND NOT caducado
                ORDER BY periodo LIMIT 1""", (user_id,))
        if primero is not None:
            await ejecutar(
                """UPDATE vacation_periods
                      SET fines_semana_consumidos = LEAST(%s, fines_semana_obligatorios)
                    WHERE id = %s""", (fds_ya_consumidos, primero["id"]))

        await ejecutar(
            """INSERT INTO vacation_movements (user_id, dias, saldo_previo, saldo_nuevo, motivo)
               VALUES (%s, 0, 0, %s, 'Carga de saldo inicial (migración de datos)')""",
            (user_id, saldo_real))

        return await refrescar_saldo_vacaciones(user_id)


async def corregir_fines_semana(user_id, periodo: int, consumidos: int, motivo: str | None,
                                por) -> dict[str, Any]:
    """Talento Humano corrige los fines de semana ya consumidos de un período.

    Queda en la bitácora con el antes, el después y el motivo.
    """
    async with transaccion():
        quien = await obtener_uno("SELECT rol FROM users WHERE id = %s", (por,))
        # Más estricta que la original: en PostgreSQL, un «por» inexistente
        # dejaba el rol en NULL y `NULL not in (...)` no levantaba el error.
        if quien is None or quien["rol"] not in ("rrhh", "admin"):
            raise ReglaDeNegocio("Solo Talento Humano puede corregir los fines de semana obligatorios")

        motivo = (motivo or "").strip()
        if len(motivo) < 15:
            raise ReglaDeNegocio(
                "Explique la corrección en al menos 15 caracteres: queda como constancia")

        p = await obtener_uno(
            "SELECT * FROM vacation_periods WHERE user_id = %s AND periodo = %s FOR UPDATE",
            (user_id, periodo))
        if p is None:
            raise ReglaDeNegocio(f"La persona no tiene un período {periodo}")
        if consumidos < 0 or consumidos > p["fines_semana_obligatorios"]:
            raise ReglaDeNegocio(
                f"Los fines de semana consumidos van de 0 a {p['fines_semana_obligatorios']} "
                "en este período")

        antes = p["fines_semana_consumidos"]
        await ejecutar("UPDATE vacation_periods SET fines_semana_consumidos = %s WHERE id = %s",
                       (consumidos, p["id"]))
        await ejecutar(
            "INSERT INTO audit_logs (user_id, accion, detalle) VALUES (%s, 'fines_semana_corregidos', %s)",
            (por, {"empleado": str(user_id), "periodo": periodo, "antes": antes,
                   "despues": consumidos, "motivo": motivo}))
        return await obtener_uno("SELECT * FROM vacation_periods WHERE id = %s", (p["id"],))


async def _caducidad_activa() -> bool:
    return bool((await obtener_uno("SELECT caducidad_activa() AS c"))["c"])
