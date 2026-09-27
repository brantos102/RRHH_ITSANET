"""Talento Humano atiende por región, y la firma deja de ser obligatoria.

Una solicitud de Quito la resuelve quien atiende la Sierra; una de
Guayaquil, quien atiende la Costa. Cualquier miembro de esa región puede
decidir: el aviso va al grupo, no a una persona.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app import notificaciones
from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA
from tests.test_reglas_nuevas import lunes_sin_feriados

CED_RRHH_SIERRA = "1700000019"
CED_RRHH_COSTA = "1700000027"
CED_JEFE_R = "1700000035"


@pytest.fixture
async def equipo_regional(cliente, codigos, empleado):
    """Un jefe, y Talento Humano en cada región."""
    await ejecutar("update public.users set ciudad = 'Quito' where id = %s", (empleado["id"],))
    jefe = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso, ciudad)
           values (%s, 'Jefe Region', 'jefer@api.test', 'jefe', current_date - 2000, 'Quito')
           on conflict (cedula) do update set rol = 'jefe' returning id""", (CED_JEFE_R,))
    await ejecutar("update public.users set jefe_id = %s where id = %s",
                   (jefe["id"], empleado["id"]))
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso, ciudad)
           values (%s, 'Talento Sierra', 'sierra@api.test', 'rrhh', current_date - 2000, 'Quito')
           on conflict (cedula) do update set rol='rrhh', ciudad='Quito' returning id""",
        (CED_RRHH_SIERRA,))
    await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso, ciudad)
           values (%s, 'Talento Costa', 'costa@api.test', 'rrhh', current_date - 2000, 'Guayaquil')
           on conflict (cedula) do update set rol='rrhh', ciudad='Guayaquil' returning id""",
        (CED_RRHH_COSTA,))
    yield jefe
    await ejecutar("delete from public.users where cedula = any(%s)",
                   ([CED_RRHH_SIERRA, CED_RRHH_COSTA, CED_JEFE_R],))


async def _sesion(cliente, codigos, cedula):
    await cliente.post("/auth/solicitar-token", json={"cedula": cedula})
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": cedula, "codigo": codigos[-1]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_la_ciudad_decide_la_region(empleado):
    for ciudad, esperado in [("Quito", "sierra"), ("Guayaquil", "costa"),
                             ("Cuenca", "sierra"), ("Manta", "costa"),
                             ("Tena", "sierra"), ("Galápagos", "costa")]:
        fila = await obtener_uno(
            "select public.region_de_ciudad(%s) as region", (ciudad,))
        assert fila["region"] == esperado, f"{ciudad} debería ser {esperado}"


async def test_una_ciudad_desconocida_se_atiende_desde_quito():
    """Mejor que llegue a la sede administrativa que a nadie."""
    fila = await obtener_uno("select public.region_de_ciudad(%s) as region", ("Timbuktú",))
    assert fila["region"] == "sierra"


async def test_la_solicitud_guarda_la_region_de_quien_la_pide(
        cliente, codigos, empleado, equipo_regional):
    auth = await _sesion(cliente, codigos, CEDULA_PRUEBA)
    lunes = await lunes_sin_feriados()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Vacaciones de quien trabaja en Quito", "firmar": False,
    })
    assert r.status_code == 201, r.text
    fila = await obtener_uno(
        "select region from public.requests where id = %s", (r.json()["id"],))
    assert fila["region"] == "sierra"


async def test_talento_humano_solo_ve_lo_de_su_region(
        cliente, codigos, empleado, equipo_regional):
    """El de Guayaquil no debe resolver papeles de gente de Quito."""
    auth = await _sesion(cliente, codigos, CEDULA_PRUEBA)
    lunes = await lunes_sin_feriados()
    creada = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Solicitud de personal de Quito", "firmar": False,
    })
    assert creada.status_code == 201, creada.text
    folio = creada.json()["id"]

    jefe_auth = await _sesion(cliente, codigos, CED_JEFE_R)
    paso = await cliente.post(f"/aprobaciones/{folio}/decidir", headers=jefe_auth,
                              json={"accion": "aprobar"})
    assert paso.status_code == 200, paso.text

    sierra = await _sesion(cliente, codigos, CED_RRHH_SIERRA)
    costa = await _sesion(cliente, codigos, CED_RRHH_COSTA)
    ids_sierra = {s["id"] for s in (await cliente.get("/aprobaciones/pendientes",
                                                      headers=sierra)).json()}
    ids_costa = {s["id"] for s in (await cliente.get("/aprobaciones/pendientes",
                                                     headers=costa)).json()}
    assert folio in ids_sierra, "Talento Humano de Quito debe verla"
    assert folio not in ids_costa, "Talento Humano de Guayaquil NO debe verla"


async def test_el_aviso_va_al_grupo_de_la_region(
        cliente, codigos, empleado, equipo_regional, monkeypatch):
    enviados: list[list[str]] = []

    async def capturar(destinatarios, solicitud, quien):
        enviados.append([d["email"] for d in destinatarios])

    monkeypatch.setattr(notificaciones, "avisar_a_rrhh", capturar)

    auth = await _sesion(cliente, codigos, CEDULA_PRUEBA)
    lunes = await lunes_sin_feriados()
    creada = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Solicitud para revisar a quien se avisa", "firmar": False,
    })
    jefe_auth = await _sesion(cliente, codigos, CED_JEFE_R)
    await cliente.post(f"/aprobaciones/{creada.json()['id']}/decidir",
                       headers=jefe_auth, json={"accion": "aprobar"})

    assert enviados, "debe avisarse a Talento Humano"
    assert "sierra@api.test" in enviados[-1]
    assert "costa@api.test" not in enviados[-1], "no se molesta a la otra región"


async def test_ningun_permiso_exige_ya_la_firma_dibujada():
    """Entrar exige un código al correo: la identidad ya está probada."""
    filas = await obtener_todos(
        "select codigo from public.permission_types where requiere_firma and activo")
    assert filas == [], f"siguen exigiendo firma: {[f['codigo'] for f in filas]}"


async def test_se_puede_pedir_un_permiso_sin_firmar(cliente, codigos, empleado, equipo_regional):
    auth = await _sesion(cliente, codigos, CEDULA_PRUEBA)
    tipo = await obtener_uno(
        "select id from public.permission_types where codigo = 'sufragio'")
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": tipo["id"],
        "fecha_inicio": str(await lunes_sin_feriados()),
        "fecha_fin": str(await lunes_sin_feriados()),
        "descripcion": "Soy miembro de junta receptora del voto", "firmar": False,
    })
    assert r.status_code == 201, r.text
