"""Dos correcciones que nacen de mirar el panel y no entenderlo.

1. La tarjeta decía «45 días» en grande y debajo «año 6 (8.75)». No era un
   error de cálculo: son cosas distintas —lo ganado en años cumplidos frente a
   lo que se acumula del año en marcha— sumadas en una sola cifra que nadie
   sabía leer.

2. Pedir menos días de los que fija la política deja la solicitud en
   `pendiente_rrhh`, pero el aviso se enviaba al jefe, que no puede resolverla,
   y Talento Humano no recibía ninguno.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, lunes_sin_feriados,
                                      rrhh_auth)


# ----------------------------------------------------------- desglose del saldo
CEDULA_DESGLOSE = "1700000738"


@pytest.fixture
async def persona_con_cinco_anios():
    """Alguien con años cumplidos y un año en marcha, sin saldo precargado.

    El empleado compartido de las pruebas nace con un saldo inicial que
    consume el período en curso, y entonces no hay nada «en formación» que
    mirar: justo la mitad del desglose que interesa comprobar.
    """
    await ejecutar("delete from public.users where cedula = %s", (CEDULA_DESGLOSE,))
    fila = await obtener_uno(
        """insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
           values (%s, 'Desglose Prueba', 'desglose@itsanet.test', 'empleado', %s)
           returning id""",
        (CEDULA_DESGLOSE, date(2021, 2, 1)),
    )
    user_id = str(fila["id"])
    await obtener_uno("select public.generar_periodos_vacaciones(%s)", (user_id,))
    await obtener_uno("select public.caducar_periodos_vencidos()")
    yield user_id
    await ejecutar("delete from public.users where cedula = %s", (CEDULA_DESGLOSE,))


async def test_el_saldo_separa_lo_ganado_de_lo_que_se_acumula(persona_con_cinco_anios):
    """Cinco años cumplidos y un año en marcha no son la misma bolsa de días."""
    d = await obtener_uno(
        "select * from public.saldo_desglosado(%s)", (persona_con_cinco_anios,))

    # Lo ganado sale de años cumplidos; lo en curso, del año que corre.
    assert float(d["dias_ganados"]) > 0, "cinco años cumplidos dan días exigibles"
    assert float(d["dias_en_curso"]) > 0, "el año en marcha acumula 1,25 por mes"
    assert float(d["dias_ganados"]) != float(d["dias_en_curso"])

    # Juntos son el total que antes se mostraba como una sola cifra: de ahí
    # salía el «45 días» encima de un detalle que decía «año 6 (8.75)».
    assert (float(d["dias_ganados"]) + float(d["dias_en_curso"])
            == pytest.approx(float(d["saldo_cacheado"])))
    assert d["desalineado"] is False

    # Y no caducó nada, porque la empresa no extingue días. Las dos claves
    # siguen existiendo —la tarjeta las lee y el día que haya un contrato de
    # plazo fijo harán falta—, pero vienen vacías.
    assert float(d["dias_caducados"]) == 0, (
        "con la caducidad apagada nadie pierde días, por antiguo que sea"
    )
    assert d["proximo_vence_en"] is None, (
        "una fecha de vencimiento que no va a cumplirse no se muestra"
    )


async def test_el_desglose_llega_por_la_api(cliente, auth, empleado):
    """Las claves nuevas deben verse desde el panel, no solo en la base."""
    await obtener_uno("select public.generar_periodos_vacaciones(%s)", (empleado["id"],))
    r = await cliente.get("/auth/mi-saldo", headers=auth)
    assert r.status_code == 200, r.text
    saldo = r.json()
    for clave in ("dias_ganados", "dias_en_curso", "dias_caducados",
                  "proximo_vence_en", "saldo_desalineado"):
        assert clave in saldo, f"falta {clave}: la tarjeta lo necesita"
    # Las claves de siempre siguen ahí: la pantalla vieja no debe romperse.
    for clave in ("saldo_total", "periodos", "anios_servicio", "fines_semana_pendientes"):
        assert clave in saldo, f"se perdió {clave}"


async def test_el_saldo_avisa_si_el_cacheado_no_cuadra(cliente, auth, empleado):
    """Un titular que no coincide con sus períodos miente sin que nadie lo note."""
    await obtener_uno("select public.generar_periodos_vacaciones(%s)", (empleado["id"],))

    sano = (await cliente.get("/auth/mi-saldo", headers=auth)).json()
    assert sano["saldo_desalineado"] is False

    # Se desalinea a mano, como lo haría una carga mal hecha.
    await ejecutar("update public.users set dias_vacaciones = dias_vacaciones + 20 where id = %s",
                   (empleado["id"],))
    roto = (await cliente.get("/auth/mi-saldo", headers=auth)).json()
    assert roto["saldo_desalineado"] is True, "debe detectarse la diferencia"

    # Y se repara.
    await obtener_uno("select public.recalcular_saldos(%s)", (empleado["id"],))
    reparado = (await cliente.get("/auth/mi-saldo", headers=auth)).json()
    assert reparado["saldo_desalineado"] is False


async def test_la_vista_de_control_lista_a_quien_tenga_el_saldo_torcido(empleado):
    await obtener_uno("select public.generar_periodos_vacaciones(%s)", (empleado["id"],))
    await obtener_uno("select public.recalcular_saldos(%s)", (empleado["id"],))

    antes = await obtener_todos(
        "select cedula from public.v_saldos_desalineados where cedula = %s", (CEDULA_PRUEBA,))
    assert antes == [], "recién recalculado no debería aparecer"

    await ejecutar("update public.users set dias_vacaciones = 90 where id = %s",
                   (empleado["id"],))
    despues = await obtener_todos(
        "select cedula, diferencia from public.v_saldos_desalineados where cedula = %s",
        (CEDULA_PRUEBA,))
    assert len(despues) == 1, "la diferencia debe salir en la vista de control"


# ------------------------------------------- la excepción la resuelve Talento Humano
async def test_un_bloque_menor_avisa_a_talento_humano_y_no_al_jefe(
        cliente, auth, jefe_auth, rrhh_auth, monkeypatch):
    """El aviso iba al jefe, que en ese estado no puede decidir nada."""
    from app import notificaciones

    avisados: dict = {}

    async def falso_rrhh(destinatarios, solicitud, empleado_email):
        avisados["rrhh"] = [d["email"] for d in destinatarios]
        avisados["copia"] = empleado_email

    async def falso_jefe(jefe, solicitud):
        avisados["jefe"] = jefe["email"]

    monkeypatch.setattr(notificaciones, "avisar_excepcion_a_rrhh", falso_rrhh)
    monkeypatch.setattr(notificaciones, "avisar_al_jefe", falso_jefe)

    lunes = await lunes_sin_feriados()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=1)),
        "descripcion": "Dos dias por un asunto familiar impostergable",
        "bloque_menor_justificado": True,
        "justificacion": "Debo acompanar a mi madre a una cirugia programada ese lunes y martes.",
        "firmar": False,
        "adjuntos": [{"storage_path": "solicitudes/x.pdf", "nombre_archivo": "orden.pdf",
                      "mime_type": "application/pdf", "tamano_bytes": 2048,
                      "hash_sha256": "c" * 64}],
    })
    assert r.status_code == 201, r.text
    cuerpo = r.json()
    assert cuerpo["estado"] == "pendiente_rrhh"
    assert cuerpo["emergente"] is True
    assert "Talento Humano" in cuerpo["mensaje"]
    assert "emergentes" in cuerpo["mensaje"]

    assert "rrhh" in avisados, "Talento Humano debía recibir el aviso"
    assert "jefe" not in avisados, "el jefe no decide en esta etapa: no debe recibirlo"
    assert avisados["copia"], "el empleado va en copia, para tener la constancia"


async def test_la_excepcion_no_exige_el_fin_de_semana_obligatorio(cliente, auth, empleado):
    """Pedir dos días no puede responderse con «tome cuatro».

    Los dos fines de semana completos son una regla del descanso anual entero
    (Art. 69 CT, 4 de los 15 días). Exigírselos a una ausencia corta y
    justificada es pedir justo lo que la excepción existe para no pedir: el
    sistema contestaba «use 2026-11-07 a 2026-11-10» a quien necesitaba el
    lunes y el martes.
    """
    # Se deja con fines de semana pendientes, que es cuando la regla muerde.
    await ejecutar(
        """update public.vacation_periods set fines_semana_consumidos = 0
           where user_id = %s and not caducado""",
        (empleado["id"],),
    )

    lunes = await lunes_sin_feriados()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=1)),
        "descripcion": "Dos dias por una urgencia familiar",
        "bloque_menor_justificado": True,
        "justificacion": "Debo acompanar a mi madre a una cirugia programada ese lunes y martes.",
        "firmar": False,
        "adjuntos": [{"storage_path": "solicitudes/y.pdf", "nombre_archivo": "orden.pdf",
                      "mime_type": "application/pdf", "tamano_bytes": 1024,
                      "hash_sha256": "d" * 64}],
    })
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "pendiente_rrhh"


async def test_una_vacacion_normal_si_respeta_el_fin_de_semana(cliente, auth, empleado):
    """La regla sigue en pie para el descanso ordinario."""
    await ejecutar(
        """update public.vacation_periods set fines_semana_consumidos = 0
           where user_id = %s and not caducado""",
        (empleado["id"],),
    )
    lunes = await lunes_sin_feriados()
    # De lunes a viernes: no incluye sábado ni domingo.
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=4)),
        "descripcion": "Cinco dias de lunes a viernes", "firmar": False,
    })
    assert r.status_code == 422, r.text


async def test_una_vacacion_normal_sigue_avisando_al_jefe(
        cliente, auth, jefe_auth, monkeypatch):
    """La ruta de siempre no cambia."""
    from app import notificaciones

    avisados: dict = {}

    async def falso_jefe(jefe, solicitud):
        avisados["jefe"] = jefe["email"]

    async def falso_rrhh(destinatarios, solicitud, empleado_email):
        avisados["rrhh"] = True

    monkeypatch.setattr(notificaciones, "avisar_al_jefe", falso_jefe)
    monkeypatch.setattr(notificaciones, "avisar_excepcion_a_rrhh", falso_rrhh)

    lunes = await lunes_sin_feriados()
    r = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes), "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Ocho dias de descanso programado", "firmar": False,
    })
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "pendiente_jefe"
    assert r.json()["emergente"] is False
    assert "jefe" in avisados
    assert "rrhh" not in avisados


async def test_el_correo_de_excepcion_lleva_copia_y_direccion_de_respuesta(monkeypatch):
    """Talento Humano debe poder responderle al empleado, no a un buzón mudo."""
    from app import correo, notificaciones

    enviados: list[dict] = []

    async def falso_envio(destinatario, asunto, texto, html=None, **extra):
        enviados.append({"para": destinatario, "asunto": asunto, **extra})

    monkeypatch.setattr(correo, "enviar", falso_envio)
    # Sin buzón del departamento, para contar solo a las personas. Se fija
    # aquí y no se da por supuesto: dependía de lo que hubiera en la tabla,
    # y una prueba anterior que lo configuraba hacía fallar a esta.
    monkeypatch.setattr(notificaciones, "_buzon_del_departamento",
                        lambda region: _sin_buzon())

    solicitud = {
        "folio": 123, "empleado": "Ana Prueba", "tipo": "vacacion",
        "fecha_inicio": date.today(), "fecha_fin": date.today() + timedelta(days=1),
        "dias_solicitados": 2, "descripcion": "Dos dias",
        "justificacion": "Motivo explicado", "rrhh_token": "11111111-1111-1111-1111-111111111111",
        "bloque_menor_justificado": True, "jefe_nombre": "Jefe Prueba",
    }
    await notificaciones.avisar_excepcion_a_rrhh(
        [{"email": "rrhh1@itsanet.com.ec", "nombre": "Uno"},
         {"email": "rrhh2@itsanet.com.ec", "nombre": "Dos"}],
        solicitud, "ana@itsanet.com.ec")

    assert len(enviados) == 2
    assert "emergentes" in enviados[0]["asunto"].lower()
    assert enviados[0]["responder_a"] == "ana@itsanet.com.ec"
    assert enviados[0]["copia"] == ["ana@itsanet.com.ec"]
    # La copia solo con el primero: el empleado no necesita el mismo aviso
    # tantas veces como personas haya en Talento Humano.
    assert enviados[1]["copia"] is None


async def _sin_buzon():
    return None


async def test_el_buzon_del_departamento_recibe_el_aviso(monkeypatch):
    """Los buzones personales fallan en silencio: la persona sale de
    vacaciones o deja la empresa y la solicitud sigue llegando a una
    dirección que nadie abre. El buzón del área suma, no reemplaza."""
    from app import correo, notificaciones

    enviados: list[dict] = []

    async def falso_envio(destinatario, asunto, texto, html=None, **extra):
        enviados.append({"para": destinatario, **extra})

    async def buzon(region):
        return "talentohumano@itsanet.com.ec"

    monkeypatch.setattr(correo, "enviar", falso_envio)
    monkeypatch.setattr(notificaciones, "_buzon_del_departamento", buzon)

    solicitud = {
        "folio": 124, "empleado": "Ana Prueba", "tipo": "vacacion",
        "fecha_inicio": date.today(), "fecha_fin": date.today() + timedelta(days=1),
        "dias_solicitados": 2, "descripcion": "Dos dias",
        "rrhh_token": "11111111-1111-1111-1111-111111111111",
        "jefe_nombre": "Jefe Prueba", "region": "sierra",
    }
    await notificaciones.avisar_a_rrhh(
        [{"email": "rrhh1@itsanet.com.ec", "nombre": "Uno"}], solicitud, "Jefe Prueba")

    destinatarios = [e["para"] for e in enviados]
    assert "talentohumano@itsanet.com.ec" in destinatarios, "el buzón del área no recibió"
    assert "rrhh1@itsanet.com.ec" in destinatarios, "el buzón personal dejó de recibir"


async def test_el_buzon_del_area_recibe_aunque_no_haya_nadie_en_la_region(monkeypatch):
    """Es justo cuando más falta hace: sin él, nadie se entera de nada."""
    from app import correo, notificaciones

    enviados: list[str] = []

    async def falso_envio(destinatario, asunto, texto, html=None, **extra):
        enviados.append(destinatario)

    async def buzon(region):
        return "talentohumano@itsanet.com.ec"

    monkeypatch.setattr(correo, "enviar", falso_envio)
    monkeypatch.setattr(notificaciones, "_buzon_del_departamento", buzon)

    solicitud = {
        "folio": 125, "empleado": "Ana Prueba", "tipo": "vacacion",
        "fecha_inicio": date.today(), "fecha_fin": date.today() + timedelta(days=1),
        "dias_solicitados": 2, "descripcion": "Dos dias",
        "rrhh_token": "11111111-1111-1111-1111-111111111111", "region": "costa",
    }
    await notificaciones.avisar_a_rrhh([], solicitud, "Jefe Prueba")
    assert enviados == ["talentohumano@itsanet.com.ec"]


async def test_no_se_duplica_cuando_el_buzon_es_el_de_una_persona(monkeypatch):
    """Si alguien puso su propio correo como buzón del área, no debe
    recibir el mismo aviso dos veces."""
    from app import correo, notificaciones

    enviados: list[str] = []

    async def falso_envio(destinatario, asunto, texto, html=None, **extra):
        enviados.append(destinatario)

    async def buzon(region):
        return "rrhh1@itsanet.com.ec"

    monkeypatch.setattr(correo, "enviar", falso_envio)
    monkeypatch.setattr(notificaciones, "_buzon_del_departamento", buzon)

    solicitud = {
        "folio": 126, "empleado": "Ana Prueba", "tipo": "vacacion",
        "fecha_inicio": date.today(), "fecha_fin": date.today() + timedelta(days=1),
        "dias_solicitados": 2, "descripcion": "Dos dias",
        "rrhh_token": "11111111-1111-1111-1111-111111111111", "region": "sierra",
    }
    await notificaciones.avisar_a_rrhh(
        [{"email": "rrhh1@itsanet.com.ec", "nombre": "Uno"}], solicitud, "Jefe Prueba")
    assert enviados == ["rrhh1@itsanet.com.ec"]
