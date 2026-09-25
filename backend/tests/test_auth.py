"""Flujo de autenticación por cédula + OTP, contra base de datos real."""
from __future__ import annotations

import jwt
import pytest

from app.db import obtener_uno
from app.routers.auth import enmascarar
from tests.conftest import CEDULA_PRUEBA, CEDULA_SIN_REGISTRO


# ----------------------------------------------------- solicitud del código
async def test_cedula_con_formato_invalido_se_rechaza(cliente):
    r = await cliente.post("/auth/solicitar-token", json={"cedula": "1234567890"})
    assert r.status_code == 422


async def test_cedula_no_registrada_no_revela_nada(cliente, codigos):
    r = await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_SIN_REGISTRO})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["enviado"] is True          # misma respuesta que una cédula válida
    assert cuerpo["correo"] is None           # pero sin correo que confirme existencia
    assert codigos == []                      # y no se envió nada


async def test_cedula_registrada_recibe_codigo(cliente, codigos, empleado):
    r = await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    assert r.status_code == 200
    assert r.json()["correo"] == "p***a@api.test"
    assert len(codigos) == 1 and len(codigos[0]) == 6 and codigos[0].isdigit()


async def test_el_codigo_se_guarda_hasheado(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    fila = await obtener_uno(
        "select code_hash from public.auth_otp where cedula = %s", (CEDULA_PRUEBA,)
    )
    assert codigos[0] not in fila["code_hash"]
    assert len(fila["code_hash"]) == 64        # SHA-256 en hexadecimal


async def test_pedir_codigo_nuevo_anula_el_anterior(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})

    r = await cliente.post(
        "/auth/validar-token", json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]}
    )
    assert r.status_code == 401                # el primero ya no sirve

    r = await cliente.post(
        "/auth/validar-token", json={"cedula": CEDULA_PRUEBA, "codigo": codigos[1]}
    )
    assert r.status_code == 200


async def test_limite_de_envios_por_hora(cliente, codigos, empleado):
    for _ in range(5):
        assert (await cliente.post(
            "/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})).status_code == 200
    r = await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    assert r.status_code == 429


# --------------------------------------------------------- validación y sesión
async def test_codigo_correcto_inicia_sesion(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    r = await cliente.post(
        "/auth/validar-token", json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]}
    )
    assert r.status_code == 200

    sesion = r.json()
    assert sesion["token_type"] == "bearer"
    assert sesion["perfil"]["cedula"] == CEDULA_PRUEBA
    assert sesion["perfil"]["anios_servicio"] == 7
    assert sesion["perfil"]["rol"] == "empleado"

    datos = jwt.decode(
        sesion["access_token"],
        "secreto-de-prueba-suficientemente-largo-1234",
        algorithms=["HS256"],
        audience="authenticated",
    )
    assert datos["role"] == "authenticated"
    assert datos["user_metadata"]["cedula"] == CEDULA_PRUEBA


async def test_codigo_incorrecto_no_inicia_sesion(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    equivocado = "000000" if codigos[0] != "000000" else "111111"

    r = await cliente.post(
        "/auth/validar-token", json={"cedula": CEDULA_PRUEBA, "codigo": equivocado}
    )
    assert r.status_code == 401

    fila = await obtener_uno(
        "select intentos from public.auth_otp where cedula = %s", (CEDULA_PRUEBA,)
    )
    assert fila["intentos"] == 1               # el intento quedó contado


async def test_el_codigo_es_de_un_solo_uso(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    cuerpo = {"cedula": CEDULA_PRUEBA, "codigo": codigos[0]}

    assert (await cliente.post("/auth/validar-token", json=cuerpo)).status_code == 200
    assert (await cliente.post("/auth/validar-token", json=cuerpo)).status_code == 401


async def test_intentos_agotados_bloquean_el_codigo(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    equivocado = "000000" if codigos[0] != "000000" else "111111"

    for _ in range(5):
        await cliente.post(
            "/auth/validar-token", json={"cedula": CEDULA_PRUEBA, "codigo": equivocado}
        )

    # Incluso con el código correcto, ya está bloqueado
    r = await cliente.post(
        "/auth/validar-token", json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]}
    )
    assert r.status_code == 429


async def test_codigo_expirado_se_rechaza(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    await obtener_uno(
        "update public.auth_otp set expira_en = now() - interval '1 minute' "
        "where cedula = %s returning id",
        (CEDULA_PRUEBA,),
    )
    r = await cliente.post(
        "/auth/validar-token", json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]}
    )
    assert r.status_code == 401


async def test_el_inicio_de_sesion_queda_auditado(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    await cliente.post(
        "/auth/validar-token", json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]}
    )
    fila = await obtener_uno(
        """select count(*) as n from public.audit_logs
           where cedula = %s and accion in ('otp_enviado','sesion_iniciada')""",
        (CEDULA_PRUEBA,),
    )
    assert fila["n"] == 2


# ----------------------------------------------------------- endpoints con token
@pytest.fixture
async def sesion(cliente, codigos, empleado):
    await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})
    r = await cliente.post(
        "/auth/validar-token", json={"cedula": CEDULA_PRUEBA, "codigo": codigos[0]}
    )
    return r.json()


async def test_me_requiere_token(cliente):
    assert (await cliente.get("/auth/me")).status_code == 401


async def test_me_rechaza_token_manipulado(cliente, sesion):
    malo = sesion["access_token"][:-4] + "abcd"
    r = await cliente.get("/auth/me", headers={"Authorization": f"Bearer {malo}"})
    assert r.status_code == 401


async def test_me_devuelve_el_perfil(cliente, sesion):
    r = await cliente.get(
        "/auth/me", headers={"Authorization": f"Bearer {sesion['access_token']}"}
    )
    assert r.status_code == 200
    assert r.json()["cedula"] == CEDULA_PRUEBA


async def test_mi_saldo_explica_con_base_legal(cliente, sesion):
    r = await cliente.get(
        "/auth/mi-saldo", headers={"Authorization": f"Bearer {sesion['access_token']}"}
    )
    assert r.status_code == 200
    detalle = r.json()
    assert detalle["anios_servicio"] == 7
    assert detalle["dias_por_anio_actual"] == 17          # Art. 69: 15 + 2
    assert any(a["articulo"] == "Art. 69" for a in detalle["base_legal"])
    assert len(detalle["periodos"]) >= 7


async def test_glosario_publico(cliente):
    r = await cliente.get("/glosario")
    assert r.status_code == 200
    codigos_legales = {a["codigo"] for a in r.json()}
    assert {"CT_ART_69", "CT_ART_75", "LOPDP_ART_7"} <= codigos_legales


async def test_salud(cliente):
    r = await cliente.get("/salud")
    assert r.status_code == 200
    assert r.json()["base_datos"] == "conectada"


# ------------------------------------------------------------------ utilidades
@pytest.mark.parametrize(
    "correo,esperado",
    [
        ("juan.perez@itsanet.com.ec", "j***z@itsanet.com.ec"),
        ("ab@itsanet.com.ec", "a***@itsanet.com.ec"),
        ("a@itsanet.com.ec", "a***@itsanet.com.ec"),
        ("maria.jose.vera@itsanet.com.ec", "m***a@itsanet.com.ec"),
    ],
)
def test_enmascarar_correo(correo, esperado):
    assert enmascarar(correo) == esperado
