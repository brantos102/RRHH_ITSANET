"""Lo que corre solo, sin que nadie lo pida: avisos diarios y retención.

Reemplaza a generar_alertas_vacaciones y aplicar_retencion. En Supabase las
programaba pg_cron; en el servidor propio las lanza un temporizador de
systemd con `mysql/tareas.py` (ver despliegue/).

Los avisos llevan una clave única por persona, tipo y mes: correr la tarea
dos veces el mismo día no duplica nada.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from ..db import ejecutar, obtener_todos, obtener_uno, transaccion
from . import periodos

# Un aviso ya existente (misma clave) no se toca: ON DUPLICATE KEY con una
# asignación que no cambia nada devuelve 0 filas afectadas, y así se cuenta
# solo lo que de verdad se generó.
_AVISO = """INSERT INTO notifications
              (user_id, tipo, severidad, titulo, mensaje, legal_ref, entidad, entidad_id,
               clave_dedupe, accion_url)
            VALUES (%s, %s, %s, %s, %s, 'CT_ART_75', %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE clave_dedupe = clave_dedupe"""


async def _avisar(user_id, tipo: str, severidad: str, titulo: str, mensaje: str,
                  clave: str, *, entidad: str | None = None, entidad_id: str | None = None,
                  accion_url: str | None = None) -> bool:
    n = await ejecutar(_AVISO, (str(user_id), tipo, severidad, titulo, mensaje,
                                entidad, entidad_id, clave, accion_url))
    return n == 1


async def _cfg_int(clave: str) -> int:
    return int((await obtener_uno("SELECT cfg_int(%s) AS v", (clave,)))["v"] or 0)


def _fecha(valor) -> str:
    return valor.strftime("%d/%m/%Y") if valor else ""


async def generar_alertas_vacaciones() -> list[dict[str, Any]]:
    """[{tipo, generadas}] para saldo_alto, vacaciones_por_caducar y periodo_caducado."""
    async with transaccion():
        umbral = await _cfg_int("alerta_saldo_alto")
        mes = (await obtener_uno("SELECT DATE_FORMAT(CURRENT_DATE(), '%%Y-%%m') AS m"))["m"]
        rrhh = [f["id"] for f in await obtener_todos(
            "SELECT id FROM users WHERE rol IN ('rrhh', 'admin') AND activo")]
        saldo_alto = por_caducar = caducado = 0

        # (a) Saldo acumulado alto: conviene programarlas. No porque se
        # pierdan —no se pierden— sino porque acumular años sin descansar es
        # lo que el Art. 75 no quiere.
        for r in await obtener_todos(
                "SELECT id, nombre, dias_vacaciones FROM users WHERE activo AND dias_vacaciones >= %s",
                (umbral,)):
            if await _avisar(
                    r["id"], "saldo_alto", "advertencia",
                    f"Tiene {r['dias_vacaciones']} días de vacaciones acumulados",
                    f"Su saldo acumulado es de {r['dias_vacaciones']} días. Ningún día se pierde: "
                    "el Art. 75 permite acumular hasta tres años y lo que no llegue a gozar se le "
                    "paga (Art. 76). Aun así conviene programarlas con su jefe inmediato: son días "
                    "de descanso, no un ahorro.",
                    f"saldo_alto:{r['id']}:{mes}", accion_url="/dashboard.html#vacaciones"):
                saldo_alto += 1

        # (b) Acumulación que ya toca resolver: tres o más años sin gozar.
        # Programarlas pasa a ser cosa de la empresa (Art. 73); nadie pierde
        # nada, lo no gozado se paga (Art. 76).
        for r in await obtener_todos(
                """SELECT user_id, nombre, periodos_sin_gozar, dias_de_anios_cumplidos,
                          desde_cuando_arrastra FROM v_acumulacion_excesiva"""):
            clave = f"acumulacion:{r['user_id']}:{mes}"
            if await _avisar(
                    r["user_id"], "vacaciones_acumuladas", "advertencia",
                    f"Tiene {r['dias_de_anios_cumplidos']} días de años ya cumplidos sin gozar",
                    f"Arrastra {r['periodos_sin_gozar']} período(s) anual(es) sin tomar vacaciones, "
                    f"el más antiguo desde el {_fecha(r['desde_cuando_arrastra'])}. El Art. 75 del "
                    "Código del Trabajo permite acumular hasta tres años para gozarlos en el "
                    "cuarto; a partir de ahí corresponde que Talento Humano programe sus "
                    "vacaciones. Ningún día se pierde: lo no gozado se paga (Art. 76).",
                    clave, entidad="users", entidad_id=str(r["user_id"]),
                    accion_url="/dashboard.html#vacaciones"):
                por_caducar += 1
            # Copia para Talento Humano: es quien tiene que programar.
            for quien in rrhh:
                await _avisar(
                    quien, "vacaciones_acumuladas", "advertencia",
                    f"{r['nombre']} arrastra {r['periodos_sin_gozar']} años de vacaciones sin gozar",
                    f"{r['nombre']} tiene {r['dias_de_anios_cumplidos']} días de períodos ya "
                    f"cumplidos, el más antiguo desde el {_fecha(r['desde_cuando_arrastra'])}. "
                    "Pasado el tercer año el Art. 75 deja de amparar la acumulación por decisión "
                    "del trabajador y el Art. 73 le da a la empresa la facultad de señalar el "
                    "período. Cada día pendiente es además una obligación de pago (Art. 76).",
                    f"{clave}:rrhh:{quien}", entidad="users", entidad_id=str(r["user_id"]),
                    accion_url="/colaboradores.html")

        # (c) Períodos caducados en los últimos 30 días. Con la caducidad
        # apagada —lo normal— no hay ninguno.
        for r in await obtener_todos(
                """SELECT p.id, p.user_id, p.periodo, p.dias_saldo, p.vence_en, u.nombre
                     FROM vacation_periods p JOIN users u ON u.id = p.user_id
                    WHERE p.caducado AND u.activo AND p.dias_saldo > 0
                      AND p.vence_en >= CURRENT_DATE() - INTERVAL 30 DAY"""):
            clave = f"caducado:{r['id']}"
            if await _avisar(
                    r["user_id"], "periodo_caducado", "critica",
                    f"Caducaron {r['dias_saldo']} días de vacaciones",
                    f"Su período {r['periodo']} venció el {_fecha(r['vence_en'])} y los "
                    f"{r['dias_saldo']} días no gozados caducaron conforme al Art. 75 del Código "
                    "del Trabajo. Si considera que hubo un error, comuníquese con Talento Humano.",
                    clave, entidad="vacation_periods", entidad_id=str(r["id"])):
                caducado += 1
            for quien in rrhh:
                await _avisar(
                    quien, "periodo_caducado", "critica",
                    f"{r['nombre']} perdió {r['dias_saldo']} días caducados",
                    f"El período {r['periodo']} de {r['nombre']} venció el {_fecha(r['vence_en'])} "
                    f"con {r['dias_saldo']} días no gozados (Art. 75 CT).",
                    f"{clave}:rrhh:{quien}", entidad="vacation_periods", entidad_id=str(r["id"]))

    return [{"tipo": "saldo_alto", "generadas": saldo_alto},
            {"tipo": "vacaciones_por_caducar", "generadas": por_caducar},
            {"tipo": "periodo_caducado", "generadas": caducado}]


async def aplicar_retencion() -> list[dict[str, Any]]:
    """Borra de las bitácoras lo que pasó su plazo de conservación (LOPDP, Art. 10).

    Las bitácoras son inmutables: un disparador impide borrarlas salvo con
    @retencion = 'autorizada', que se enciende y se apaga aquí, en la misma
    conexión y dentro de la misma transacción.
    """
    async with transaccion():
        meses_audit = await _cfg_int("retencion_audit_logs_meses")
        meses_access = await _cfg_int("retencion_access_logs_meses")
        await ejecutar("SET @retencion = 'autorizada'")
        try:
            n1 = await ejecutar("DELETE FROM audit_logs WHERE created_at < NOW(6) - INTERVAL %s MONTH",
                                (meses_audit,))
            n2 = await ejecutar("DELETE FROM access_logs WHERE created_at < NOW(6) - INTERVAL %s MONTH",
                                (meses_access,))
        finally:
            await ejecutar("SET @retencion = NULL")
    return [{"tabla": "audit_logs", "eliminados": n1}, {"tabla": "access_logs", "eliminados": n2}]


async def tarea_diaria() -> dict[str, Any]:
    """Lo que antes hacía pg_cron cada mañana: caducar (si está activa) y avisar."""
    caducados = await periodos.caducar_periodos_vencidos()
    avisos = await generar_alertas_vacaciones()
    return {"fecha": dt.date.today().isoformat(), "periodos_caducados": caducados, "avisos": avisos}
