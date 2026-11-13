"""Primer ingreso: cómo se comprueba la identidad y qué se pide al entrar.

Dos decisiones que toma Talento Humano o Administración desde el sistema
(`app_config`), no el código:

  alta_verificacion     «correo»: quien no tiene correo registra uno y entra
                        con el código que le llega ahí. «nacimiento»: además
                        debe coincidir su fecha de nacimiento con el
                        expediente. Se empieza con «correo» porque la planilla
                        llegó sin fechas de nacimiento; cuando la cobertura
                        sea alta (≈90 %) se pasa a «nacimiento».

  ficha_inicial_campos  lo que se pide al entrar, antes de usar el sistema:
                        fecha de nacimiento, confirmar la fecha de ingreso,
                        confirmar jefe y cargo, teléfono y contacto de
                        emergencia. Lo que ya consta o ya se confirmó no se
                        vuelve a pedir.
"""
from __future__ import annotations

from typing import Any

from ..db import obtener_uno

MODOS = ("correo", "nacimiento")
CAMPOS = ("fecha_nacimiento", "fecha_ingreso", "jefe", "cargo", "telefono", "emergencia")
CAMPOS_POR_DEFECTO = ",".join(CAMPOS)


async def _config(clave: str, defecto: str) -> str:
    fila = await obtener_uno("SELECT valor FROM app_config WHERE clave = %s", (clave,))
    return (fila or {}).get("valor") or defecto


async def modo_alta() -> str:
    modo = (await _config("alta_verificacion", "correo")).strip()
    return modo if modo in MODOS else "correo"


async def campos_ficha_inicial() -> list[str]:
    texto = await _config("ficha_inicial_campos", CAMPOS_POR_DEFECTO)
    return [c for c in (p.strip() for p in texto.split(",")) if c in CAMPOS]


async def pendientes(user_id) -> list[str]:
    """Lo que esta persona todavía tiene que completar o confirmar.

    Un pedido de corrección ya enviado cuenta como respondido: la persona
    hizo su parte y lo que falta es de Talento Humano.
    """
    campos = await campos_ficha_inicial()
    if not campos:
        return []
    u = await obtener_uno(
        """SELECT u.fecha_nacimiento IS NULL AS sin_nacimiento,
                  u.fecha_ingreso_confirmada_en IS NULL AS ingreso_sin_confirmar,
                  u.jefe_confirmado_en IS NULL AS jefe_sin_confirmar,
                  -- El cargo y el área se piden solo si no constan: de ahí en
                  -- adelante los administra Talento Humano.
                  (NULLIF(TRIM(COALESCE(u.cargo, '')), '') IS NULL
                   OR (NULLIF(TRIM(COALESCE(u.departamento, '')), '') IS NULL
                       AND u.cargo_confirmado_en IS NULL)) AS cargo_sin_confirmar,
                  NULLIF(TRIM(COALESCE(u.telefono, '')), '') IS NULL AS sin_telefono,
                  NOT EXISTS (SELECT 1 FROM emergency_contacts c
                               WHERE c.user_id = u.id AND c.es_principal) AS sin_emergencia,
                  EXISTS (SELECT 1 FROM cambios_ficha c WHERE c.user_id = u.id
                             AND c.campo = 'fecha_ingreso' AND c.estado = 'pendiente') AS ingreso_pedido,
                  EXISTS (SELECT 1 FROM cambios_ficha c WHERE c.user_id = u.id
                             AND c.campo IN ('jefe_id', 'jefe_por_registrar')
                             AND c.estado = 'pendiente') AS jefe_pedido,
                  EXISTS (SELECT 1 FROM cambios_ficha c WHERE c.user_id = u.id
                             AND c.campo IN ('cargo', 'departamento')
                             AND c.estado = 'pendiente') AS cargo_pedido
             FROM users u WHERE u.id = %s""", (str(user_id),))
    if u is None:
        return []
    falta = {
        "fecha_nacimiento": u["sin_nacimiento"],
        "fecha_ingreso": u["ingreso_sin_confirmar"] and not u["ingreso_pedido"],
        "jefe": u["jefe_sin_confirmar"] and not u["jefe_pedido"],
        "cargo": u["cargo_sin_confirmar"] and not u["cargo_pedido"],
        "telefono": u["sin_telefono"],
        "emergencia": u["sin_emergencia"],
    }
    return [c for c in campos if falta.get(c)]


async def cobertura() -> dict[str, Any]:
    """Cuántos activos tienen fecha de nacimiento y correo: con esto se decide
    cuándo pasar a verificar con la fecha de nacimiento."""
    f = await obtener_uno(
        """SELECT COUNT(*) AS activos,
                  SUM(fecha_nacimiento IS NOT NULL) AS con_nacimiento,
                  SUM(email IS NOT NULL AND NOT correo_pendiente) AS con_correo,
                  SUM(fecha_ingreso_confirmada_en IS NOT NULL) AS ingreso_confirmado
             FROM users WHERE activo""")
    activos = int(f["activos"] or 0)

    def pct(n) -> float:
        return round(100 * int(n or 0) / activos, 1) if activos else 0.0

    return {
        "activos": activos,
        "con_nacimiento": int(f["con_nacimiento"] or 0),
        "con_correo": int(f["con_correo"] or 0),
        "ingreso_confirmado": int(f["ingreso_confirmado"] or 0),
        "pct_nacimiento": pct(f["con_nacimiento"]),
        "pct_correo": pct(f["con_correo"]),
        "pct_ingreso_confirmado": pct(f["ingreso_confirmado"]),
    }
