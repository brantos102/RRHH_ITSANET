"""Prueba de extremo a extremo de la interfaz del empleado.

Recorre con un navegador real: validación de cédula, envío y verificación
del código, panel, detalle del saldo con su base legal, firma dibujada con
el mouse, previsualización en vivo y envío de una solicitud.

Requiere, en tres terminales:
    1. PostgreSQL con las migraciones aplicadas
    2. cd backend && EMAIL_BACKEND=console uvicorn app.main:app --port 8099
       (el código OTP se lee del log del servidor, en /tmp/uvicorn.log)
    3. cd frontend && python -m http.server 8100
       con config.js apuntando a http://localhost:8099

    python frontend/tests/e2e.py

Los clics usan force=True para no depender de animaciones ni de la posición
exacta de cada elemento. Los estilos se compilan localmente
(frontend/vendor/tailwind.css), así que la página se ve como en producción.
"""
import asyncio
import os
import re
from playwright.async_api import async_playwright

CEDULA = "0926687856"          # Ana Suárez, del seed

def ultimo_codigo():
    log = open("/tmp/uvicorn.log").read()
    codigos = re.findall(r"Asunto: Código de acceso: (\d{6})", log)
    return codigos[-1] if codigos else None

async def main():
    errores_consola = []
    async with async_playwright() as p:
        navegador = await p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        # Tamaño de teléfono: la app debe funcionar ahí primero
        movil = await navegador.new_context(viewport={"width": 390, "height": 844},
                                            device_scale_factor=2, is_mobile=True, has_touch=True)
        pagina = await movil.new_page()
        pagina.on("console", lambda m: errores_consola.append(m.text) if m.type == "error" else None)
        pagina.on("pageerror", lambda e: errores_consola.append(str(e)))

        # ---------- Login ----------
        await pagina.goto("http://localhost:8100/index.html")
        await pagina.screenshot(path="/tmp/capturas/1-login-movil.png")

        # Cédula inválida: validación en el navegador, sin ir al servidor
        await pagina.fill("#cedula", "1234567890")
        await pagina.click("#btn-enviar")
        await pagina.wait_for_selector("#error-cedula:not(.hidden)")
        print("✓ cédula inválida rechazada en el cliente:", await pagina.inner_text("#error-cedula"))

        await pagina.fill("#cedula", CEDULA)
        await pagina.click("#btn-enviar")
        await pagina.wait_for_selector("#paso-codigo:not(.hidden)")
        print("✓ código solicitado; correo mostrado:", await pagina.inner_text("#correo-destino"))
        await pagina.screenshot(path="/tmp/capturas/2-codigo-movil.png")

        # Código incorrecto
        await pagina.fill("#codigo", "000000")
        await pagina.wait_for_selector("#error-codigo:not(.hidden)", timeout=5000)
        print("✓ código incorrecto rechazado:", await pagina.inner_text("#error-codigo"))

        codigo = ultimo_codigo()
        await pagina.fill("#codigo", codigo)
        await pagina.wait_for_url("**/dashboard.html", timeout=10000)
        print("✓ sesión iniciada con el código real")

        # ---------- Dashboard ----------
        await pagina.wait_for_selector("#saldo-dias:not(:text('—'))", timeout=10000)
        await pagina.wait_for_timeout(700)
        print("  nombre:", await pagina.inner_text("#cab-nombre"),
              "| saldo:", await pagina.inner_text("#saldo-dias"),
              "| antigüedad:", await pagina.inner_text("#antiguedad"))
        await pagina.screenshot(path="/tmp/capturas/3-dashboard-movil.png", full_page=True)

        # Detalle del saldo con base legal
        await pagina.click("#btn-detalle-saldo", force=True)
        await pagina.wait_for_selector("#modal-saldo[open]")
        texto = await pagina.inner_text("#contenido-saldo")
        assert "Art. 69" in texto, "falta la base legal"
        print("✓ detalle del saldo con artículos:", [a for a in re.findall(r"Art\. \d+", texto)][:4])
        await pagina.screenshot(path="/tmp/capturas/4-detalle-saldo.png")
        await pagina.keyboard.press("Escape")

        # ---------- Firma dibujada ----------
        await pagina.click("#btn-firma", force=True)
        await pagina.wait_for_selector("#modal-firma[open]")
        caja = await pagina.locator("#lienzo-firma").bounding_box()
        await pagina.mouse.move(caja["x"] + 40, caja["y"] + 90)
        await pagina.mouse.down()
        for dx, dy in [(40, -35), (80, 25), (120, -40), (170, 15), (210, -25)]:
            await pagina.mouse.move(caja["x"] + dx, caja["y"] + 90 + dy)
        await pagina.mouse.up()
        await pagina.screenshot(path="/tmp/capturas/5-firma.png")
        await pagina.click("#btn-guardar-firma", force=True)
        await pagina.wait_for_function("!document.getElementById('modal-firma').open", timeout=8000)
        await pagina.wait_for_timeout(500)
        print("✓ firma guardada:", await pagina.inner_text("#estado-firma"))

        # ---------- Solicitud de vacaciones ----------
        await pagina.click("[data-nueva='vacacion']", force=True)
        await pagina.wait_for_selector("#modal-solicitud[open]")

        # Un viernes como fin: debe activarse la regla de fin de semana
        import datetime as dt
        lunes = dt.date.today() + dt.timedelta(weeks=8)
        lunes -= dt.timedelta(days=lunes.weekday())
        await pagina.fill("#fecha-inicio", str(lunes))
        await pagina.fill("#fecha-fin", str(lunes + dt.timedelta(days=4)))
        await pagina.wait_for_timeout(1200)
        previa = await pagina.inner_text("#previsualizacion")
        print("✓ previsualización en vivo:", previa.replace("\n", " ")[:150])
        await pagina.screenshot(path="/tmp/capturas/6-aviso-fin-de-semana.png")

        if await pagina.locator("#btn-corregir").count():
            await pagina.click("#btn-corregir", force=True)
            await pagina.wait_for_timeout(1000)
            print("✓ rango corregido a:", await pagina.input_value("#fecha-inicio"),
                  "–", await pagina.input_value("#fecha-fin"))

        await pagina.fill("#descripcion", "Viaje familiar programado con anticipación")
        await pagina.click("#btn-enviar-solicitud", force=True)
        await pagina.wait_for_timeout(2000)

        # Lunes a viernes son 5 días: por debajo del bloque mínimo. La regla
        # debe frenarlo y ofrecer la salida, no dejar al colaborador varado.
        if await pagina.locator("#modal-solicitud[open]").count():
            error = await pagina.inner_text("#error-solicitud")
            assert "bloques de al menos" in error, f"se esperaba el aviso del mínimo: {error}"
            print("✓ bloque mínimo aplicado:", error.split(".")[0][:90])
            assert await pagina.locator("#campo-excepcion").is_visible(), \
                "debe ofrecerse la vía de excepción"
            await pagina.click("#btn-aplicar-sugerido", force=True)
            await pagina.wait_for_timeout(800)
            print("  corregido con un clic a:", await pagina.input_value("#fecha-inicio"),
                  "–", await pagina.input_value("#fecha-fin"))
            await pagina.click("#btn-enviar-solicitud", force=True)

        await pagina.wait_for_function("!document.getElementById('modal-solicitud').open", timeout=10000)
        await pagina.wait_for_timeout(1200)
        print("✓ solicitud enviada:", (await pagina.inner_text("#lista-solicitudes")).split("\n")[0])
        await pagina.screenshot(path="/tmp/capturas/7-solicitud-creada.png", full_page=True)

        # ---------- Escritorio ----------
        guardada = await pagina.evaluate("localStorage.getItem('rrhh_sesion')")
        escritorio = await navegador.new_context(viewport={"width": 1280, "height": 900})
        pe = await escritorio.new_page()
        await pe.add_init_script("localStorage.setItem('rrhh_sesion', " + repr(guardada) + ")")
        await pe.goto("http://localhost:8100/dashboard.html")
        await pe.wait_for_timeout(2000)
        await pe.screenshot(path="/tmp/capturas/8-dashboard-escritorio.png", full_page=True)
        print("✓ vista de escritorio renderizada")

        await navegador.close()

    if errores_consola:
        print("\n⚠ errores de consola:")
        for e in errores_consola[:10]:
            print("   ", e[:160])
    else:
        print("\n✓ sin errores de consola en el navegador")

asyncio.run(main())
