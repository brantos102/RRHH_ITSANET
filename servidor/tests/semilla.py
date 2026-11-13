"""El personal de prueba de siempre (supabase/seed.sql), sembrado en MySQL.

Cinco personas inventadas —correos @itsanet.test, que no existen— con los
mismos saldos que la semilla de PostgreSQL, para que las pruebas que cuentan
con ellas encuentren lo mismo. Se generan con las reglas de Python (períodos
y saldo inicial), igual que el sistema.

Se puede ejecutar dos veces: quien ya está no se toca.
"""
from __future__ import annotations

import datetime as dt
import json

from app.db import ejecutar, nuevo_id, obtener_uno
from app.reglas import periodos

PERSONAL = [
    # cédula, nombre, correo, teléfono, rol, cargo, departamento, jefe, ingreso, saldo, fds, logros
    ("0703886002", "María Vera", "rrhh@itsanet.test", "0999000001", "rrhh", "Analista de RRHH",
     "Talento Humano", None, dt.date(2019, 3, 1), 22, 2, []),
    ("1710034065", "Carlos Moreno", "jefe@itsanet.test", "0999000002", "jefe", "Jefe de Operaciones",
     "Operaciones", None, dt.date(2017, 6, 15), 18, 0, []),
    ("0926687856", "Ana Suárez", "empleado@itsanet.test", "0999000003", "empleado",
     "Asistente Administrativo", "Operaciones", "1710034065", dt.date(2021, 9, 1), 12.5, 1,
     [{"titulo": "Empleado del mes", "fecha": "2026-05-31", "detalle": "Marzo 2026"}]),
    ("1713175071", "Luis Pinto", "guardia@itsanet.test", "0999000004", "guardia",
     "Guardia de Seguridad", "Seguridad", None, dt.date(2022, 1, 10), 10, 0, []),
    ("0602910945", "Admin Sistema", "admin@itsanet.test", "0999000005", "admin", "Administrador",
     "TI", None, dt.date(2016, 1, 4), 15, 0, []),
]


async def sembrar() -> None:
    for (cedula, nombre, correo, telefono, rol, cargo, depto, jefe_cedula, ingreso,
         saldo, fds, logros) in PERSONAL:
        if await obtener_uno("SELECT 1 AS x FROM users WHERE cedula = %s", (cedula,)):
            continue
        jefe = (await obtener_uno("SELECT id FROM users WHERE cedula = %s", (jefe_cedula,))
                if jefe_cedula else None)
        pid = nuevo_id()
        await ejecutar(
            """INSERT INTO users (id, cedula, nombre, email, telefono, rol, cargo, departamento,
                                  jefe_id, fecha_ingreso, logros)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (pid, cedula, nombre, correo, telefono, rol, cargo, depto,
             jefe["id"] if jefe else None, ingreso, json.dumps(logros, ensure_ascii=False)))
        await periodos.cargar_saldo_inicial(pid, saldo, fds)
