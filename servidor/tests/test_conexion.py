"""Cómo se abre la conexión a MySQL.

Dos cosas que no se ven al arrancar y que rompen datos sin dar error:

  · El juego de caracteres. Un cliente que no declara utf8mb4 guarda
    «Suárez» corrompido, y después no aparece al buscar «suarez».
  · La zona horaria. Las fechas se guardan sin zona (DATETIME); si la
    conexión no está en la hora de Ecuador, un permiso pedido a las 20:00
    queda anotado al día siguiente y la garita lo valida mal.
"""
from __future__ import annotations

from app.db import obtener_uno


async def test_la_conexion_habla_utf8mb4():
    fila = await obtener_uno(
        "select @@character_set_client as cliente, @@character_set_connection as conexion, "
        "@@character_set_results as resultados")
    assert fila == {"cliente": "utf8mb4", "conexion": "utf8mb4", "resultados": "utf8mb4"}


async def test_una_tilde_va_y_vuelve_intacta():
    fila = await obtener_uno("select %s as nombre", ("Suárez Ñañez",))
    assert fila["nombre"] == "Suárez Ñañez"


async def test_la_conexion_esta_en_la_hora_de_ecuador():
    fila = await obtener_uno("select @@session.time_zone as zona")
    assert fila["zona"] == "-05:00"


async def test_una_consulta_repetida_muchas_veces_no_falla():
    """Las conexiones se reutilizan entre peticiones: repetir no debe romper."""
    for _ in range(8):
        fila = await obtener_uno(
            """select count(*) > 0 as existe from information_schema.tables
                where table_schema = database() and table_name = %s""", ("users",))
        assert fila["existe"]
