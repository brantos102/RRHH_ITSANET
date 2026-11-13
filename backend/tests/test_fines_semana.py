"""Los fines de semana obligatorios los corrige Talento Humano, nadie más.

El panel puede decir «le faltan 2» a quien ya los tomó antes de que existiera
el sistema, y entonces la regla le bloquea unas vacaciones normales por un
dato que no refleja la realidad. Hace falta poder corregirlo, con constancia
de quién lo hizo y por qué, y que el empleado no pueda tocarlo.
"""
from __future__ import annotations

import pytest

from app.db import obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, rrhh_auth)

MOTIVO = "Tomo sus dos fines de semana en 2024, antes de que existiera el sistema"


@pytest.fixture
async def con_periodos(empleado):
    await obtener_uno("select public.generar_periodos_vacaciones(%s)", (empleado["id"],))
    return empleado


async def test_talento_humano_corrige_el_contador(cliente, rrhh_auth, con_periodos):
    periodos = await cliente.get(f"/admin/usuarios/{con_periodos['id']}/periodos",
                                 headers=rrhh_auth)
    assert periodos.status_code == 200, periodos.text
    abierto = next(p for p in periodos.json() if not p["caducado"])

    r = await cliente.post(f"/admin/usuarios/{con_periodos['id']}/fines-semana",
                           headers=rrhh_auth,
                           json={"periodo": abierto["periodo"], "consumidos": 2,
                                 "motivo": MOTIVO})
    assert r.status_code == 200, r.text

    fila = await obtener_uno(
        """select fines_semana_consumidos from public.vacation_periods
            where user_id = %s and periodo = %s""",
        (con_periodos["id"], abierto["periodo"]))
    assert fila["fines_semana_consumidos"] == 2


async def test_queda_constancia_de_quien_lo_corrigio(cliente, rrhh_auth, con_periodos):
    periodos = (await cliente.get(f"/admin/usuarios/{con_periodos['id']}/periodos",
                                  headers=rrhh_auth)).json()
    abierto = next(p for p in periodos if not p["caducado"])
    await cliente.post(f"/admin/usuarios/{con_periodos['id']}/fines-semana",
                       headers=rrhh_auth,
                       json={"periodo": abierto["periodo"], "consumidos": 1, "motivo": MOTIVO})

    rastro = await obtener_todos(
        """select detalle from public.audit_logs
            where accion = 'fines_semana_corregidos' order by created_at desc limit 5""")
    assert rastro, "la corrección debe quedar en la bitácora"
    assert any(MOTIVO in str(r["detalle"]) for r in rastro), \
        "el motivo es la constancia: sin él, la corrección no se puede defender"


async def test_el_empleado_no_puede_corregirse_a_si_mismo(cliente, auth, con_periodos):
    r = await cliente.post(f"/admin/usuarios/{con_periodos['id']}/fines-semana",
                           headers=auth, json={"periodo": 1, "consumidos": 2, "motivo": MOTIVO})
    assert r.status_code == 403


async def test_el_jefe_tampoco(cliente, jefe_auth, con_periodos):
    r = await cliente.post(f"/admin/usuarios/{con_periodos['id']}/fines-semana",
                           headers=jefe_auth, json={"periodo": 1, "consumidos": 2, "motivo": MOTIVO})
    assert r.status_code == 403


async def test_se_exige_explicar_la_correccion(cliente, rrhh_auth, con_periodos):
    r = await cliente.post(f"/admin/usuarios/{con_periodos['id']}/fines-semana",
                           headers=rrhh_auth,
                           json={"periodo": 1, "consumidos": 2, "motivo": "ok"})
    assert r.status_code == 422


async def test_no_se_pueden_consumir_mas_de_los_obligatorios(cliente, rrhh_auth, con_periodos):
    """Dos son dos: poner cinco dejaría el dato sin sentido."""
    periodos = (await cliente.get(f"/admin/usuarios/{con_periodos['id']}/periodos",
                                  headers=rrhh_auth)).json()
    abierto = next(p for p in periodos if not p["caducado"])
    r = await cliente.post(f"/admin/usuarios/{con_periodos['id']}/fines-semana",
                           headers=rrhh_auth,
                           json={"periodo": abierto["periodo"],
                                 "consumidos": abierto["fines_semana_obligatorios"] + 3,
                                 "motivo": MOTIVO})
    assert r.status_code == 422


async def test_corregirlo_quita_ese_obstaculo(cliente, auth, rrhh_auth, con_periodos):
    """Es el motivo de todo esto: el dato falso impedía pedir vacaciones.

    Se comprueba que desaparece *esa* traba en concreto y no que la solicitud
    pase: un rango de lunes a viernes choca además con el bloque mínimo de
    siete días, y un rango de siete días siempre incluye un fin de semana, así
    que no existe un caso que aísle las dos reglas a la vez. Lo que importa es
    que el contador deje de estorbar.
    """
    from datetime import timedelta

    from tests.test_reglas_nuevas import lunes_sin_feriados

    # El fixture de sesión deja los fines de semana como ya consumidos, para
    # que las demás pruebas no tropiecen con esta regla. Aquí se necesita lo
    # contrario: alguien a quien el sistema se los reclama.
    from app.db import ejecutar
    await ejecutar(
        """update public.vacation_periods set fines_semana_consumidos = 0
            where user_id = %s and not caducado""",
        (con_periodos["id"],))

    lunes = await lunes_sin_feriados()
    cuerpo = {"tipo": "vacacion", "fecha_inicio": str(lunes),
              "fecha_fin": str(lunes + timedelta(days=4)),
              "descripcion": "Cinco dias de lunes a viernes", "firmar": False}

    antes = await cliente.post("/solicitudes", headers=auth, json=cuerpo)
    assert antes.status_code == 422
    assert "fin(es) de semana" in antes.text, \
        "con el contador en cero, la traba debe ser la del fin de semana"

    periodos = (await cliente.get(f"/admin/usuarios/{con_periodos['id']}/periodos",
                                  headers=rrhh_auth)).json()
    for p in periodos:
        if not p["caducado"] and p["fines_semana_obligatorios"]:
            r = await cliente.post(f"/admin/usuarios/{con_periodos['id']}/fines-semana",
                                   headers=rrhh_auth,
                                   json={"periodo": p["periodo"],
                                         "consumidos": p["fines_semana_obligatorios"],
                                         "motivo": MOTIVO})
            assert r.status_code == 200, r.text

    despues = await cliente.post("/solicitudes", headers=auth, json=cuerpo)
    assert "fin(es) de semana" not in despues.text, \
        "corregido el contador, esa traba ya no debe aparecer"
    # Sigue sin poder pedirlas, pero por la política del bloque mínimo, que es
    # una regla distinta y con su propia salida.
    assert "bloques de al menos" in despues.text
