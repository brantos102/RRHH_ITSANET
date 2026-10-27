"""La explicación del saldo en Python, comparada con PostgreSQL para cada
persona de la muestra: sus períodos, sus textos, sus citas legales."""
from __future__ import annotations

import datetime as dt

import pytest

from app.reglas import saldo
from tests.diferencial import json_normal, muestra  # noqa: F401


def _sin_empate(en_pg: dict, en_py: dict, pid, pg, claves_pg: tuple, claves_py: tuple):
    """Si no hay fecha de vencimiento, PostgreSQL elige un período cualquiera
    entre los empatados (ver app/reglas/saldo.py). Se comprueba que el suyo
    sea uno de los empatados y que Python elija el más antiguo; lo demás se
    compara igual."""
    if en_pg.get(claves_pg[0]) is not None or en_pg.get(claves_pg[1]) is None:
        return
    candidatos = pg.execute(
        """select periodo, dias_saldo from vacation_periods
            where user_id = %s and not caducado and dias_saldo > 0 and vence_en is null
              and (%s or devengado) order by periodo""", (pid, claves_pg[2])).fetchall()
    assert float(en_pg[claves_pg[1]]) in [float(c["dias_saldo"]) for c in candidatos]
    assert float(en_py[claves_py[1]]) == float(candidatos[0]["dias_saldo"]), "el más antiguo"
    for k in claves_pg[3:]:
        en_pg.pop(k, None)
    for k in claves_py[3:]:
        en_py.pop(k, None)


async def _personas(pg):
    return [f["id"] for f in pg.execute("select id from users order by cedula").fetchall()]


async def test_explicar_saldo_de_toda_la_muestra(muestra):
    personas = await _personas(muestra)
    assert len(personas) > 50
    for pid in personas:
        en_pg = muestra.execute("select explicar_saldo(%s) as e", (pid,)).fetchone()["e"]
        en_py = json_normal(await saldo.explicar_saldo(pid))
        _sin_empate(en_pg, en_py, pid, muestra,
                    ("proximo_vence_en", "proximo_dias", False, "proximo_dias"),
                    ("proximo_vence_en", "proximo_dias", False, "proximo_dias"))
        if en_pg.get("proximo_vencimiento") and en_pg["proximo_vencimiento"]["vence_en"] is None:
            sub_pg, sub_py = en_pg["proximo_vencimiento"], en_py["proximo_vencimiento"]
            _sin_empate(sub_pg, sub_py, pid, muestra,
                        ("vence_en", "dias_en_riesgo", True, "dias_en_riesgo", "periodo"),
                        ("vence_en", "dias_en_riesgo", True, "dias_en_riesgo", "periodo"))
        assert en_py == en_pg, pid


async def test_una_persona_que_no_existe(muestra):
    import uuid
    falso = uuid.uuid4()
    en_pg = muestra.execute("select explicar_saldo(%s) as e", (falso,)).fetchone()["e"]
    assert json_normal(await saldo.explicar_saldo(falso)) == en_pg


async def test_saldo_desglosado_de_toda_la_muestra(muestra):
    for pid in await _personas(muestra):
        en_pg = json_normal(muestra.execute("select * from saldo_desglosado(%s)", (pid,)).fetchone())
        en_py = json_normal(await saldo.saldo_desglosado(pid))
        _sin_empate(en_pg, en_py, pid, muestra,
                    ("proximo_vence_en", "proximo_dias", False, "proximo_dias"),
                    ("proximo_vence_en", "proximo_dias", False, "proximo_dias"))
        assert en_py == en_pg, pid


@pytest.mark.parametrize("tipo", ["vacacion", "permiso"])
async def test_desglose_de_dias(muestra, tipo):
    """Rangos que cruzan feriados, fines de semana, fin de año y uno al revés."""
    hoy = dt.date(2026, 1, 1)
    for inicio_offset, largo in [(0, 1), (0, 14), (100, 30), (300, 70), (358, 10), (40, -3), (5, 0)]:
        inicio = hoy + dt.timedelta(days=inicio_offset)
        fin = inicio + dt.timedelta(days=largo)
        en_pg = muestra.execute("select desglose_dias(%s, %s, %s) as d",
                                (tipo, inicio, fin)).fetchone()["d"]
        assert json_normal(await saldo.desglose_dias(tipo, inicio, fin)) == en_pg, (inicio, fin)


async def test_base_legal_visible(muestra):
    codigos = ["CT_ART_69", "CT_ART_75", "CT_ART_73", "CT_ART_74", "NO_EXISTE"]
    en_pg = muestra.execute("select * from base_legal_visible(%s)", (codigos,)).fetchall()
    assert json_normal(await saldo.base_legal_visible(codigos)) == json_normal(en_pg)
