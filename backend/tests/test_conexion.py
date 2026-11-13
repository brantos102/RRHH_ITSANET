"""Cómo se abre la conexión a Supabase.

El pooler de Supabase en modo transacción —el puerto 6543, el que la propia
documentación recomienda— reparte cada consulta por la conexión que tenga
libre. Cualquier cosa que dé por supuesto que la sesión de PostgreSQL es
siempre la misma se rompe ahí, y las sentencias preparadas son justamente
eso. El fallo no aparece al arrancar: espera a que algún bucle repita la
misma consulta más de cinco veces, que es cuando psycopg decide prepararla.
"""
from __future__ import annotations

from app.db import abrir_pool


async def test_el_pool_no_prepara_sentencias():
    """`prepare_threshold=None` es lo que hace compatible al pooler.

    Sin esto, `verificar.py` reventaba con «prepared statement "_pg3_0"
    already exists» en cuanto la lista de migraciones pasó de cinco.
    """
    pool = await abrir_pool()
    assert pool.kwargs.get("prepare_threshold", "sin definir") is None, (
        "El pool debe abrirse con prepare_threshold=None: el pooler de "
        "Supabase reparte las consultas entre conexiones distintas."
    )


async def test_una_consulta_repetida_muchas_veces_no_falla():
    """Ocho repeticiones: más allá del umbral en que psycopg prepararía."""
    from app.db import obtener_uno

    for _ in range(8):
        fila = await obtener_uno(
            "select to_regclass(%s) is not null as existe", ("public.users",))
        assert fila["existe"] is True
