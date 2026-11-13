"""Una persona no puede estar ausente dos veces los mismos días.

Salió a la luz probando el calendario del equipo con datos acumulados: una
misma colaboradora tenía cinco ausencias aprobadas que empezaban el mismo día,
y el jefe veía un folio mientras Talento Humano veía otro para esa fecha. Nada
lo impedía, y las consecuencias no son cosméticas: el saldo se descuenta una
vez por solicitud —los mismos días se pagan dos veces— y garita acepta varios
QR válidos para la misma jornada.

La única convivencia legítima es la de dos permisos por horas del mismo día en
horarios que no se pisan.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from app.db import ejecutar, obtener_todos, obtener_uno
from tests.conftest import CEDULA_PRUEBA
from tests.test_reglas_nuevas import (CEDULA_JEFE_R, CEDULA_RRHH_R,  # noqa: F401
                                      auth, jefe_auth, lunes_sin_feriados,
                                      rrhh_auth)


async def _tipo_por_horas(horas_necesarias: float = 3) -> dict:
    """Un subtipo por horas, sin respaldo obligatorio y con margen suficiente.

    El tope de horas importa: «lactancia» admite horas pero solo dos, y una
    prueba de traslape de 12:00 a 15:00 chocaba con ese límite en vez de con
    la regla que se quiere comprobar.
    """
    return await obtener_uno(
        """select id, codigo, nombre, max_horas from public.permission_types
           where admite_horas and not requiere_adjunto and activo
             and (max_horas is null or max_horas >= %s)
           order by id limit 1""",
        (horas_necesarias,),
    )


# ------------------------------------------------------------ días completos
async def test_no_se_puede_pedir_dos_veces_el_mismo_rango(cliente, auth):
    lunes = await lunes_sin_feriados()
    cuerpo = {"tipo": "vacacion", "fecha_inicio": str(lunes),
              "fecha_fin": str(lunes + timedelta(days=7)),
              "descripcion": "Ocho dias de descanso programado", "firmar": False}

    primera = await cliente.post("/solicitudes", headers=auth, json=cuerpo)
    assert primera.status_code == 201, primera.text

    segunda = await cliente.post("/solicitudes", headers=auth, json=cuerpo)
    assert segunda.status_code == 422, segunda.text
    detalle = segunda.json()["detail"]
    # El mensaje debe permitir actuar: qué fechas y qué solicitud estorban.
    assert "ya tiene una ausencia" in detalle["mensaje"].lower(), detalle
    assert str(primera.json()["folio"]) in detalle["mensaje"], detalle
    # El folio también aparte, para que el formulario pueda enlazarlo.
    assert detalle.get("solapa_con_folio") == str(primera.json()["folio"]), detalle
    # Y nunca como rango sugerido: la pista «solape|1234» tiene dos partes y el
    # formato antiguo la tomaba por un par de fechas, así que el formulario
    # ofrecía corregir el rango a «solape»–«1234».
    assert "rango_sugerido" not in detalle, detalle


async def test_basta_que_se_cruce_un_solo_dia(cliente, auth):
    lunes = await lunes_sin_feriados()
    primera = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Primer bloque de ocho dias", "firmar": False})
    assert primera.status_code == 201, primera.text

    # Empieza el último día del bloque anterior: un día compartido ya es estar
    # ausente dos veces.
    solapada = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes + timedelta(days=7)),
        "fecha_fin": str(lunes + timedelta(days=14)),
        "descripcion": "Segundo bloque que pisa un dia del primero", "firmar": False})
    assert solapada.status_code == 422, solapada.text


@pytest.mark.parametrize(
    "desplazamiento_inicio, desplazamiento_fin, caso",
    [
        (-4, 18, "un rango que engloba por completo al ya pedido"),
        (2, 4, "un rango enteramente dentro del ya pedido"),
    ],
)
async def test_contener_o_estar_contenido_tambien_es_solaparse(
        cliente, auth, desplazamiento_inicio, desplazamiento_fin, caso):
    """No basta con mirar los extremos: uno puede tragarse al otro."""
    lunes = await lunes_sin_feriados()
    primera = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Bloque de ocho dias ya comprometido", "firmar": False})
    assert primera.status_code == 201, primera.text

    # El segundo se arma con un tipo por horas cuando es corto, para no topar
    # con el mínimo de días de vacaciones en vez de con la regla del solape.
    tipo = await _tipo_por_horas()
    inicio = lunes + timedelta(days=desplazamiento_inicio)
    fin = lunes + timedelta(days=desplazamiento_fin)
    if (fin - inicio).days + 1 >= 7:
        cuerpo = {"tipo": "vacacion", "fecha_inicio": str(inicio), "fecha_fin": str(fin),
                  "descripcion": f"Segundo pedido: {caso}", "firmar": False}
    else:
        cuerpo = {"tipo": "permiso", "permission_type_id": tipo["id"],
                  "fecha_inicio": str(inicio), "fecha_fin": str(fin),
                  "descripcion": f"Segundo pedido: {caso}",
                  "justificacion": f"Se comprueba que {caso} tambien se rechaza.",
                  "firmar": False}

    segunda = await cliente.post("/solicitudes", headers=auth, json=cuerpo)
    assert segunda.status_code == 422, f"{caso}: {segunda.text}"


async def test_un_bloque_contiguo_si_se_permite(cliente, auth):
    """Terminar un lunes y empezar el martes no es solaparse."""
    lunes = await lunes_sin_feriados()
    primera = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Primer bloque de ocho dias", "firmar": False})
    assert primera.status_code == 201, primera.text

    segunda = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes + timedelta(days=8)),
        "fecha_fin": str(lunes + timedelta(days=15)),
        "descripcion": "Segundo bloque, empieza al dia siguiente del primero",
        "firmar": False})
    assert segunda.status_code == 201, segunda.text


async def test_lo_cancelado_libera_las_fechas(cliente, auth):
    """Si se anula, esos días vuelven a estar disponibles."""
    lunes = await lunes_sin_feriados()
    cuerpo = {"tipo": "vacacion", "fecha_inicio": str(lunes),
              "fecha_fin": str(lunes + timedelta(days=7)),
              "descripcion": "Ocho dias que luego se cancelan", "firmar": False}

    primera = await cliente.post("/solicitudes", headers=auth, json=cuerpo)
    assert primera.status_code == 201, primera.text
    await ejecutar("update public.requests set estado = 'cancelado' where id = %s",
                   (primera.json()["id"],))

    otra_vez = await cliente.post("/solicitudes", headers=auth, json=cuerpo)
    assert otra_vez.status_code == 201, otra_vez.text


# --------------------------------------------------------- permisos por horas
async def test_dos_permisos_el_mismo_dia_en_horarios_distintos_conviven(cliente, auth):
    """Una cita a media mañana y un trámite en la tarde son compatibles."""
    tipo = await _tipo_por_horas()
    assert tipo, "debe existir al menos un subtipo por horas sin respaldo obligatorio"
    lunes = await lunes_sin_feriados()

    manana = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": tipo["id"],
        "fecha_inicio": str(lunes), "fecha_fin": str(lunes),
        "hora_inicio": "09:00", "hora_fin": "11:00",
        "descripcion": "Diligencia personal a primera hora de la manana",
        "justificacion": "Tramite que solo se atiende en la manana.", "firmar": False})
    assert manana.status_code == 201, manana.text

    tarde = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": tipo["id"],
        "fecha_inicio": str(lunes), "fecha_fin": str(lunes),
        "hora_inicio": "16:00", "hora_fin": "18:00",
        "descripcion": "Otra diligencia en la tarde del mismo dia",
        "justificacion": "Turno asignado para la tarde de ese mismo dia.", "firmar": False})
    assert tarde.status_code == 201, tarde.text


async def test_pegados_sin_pisarse_tambien_conviven(cliente, auth):
    """Sale a las 11:00 y el siguiente empieza a las 11:00: no hay conflicto."""
    tipo = await _tipo_por_horas()
    lunes = await lunes_sin_feriados()
    base = {"tipo": "permiso", "permission_type_id": tipo["id"],
            "fecha_inicio": str(lunes), "fecha_fin": str(lunes), "firmar": False}

    primero = await cliente.post("/solicitudes", headers=auth, json={
        **base, "hora_inicio": "09:00", "hora_fin": "11:00",
        "descripcion": "Primera diligencia de la manana",
        "justificacion": "Turno de las nueve de la manana."})
    assert primero.status_code == 201, primero.text

    segundo = await cliente.post("/solicitudes", headers=auth, json={
        **base, "hora_inicio": "11:00", "hora_fin": "13:00",
        "descripcion": "Segunda diligencia, justo despues de la primera",
        "justificacion": "Turno encadenado con el anterior, sin traslape."})
    assert segundo.status_code == 201, segundo.text


async def test_horarios_que_se_pisan_no_conviven(cliente, auth):
    tipo = await _tipo_por_horas()
    lunes = await lunes_sin_feriados()
    base = {"tipo": "permiso", "permission_type_id": tipo["id"],
            "fecha_inicio": str(lunes), "fecha_fin": str(lunes), "firmar": False}

    primero = await cliente.post("/solicitudes", headers=auth, json={
        **base, "hora_inicio": "12:00", "hora_fin": "15:00",
        "descripcion": "Cita agendada a las trece horas de ese dia",
        "justificacion": "Cita confirmada para las 13:00."})
    assert primero.status_code == 201, primero.text

    encimado = await cliente.post("/solicitudes", headers=auth, json={
        **base, "hora_inicio": "14:00", "hora_fin": "17:00",
        "descripcion": "Otra diligencia que se cruza una hora con la anterior",
        "justificacion": "Se cruza con el permiso anterior a proposito."})
    assert encimado.status_code == 422, encimado.text


async def test_una_ausencia_de_jornada_completa_choca_con_las_de_horas(cliente, auth):
    tipo = await _tipo_por_horas()
    lunes = await lunes_sin_feriados()

    por_horas = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": tipo["id"],
        "fecha_inicio": str(lunes), "fecha_fin": str(lunes),
        "hora_inicio": "09:00", "hora_fin": "11:00",
        "descripcion": "Diligencia breve de la manana",
        "justificacion": "Turno de la manana de ese dia.", "firmar": False})
    assert por_horas.status_code == 201, por_horas.text

    # Sin horas: es la jornada entera, así que se come el permiso anterior.
    completa = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "permiso", "permission_type_id": tipo["id"],
        "fecha_inicio": str(lunes), "fecha_fin": str(lunes),
        "descripcion": "Jornada completa el mismo dia del permiso por horas",
        "justificacion": "Ausencia de todo el dia sobre un permiso de horas.",
        "firmar": False})
    assert completa.status_code == 422, completa.text


# ------------------------------------------------- el ajuste de Talento Humano
async def test_talento_humano_no_puede_extender_encima_de_otra_ausencia(
        cliente, auth, jefe_auth, rrhh_auth):
    """Extender es tan capaz de solapar como crear."""
    lunes = await lunes_sin_feriados()

    primera = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Bloque que luego intentaran extender", "firmar": False})
    assert primera.status_code == 201, primera.text
    uno = primera.json()

    segunda = await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes + timedelta(days=10)),
        "fecha_fin": str(lunes + timedelta(days=17)),
        "descripcion": "Segundo bloque, mas adelante en el calendario", "firmar": False})
    assert segunda.status_code == 201, segunda.text

    for etapa in (jefe_auth, rrhh_auth):
        await cliente.post(f"/aprobaciones/{uno['id']}/decidir", headers=etapa,
                           json={"accion": "aprobar"})

    # Extenderla hasta el día 12 la mete encima del segundo bloque.
    choque = await cliente.post(f"/aprobaciones/{uno['id']}/ajustar", headers=rrhh_auth, json={
        "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=12)),
        "motivo": "El especialista prolongo el reposo por cinco dias adicionales",
        "resolucion": "Se intenta ampliar la ausencia con el certificado entregado"})
    assert choque.status_code == 422, choque.text

    # Y hasta el día 9, que no toca nada, sí procede.
    valido = await cliente.post(f"/aprobaciones/{uno['id']}/ajustar", headers=rrhh_auth, json={
        "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=9)),
        "motivo": "El especialista prolongo el reposo por dos dias adicionales",
        "resolucion": "Se amplia la ausencia hasta el dia nueve con el certificado"})
    assert valido.status_code == 200, valido.text


async def test_el_ajuste_mantiene_vigente_el_qr_hasta_el_nuevo_fin(
        cliente, auth, jefe_auth, rrhh_auth):
    """Al extender, garita debe seguir reconociendo la salida."""
    lunes = await lunes_sin_feriados()
    creada = (await cliente.post("/solicitudes", headers=auth, json={
        "tipo": "vacacion", "fecha_inicio": str(lunes),
        "fecha_fin": str(lunes + timedelta(days=7)),
        "descripcion": "Ocho dias que se extenderan dos mas", "firmar": False})).json()
    for etapa in (jefe_auth, rrhh_auth):
        await cliente.post(f"/aprobaciones/{creada['id']}/decidir", headers=etapa,
                           json={"accion": "aprobar"})

    nuevo_fin = lunes + timedelta(days=9)
    r = await cliente.post(f"/aprobaciones/{creada['id']}/ajustar", headers=rrhh_auth, json={
        "fecha_inicio": str(lunes), "fecha_fin": str(nuevo_fin),
        "motivo": "El especialista prolongo el reposo por dos dias adicionales",
        "resolucion": "Se amplia la ausencia con el certificado entregado en Talento Humano"})
    assert r.status_code == 200, r.text

    fila = await obtener_uno(
        "select fecha_fin, qr_expira_en from public.requests where id = %s", (creada["id"],))
    assert fila["fecha_fin"] == nuevo_fin
    assert fila["qr_expira_en"] is not None, "el QR debe seguir vigente tras extender"
    assert fila["qr_expira_en"].date() > nuevo_fin - timedelta(days=1)
