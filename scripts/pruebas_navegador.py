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


RECORRIDOS = {
    "acceso": (recorrido_acceso, "Entrar con cédula y código; el saldo sin decimales"),
    "chat": (recorrido_chat, "Consulta a Talento Humano, su bandeja y la respuesta"),
    "ficha": (recorrido_ficha, "Ficha personal, quién decide cada dato, confirmación de RR.HH."),
    "garita": (recorrido_garita, "Salida, regreso y exceso sobre la hora autorizada"),
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
