"""Que el manual de depuración siga diciendo la verdad.

Los archivos de `supabase/depuracion/` los va a ejecutar una persona contra
datos reales desde DBeaver. Si una consulta de ahí deja de funcionar porque
una migración renombró algo, nadie se entera hasta que alguien la corre sobre
la planilla y le sale un error a mitad de una transacción abierta.

Estas pruebas corren las consultas que no llevan marcadores y comprueban que
lo que el manual afirma sobre la base sigue siendo cierto.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.db import obtener_todos, obtener_uno

CARPETA = Path(__file__).resolve().parents[2] / "supabase" / "depuracion"


def _consultas_ejecutables(archivo: Path) -> list[str]:
    """Las sentencias del archivo que se pueden correr tal cual.

    Se descartan las que llevan marcadores `<<< >>>` —son plantillas que la
    persona completa— y las que cambian algo: aquí solo se comprueba que las
    consultas de lectura sigan siendo válidas.
    """
    texto = archivo.read_text(encoding="utf-8")
    sin_comentarios = re.sub(r"^\s*--.*$", "", texto, flags=re.M)
    piezas = [p.strip() for p in sin_comentarios.split(";")]
    return [p for p in piezas
            if p.lower().startswith("select")
            and "<<<" not in p
            and "\\" not in p]


def test_los_archivos_del_manual_existen():
    for nombre in ("00_LEER_PRIMERO.sql", "01_revisar.sql",
                   "02_corregir.sql", "03_eliminar.sql"):
        assert (CARPETA / nombre).exists(), f"falta {nombre}"


@pytest.mark.parametrize("archivo", sorted(CARPETA.glob("*.sql")), ids=lambda a: a.name)
async def test_las_consultas_de_lectura_siguen_siendo_validas(cliente, archivo):
    """Una consulta rota se descubre aquí, no a mitad de una depuración."""
    consultas = _consultas_ejecutables(archivo)
    for consulta in consultas:
        try:
            # Se duplica el signo de porcentaje solo para poder ejecutarla
            # desde aquí: psycopg lo lee como marcador de parámetro. En
            # DBeaver la consulta va tal como está en el archivo, que es lo
            # que la persona va a copiar.
            await obtener_todos(consulta.replace("%", "%%"))
        except Exception as exc:                # noqa: BLE001
            pytest.fail(f"{archivo.name}: dejó de funcionar\n"
                        f"{consulta[:220]}\n→ {exc}")


async def test_revisar_trae_las_doce_comprobaciones(cliente):
    """Si alguien quita una, que se note."""
    consultas = _consultas_ejecutables(CARPETA / "01_revisar.sql")
    assert len(consultas) >= 10, f"solo quedan {len(consultas)} consultas de revisión"


async def test_borrar_una_persona_sigue_arrastrando_su_expediente(cliente):
    """Es la advertencia central del manual. Si algún día deja de ser cierta
    —porque una migración cambió una cascada por SET NULL— el manual estaría
    asustando de más, y eso también se corrige."""
    cascadas = await obtener_todos("""
        select c.conrelid::regclass::text as tabla
          from pg_constraint c
         where c.contype = 'f' and c.confdeltype = 'c'
           and c.connamespace = 'public'::regnamespace
           and c.confrelid = 'public.users'::regclass""")
    nombres = {c["tabla"].replace("public.", "") for c in cascadas}
    # Las que de verdad duelen: el expediente y lo que la LOPDP obliga a
    # conservar.
    for tabla in ("requests", "vacation_periods", "vacaciones_historicas",
                  "data_consents", "signatures"):
        assert tabla in nombres, (
            f"«{tabla}» ya no se borra en cascada con la persona. "
            "El manual dice que sí: actualícelo.")


async def test_el_saldo_lo_recalcula_un_disparador(cliente):
    """La razón por la que el manual prohíbe editar `dias_vacaciones` a mano."""
    fila = await obtener_uno("""
        select count(*) as n from pg_trigger t
          join pg_class c on c.oid = t.tgrelid
          join pg_proc p on p.oid = t.tgfoid
         where not t.tgisinternal
           and c.relname = 'vacation_periods'
           and p.proname = 'tg_vac_periods_sync'""")
    assert fila["n"] == 1, (
        "desapareció el disparador que recalcula el saldo; el manual dice que "
        "existe y que por eso no se edita `users.dias_vacaciones` a mano")


async def test_las_funciones_que_el_manual_manda_ejecutar_existen(cliente):
    """Nombres que la persona va a teclear en DBeaver tal como están escritos."""
    for nombre in ("recalcular_saldos", "generar_periodos_vacaciones",
                   "cargar_saldo_inicial", "es_cedula_valida", "anios_cumplidos"):
        fila = await obtener_uno(
            """select count(*) as n from pg_proc
                where pronamespace = 'public'::regnamespace and proname = %s""",
            (nombre,))
        assert fila["n"] >= 1, f"el manual manda ejecutar «{nombre}» y no existe"


async def test_las_vistas_que_usa_el_manual_existen(cliente):
    for vista in ("v_sin_entrada", "v_fines_semana"):
        fila = await obtener_uno(
            """select count(*) as n from information_schema.views
                where table_schema = 'public' and table_name = %s""", (vista,))
        assert fila["n"] == 1, f"el manual consulta «{vista}» y no existe"
