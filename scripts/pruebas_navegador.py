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
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

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
    paso = Paso("chat")
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

    await rh.click("#chat-burbuja")
    await rh.wait_for_url("**/mensajes.html", timeout=15000)
    await rh.wait_for_selector("[data-hilo]", timeout=15000)
    await rh.click("[data-hilo] >> nth=0")
    await rh.wait_for_selector(f"#hilo-mensajes >> text={consulta[:40]}", timeout=15000)

    respuesta = "Comprobacion automatica: si, le quedan y no caducan este ano."
    await rh.fill("#texto-respuesta", respuesta)
    await rh.click("#form-responder button[type=submit]")
    await rh.wait_for_selector(f"#hilo-mensajes >> text={respuesta[:40]}", timeout=15000)
    paso.ok("responde desde su bandeja")
    if capturas:
        await rh.screenshot(path=str(capturas / "bandeja-chat.png"), full_page=True)

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
    await pg.fill("#t-valor", "4.50")
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

    # La liquidación de la semana.
    horas = (await pg.inner_text("#semana-horas")).strip()
    total = (await pg.inner_text("#semana-total")).strip()
    if total == "—":
        raise Falla("El total de la semana sale «—» aunque el operario tiene "
                    "valor por hora. Cero es un total, no la ausencia de uno.")
    paso.ok(f"la semana suma {horas} y {total}")
    if capturas:
        await pg.screenshot(path=str(capturas / "personal-temporal.png"), full_page=True)

    # Una jornada de ayer sin cerrar tiene que saltar a la vista.
    persona = await obtener_uno(
        "select id from public.personal_temporal where cedula = %s", (CEDULA_OP,))
    await ejecutar(
        """insert into public.jornadas_temporales (temporal_id, fecha, entrada_en)
           values (%s, current_date - 1, now() - interval '1 day')""", (persona["id"],))
    await pg.reload()
    await pg.wait_for_selector("#caja-sin-cerrar:not(.hidden)", timeout=15000)
    paso.ok("una jornada de ayer sin salida aparece señalada en rojo")

    aviso = await pg.inner_text("#semana-aviso")
    if "incompleto" not in aviso:
        raise Falla("El total de la semana no avisa de que está incompleto.")
    paso.ok("y el total de la semana avisa de que está incompleto")

    # Talento Humano la cierra a mano, con motivo.
    await pg.click("[data-cerrar-jornada]")
    await pg.wait_for_selector("#modal-cerrar[open]", timeout=8000)
    await pg.fill("#c-salida", "2026-09-29T17:00")
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

    await ejecutar("delete from public.personal_temporal where cedula = %s", (CEDULA_OP,))
    return paso


RECORRIDOS = {
    "acceso": (recorrido_acceso, "Entrar con cédula y código; el saldo sin decimales"),
    "chat": (recorrido_chat, "Consulta a Talento Humano, su bandeja y la respuesta"),
    "ficha": (recorrido_ficha, "Ficha personal, quién decide cada dato, confirmación de RR.HH."),
    "garita": (recorrido_garita, "Salida, regreso y exceso sobre la hora autorizada"),
    "panel-garita": (recorrido_panel_garita,
                     "Panel del día: quién está fuera y a quién se le pasó la hora"),
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
    args = p.parse_args()

    if args.lista:
        print("Recorridos disponibles:\n")
        for nombre, (_, que) in RECORRIDOS.items():
            print(f"  {nombre:<10} {que}")
        raise SystemExit(0)

    if args.capturas:
        args.capturas.mkdir(parents=True, exist_ok=True)

    raise SystemExit(asyncio.run(
        principal(args.solo or list(RECORRIDOS), args.capturas)))
