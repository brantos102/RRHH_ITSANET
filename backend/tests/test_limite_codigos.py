"""El tope de códigos por hora: que frene el abuso y no a quien usa bien.

Antes se contaba TODO código pedido en la última hora. Eso castiga justo al
que usa bien el sistema: alguien que entra, cierra sesión y vuelve a entrar
—probando, cambiando de pantalla en el teléfono, compartiendo el equipo de
garita— llegaba al tope de cinco en minutos y se quedaba una hora fuera sin
haber hecho nada malo. Y el mensaje, «Demasiados intentos», sugería que
había hecho algo mal.

Ahora se cuentan solo los códigos SIN CONSUMIR, que es la forma que tiene
el abuso: pedir una y otra vez sin usar ninguno.
"""
from __future__ import annotations

import pytest

from app.db import ejecutar, obtener_uno
from tests.conftest import CEDULA_PRUEBA


async def _pedir(cliente):
    return await cliente.post("/auth/solicitar-token", json={"cedula": CEDULA_PRUEBA})


async def _entrar_con_el_ultimo(cliente, codigos):
    """Entra de verdad con el código recién enviado.

    Se hace por la ruta real y no marcando la fila a mano: lo que libera el
    cupo es haber entrado, y esa es justamente la distinción que se prueba.
    """
    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_PRUEBA, "codigo": codigos[-1]})
    assert r.status_code == 200, r.text


async def test_entrar_varias_veces_no_bloquea(cliente, codigos, empleado):
    """El caso que importa: ocho ingresos normales, ninguno bloqueado."""
    for numero in range(8):
        r = await _pedir(cliente)
        assert r.status_code == 200, f"bloqueó en el ingreso {numero + 1}: {r.text}"
        # Lo que distingue un ingreso de un intento: el código se usa.
        await _entrar_con_el_ultimo(cliente, codigos)


async def test_pedir_sin_usar_ninguno_sigue_frenando(cliente, codigos, empleado):
    """Es la forma del abuso, y la protección tiene que quedarse."""
    from app.config import get_settings

    tope = get_settings().otp_max_envios_hora
    for _ in range(tope):
        assert (await _pedir(cliente)).status_code == 200

    r = await _pedir(cliente)
    assert r.status_code == 429, "dejó pedir por encima del tope sin usar ninguno"


async def test_el_mensaje_dice_qué_pasó_y_dónde_mirar(cliente, codigos, empleado):
    """«Demasiados intentos» suena a reproche y no orienta. La causa real
    casi siempre es que el correo no está llegando."""
    from app.config import get_settings

    for _ in range(get_settings().otp_max_envios_hora + 1):
        r = await _pedir(cliente)
    mensaje = r.json()["detail"]
    assert "no usó ninguno" in mensaje
    assert "no deseado" in mensaje, "debe sugerir dónde buscar el correo"
    assert "Talento Humano" in mensaje


async def test_usar_un_codigo_libera_el_cupo(cliente, codigos, empleado):
    """Quien se desbloqueó entrando no tiene que esperar una hora."""
    from app.config import get_settings

    tope = get_settings().otp_max_envios_hora
    for _ in range(tope):
        await _pedir(cliente)
    assert (await _pedir(cliente)).status_code == 429

    await _entrar_con_el_ultimo(cliente, codigos)
    assert (await _pedir(cliente)).status_code == 200, "entrar no liberó el cupo"


async def test_anular_un_codigo_no_cuenta_como_haber_entrado(cliente, codigos, empleado):
    """La trampa que casi se cuela: pedir otro código ANULA el anterior, y si
    anular se marcara igual que usar, pedir de nuevo contaría como ingreso y
    el tope no frenaría nunca a nadie."""
    from app.config import get_settings

    tope = get_settings().otp_max_envios_hora
    for _ in range(tope):
        assert (await _pedir(cliente)).status_code == 200
    r = await _pedir(cliente)
    assert r.status_code == 429, "pedir otro código no puede valer como haber entrado"

    fila = await obtener_uno(
        """select count(*) filter (where anulado_en is not null) as anulados,
                  count(*) filter (where consumido_en is not null) as usados
             from public.auth_otp where cedula = %s""", (CEDULA_PRUEBA,))
    assert fila["anulados"] >= tope - 1, "los anteriores deberían quedar anulados"
    assert fila["usados"] == 0, "nadie entró: ninguno debería figurar como usado"


async def test_agotar_los_intentos_anula_y_no_cuenta_como_ingreso(cliente, codigos, empleado):
    """Teclear mal el código cinco veces lo inutiliza, pero no es un ingreso."""
    await _pedir(cliente)
    for _ in range(6):
        await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_PRUEBA, "codigo": "000000"})

    fila = await obtener_uno(
        """select anulado_en is not null as anulado, consumido_en is not null as usado
             from public.auth_otp where cedula = %s
            order by created_at desc limit 1""", (CEDULA_PRUEBA,))
    assert fila["anulado"], "al agotar los intentos el código debe quedar anulado"
    assert not fila["usado"], "no entró nadie: no puede figurar como usado"


async def test_el_desbloqueo_no_da_acceso_a_nadie(cliente, codigos, empleado):
    """Levantar el bloqueo no puede ser una puerta: el código que se venció
    no debe servir para entrar."""
    await _pedir(cliente)
    codigo = codigos[-1]
    await ejecutar(
        """update public.auth_otp set expira_en = now() - interval '1 second'
            where cedula = %s and consumido_en is null""", (CEDULA_PRUEBA,))

    r = await cliente.post("/auth/validar-token",
                           json={"cedula": CEDULA_PRUEBA, "codigo": codigo})
    assert r.status_code == 401, "un código vencido dejó entrar"
