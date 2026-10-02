"""Cómo terminó la relación laboral.

Una baja era `activo = false` y una fecha. Eso basta para que la persona
deje de entrar, y no basta para nada más: de la causa depende qué se
liquida, y es lo primero que pregunta cualquiera que revise el expediente
—una auditoría, el Ministerio del Trabajo, o el propio ex colaborador—.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.db import ejecutar, obtener_uno
from tests.test_reglas_nuevas import CEDULA_RRHH_R, auth, rrhh_auth  # noqa: F401


async def test_las_causas_vienen_con_el_articulo_que_las_sustenta(cliente, rrhh_auth):
    """De la causa depende lo que corresponde pagar: quien la elige tiene
    que ver el sustento al elegirla, no buscarlo después."""
    r = await cliente.get("/admin/motivos-salida", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    motivos = {m["codigo"]: m for m in r.json()}
    assert "despido_intempestivo" in motivos
    assert motivos["despido_intempestivo"]["articulo"] == "Art. 188"
    assert motivos["renuncia"]["articulo"] == "Art. 169 núm. 2"
    # Las dos clases de visto bueno son distintas y se pagan distinto.
    assert motivos["visto_bueno_empleador"]["articulo"] == "Art. 172"
    assert motivos["visto_bueno_trabajador"]["articulo"] == "Art. 173"


async def test_la_baja_queda_con_su_causa(cliente, rrhh_auth, empleado):
    r = await cliente.post(f"/admin/usuarios/{empleado['id']}/baja", headers=rrhh_auth,
                           json={"fecha_salida": str(date.today()),
                                 "motivo": "renuncia",
                                 "detalle": "Presentó renuncia con 15 días de aviso."})
    assert r.status_code == 200, r.text

    fila = await obtener_uno(
        """select activo, fecha_salida, motivo_salida::text as motivo, detalle_salida,
                  salida_registrada_por is not null as con_responsable
             from public.users where id = %s""", (empleado["id"],))
    assert fila["activo"] is False
    assert fila["motivo"] == "renuncia"
    assert "15 días" in fila["detalle_salida"]
    assert fila["con_responsable"], "debe quedar quién la registró"


async def test_dice_cuantos_dias_quedan_por_liquidar(cliente, rrhh_auth, empleado):
    """Las vacaciones no gozadas se pagan SIEMPRE, sea cual sea la causa
    (Art. 76). Es la confusión más común al dar una baja por despido."""
    r = await cliente.post(f"/admin/usuarios/{empleado['id']}/baja", headers=rrhh_auth,
                           json={"fecha_salida": str(date.today()),
                                 "motivo": "despido_intempestivo"})
    cuerpo = r.json()
    assert cuerpo["dias_por_liquidar"] > 0, "el empleado de prueba tiene saldo"
    assert "Art. 76" in cuerpo["mensaje"]


async def test_avisa_de_lo_que_queda_abierto_a_su_nombre(cliente, rrhh_auth, empleado):
    """No se impide la baja —la persona ya se fue— pero se devuelve para
    resolverlo ahora en vez de descubrirlo semanas después."""
    await ejecutar(
        """insert into public.requests
             (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin, dias_solicitados,
              descripcion, justificacion, estado)
           select %s, 'permiso', id, current_date + 20, current_date + 20, 1,
                  'Tramite pendiente', 'Quedo en tramite al salir', 'pendiente_jefe'
             from public.permission_types
            where activo and not requiere_adjunto order by id limit 1""",
        (empleado["id"],))

    r = await cliente.post(f"/admin/usuarios/{empleado['id']}/baja", headers=rrhh_auth,
                           json={"fecha_salida": str(date.today()), "motivo": "renuncia"})
    assert r.json()["solicitudes_pendientes"] >= 1


async def test_una_baja_sin_causa_no_se_admite(cliente, rrhh_auth, empleado):
    r = await cliente.post(f"/admin/usuarios/{empleado['id']}/baja", headers=rrhh_auth,
                           json={"fecha_salida": str(date.today())})
    assert r.status_code == 422


async def test_una_causa_inventada_no_se_admite(cliente, rrhh_auth, empleado):
    """Las causas son las del Código del Trabajo, no texto libre."""
    r = await cliente.post(f"/admin/usuarios/{empleado['id']}/baja", headers=rrhh_auth,
                           json={"fecha_salida": str(date.today()), "motivo": "lo_botaron"})
    assert r.status_code == 422


async def test_la_fecha_de_salida_no_puede_ser_futura(cliente, rrhh_auth, empleado):
    r = await cliente.post(f"/admin/usuarios/{empleado['id']}/baja", headers=rrhh_auth,
                           json={"fecha_salida": str(date.today() + timedelta(days=30)),
                                 "motivo": "renuncia"})
    assert r.status_code >= 400


async def test_nadie_se_da_de_baja_a_si_mismo(cliente, rrhh_auth):
    yo = await obtener_uno("select id from public.users where cedula = %s", (CEDULA_RRHH_R,))
    r = await cliente.post(f"/admin/usuarios/{yo['id']}/baja", headers=rrhh_auth,
                           json={"fecha_salida": str(date.today()), "motivo": "renuncia"})
    assert r.status_code >= 400
    assert "usted mismo" in r.text


async def test_un_empleado_no_da_de_baja_a_nadie(cliente, auth, empleado):
    r = await cliente.post(f"/admin/usuarios/{empleado['id']}/baja", headers=auth,
                           json={"fecha_salida": str(date.today()), "motivo": "renuncia"})
    assert r.status_code == 403


async def test_la_lista_de_salidas_sirve_para_la_liquidación(cliente, rrhh_auth, empleado):
    await cliente.post(f"/admin/usuarios/{empleado['id']}/baja", headers=rrhh_auth,
                       json={"fecha_salida": str(date.today()), "motivo": "jubilacion"})
    r = await cliente.get("/admin/salidas", headers=rrhh_auth)
    assert r.status_code == 200, r.text
    mia = next((s for s in r.json() if s["id"] == empleado["id"]), None)
    assert mia is not None
    assert mia["motivo"] == "jubilacion"
    assert mia["dias_por_liquidar"] > 0
    assert mia["anios_servicio"] >= 1
