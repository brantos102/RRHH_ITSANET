"""Recorre la aplicación en un navegador de verdad y dice qué funciona.

Las pruebas de `backend/tests` comprueban la API; esto comprueba la pantalla,
que es donde estaban los huecos más caros de este proyecto: el chat existía en
el servidor y no en la interfaz, la ficha personal igual, y la bandeja de
Talento Humano no la consumía nadie. Ninguna prueba de API podía verlo.

    python scripts/pruebas_navegador.py --lista
    python scripts/pruebas_navegador.py                  # todo
    python scripts/pruebas_navegador.py --solo chat
    python scripts/pruebas_navegador.py --capturas ./ver  # deja las pantallas

Antes de empezar repone el estado del personal de prueba, así que se puede
repetir las veces que haga falta. Toca solo a quien tiene correo
`@itsanet.test` o cédula de prueba; nunca a la planilla real, y se niega a
correr con ENTORNO=produccion.

Necesita las dos cosas levantadas —backend en :8000 y frontend en :8100— y
Chromium. En Windows:

    py -m playwright install chromium
"""
from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

# psycopg no arranca sobre el bucle de eventos que Windows usa por
# omisión. La política correcta hay que fijarla antes de crear ningún
# bucle, es decir aquí. Ver scripts/_windows.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _windows  # noqa: F401,E402
import _cli  # noqa: E402

FRONTEND = "http://localhost:8100"
BACKEND = "http://localhost:8000"

# Personal de la semilla. Si cambia `supabase/seed.sql`, cambia aquí.
EMPLEADA = "0926687856"
ADMIN = "0602910945"
GUARDIA = "1713175071"
JEFE = "1710034065"
RRHH = "0703886002"


class Falla(Exception):
    """Algo no funciona en la pantalla. El mensaje va al usuario tal cual."""


# --------------------------------------------------------------- utilidades

def _ultimo_codigo() -> str | None:
    """El último código de acceso que escribió el backend.

    En desarrollo el correo no se envía: se escribe en el registro. Es la
    única forma de entrar sin un buzón real, y por eso estas pruebas solo
    corren fuera de producción.

    Se mira el último y no cuántos hay. Contar dentro de una ventana fija del
    registro parecía más seguro, pero el propio navegador genera tantas
    líneas por pantalla que los códigos viejos se salen de la ventana: la
    cuenta no subía nunca y la prueba se quedaba esperando un código que sí
    había llegado.
    """
    salida = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / "ver_logs.py"), "--buscar",
         "Código de acceso", "--ultimas", "300"],
        capture_output=True, text=True,
    )
    codigos = re.findall(r"Código de acceso: (\d{6})", salida.stdout)
    return codigos[-1] if codigos else None


class Paso:
    """Lleva la cuenta de lo comprobado para poder resumirlo al final."""

    def __init__(self, nombre: str) -> None:
        self.nombre = nombre
        self.hechos: list[str] = []

    def ok(self, texto: str) -> None:
        self.hechos.append(texto)
        print(f"  ✓ {texto}")


async def _entrar(pagina, cedula: str) -> None:
    antes = _ultimo_codigo()
    await pagina.goto(f"{FRONTEND}/index.html")
    await pagina.fill("#cedula", cedula)
    await pagina.click("#btn-enviar")
    await pagina.wait_for_selector("#paso-codigo:not(.hidden)", timeout=15000)
    for _ in range(60):
        ahora = _ultimo_codigo()
        if ahora is not None and ahora != antes:
            break
        await pagina.wait_for_timeout(250)
    else:
        raise Falla(f"No llegó el código de acceso de {cedula}. "
                    "¿Está el backend escribiendo su registro en backend/logs/?")
    await pagina.fill("#codigo", ahora)
    await pagina.wait_for_url("**/dashboard.html", timeout=20000)


# ------------------------------------------------------------- los recorridos

async def recorrido_acceso(nav, capturas) -> Paso:
    """Entrar, ver el saldo y que la barra se dibuje según el rol."""
    paso = Paso("acceso")
    pg = await (await nav.new_context(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)).new_page()

    await pg.goto(f"{FRONTEND}/index.html")
    await pg.fill("#cedula", "1234567890")
    await pg.click("#btn-enviar")
    await pg.wait_for_selector("#error-cedula:not(.hidden)", timeout=10000)
    paso.ok("una cédula inválida se rechaza en el navegador, sin ir al servidor")

    await _entrar(pg, EMPLEADA)
    await pg.wait_for_selector("#saldo-dias", timeout=15000)
    await pg.wait_for_timeout(1200)
    saldo = (await pg.inner_text("#saldo-dias")).strip()

    # La cifra tiene que ser la real, decimales incluidos. Hubo una versión
    # que redondeaba hacia abajo «para que se leyera mejor» y otra que
    # mostraba solo los días de años cumplidos: a quien ya había gozado sus
    # años anteriores le ponía un «0 días» enorme teniendo 8,75. Una cifra
    # que no cuadra con la que lleva Talento Humano no genera confianza,
    # genera un reclamo.
    from app.db import obtener_uno
    real = await obtener_uno(
        "select dias_vacaciones from public.users where cedula = %s", (EMPLEADA,))
    esperado = f"{float(real['dias_vacaciones']):g}".replace(".", ",")
    if saldo != esperado:
        raise Falla(f"El panel muestra «{saldo}» y la persona tiene {esperado} días. "
                    "La cifra grande debe ser la misma que lleva Talento Humano.")
    paso.ok(f"la colaboradora entra y ve su saldo exacto: {saldo} día(s)")

    composicion = (await pg.inner_text("#saldo-composicion")).strip()
    if not composicion:
        raise Falla("El panel no explica de qué se compone el saldo. "
                    "Una cifra sin explicación es una cifra que se discute.")
    paso.ok(f"y de qué se compone: «{composicion[:70]}…»")

    if capturas:
        await pg.screenshot(path=str(capturas / "panel-empleada.png"), full_page=True)
    return paso


async def recorrido_chat(nav, capturas) -> Paso:
    """La consulta llega a Talento Humano y la respuesta vuelve."""
    from app.db import ejecutar

    paso = Paso("chat")
    # Se parte sin hilos abiertos: la sede solo se ofrece al empezar uno, y
    # con una conversación en marcha el selector desaparece a propósito.
    await ejecutar(
        """delete from public.mensajes m using public.conversaciones c
            where m.conversacion_id = c.id
              and c.user_id in (select id from public.users where cedula = %s)""",
        (EMPLEADA,))
    await ejecutar(
        """delete from public.conversaciones
            where user_id in (select id from public.users where cedula = %s)""",
        (EMPLEADA,))

    emp = await (await nav.new_context(viewport={"width": 390, "height": 844},
                                       is_mobile=True, has_touch=True)).new_page()
    await _entrar(emp, EMPLEADA)

    await emp.wait_for_selector("#chat-burbuja", timeout=15000)
    paso.ok("la burbuja del chat está en el panel")

    for pantalla in ("equipo.html", "informes.html"):
        await emp.goto(f"{FRONTEND}/{pantalla}")
        try:
            await emp.wait_for_selector("#chat-burbuja", timeout=10000)
        except Exception as exc:
            raise Falla(f"El chat no aparece en {pantalla}. La barra lo monta "
                        "en todas las pantallas; si falta, revise "
                        "montarNavegacion en frontend/js/navegacion.js.") from exc
    paso.ok("y también en el calendario y los informes")

    await emp.goto(f"{FRONTEND}/dashboard.html")
    await emp.wait_for_selector("#chat-burbuja", timeout=15000)
    await emp.click("#chat-burbuja")
    await emp.wait_for_selector("#chat-panel:not(.hidden)")

    # Una ventana pequeña, no una pantalla. En el teléfono ocupa el ancho
    # menos los márgenes; lo que no puede es tapar la pantalla entera.
    caja = await emp.locator("#chat-panel").bounding_box()
    alto = await emp.evaluate("() => window.innerHeight")
    if caja["height"] > alto * 0.9:
        raise Falla(f"El chat ocupa {caja['height']:.0f} de {alto} px de alto: "
                    "es una ventana, no una pantalla.")
    paso.ok(f"se abre como ventana de {caja['width']:.0f}x{caja['height']:.0f} px")

    # Y se elige a qué sede va: Talento Humano está en Quito y en Guayaquil.
    sedes = emp.locator("#chat-sedes [data-sede]")
    if await sedes.count() < 2:
        raise Falla("No se puede elegir a qué sede va la consulta (UIO o GYE).")
    siglas = [(await sedes.nth(i).inner_text()).strip() for i in range(await sedes.count())]
    if not any("UIO" in s for s in siglas) or not any("GYE" in s for s in siglas):
        raise Falla(f"Las sedes ofrecidas son {siglas} y deberían ser UIO y GYE.")
    if "su sede" not in siglas[0]:
        raise Falla(f"La sede propia no va primero: {siglas}")
    paso.ok(f"se elige la sede: {' · '.join(siglas)}")

    consulta = "Comprobacion automatica: me quedan dias del periodo anterior?"
    await emp.fill("#chat-texto", consulta)
    await emp.click("#chat-form button[type=submit]")
    await emp.wait_for_selector(f"#chat-mensajes >> text={consulta[:40]}", timeout=15000)
    paso.ok("la consulta se envía y queda en el hilo")

    rh = await (await nav.new_context(viewport={"width": 1280, "height": 900})).new_page()
    await _entrar(rh, ADMIN)
    await rh.wait_for_selector("#chat-burbuja", timeout=15000)
    etiqueta = await rh.get_attribute("#chat-burbuja", "aria-label")
    if "sin leer" not in (etiqueta or ""):
        raise Falla("La burbuja de Talento Humano no avisa de mensajes sin leer.")
    paso.ok(f"Talento Humano lo ve: «{etiqueta}»")

    # La bandeja se abre EN LA MISMA PANTALLA, como ventanita.
    #
    # Antes la burbuja llevaba a una página entera: para contestar «sí, le
    # quedan ocho días» había que abandonar lo que se estaba haciendo, ir a
    # otra pantalla y volver. Así no contesta nadie, y la consulta se queda
    # sin respuesta.
    antes = rh.url
    await rh.click("#chat-burbuja")
    await rh.wait_for_selector("#chat-panel:not(.hidden)", timeout=15000)
    if rh.url != antes:
        raise Falla("La burbuja de Talento Humano sigue cambiando de página "
                    "en vez de abrir una ventana.")
    caja = await rh.locator("#chat-panel").bounding_box()
    alto = await rh.evaluate("() => window.innerHeight")
    if caja["height"] > alto * 0.9:
        raise Falla(f"La bandeja ocupa {caja['height']:.0f} de {alto} px: "
                    "es una ventana, no una pantalla.")
    paso.ok(f"la bandeja se abre como ventana de {caja['width']:.0f}x{caja['height']:.0f} px")

    await rh.wait_for_selector("#bandeja-lista [data-hilo]", timeout=15000)
    await rh.locator("#bandeja-lista [data-hilo]").first.click()
    await rh.wait_for_selector(f"#chat-mensajes >> text={consulta[:40]}", timeout=15000)

    respuesta = "Comprobacion automatica: si, le quedan y no caducan este ano."
    await rh.fill("#chat-texto", respuesta)
    await rh.click("#chat-form button[type=submit]")
    await rh.wait_for_selector(f"#chat-mensajes >> text={respuesta[:40]}", timeout=15000)
    paso.ok("responde sin salir de la pantalla en la que estaba")
    if capturas:
        await rh.screenshot(path=str(capturas / "bandeja-chat.png"))

    # Y la pantalla completa sigue estando para quien quiera trabajar la
    # bandeja entera: se llega por el menú, no se perdió.
    await rh.goto(f"{FRONTEND}/mensajes.html")
    await rh.wait_for_selector("[data-hilo]", timeout=15000)
    paso.ok("la bandeja completa sigue existiendo por el menú")

    await emp.reload()
    await emp.wait_for_selector("#chat-burbuja", timeout=15000)
    await emp.click("#chat-burbuja")
    await emp.wait_for_selector(f"#chat-mensajes >> text={respuesta[:40]}", timeout=15000)
    paso.ok("y la respuesta llega al chat de la colaboradora")
    return paso


async def recorrido_ficha(nav, capturas) -> Paso:
    """Lo que se corrige solo, lo que confirma Talento Humano, y quién decide."""
    paso = Paso("ficha")
    emp = await (await nav.new_context(viewport={"width": 390, "height": 844},
                                       is_mobile=True, has_touch=True)).new_page()
    await _entrar(emp, EMPLEADA)

    await emp.goto(f"{FRONTEND}/mi-ficha.html")
    await emp.wait_for_selector("#mf-expediente > div", timeout=15000)
    etiquetas = await emp.locator("#mf-expediente span").all_inner_texts()
    for esperada in ("No se modifica desde aquí", "Lo confirma Talento Humano"):
        if esperada not in etiquetas:
            raise Falla(f"La ficha no dice «{esperada}» en ningún dato. "
                        "Cada campo debe declarar quién decide sobre él.")
    paso.ok("cada dato de la ficha dice quién decide sobre él")

    await emp.fill("#mf-telefono", "0987000111")
    await emp.click("#form-contacto button[type=submit]")
    await emp.wait_for_selector("#aviso:not(.hidden)", timeout=15000)
    await emp.reload()
    await emp.wait_for_selector("#mf-expediente > div", timeout=15000)
    if await emp.input_value("#mf-telefono") != "0987000111":
        raise Falla("El teléfono no quedó guardado. Es un campo «libre»: "
                    "debe aplicarse sin que nadie lo apruebe.")
    paso.ok("el teléfono se corrige solo, sin aprobación de nadie")

    # El cargo propuesto lleva una marca distinta en cada corrida: pedir el
    # valor que ya está registrado se rechaza —con razón—, y con un texto fijo
    # la segunda corrida fallaba por eso y parecía un defecto del sistema.
    from app.db import obtener_uno
    original = await obtener_uno(
        "select cargo from public.users where cedula = %s", (EMPLEADA,))
    marca = datetime.now().strftime("%H%M%S")
    nuevo_cargo = f"Comprobacion automatica {marca}"

    await emp.wait_for_selector("#caja-confirmar:not(.hidden)", timeout=10000)
    await emp.check('input[name="mf-cargo-ok"][value="no"]')
    await emp.fill("#mf-cargo-nuevo", nuevo_cargo)
    await emp.click("#btn-confirmar-datos")
    await emp.wait_for_selector("#aviso:not(.hidden)", timeout=15000)
    dijo = await emp.inner_text("#aviso")
    if "revisará" not in dijo:
        raise Falla(f"Al señalar el cargo el sistema respondió «{dijo}».")
    paso.ok("señalar que el cargo está mal abre un pedido, no lo aplica")
    if capturas:
        await emp.screenshot(path=str(capturas / "mi-ficha.png"), full_page=True)

    rh = await (await nav.new_context(viewport={"width": 1280, "height": 900})).new_page()
    await _entrar(rh, ADMIN)
    await rh.goto(f"{FRONTEND}/administracion.html#cambios-ficha")
    await rh.wait_for_selector("[data-cambio]", timeout=15000)

    # Se filtra antes de confirmar: la bandeja puede traer pedidos de otras
    # personas y «el primero» sería cualquiera.
    await rh.fill("#cf-buscar", nuevo_cargo)
    await rh.wait_for_selector("[data-cambio]", timeout=10000)
    cuantos = await rh.locator("[data-cambio]").count()
    if cuantos != 1:
        raise Falla(f"El buscador de la bandeja devolvió {cuantos} pedidos "
                    "para un texto que identifica a uno solo.")
    texto = await rh.inner_text("[data-cambio]")
    if re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", texto):
        raise Falla("La bandeja muestra identificadores en bruto. "
                    "Quien revisa necesita nombres para poder confirmar.")
    paso.ok("la bandeja de Talento Humano muestra nombres, no identificadores")

    await rh.click("[data-aprobar]")
    await rh.wait_for_selector("#aviso:not(.hidden)", timeout=15000)
    if capturas:
        await rh.screenshot(path=str(capturas / "cambios-ficha.png"), full_page=True)

    await emp.reload()
    await emp.wait_for_selector("#mf-expediente > div", timeout=15000)
    if nuevo_cargo not in await emp.inner_text("#ficha-resumen"):
        raise Falla("El cargo confirmado por Talento Humano no rigió.")
    paso.ok("confirmado por Talento Humano, el cargo nuevo rige")

    # Se devuelve el cargo original: la comprobación no debe dejar el personal
    # de prueba con un cargo inventado.
    await obtener_uno(
        "update public.users set cargo = %s where cedula = %s returning id",
        (original["cargo"], EMPLEADA))
    return paso


async def recorrido_garita(nav, capturas) -> Paso:
    """Salida, regreso y el exceso sobre la hora autorizada."""
    from app.db import obtener_uno

    paso = Paso("garita")

    # Un permiso por horas, aprobado, para hoy. Se crea aquí y no por la
    # pantalla: lo que se comprueba es la garita, no el formulario.
    # Se crea y se aprueba en dos pasos, no en uno: el disparador de alta fija
    # el estado según la ruta de autorización que corresponda, así que pedir
    # «aprobado» en el INSERT no sirve de nada. Es al pasar a aprobado cuando
    # se emite el código QR, que es lo que la garita va a leer.
    solicitud = await obtener_uno(
        """insert into public.requests
             (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
              hora_inicio, hora_fin, horas_solicitadas, descripcion,
              justificacion, estado)
           select u.id, 'permiso',
                  -- El tipo se elige por lo que la comprobación necesita y no
                  -- por su nombre: uno que admita horas, no descuente
                  -- vacaciones y no exija adjuntar un respaldo, que aquí no
                  -- hay ninguno que adjuntar.
                  (select id from public.permission_types
                    where activo and admite_horas
                      and not coalesce(descuenta_vacaciones, false)
                      and not coalesce(requiere_adjunto, false)
                      and not coalesce(requiere_justificacion, false)
                    order by id limit 1),
                  current_date, current_date, '08:00', '10:00', 2,
                  'Comprobacion automatica de la garita',
                  'Permiso creado por scripts/pruebas_navegador.py para '
                  'comprobar el registro de salida y regreso en la garita',
                  'pendiente_jefe'
             from public.users u where u.cedula = %s
           returning id, folio""",
        (EMPLEADA,),
    )
    # Y por los dos peldaños, no de un salto: el sistema no acepta que una
    # solicitud pase de «pendiente del jefe» a «aprobada» sin haber estado en
    # manos de Talento Humano, y tiene razón en no aceptarlo.
    for etapa in ("pendiente_rrhh", "aprobado"):
        solicitud = await obtener_uno(
            """update public.requests set estado = %s
                where id = %s returning id, folio, qr_hash""",
            (etapa, solicitud["id"]),
        )
    paso.ok(f"permiso de prueba Nº {solicitud['folio']} (08:00 a 10:00 de hoy)")

    pg = await (await nav.new_context(viewport={"width": 1280, "height": 900})).new_page()
    await _entrar(pg, GUARDIA)
    await pg.goto(f"{FRONTEND}/garita.html")
    await pg.wait_for_selector("#entrada-qr", timeout=15000)

    codigo = str(solicitud["qr_hash"])

    async def escanear() -> tuple[str, str]:
        await pg.fill("#entrada-qr", codigo)
        await pg.press("#entrada-qr", "Enter")
        await pg.wait_for_selector("#veredicto[open]", timeout=15000)
        titulo = await pg.inner_text("#veredicto-titulo")
        motivo = await pg.inner_text("#veredicto-motivo")
        # El veredicto ocupa toda la pantalla: sin cerrarlo, el siguiente
        # clic cae encima de él y no llega al formulario.
        await pg.click("#veredicto-cerrar")
        await pg.wait_for_timeout(400)
        return titulo.strip(), motivo.strip()

    titulo, _ = await escanear()
    if "SALIDA" not in titulo.upper():
        raise Falla(f"La primera lectura dijo «{titulo}» y debía autorizar la salida.")
    paso.ok(f"primera lectura: {titulo}")

    titulo, motivo = await escanear()
    if "REGRESO" not in titulo.upper():
        raise Falla(f"La segunda lectura dijo «{titulo}» y debía registrar el regreso.")
    paso.ok(f"segunda lectura: {titulo} — {motivo}")
    if capturas:
        await pg.screenshot(path=str(capturas / "garita-regreso.png"))

    titulo, _ = await escanear()
    if "COMPLETO" not in titulo.upper():
        raise Falla(f"La tercera lectura dijo «{titulo}»: no debía inventar otro movimiento.")
    paso.ok(f"tercera lectura: {titulo}")

    fila = await obtener_uno(
        """select retorno_en is not null as volvio, retorno_exceso_minutos as exceso
             from public.requests where id = %s""",
        (solicitud["id"],),
    )
    if not fila["volvio"]:
        raise Falla("No quedó registrada la hora de reincorporación en la base.")
    paso.ok(f"en la base queda la hora real de regreso (exceso: {fila['exceso']} min)")
    return paso


async def recorrido_panel_garita(nav, capturas) -> Paso:
    """El panel del día: quién está fuera y a quién ya se le pasó la hora.

    La garita tenía la lista de quién tiene permiso hoy. Lo que no tenía era
    la respuesta a la pregunta que el guardia se hace a media tarde: de esos,
    ¿quién salió y todavía no vuelve? Se comprueba además que las dos listas
    de la pantalla digan lo mismo: durante un rato una miraba `qr_usado_en` y
    la otra los registros de acceso, y la misma pantalla se contradecía sobre
    si alguien había salido.

    Usa al jefe y a Talento Humano, no a la empleada: el recorrido `garita`
    ya le crea a ella un permiso de hoy, y el sistema —con razón— no admite
    dos ausencias solapadas de la misma persona.
    """
    from app.db import obtener_todos, obtener_uno

    paso = Paso("panel-garita")

    # El tipo de permiso se elige por lo que la comprobación necesita y no
    # por su nombre: uno que admita horas y no exija respaldo ni justificación,
    # que aquí no hay ninguna que dar. Su tope de horas manda sobre el largo
    # de las franjas: el sistema rechaza un permiso que lo pase, y tiene razón.
    tipo = await obtener_uno(
        """select id, coalesce(max_horas, 4)::numeric as tope
             from public.permission_types
            where activo and admite_horas
              and not coalesce(descuenta_vacaciones, false)
              and not coalesce(requiere_adjunto, false)
              and not coalesce(requiere_justificacion, false)
            order by coalesce(max_horas, 4) desc, id limit 1""")

    async def permiso(cedula: str, desde: str, hasta: str) -> dict:
        fila = await obtener_uno(
            """insert into public.requests
                 (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                  hora_inicio, hora_fin, horas_solicitadas, descripcion,
                  justificacion, estado)
               select u.id, 'permiso', %s, current_date, current_date,
                      %s::time, %s::time,
                      round(extract(epoch from (%s::time - %s::time)) / 3600.0, 2),
                      'Comprobacion automatica del panel de garita',
                      'Permiso creado por scripts/pruebas_navegador.py para '
                      'comprobar el panel de movimientos del dia',
                      'pendiente_jefe'
                 from public.users u where u.cedula = %s
               returning id""",
            (tipo["id"], desde, hasta, hasta, desde, cedula))
        if fila is None:
            raise Falla(f"No se pudo crear el permiso de prueba de {cedula}.")
        for etapa in ("pendiente_rrhh", "aprobado"):
            fila = await obtener_uno(
                """update public.requests set estado = %s
                    where id = %s returning id, folio, qr_hash""",
                (etapa, fila["id"]))
        return fila

    # La franja vencida se calcula desde la hora actual y no con un valor
    # fijo, para que el atraso sea real a cualquier hora del día. De
    # madrugada no hay horas hacia atrás sin cambiar de día, así que se cae a
    # una franja mínima que a las 00:02 ya está vencida igual.
    h = await obtener_uno(
        """select case when current_time > time '04:00'
                       then to_char(now() - interval '40 minutes'
                                    - least(%s, 2) * interval '1 hour', 'HH24:MI')
                       else '00:01' end as desde,
                  case when current_time > time '04:00'
                       then to_char(now() - interval '40 minutes', 'HH24:MI')
                       else '00:02' end as hasta,
                  to_char(time '00:01' + least(%s, 4) * interval '1 hour',
                          'HH24:MI') as fin_vigente""",
        (tipo["tope"], tipo["tope"]))
    atrasada = await permiso(JEFE, h["desde"], h["hasta"])
    # Y alguien con permiso vigente que todavía no ha usado su código. Su
    # franja empieza a las 00:01 a propósito: así no depende de la hora a la
    # que se corra la prueba ni se pasa de medianoche por la noche.
    await permiso(RRHH, "00:01", h["fin_vigente"])
    paso.ok(f"permiso Nº {atrasada['folio']} vencido a las {h['hasta']} y otro sin usar")

    pg = await (await nav.new_context(viewport={"width": 1280, "height": 1000})).new_page()
    await _entrar(pg, GUARDIA)
    await pg.goto(f"{FRONTEND}/garita.html")
    await pg.wait_for_selector("#entrada-qr", timeout=15000)

    # La salida se registra por la pantalla y no por la base: lo que se
    # comprueba es que el panel refleje lo que hace el guardia.
    await pg.fill("#entrada-qr", str(atrasada["qr_hash"]))
    await pg.press("#entrada-qr", "Enter")
    await pg.wait_for_selector("#veredicto[open]", timeout=15000)
    await pg.click("#veredicto-cerrar")
    await pg.wait_for_timeout(900)

    if not await pg.locator("#panel-dia").is_visible():
        raise Falla("Con dos permisos aprobados hoy, el panel del día no se dibuja.")

    cuenta = " ".join((await pg.inner_text("#panel-cuenta")).split())
    if "atrasado" not in cuenta.lower():
        raise Falla(f"El recuento del panel dice «{cuenta}» y no menciona a nadie atrasado.")
    paso.ok(f"recuento: {cuenta[:80]}")

    primera = " ".join((await pg.locator("#panel-lista > article").first.inner_text()).split())
    if "Fuera y atrasado" not in primera:
        raise Falla("Quien está atrasado no encabeza el panel: "
                    f"el primero dice «{primera[:90]}».")
    if "min" not in primera:
        raise Falla("El atrasado aparece sin los minutos de atraso contados.")
    paso.ok(f"encabeza el panel: {primera[:95]}")

    fila = await obtener_uno(
        "select nombre from public.v_garita_hoy where request_id = %s", (atrasada["id"],))
    nombre = fila["nombre"]

    # Las dos listas de la misma pantalla, sobre la misma persona.
    tarjeta = pg.locator("#lista-hoy > div", has_text=nombre).first
    if not await tarjeta.count():
        raise Falla(f"«{nombre}» está en el panel pero no en la lista de autorizados.")
    if "fuera y atrasado" not in (await tarjeta.inner_text()).lower():
        raise Falla(f"La misma pantalla se contradice sobre «{nombre}»: el panel dice "
                    "«fuera y atrasado» y la lista de autorizados dice otra cosa.")
    paso.ok("las dos listas de la pantalla coinciden en quién salió")

    sin_salir = await obtener_todos(
        "select 1 from public.v_garita_hoy where situacion = 'sin_salir'")
    if not sin_salir:
        raise Falla("Quien tiene permiso y no ha usado su código debía constar «sin salir».")
    paso.ok(f"{len(sin_salir)} con permiso vigente y sin salir todavía")

    if capturas:
        await pg.screenshot(path=str(capturas / "garita-panel-del-dia.png"), full_page=True)
    return paso


async def recorrido_pantalla_principal(nav, capturas) -> Paso:
    """El administrador decide qué ve el colaborador al entrar.

    Lo que se comprueba no es que los interruptores se muevan, sino las dos
    cosas que pueden salir caras: que apagar un bloque lo quite de verdad del
    panel de otra persona, y que los bloques imprescindibles no se dejen
    apagar. Un administrador que apaga el saldo por error deja a 350 personas
    con una pantalla en blanco.
    """
    from app.db import ejecutar

    paso = Paso("pantalla-principal")

    # Se parte del panel como viene de fábrica para que el recorrido se pueda
    # repetir, y se deja igual al terminar.
    await ejecutar("update public.panel_bloques set visible = true, cuerpo = null")

    pg = await (await nav.new_context(viewport={"width": 1280, "height": 1000})).new_page()
    await _entrar(pg, ADMIN)
    await pg.goto(f"{FRONTEND}/pantalla-principal.html")
    await pg.wait_for_selector("[data-clave='logros']", timeout=15000)
    paso.ok(f"{await pg.locator('#lista [data-clave]').count()} bloques listados")

    # Lo imprescindible ni siquiera se ofrece: el interruptor está inactivo.
    saldo = pg.locator("[data-clave='saldo'] [data-visible]")
    if not await saldo.is_disabled():
        raise Falla("El interruptor del saldo se puede apagar y no debería.")
    paso.ok("el saldo no se deja apagar: el interruptor está inactivo")

    # Se pulsa la etiqueta y no la casilla: la casilla está oculta a la vista
    # —el interruptor que se ve es el recuadro de al lado— y solo se deja
    # pulsar a través de ella, igual que le pasa a una persona.
    await pg.locator("[data-clave='logros'] [data-interruptor]").click()
    await pg.wait_for_timeout(900)
    await pg.fill("#anuncio", "Prueba automatica: el viernes se cierra a la una.")
    await pg.click("#btn-anuncio")
    await pg.wait_for_timeout(900)
    paso.ok("logros apagado y aviso escrito")

    # Y ahora lo que importa: cómo lo ve otra persona.
    otra = await (await nav.new_context(viewport={"width": 1280, "height": 1000})).new_page()
    await _entrar(otra, EMPLEADA)
    await otra.wait_for_selector("#saldo-dias", timeout=15000)
    await otra.wait_for_timeout(1200)

    if await otra.locator("[data-bloque='logros']").is_visible():
        raise Falla("El administrador apagó «Mis logros» y el colaborador los sigue viendo.")
    paso.ok("el bloque apagado desapareció del panel del colaborador")

    if not await otra.locator("[data-bloque='saldo']").is_visible():
        raise Falla("El saldo dejó de verse: es lo único que no puede pasar.")
    paso.ok("el saldo sigue en su sitio")

    aviso = otra.locator("#anuncio")
    if not await aviso.is_visible():
        raise Falla("El aviso de la empresa no aparece en el panel.")
    if "viernes" not in (await aviso.inner_text()):
        raise Falla("El aviso aparece pero con otro texto.")
    paso.ok("el aviso de la empresa se ve arriba del panel")

    if capturas:
        await otra.screenshot(path=str(capturas / "panel-configurado.png"), full_page=True)

    # Se deja como estaba: el aviso de una prueba no puede quedarse puesto en
    # el panel de 350 personas.
    await ejecutar("update public.panel_bloques set visible = true, cuerpo = null")
    paso.ok("panel repuesto: todo visible y sin aviso")
    return paso


async def recorrido_expediente(nav, capturas) -> Paso:
    """Escribir un nombre en la barra y llegar a su expediente.

    Era lo que no se podía hacer: la ficha vivía en una pantalla, los
    períodos en otra, las solicitudes en una tercera y el historial de la
    hoja dentro de un diálogo del panel de cada quien. Para responder
    «¿cuándo tomó vacaciones Fulano y qué tiene pendiente?» había que abrir
    las tres y cruzarlas a mano.
    """
    paso = Paso("expediente")

    pg = await (await nav.new_context(viewport={"width": 1440, "height": 950})).new_page()
    await _entrar(pg, ADMIN)
    await pg.wait_for_timeout(1200)

    entrada = pg.locator("aside [data-buscar-persona]").first
    if not await entrada.count():
        raise Falla("La barra no tiene el buscador de personas.")

    # Sin tilde a propósito: con trescientas cincuenta personas, un buscador
    # que exige escribir el acento no lo usa nadie.
    await entrada.fill("suarez")
    await pg.wait_for_timeout(1400)
    resultados = pg.locator("aside [data-resultados] a")
    if not await resultados.count():
        raise Falla("Buscar «suarez» sin tilde no encontró a «Suárez».")
    paso.ok(f"«suarez» sin tilde encuentra {await resultados.count()} resultado(s)")

    await resultados.first.click()
    await pg.wait_for_selector("#contenido:not(.hidden)", timeout=15000)
    nombre = (await pg.inner_text("#nombre")).strip()
    paso.ok(f"abre el expediente de {nombre}")

    for identificador, que in (("saldo", "el saldo"), ("antiguedad", "la antigüedad"),
                               ("veces", "las vacaciones tomadas"),
                               ("en-tramite", "lo que está en trámite")):
        valor = (await pg.inner_text(f"#{identificador}")).strip()
        if not valor or valor == "—":
            raise Falla(f"El expediente no muestra {que}.")
    paso.ok("saldo, antigüedad, vacaciones tomadas y trámites, en una pantalla")

    if not await pg.locator("#vacaciones, #solicitudes").count():
        raise Falla("Faltan el historial de vacaciones o las solicitudes.")
    paso.ok("historial de vacaciones y solicitudes, juntos")

    if capturas:
        await pg.screenshot(path=str(capturas / "expediente.png"), full_page=True)

    # Y quien no tiene por qué verlo, no lo ve.
    otra = await (await nav.new_context(viewport={"width": 1280, "height": 900})).new_page()
    await _entrar(otra, EMPLEADA)
    await otra.wait_for_timeout(1000)
    if await otra.locator("aside [data-buscar-persona]").count():
        raise Falla("Un colaborador ve el buscador de personas y no debería.")
    await otra.goto(f"{FRONTEND}{pg.url[len(FRONTEND):]}")
    await otra.wait_for_timeout(2000)
    if await otra.locator("#contenido").is_visible():
        raise Falla("Un colaborador abrió el expediente de otra persona escribiendo la dirección.")
    paso.ok("un compañero no lo abre ni escribiendo la dirección")

    # Y se llega también por el nombre, desde donde ya se está mirando gente.
    for pantalla, selector in (("colaboradores.html", "#tabla a[href^='persona.html']"),
                               ("administracion.html#usuarios", "#tabla-usuarios a[href^='persona.html']")):
        await pg.goto(f"{FRONTEND}/{pantalla}")
        await pg.wait_for_timeout(2500)
        if not await pg.locator(selector).count():
            raise Falla(f"Desde {pantalla} no se puede abrir el expediente de nadie: "
                        "el nombre tendría que llevar a él.")
    paso.ok("se llega por el nombre desde Colaboradores y desde Usuarios")
    return paso


async def recorrido_lineamientos(nav, capturas) -> Paso:
    """Talento Humano escribe lo que el colaborador lee antes de enviar.

    El recuadro «Antes de enviar, tenga presente» estaba dentro del HTML:
    para cambiar una coma hacía falta un programador, y son reglas que
    cambian por una circular.
    """
    from app.db import ejecutar, obtener_uno

    paso = Paso("lineamientos")
    TEXTO = "Comprobacion automatica: esta regla la escribio la prueba."

    pg = await (await nav.new_context(viewport={"width": 1280, "height": 950})).new_page()
    await _entrar(pg, ADMIN)
    await pg.goto(f"{FRONTEND}/administracion.html#lineamientos")
    await pg.wait_for_selector("#lista-lineamientos [data-lineamiento]", timeout=15000)
    cuantos = await pg.locator("#lista-lineamientos [data-lineamiento]").count()
    paso.ok(f"{cuantos} lineamiento(s) listados y editables")

    await pg.fill("#nuevo-lineamiento", TEXTO)
    await pg.select_option("#nuevo-lineamiento-ambito", "vacacion")
    await pg.click("#btn-nuevo-lineamiento")
    await pg.wait_for_timeout(1200)
    if await pg.locator("#lista-lineamientos [data-lineamiento]").count() != cuantos + 1:
        raise Falla("El lineamiento nuevo no aparece en la lista.")
    paso.ok("se agrega desde la pantalla, sin tocar el código")

    try:
        # Y ahora lo que importa: qué lee el colaborador.
        otra = await (await nav.new_context(viewport={"width": 1280, "height": 950})).new_page()
        await _entrar(otra, EMPLEADA)
        await otra.wait_for_timeout(1000)
        await otra.click("[data-nueva='vacacion']")
        await otra.wait_for_timeout(1200)

        aviso = otra.locator("#aviso-vacaciones")
        if not await aviso.is_visible():
            raise Falla("El recuadro de lineamientos no aparece al pedir vacaciones.")
        if await aviso.evaluate("e => e.open"):
            raise Falla("El recuadro sale abierto: son cinco renglones delante de "
                        "quien solo quiere pedir tres días.")
        paso.ok(f"plegado y con la cuenta: «{(await otra.inner_text('#aviso-titulo')).strip()}»")

        await otra.click("#aviso-titulo")
        await otra.wait_for_timeout(400)
        if TEXTO not in (await otra.inner_text("#aviso-lista")):
            raise Falla("Lo que escribió Talento Humano no llegó al formulario.")
        paso.ok("lo escrito por Talento Humano se lee en el formulario")
        if capturas:
            await otra.screenshot(path=str(capturas / "lineamientos.png"))
    finally:
        # No se deja puesta una regla de prueba en el formulario de 350 personas.
        await ejecutar("delete from public.lineamientos_solicitud where texto = %s", (TEXTO,))

    restante = await obtener_uno(
        "select count(*) as n from public.lineamientos_solicitud where texto = %s", (TEXTO,))
    if restante["n"]:
        raise Falla("La regla de prueba quedó puesta.")
    paso.ok("y la regla de prueba se retira al terminar")
    return paso


async def recorrido_depuracion(nav, capturas) -> Paso:
    """Lo que hay que revisar a mano tras la carga inicial, sin abrir DBeaver.

    Y el fallo que traía la pantalla de usuarios: la lista de «Jefe
    inmediato» salía del resultado de la búsqueda, así que buscar una cédula
    —que es justo lo que uno hace para editar a alguien— la dejaba vacía.
    """
    paso = Paso("depuracion")

    pg = await (await nav.new_context(viewport={"width": 1440, "height": 1000})).new_page()
    await _entrar(pg, ADMIN)

    # --- El desplegable de jefes, con el filtro puesto ---------------------
    await pg.goto(f"{FRONTEND}/administracion.html#usuarios")
    await pg.wait_for_selector("#tabla-usuarios tbody tr", timeout=15000)
    await pg.wait_for_timeout(1200)
    sin_filtro = await pg.locator("#u-jefe option").count()

    await pg.fill("#buscar-usuario", EMPLEADA)
    await pg.wait_for_timeout(1500)
    if await pg.locator("#tabla-usuarios tbody tr").count() != 1:
        raise Falla("La búsqueda por cédula no dejó una sola fila.")
    await pg.locator("#tabla-usuarios [data-editar]").first.click()
    await pg.wait_for_selector("#modal-usuario[open]", timeout=8000)

    con_filtro = await pg.locator("#u-jefe option").count()
    if con_filtro < sin_filtro:
        raise Falla(f"Con la búsqueda puesta el desplegable de jefes baja de "
                    f"{sin_filtro} a {con_filtro} opciones: vuelve a salir del "
                    "resultado del filtro en vez del catálogo.")
    if con_filtro < 2:
        raise Falla("El desplegable de «Jefe inmediato» no ofrece a nadie.")
    paso.ok(f"el desplegable de jefes mantiene {con_filtro} opciones al buscar por cédula")
    await pg.keyboard.press("Escape")

    # --- La pantalla de depuración ----------------------------------------
    await pg.goto(f"{FRONTEND}/administracion.html#depuracion")
    await pg.wait_for_selector("#dep-resumen article", timeout=15000)
    await pg.wait_for_timeout(1500)

    tarjetas = await pg.locator("#dep-resumen article").count()
    if tarjetas != 5:
        raise Falla(f"La depuración muestra {tarjetas} grupos y deberían ser cinco.")
    paso.ok(f"cinco grupos: {' '.join((await pg.inner_text('#dep-resumen')).split())[:90]}")

    secciones = await pg.locator("#dep-detalle section").count()
    if secciones != 5:
        raise Falla(f"Se dibujaron {secciones} secciones de detalle.")

    # Cada cuenta de prueba tiene que decir qué hacer con ella. Es la
    # distinción que importa: a una persona real se le corrige el correo; una
    # cuenta que no es de nadie se desactiva. Confundirlas significa desactivar
    # a alguien que trabaja aquí.
    texto = await pg.inner_text("#dep-detalle")
    consejos = ("corríjale el correo", "se puede desactivar", "reasígnela")
    if not any(c in texto for c in consejos):
        raise Falla("Las cuentas de prueba se listan sin decir qué hacer con cada una.")
    paso.ok("cada cuenta dice si es una persona real o una cuenta que se puede quitar")

    # Y desde cada fila se llega al expediente, que es donde se corrige.
    if not await pg.locator("#dep-detalle a[href^='persona.html']").count():
        raise Falla("Ninguna fila lleva al expediente de la persona.")
    paso.ok("y cada fila lleva al expediente, que es donde se corrige")

    if capturas:
        await pg.screenshot(path=str(capturas / "depuracion.png"), full_page=True)

    # Y no la ve quien no debe.
    otra = await (await nav.new_context(viewport={"width": 1280, "height": 900})).new_page()
    await _entrar(otra, EMPLEADA)
    await otra.goto(f"{FRONTEND}/administracion.html#depuracion")
    await otra.wait_for_timeout(2000)
    if "administracion" in otra.url:
        raise Falla("Un colaborador entró a la pantalla de administración.")
    paso.ok("un colaborador no llega a esta pantalla")
    return paso


async def recorrido_jefaturas(nav, capturas) -> Paso:
    """Nombrar y quitar jefaturas sin dejar gente sin a quién pedirle permiso.

    La baja es lo que se probaba mal a ojo: en la pantalla no pasa nada raro
    —el rol cambia, no sale ningún error— y lo que queda roto es invisible.
    Sus colaboradores siguen apuntándole, piden vacaciones, y el pedido va
    dirigido a alguien que ya no puede resolverlo.
    """
    from app.db import ejecutar, obtener_uno

    paso = Paso("jefaturas")

    pg = await (await nav.new_context(viewport={"width": 1440, "height": 1000})).new_page()
    await _entrar(pg, ADMIN)
    await pg.goto(f"{FRONTEND}/administracion.html#jefaturas")
    await pg.wait_for_selector("#jef-tabla tr", timeout=15000)
    await pg.wait_for_timeout(800)

    cuantas = " ".join((await pg.inner_text("#jef-cuantas")).split())
    if "jefatura" not in cuantas:
        raise Falla(f"La cabecera no dice cuántas jefaturas hay: «{cuantas}».")
    paso.ok(f"la lista se abre con el resumen: {cuantas}")

    # La jefatura de la semilla, con gente a cargo.
    jefe = await obtener_uno(
        """select u.id, u.nombre,
                  (select count(*) from public.users s where s.jefe_id = u.id and s.activo) as a_cargo
             from public.users u where u.cedula = %s""", (JEFE,))
    if not jefe["a_cargo"]:
        raise Falla("La jefatura de prueba no tiene a nadie a cargo; no hay nada que trasladar.")

    fila = pg.locator(f"[data-quitar-jefatura='{jefe['id']}']")
    if not await fila.count():
        raise Falla(f"{jefe['nombre']} no figura entre las jefaturas.")
    await fila.click()
    await pg.wait_for_selector("#modal-jefatura[open]", timeout=8000)

    aviso = " ".join((await pg.inner_text("#jef-aviso")).split())
    if str(jefe["a_cargo"]) not in aviso:
        raise Falla(f"El diálogo no dice cuánta gente se traslada: «{aviso}».")
    paso.ok(f"al quitarla, el diálogo advierte primero: {aviso[:95]}")

    if await pg.locator("#jef-destino-caja").is_hidden():
        raise Falla("Con gente a cargo, el diálogo no pregunta a qué jefatura pasa.")
    if await pg.locator("#jef-destino option").count() < 1:
        raise Falla("No ofrece ninguna jefatura de destino.")
    paso.ok("y obliga a elegir a quién pasan antes de dejar hacerlo")

    destino = await pg.locator("#jef-destino option").first.get_attribute("value")
    await pg.select_option("#jef-destino", destino)
    await pg.click("#form-jefatura button[type=submit]")
    await pg.wait_for_selector("#aviso:not(.hidden)", timeout=10000)
    mensaje = " ".join((await pg.inner_text("#aviso")).split())
    paso.ok(f"se traslada en un solo movimiento: {mensaje[:95]}")

    colgando = await obtener_uno(
        "select count(*) as n from public.users where jefe_id = %s and activo", (jefe["id"],))
    if colgando["n"]:
        raise Falla(f"Quedaron {colgando['n']} persona(s) apuntando a quien ya no manda.")
    paso.ok("nadie queda apuntando a quien ya no puede aprobarle nada")

    # Y se vuelve a nombrar, que es la otra mitad de lo pedido.
    await pg.fill("#jef-buscar", jefe["nombre"][:14])
    await pg.wait_for_timeout(1200)
    if not await pg.locator("#jef-candidatos [data-candidato]").count():
        raise Falla("La búsqueda para nombrar una jefatura no devuelve a nadie.")
    await pg.locator("#jef-candidatos [data-candidato]").first.click()
    await pg.click("#jef-nombrar")
    await pg.wait_for_timeout(1500)
    rol = await obtener_uno("select rol::text as rol from public.users where id = %s", (jefe["id"],))
    if rol["rol"] != "jefe":
        raise Falla(f"Tras nombrarla, su rol quedó en «{rol['rol']}».")
    paso.ok("y se vuelve a nombrar jefatura desde la misma pantalla")

    if capturas:
        await pg.screenshot(path=str(capturas / "jefaturas.png"), full_page=True)

    # Se deja como estaba: la semilla cuenta con esa jefatura y su gente.
    await ejecutar("update public.users set jefe_id = %s where jefe_id = %s",
                   (jefe["id"], destino))
    paso.ok("y la semilla queda como estaba para el resto de los recorridos")
    return paso


async def recorrido_talento_humano(nav, capturas) -> Paso:
    """El departamento: quiénes lo integran y a qué buzón le llega el trabajo.

    Y de paso, que la firma dibujada ya no aparezca por ninguna parte. Se
    comprueba en la pantalla del colaborador, que es donde estorbaba: la
    casilla «aún no registra su firma» lo frenaba en el último paso, justo
    cuando ya había escrito todo.
    """
    from app.db import ejecutar, obtener_uno

    paso = Paso("talento-humano")

    pg = await (await nav.new_context(viewport={"width": 1440, "height": 1000})).new_page()
    await _entrar(pg, ADMIN)
    await pg.goto(f"{FRONTEND}/administracion.html#talento-humano")
    await pg.wait_for_selector("#th-tabla tr", timeout=15000)
    await pg.wait_for_timeout(800)

    cuantos = " ".join((await pg.inner_text("#th-cuantos")).split())
    if "persona" not in cuantos:
        raise Falla(f"No dice quiénes integran el departamento: «{cuantos}».")
    paso.ok(f"el departamento se lista con su reparto: {cuantos}")

    # El buzón del área, que es lo que sobrevive a que alguien se vaya.
    await pg.fill("#correo-rrhh-sierra", "talentohumano.uio@itsanet.com.ec")
    await pg.fill("#correo-rrhh-costa", "talentohumano.gye@itsanet.com.ec")
    await pg.click("#form-correos-rrhh button[type=submit]")
    await pg.wait_for_selector("#aviso:not(.hidden)", timeout=10000)
    guardado = await obtener_uno(
        "select public.rrhh_correo_de_region('costa') as buzon")
    if guardado["buzon"] != "talentohumano.gye@itsanet.com.ec":
        raise Falla(f"El buzón de la Costa quedó en «{guardado['buzon']}».")
    paso.ok("el buzón del departamento se guarda por región")

    # Una dirección mal escrita es tan silenciosa como no tener ninguna.
    await pg.fill("#correo-rrhh-sierra", "talentohumano.itsanet.com.ec")
    await pg.click("#form-correos-rrhh button[type=submit]")
    await pg.wait_for_timeout(1200)
    sigue = await obtener_uno("select public.rrhh_correo_de_region('sierra') as buzon")
    if sigue["buzon"] != "talentohumano.uio@itsanet.com.ec":
        raise Falla("Aceptó una dirección sin arroba y pisó la que estaba bien.")
    paso.ok("y una dirección con errata no reemplaza a la que funcionaba")

    if capturas:
        await pg.screenshot(path=str(capturas / "talento-humano.png"), full_page=True)

    # Se deja como estaba: el resto de los recorridos no espera buzón.
    await ejecutar("update public.app_config set valor = '' where clave like 'rrhh_correo%%'")

    # --- Y la firma, que ya no existe ------------------------------------
    emp = await (await nav.new_context(viewport={"width": 1280, "height": 1000})).new_page()
    await _entrar(emp, EMPLEADA)
    await emp.wait_for_selector("#saldo-dias", timeout=15000)
    await emp.wait_for_timeout(1200)

    for selector in ("#tarjeta-firma", "#modal-firma", "#campo-firma", "#btn-firma"):
        if await emp.locator(selector).count():
            raise Falla(f"La firma sigue en la pantalla del colaborador: {selector}")
    paso.ok("en el panel del colaborador no queda nada de la firma")

    pantalla = await emp.inner_text("body")
    for frase in ("firma electrónica", "Registrar firma", "registra su firma"):
        if frase.lower() in pantalla.lower():
            raise Falla(f"La pantalla todavía dice «{frase}».")
    paso.ok("ni el texto que frenaba al operario en el último paso")

    # Y el circuito del servidor, cerrado: no basta con esconder el botón.
    respuesta = await emp.evaluate(
        """async () => {
             const r = await fetch(window.RRHH_CONFIG.API || ('http://' + location.hostname + ':8000')
                                   , { method: 'GET' }).catch(() => null);
             const f = await fetch((window.RRHH_CONFIG.API || ('http://' + location.hostname + ':8000'))
                                   + '/firmas/mia').catch(() => null);
             return f ? f.status : 0;
           }""")
    if respuesta not in (401, 403, 404):
        raise Falla(f"La ruta /firmas/mia sigue respondiendo {respuesta}.")
    paso.ok(f"y la ruta del servidor tampoco existe (responde {respuesta})")
    return paso


async def recorrido_menu(nav, capturas) -> Paso:
    """La navegación, que ahora es vertical y tiene dos formas."""
    paso = Paso("menu")

    pg = await (await nav.new_context(viewport={"width": 1440, "height": 950})).new_page()
    await _entrar(pg, ADMIN)
    await pg.wait_for_timeout(1200)

    lateral = pg.locator("aside").first
    if not await lateral.is_visible():
        raise Falla("No se dibuja la barra lateral en pantalla de escritorio.")
    enlaces = await lateral.locator("nav a").count()
    if enlaces < 10:
        raise Falla(f"La barra lateral solo tiene {enlaces} enlaces. En vertical los "
                    "módulos van abiertos: si hay menos, algo no se está dibujando.")
    paso.ok(f"barra lateral con {enlaces} opciones a la vista, sin desplegables")

    # Que no se corte ningún texto: es lo que obligó a acortar las etiquetas.
    cortados = await pg.evaluate("""() => {
        const a = document.querySelector('aside');
        return [...a.querySelectorAll('nav a span')]
          .filter(s => s.scrollWidth > s.clientWidth + 1)
          .map(s => s.textContent.trim());
    }""")
    if cortados:
        raise Falla(f"Estas opciones no caben y salen cortadas: {cortados}")
    paso.ok("y ninguna etiqueta se corta")

    # Lo operativo tiene que verse sin desplazar la barra: es lo que un
    # guardia usa a diario, y al final de la lista quedaba fuera de pantalla.
    for texto in ("Garita", "Personal temporal"):
        enlace = lateral.locator(f'nav a:has-text("{texto}")').first
        if not await enlace.is_visible():
            raise Falla(f"«{texto}» no se ve sin desplazar el menú.")
        caja = await enlace.bounding_box()
        if caja["y"] + caja["height"] > 950:
            raise Falla(f"«{texto}» queda por debajo del corte de la pantalla.")
    paso.ok("Garita y Personal temporal se ven sin desplazar")

    # El riel gris permanente a la derecha del menú, fuera; la rueda, dentro.
    barra = await pg.evaluate("""() => {
        const n = document.querySelector('aside nav');
        return { riel: n.offsetWidth - n.clientWidth,
                 desplazable: n.scrollHeight > n.clientHeight + 1,
                 desborde: getComputedStyle(n).overflowY };
    }""")
    if barra["riel"] > 0:
        raise Falla(f"El menú sigue enseñando la barra de desplazamiento ({barra['riel']} px).")
    if barra["desborde"] not in ("auto", "scroll"):
        raise Falla("El menú no se puede desplazar con la rueda.")
    paso.ok("sin riel de desplazamiento, y la rueda sigue sirviendo")

    # Los grupos se pliegan, y el que se plegó sigue plegado al volver.
    grupos = pg.locator("aside [data-plegar]")
    if await grupos.count() < 3:
        raise Falla("El menú no tiene grupos plegables.")
    # `.first` en todo: hay dos copias del menú —la fija y la del cajón— y en
    # esta anchura solo una está a la vista.
    grupo = pg.locator('aside [data-plegar="informes"]').first
    opciones = pg.locator('aside [data-grupo="informes"] [data-opciones]').first
    antes = await opciones.locator("a").count()
    await grupo.click()
    await pg.wait_for_timeout(300)
    if await opciones.is_visible():
        raise Falla("Un grupo plegado sigue mostrando sus opciones.")
    paso.ok(f"los grupos se pliegan ({antes} opciones de Informes recogidas)")

    await pg.goto(f"{FRONTEND}/dashboard.html")
    await pg.wait_for_timeout(1500)
    if await pg.locator('aside [data-grupo="informes"] [data-opciones]').first.is_visible():
        raise Falla("El grupo plegado volvió a abrirse solo al cambiar de pantalla.")
    paso.ok("y siguen plegados al cambiar de pantalla")
    await pg.locator('aside [data-plegar="informes"]').first.click()
    await pg.wait_for_timeout(300)

    await pg.click("#nav-campana")
    await pg.wait_for_selector("#modal-notificaciones[open]", timeout=10000)
    await pg.keyboard.press("Escape")
    paso.ok("la campana de la barra abre las notificaciones")

    for pantalla in ("equipo.html", "informes.html", "colaboradores.html",
                     "administracion.html", "mensajes.html", "mi-ficha.html", "garita.html"):
        await pg.goto(f"{FRONTEND}/{pantalla}")
        try:
            await pg.wait_for_selector("aside", timeout=12000)
            if not await pg.locator("aside").first.is_visible():
                raise Exception("invisible")
        except Exception as exc:
            raise Falla(f"La barra lateral no aparece en {pantalla}.") from exc
    paso.ok("y está en las siete pantallas")
    if capturas:
        await pg.goto(f"{FRONTEND}/dashboard.html")
        await pg.wait_for_timeout(1500)
        await pg.screenshot(path=str(capturas / "menu-escritorio.png"))

    # En teléfono la barra se guarda en un cajón.
    pm = await (await nav.new_context(viewport={"width": 390, "height": 844},
                                      is_mobile=True, has_touch=True)).new_page()
    await _entrar(pm, EMPLEADA)
    await pm.wait_for_timeout(1000)
    if await pm.locator("aside").first.is_visible():
        raise Falla("En teléfono la barra lateral no debe ocupar la pantalla.")
    await pm.click("#nav-abrir")
    await pm.wait_for_selector("#nav-cajon:not(.hidden)", timeout=8000)
    paso.ok("en teléfono se abre como cajón")
    if capturas:
        await pm.screenshot(path=str(capturas / "menu-movil.png"))

    # Se toca el fondo visible, a la derecha del cajón: el centro de la
    # pantalla en un teléfono cae dentro del propio cajón.
    await pm.mouse.click(350, 400)
    await pm.wait_for_timeout(500)
    if not await pm.locator("#nav-cajon").is_hidden():
        raise Falla("El cajón no se cierra al tocar fuera.")
    paso.ok("y se cierra al tocar fuera")
    return paso


async def recorrido_temporal(nav, capturas) -> Paso:
    """Personal temporal: entra, sale, y la semana cuadra."""
    from app.db import ejecutar, obtener_uno

    paso = Paso("temporal")
    CEDULA_OP = "1300000054"

    # Se parte de cero: el guion tiene que poder repetirse.
    await ejecutar("delete from public.personal_temporal where cedula = %s", (CEDULA_OP,))

    pg = await (await nav.new_context(viewport={"width": 1280, "height": 950})).new_page()
    await _entrar(pg, ADMIN)
    await pg.goto(f"{FRONTEND}/temporal.html")
    await pg.wait_for_selector("#lista-temporal", timeout=15000)

    await pg.click("#btn-nuevo-temporal")
    await pg.wait_for_selector("#modal-temporal[open]", timeout=8000)
    await pg.fill("#t-cedula", CEDULA_OP)
    await pg.fill("#t-nombre", "Operario De Comprobacion")
    await pg.fill("#t-labor", "Estibador")
    await pg.fill("#t-proveedor", "Servicios de prueba")
    await pg.click("#form-temporal button[type=submit]")
    await pg.wait_for_selector("#aviso:not(.hidden)", timeout=10000)
    paso.ok(f"alta del operario: {(await pg.inner_text('#aviso')).strip()}")

    async def boton():
        await pg.fill("#buscar-temporal", "Comprobacion")
        await pg.wait_for_timeout(400)
        return pg.locator("[data-mover]").first

    b = await boton()
    if (await b.inner_text()).strip() != "Entró":
        raise Falla(f"El botón dice «{await b.inner_text()}» y debería ofrecer registrar la entrada.")
    await b.click()
    await pg.wait_for_selector("#aviso:not(.hidden)", timeout=10000)
    paso.ok("entrada registrada; el botón pasa a ofrecer la salida")

    b = await boton()
    if (await b.inner_text()).strip() != "Salió":
        raise Falla(f"Tras entrar el botón dice «{await b.inner_text()}».")
    await pg.wait_for_timeout(600)
    await b.click()
    # Se espera a que el aviso CAMBIE, no a que exista: el de la entrada
    # sigue en pantalla cinco segundos y se leería ese.
    await pg.wait_for_function(
        "() => (document.getElementById('aviso').textContent || '').includes('salió')",
        timeout=10000)
    paso.ok(f"salida registrada: {(await pg.inner_text('#aviso')).strip()}")

    b = await boton()
    if not await b.is_disabled():
        raise Falla("Con la jornada cumplida el botón no debe dejar registrar otra: "
                    "dos jornadas del mismo día se pagan dos veces.")
    paso.ok("y con la jornada cumplida el botón queda inactivo")

    # Lo trabajado en la semana: horas y jornadas, nunca dinero.
    horas = (await pg.inner_text("#semana-horas")).strip()
    jornadas = (await pg.inner_text("#semana-jornadas")).strip()
    if horas in ("—", "") or jornadas in ("—", ""):
        raise Falla(f"La semana no suma: horas «{horas}», jornadas «{jornadas}».")
    paso.ok(f"la semana suma {horas} en {jornadas} jornada(s)")

    # Y no vuelve a hablar de pagos: cuánto se le paga a un operario sale del
    # contrato del proveedor, y esa cuenta la hace Finanzas.
    pantalla = await pg.inner_text("main")
    for palabra in ("$", "Total a pagar", "valor por hora", "Lo que se debe pagar"):
        if palabra in pantalla:
            raise Falla(f"La pantalla de personal temporal todavía dice «{palabra}».")
    paso.ok("sin importes en pantalla: el pago lo calcula Finanzas")
    if capturas:
        await pg.screenshot(path=str(capturas / "personal-temporal.png"), full_page=True)

    # Una jornada de ayer sin cerrar tiene que saltar a la vista.
    persona = await obtener_uno(
        "select id from public.personal_temporal where cedula = %s", (CEDULA_OP,))
    # Hora fija de entrada, no «hace un día»: si el guion se corre por la
    # tarde, «hace un día» cae después de la salida que se registra abajo y
    # la base la rechaza con razón. La jornada de ayer empieza a las ocho.
    await ejecutar(
        """insert into public.jornadas_temporales (temporal_id, fecha, entrada_en)
           values (%s, current_date - 1, (current_date - 1) + time '08:00')""",
        (persona["id"],))
    await pg.reload()
    await pg.wait_for_selector("#caja-sin-cerrar:not(.hidden)", timeout=15000)
    paso.ok("una jornada de ayer sin salida aparece señalada en rojo")

    aviso = await pg.inner_text("#semana-aviso")
    if "incompleta" not in aviso:
        raise Falla("Las horas de la semana no avisan de que están incompletas.")
    paso.ok("y el total de la semana avisa de que está incompleto")

    # Talento Humano la cierra a mano, con motivo.
    await pg.click("[data-cerrar-jornada]")
    await pg.wait_for_selector("#modal-cerrar[open]", timeout=8000)
    ayer = date.today() - timedelta(days=1)
    await pg.fill("#c-salida", f"{ayer.isoformat()}T17:00")
    await pg.fill("#c-motivo", "Se retiró sin timbrar; lo confirma el supervisor de bodega")
    await pg.click("#form-cerrar button[type=submit]")
    await pg.wait_for_selector("#aviso:not(.hidden)", timeout=10000)
    await pg.wait_for_timeout(900)
    if not await pg.locator("#caja-sin-cerrar").is_hidden():
        raise Falla("Tras cerrarla, la jornada sigue figurando como pendiente.")
    paso.ok("Talento Humano la cierra con motivo y deja de estar pendiente")

    guardada = await obtener_uno(
        """select observacion from public.jornadas_temporales
            where temporal_id = %s and fecha = current_date - 1""", (persona["id"],))
    if "Cerrada a mano" not in (guardada["observacion"] or ""):
        raise Falla("El cierre manual no quedó anotado en la jornada.")
    paso.ok("y queda constancia de que la cerró una persona, no la garita")

    # El informe que se presenta a Finanzas: filtros, total en vivo y los
    # tres formatos. Bajar un archivo para descubrir que venía vacío es la
    # forma más rápida de perderle la confianza a un botón de descarga.
    await pg.click("#btn-informe")
    await pg.wait_for_selector("#modal-informe[open]", timeout=10000)
    await pg.wait_for_timeout(1200)

    resumen = " ".join((await pg.inner_text("#i-resumen")).split())
    if "operario" not in resumen:
        raise Falla(f"El informe no calcula el total antes de bajarlo: «{resumen}».")
    paso.ok(f"el informe se calcula antes de bajarlo: {resumen[:70]}")

    if not await pg.locator("#i-personas [data-operario]").count():
        raise Falla("No se puede elegir a qué operarios sale el informe.")
    # Una sola persona: es la pregunta que llega cuando alguien reclama.
    await pg.locator("#i-personas [data-operario]").first.check()
    await pg.wait_for_timeout(1200)
    paso.ok("se puede pedir el historial de una persona suelta")

    descargados = []
    for formato in ("csv", "xlsx", "pdf"):
        async with pg.expect_download(timeout=20000) as espera:
            await pg.click(f"[data-bajar='{formato}']")
        archivo = await espera.value
        descargados.append(archivo.suggested_filename)
    paso.ok(f"se baja en los tres formatos: {', '.join(descargados)}")
    if capturas:
        await pg.screenshot(path=str(capturas / "temporal-informe.png"))
    await pg.click("#modal-informe [data-cerrar]")

    await ejecutar("delete from public.personal_temporal where cedula = %s", (CEDULA_OP,))
    return paso


RECORRIDOS = {
    "acceso": (recorrido_acceso, "Entrar con cédula y código; el saldo sin decimales"),
    "chat": (recorrido_chat, "Consulta a Talento Humano, su bandeja y la respuesta"),
    "ficha": (recorrido_ficha, "Ficha personal, quién decide cada dato, confirmación de RR.HH."),
    "garita": (recorrido_garita, "Salida, regreso y exceso sobre la hora autorizada"),
    "panel-garita": (recorrido_panel_garita,
                     "Panel del día: quién está fuera y a quién se le pasó la hora"),
    "pantalla-principal": (recorrido_pantalla_principal,
                          "El administrador decide qué bloques ve el colaborador"),
    "expediente": (recorrido_expediente,
                   "Buscar a una persona por su nombre y abrir su expediente"),
    "lineamientos": (recorrido_lineamientos,
                     "Talento Humano escribe lo que se lee antes de enviar"),
    "depuracion": (recorrido_depuracion,
                   "Depuración de la carga y el desplegable de jefes"),
    "jefaturas": (recorrido_jefaturas,
                  "Nombrar y quitar jefaturas trasladando a la gente"),
    "talento-humano": (recorrido_talento_humano,
                       "El departamento, su buzón, y la firma dibujada retirada"),
    "menu": (recorrido_menu, "La navegación vertical: barra en escritorio, cajón en teléfono"),
    "temporal": (recorrido_temporal, "Personal temporal: jornada, cierre manual y semana"),
}


# ----------------------------------------------------------------- ejecución

async def principal(cuales: list[str], capturas: Path | None) -> int:
    from app.config import get_settings
    from app.db import cerrar_pool

    if get_settings().es_produccion:
        print("Esto no se ejecuta en producción: crea datos y los borra.")
        return 2

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("Falta Playwright. Instálelo con:\n"
              "    pip install playwright\n"
              "    python -m playwright install chromium")
        return 2

    # Estado repuesto antes de empezar: si no, la segunda corrida choca con lo
    # que dejó la primera y el fallo parece del sistema.
    print("Reponiendo el estado del personal de prueba…")
    subprocess.run([sys.executable, str(RAIZ / "scripts" / "limpiar_pruebas.py"),
                    "--aplicar"], capture_output=True, text=True)

    ejecutable = "/opt/pw-browsers/chromium"
    if not Path(ejecutable).exists():
        ejecutable = None          # que Playwright busque el suyo

    resultados: list[tuple[str, str | None, int]] = []
    errores_consola: list[str] = []

    async with async_playwright() as p:
        nav = await p.chromium.launch(executable_path=ejecutable)
        for nombre in cuales:
            funcion, _ = RECORRIDOS[nombre]
            print(f"\n{nombre.upper()}")
            try:
                paso = await funcion(nav, capturas)
                resultados.append((nombre, None, len(paso.hechos)))
            except Falla as fallo:
                print(f"  ✗ {fallo}")
                resultados.append((nombre, str(fallo), 0))
            except Exception as exc:  # noqa: BLE001
                # Un tiempo agotado casi siempre significa «la pantalla no
                # llegó a ese estado», que es información útil tal cual.
                resumen = str(exc).split("\n")[0][:160]
                print(f"  ✗ {resumen}")
                resultados.append((nombre, resumen, 0))
        await nav.close()

    await cerrar_pool()

    print("\n" + "=" * 62)
    fallidos = [r for r in resultados if r[1]]
    for nombre, error, cuantos in resultados:
        if error:
            print(f"  ✗ {nombre:<10} {error[:48]}")
        else:
            print(f"  ✓ {nombre:<10} {cuantos} comprobación(es)")
    if capturas:
        print(f"\nPantallas en {capturas}")
    print("=" * 62)

    if errores_consola:
        print("\nErrores de JavaScript:")
        for e in dict.fromkeys(errores_consola):
            print("   ", e)

    return 1 if fallidos else 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--solo", action="append", choices=list(RECORRIDOS),
                   help="Correr solo este recorrido (se puede repetir).")
    p.add_argument("--lista", action="store_true", help="Qué recorridos hay.")
    p.add_argument("--capturas", type=Path, default=None,
                   help="Carpeta donde dejar las pantallas.")
    args = _cli.analizar(p)

    if args.lista:
        print("Recorridos disponibles:\n")
        for nombre, (_, que) in RECORRIDOS.items():
            print(f"  {nombre:<10} {que}")
        raise SystemExit(0)

    if args.capturas:
        args.capturas.mkdir(parents=True, exist_ok=True)

    raise SystemExit(asyncio.run(
        principal(args.solo or list(RECORRIDOS), args.capturas)))
