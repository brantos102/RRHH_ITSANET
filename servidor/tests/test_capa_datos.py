"""La capa de datos sobre MySQL entrega lo mismo que entregaba PostgreSQL.

Los routers y las reglas se escribieron leyendo filas de psycopg: un booleano
es True o False, un JSON es un dict, un id es un UUID y una fecha trae su
zona. MySQL entrega 1/0, texto y fechas sin zona. Si db.py no convirtiera,
`if fila["activo"]` seguiría funcionando por casualidad y `fila["id"] ==
usuario["id"]` fallaría en silencio, comparando un texto con un UUID.

Además, lo que en PostgreSQL era UNA función de la base —atómica por
naturaleza— en MySQL son varias consultas desde Python. Aquí se prueba que
`transaccion()` las confirma juntas o no confirma ninguna.
"""
from __future__ import annotations

import datetime as dt
import uuid

import pytest

from app import db
from app.db import ZONA_ECUADOR, ejecutar, lista, obtener_todos, obtener_uno, transaccion


@pytest.fixture
async def tabla():
    """Una tabla propia de la prueba: no toca ningún dato del sistema."""
    nombre = f"prueba_capa_{uuid.uuid4().hex[:8]}"
    await ejecutar(f"""CREATE TABLE {nombre} (
        id CHAR(36) PRIMARY KEY, activo BOOLEAN, datos JSON, cuando DATETIME(6),
        nombre VARCHAR(80), cantidad INT, monto DECIMAL(6,2))""")
    yield nombre
    await ejecutar(f"DROP TABLE {nombre}")


async def test_cada_tipo_vuelve_como_lo_entregaba_postgresql(tabla):
    ident = uuid.uuid4()
    cuando = dt.datetime(2026, 12, 24, 18, 30, tzinfo=ZONA_ECUADOR)
    await ejecutar(f"INSERT INTO {tabla} VALUES (%s, %s, %s, %s, %s, %s, %s)",
                   (ident, True, {"motivo": "Navidad", "días": 3}, cuando, "Núñez", 1, "12.50"))
    fila = await obtener_uno(f"SELECT * FROM {tabla} WHERE id = %s", (ident,))
    assert fila["id"] == ident and isinstance(fila["id"], uuid.UUID)
    assert fila["activo"] is True
    assert fila["datos"] == {"motivo": "Navidad", "días": 3}
    assert fila["cuando"] == cuando and fila["cuando"].tzinfo is not None
    assert fila["nombre"] == "Núñez"
    # Un entero de verdad sigue siendo entero, aunque valga 1: no es un booleano.
    assert fila["cantidad"] == 1 and fila["cantidad"] is not True


async def test_las_expresiones_logicas_son_booleanos(tabla):
    fila = await obtener_uno("SELECT 1 = 1 AS si, 1 = 2 AS no, EXISTS(SELECT 1) AS hay, 7 AS siete")
    assert fila["si"] is True and fila["no"] is False and fila["hay"] is True
    assert fila["siete"] == 7


async def test_una_fecha_en_otra_zona_se_guarda_en_hora_de_ecuador(tabla):
    """Un token trae la hora en UTC. Guardarla tal cual escribiría la hora de
    Londres en una columna que se lee como hora de Quito."""
    ident = uuid.uuid4()
    utc = dt.datetime(2026, 1, 1, 5, 0, tzinfo=dt.timezone.utc)
    await ejecutar(f"INSERT INTO {tabla} (id, cuando) VALUES (%s, %s)", (ident, utc))
    crudo = await obtener_uno(f"SELECT DATE_FORMAT(cuando, '%%H:%%i') AS h FROM {tabla} WHERE id = %s",
                              (ident,))
    assert crudo["h"] == "00:00"


async def test_hoy_empieza_a_medianoche_en_ecuador():
    """Sobre Supabase, en UTC, «hoy» empezaba a las 19:00 de Quito."""
    fila = await obtener_uno("SELECT @@session.time_zone AS zona, NOW() AS ahora")
    assert fila["zona"] == "-05:00"
    ahora = dt.datetime.now(ZONA_ECUADOR)
    assert abs((fila["ahora"] - ahora).total_seconds()) < 120


async def test_las_tildes_llegan_intactas_a_la_base_y_vuelven():
    fila = await obtener_uno("SELECT %s AS t, HEX(%s) AS h", ("Suárez", "á"))
    assert fila["t"] == "Suárez" and fila["h"] == "C3A1"


async def test_el_porcentaje_doble_significa_porcentaje():
    """Las consultas se escribieron para psycopg, donde %% es un %."""
    fila = await obtener_uno("SELECT 'a%%b' AS t")
    assert fila["t"] == "a%b"


async def test_lista_para_in(tabla):
    ids = [uuid.uuid4() for _ in range(3)]
    for i in ids:
        await ejecutar(f"INSERT INTO {tabla} (id) VALUES (%s)", (i,))
    filas = await obtener_todos(f"SELECT id FROM {tabla} WHERE id IN %s", (lista(ids[:2]),))
    assert {f["id"] for f in filas} == set(ids[:2])
    # Una lista vacía no coincide con nada —como `= any('{}')`— y no es un
    # error de sintaxis.
    assert await obtener_todos(f"SELECT id FROM {tabla} WHERE id IN %s", (lista([]),)) == []


async def test_la_transaccion_confirma_todo_junto(tabla):
    a, b = uuid.uuid4(), uuid.uuid4()
    async with transaccion():
        await ejecutar(f"INSERT INTO {tabla} (id) VALUES (%s)", (a,))
        await ejecutar(f"INSERT INTO {tabla} (id) VALUES (%s)", (b,))
    assert len(await obtener_todos(f"SELECT id FROM {tabla}")) == 2


async def test_un_fallo_a_mitad_no_deja_nada_a_medias(tabla):
    """Como jefatura_quitar: o se mueve a la gente Y sus solicitudes, o nada."""
    a = uuid.uuid4()
    with pytest.raises(RuntimeError):
        async with transaccion():
            await ejecutar(f"INSERT INTO {tabla} (id) VALUES (%s)", (a,))
            raise RuntimeError("falla el segundo paso")
    assert await obtener_todos(f"SELECT id FROM {tabla}") == []


async def test_una_transaccion_dentro_de_otra_es_la_misma(tabla):
    a, b = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(RuntimeError):
        async with transaccion():
            await ejecutar(f"INSERT INTO {tabla} (id) VALUES (%s)", (a,))
            async with transaccion():   # una regla que abre la suya
                await ejecutar(f"INSERT INTO {tabla} (id) VALUES (%s)", (b,))
            raise RuntimeError("falla después de la regla interna")
    assert await obtener_todos(f"SELECT id FROM {tabla}") == []


async def test_dentro_de_la_transaccion_se_ve_lo_propio_y_fuera_no(tabla):
    a = uuid.uuid4()
    async with transaccion():
        await ejecutar(f"INSERT INTO {tabla} (id) VALUES (%s)", (a,))
        assert await obtener_uno(f"SELECT id FROM {tabla} WHERE id = %s", (a,)) is not None
        # Otra conexión del pool todavía no lo ve.
        pool = await db.abrir_pool()
        async with pool.acquire() as otra:
            async with otra.cursor() as cur:
                await cur.execute(f"SELECT COUNT(*) AS n FROM {tabla}")
                assert (await cur.fetchone())["n"] == 0


async def test_insertar_devuelve_el_id_generado():
    """Sin RETURNING: el folio sale de LAST_INSERT_ID de la misma conexión."""
    nombre = f"prueba_ai_{uuid.uuid4().hex[:8]}"
    await ejecutar(f"CREATE TABLE {nombre} (n INT AUTO_INCREMENT PRIMARY KEY, x INT)")
    try:
        primero = await db.insertar(f"INSERT INTO {nombre} (x) VALUES (%s)", (1,))
        segundo = await db.insertar(f"INSERT INTO {nombre} (x) VALUES (%s)", (2,))
        assert segundo == primero + 1
    finally:
        await ejecutar(f"DROP TABLE {nombre}")
