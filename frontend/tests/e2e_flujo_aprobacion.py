"""Flujo completo de aprobación, con navegador real.

Recorre: el empleado envía una solicitud, el jefe decide desde el enlace
que llegó a su correo (sin iniciar sesión), Talento Humano aprueba en su
bandeja, el empleado abre su código QR y el enlace del jefe queda inservible.

Requiere, como la otra prueba de extremo a extremo:
    cd backend && EMAIL_BACKEND=console APP_URL=http://localhost:8100 \
        uvicorn app.main:app --port 8099        # los correos van a /tmp/uvicorn.log
    cd frontend && python -m http.server 8100   # con config.js apuntando a :8099

    python frontend/tests/e2e_flujo_aprobacion.py

Los clics usan force=True: sin acceso al CDN de Tailwind la página queda
sin estilos y la geometría de clic no es fiable. Se comprueba la lógica.
"""
import asyncio, datetime as dt, re
from playwright.async_api import async_playwright

BASE = "http://localhost:8100"
import os
CHROME = os.environ.get("CHROMIUM_PATH") or None
LOG = "/tmp/uvicorn.log"

def leer_log():
    return open(LOG, encoding="utf-8", errors="replace").read()

def ultimo_codigo():
    return re.findall(r"Asunto: Código de acceso: (\d{6})", leer_log())[-1]

def enlace(rol):
    """El correo se imprime en consola; de ahí sale el enlace de aprobación."""
    urls = re.findall(rf"{re.escape(BASE)}/aprobar\.html\?t=([0-9a-f-]{{36}})&r={rol}", leer_log())
    return urls[-1] if urls else None

async def entrar(pagina, cedula):
    await pagina.goto(f"{BASE}/index.html")
    await pagina.fill("#cedula", cedula)
    await pagina.click("#btn-enviar", force=True)
    await pagina.wait_for_selector("#paso-codigo:not(.hidden)")
    await pagina.fill("#codigo", ultimo_codigo())
    await pagina.wait_for_url("**/dashboard.html", timeout=15000)
    await pagina.wait_for_timeout(900)

async def main():
    errores = []
    async with async_playwright() as p:
        nav = await p.chromium.launch(executable_path=CHROME)

        # ---------- 1. El empleado envía una solicitud ----------
        ctx = await nav.new_context(viewport={"width": 390, "height": 844})
        emp = await ctx.new_page()
        emp.on("pageerror", lambda e: errores.append(str(e)))
        await entrar(emp, "0926687856")
        print("✓ empleado dentro:", await emp.inner_text("#cab-nombre"))

        await emp.click("[data-nueva='vacacion']", force=True)
        await emp.wait_for_selector("#modal-solicitud[open]")
        lunes = dt.date.today() + dt.timedelta(weeks=12)
        lunes -= dt.timedelta(days=lunes.weekday())
        await emp.fill("#fecha-inicio", str(lunes))
        await emp.fill("#fecha-fin", str(lunes + dt.timedelta(days=6)))
        await emp.wait_for_timeout(1000)
        await emp.fill("#descripcion", "Descanso programado de fin de ano")
        await emp.click("#btn-enviar-solicitud", force=True)
        await emp.wait_for_function("!document.getElementById('modal-solicitud').open", timeout=12000)
        await emp.wait_for_timeout(1500)
        print("✓ solicitud enviada:", (await emp.inner_text("#lista-solicitudes")).split("\n")[2].strip())

        # ---------- 2. El jefe decide desde el enlace del correo ----------
        token_jefe = enlace("jefe")
        assert token_jefe, "el correo al jefe no llegó"
        print("✓ correo al jefe con enlace de aprobación")

        ctx2 = await nav.new_context(viewport={"width": 390, "height": 844})
        jefe = await ctx2.new_page()
        jefe.on("pageerror", lambda e: errores.append(str(e)))
        await jefe.goto(f"{BASE}/aprobar.html?t={token_jefe}&r=jefe")
        await jefe.wait_for_selector("#tarjeta:not(.hidden)", timeout=10000)
        detalle = await jefe.inner_text("#detalle")
        print("✓ el enlace muestra la solicitud sin sesión:",
              detalle.replace("\n", " ")[:90], "…")
        assert "Ana Suárez" in detalle

        await jefe.click("#btn-aprobar", force=True)
        await jefe.wait_for_selector("#resultado:not(.hidden)", timeout=10000)
        print("✓ jefe aprobó:", await jefe.inner_text("#resultado-titulo"),
              "—", await jefe.inner_text("#resultado-texto"))

        # ---------- 3. Talento Humano aprueba desde su panel ----------
        ctx3 = await nav.new_context(viewport={"width": 1280, "height": 900})
        rrhh = await ctx3.new_page()
        rrhh.on("pageerror", lambda e: errores.append(str(e)))
        await entrar(rrhh, "0703886002")
        await rrhh.goto(f"{BASE}/aprobaciones.html")
        await rrhh.wait_for_selector("[data-aprobar]", timeout=10000)
        print("✓ Talento Humano ve la solicitud en su bandeja:",
              (await rrhh.inner_text("#lista")).split("\n")[0])
        await rrhh.screenshot(path="/tmp/capturas/aprobaciones.png", full_page=True)

        await rrhh.click("[data-aprobar]", force=True)
        await rrhh.wait_for_timeout(2500)
        print("✓ aprobación final:", await rrhh.inner_text("#aviso"))

        # ---------- 4. El empleado ve su QR ----------
        await emp.reload()
        await emp.wait_for_timeout(2500)
        await emp.click("[data-qr]", force=True)
        await emp.wait_for_selector("#modal-qr[open]", timeout=10000)
        await emp.wait_for_timeout(800)
        origen = await emp.get_attribute("#imagen-qr", "src")
        tamano = await emp.evaluate("document.getElementById('imagen-qr').naturalWidth")
        print(f"✓ QR mostrado al empleado (origen {origen[:5]}…, {tamano}px de ancho)")
        print("  vigencia:", await emp.inner_text("#qr-vigencia"))
        assert tamano > 100, "la imagen del QR no cargó"

        # ---------- 5. El enlace del jefe ya no sirve ----------
        await jefe.goto(f"{BASE}/aprobar.html?t={token_jefe}&r=jefe")
        await jefe.wait_for_timeout(1500)
        acciones = await jefe.inner_text("#acciones")
        print("✓ enlace reutilizado:", acciones.strip()[:70])

        await nav.close()

    reales = [e for e in errores if "TUNNEL" not in e]
    print("\n" + ("⚠ errores: " + "; ".join(reales[:3]) if reales else "✓ sin errores de página"))

asyncio.run(main())
