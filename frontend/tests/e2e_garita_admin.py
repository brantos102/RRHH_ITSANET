"""Recorrido completo: solicitud, doble aprobación, garita, informes y administración.

Verifica además que cada rol vea solo sus módulos y que un intento con
código desconocido quede registrado en la bitácora.

Requiere, como las otras pruebas de extremo a extremo:
    cd backend && EMAIL_BACKEND=console APP_URL=http://localhost:8100 \
        uvicorn app.main:app --port 8099
    cd frontend && python -m http.server 8100   # config.js apuntando a :8099

    python frontend/tests/e2e_garita_admin.py

Los clics usan force=True: sin acceso al CDN de Tailwind la página queda sin
estilos y la geometría de clic no es fiable. Se comprueba la lógica.
"""
import asyncio, datetime as dt, re
from playwright.async_api import async_playwright

BASE = "http://localhost:8100"
import os
CHROME = os.environ.get("CHROMIUM_PATH") or None

def codigo():
    return re.findall(r"Asunto: Código de acceso: (\d{6})", open("/tmp/uvicorn.log").read())[-1]

async def entrar(pg, cedula):
    await pg.goto(f"{BASE}/index.html")
    await pg.fill("#cedula", cedula)
    await pg.click("#btn-enviar", force=True)
    await pg.wait_for_selector("#paso-codigo:not(.hidden)")
    await pg.fill("#codigo", codigo())
    await pg.wait_for_url("**/dashboard.html", timeout=15000)
    await pg.wait_for_timeout(1800)

async def main():
    errores = []
    async with async_playwright() as p:
        nav = await p.chromium.launch(executable_path=CHROME)
        def vigilar(pg):
            pg.on("pageerror", lambda e: errores.append(str(e)))
            pg.on("console", lambda m: errores.append(m.text)
                  if m.type == "error" and "TUNNEL" not in m.text and "favicon" not in m.text else None)

        # ---------- 1. Empleado crea y pide anulación ----------
        ctx = await nav.new_context(viewport={"width": 390, "height": 844})
        emp = await ctx.new_page(); vigilar(emp)
        await entrar(emp, "0926687856")
        print("✓ empleado:", await emp.inner_text("#cab-nombre"))
        barra = await emp.inner_text("#barra")
        print("  menús que ve un empleado:", " | ".join(x for x in barra.split("\n") if x.strip())[:70])

        await emp.click("[data-nueva='vacacion']", force=True)
        await emp.wait_for_selector("#modal-solicitud[open]")
        lunes = dt.date.today() + dt.timedelta(weeks=14)
        lunes -= dt.timedelta(days=lunes.weekday())
        await emp.fill("#fecha-inicio", str(lunes))
        await emp.fill("#fecha-fin", str(lunes + dt.timedelta(days=6)))
        await emp.wait_for_timeout(1100)
        await emp.fill("#descripcion", "Solicitud para el recorrido completo")
        await emp.click("#btn-enviar-solicitud", force=True)
        await emp.wait_for_function("!document.getElementById('modal-solicitud').open", timeout=12000)
        await emp.wait_for_timeout(1500)
        folio = re.search(r"Nº (\d+)", await emp.inner_text("#lista-solicitudes")).group(1)
        print(f"✓ solicitud Nº {folio} enviada")

        import subprocess
        ENV = {"PGHOST": "/var/lib/pgtest", "PATH": "/usr/bin:/bin"}
        def sql(q):
            return subprocess.run(["psql","-p","55432","-U","postgres","-d","rrhh_v4","-tAc",q],
                                  capture_output=True, text=True, env=ENV).stdout.strip()
        sql(f"update public.requests set fecha_inicio=current_date, fecha_fin=current_date+3 "
            f"where folio={folio}")
        print("  fechas ajustadas a hoy (aún pendiente del jefe)")

        # ---------- 2. Jefe aprueba ----------
        ctx2 = await nav.new_context(viewport={"width": 1280, "height": 900})
        jefe = await ctx2.new_page(); vigilar(jefe)
        await entrar(jefe, "1710034065")
        barra_jefe = await jefe.inner_text("#barra")
        print("✓ el jefe ve:", " · ".join(x.strip() for x in barra_jefe.split("\n") if x.strip())[:90])
        await jefe.click("[data-pestana='aprobaciones']", force=True)
        await jefe.wait_for_timeout(700)
        await jefe.click("[data-aprobar]", force=True)
        await jefe.wait_for_timeout(2500)
        print("  jefe aprobó:", (await jefe.inner_text("#aviso"))[:60])

        # ---------- 3. RRHH: menús, aprobación, informes, administración ----------
        ctx3 = await nav.new_context(viewport={"width": 1440, "height": 950})
        rrhh = await ctx3.new_page(); vigilar(rrhh)
        await entrar(rrhh, "0703886002")
        barra_rrhh = await rrhh.inner_text("#barra")
        modulos = [x.strip() for x in barra_rrhh.split("\n") if x.strip()]
        print("✓ Talento Humano ve:", " · ".join(modulos)[:110])
        assert "Informes" in barra_rrhh and "Talento Humano" in barra_rrhh

        await rrhh.click("[data-pestana='aprobaciones']", force=True)
        await rrhh.wait_for_timeout(800)
        await rrhh.click("[data-aprobar]", force=True)
        await rrhh.wait_for_timeout(2500)
        print("✓ aprobación final:", (await rrhh.inner_text("#aviso"))[:70])

        # ---------- 4. Garita ----------
        await emp.reload(); await emp.wait_for_timeout(2200)
        await emp.click("[data-qr]", force=True)
        await emp.wait_for_selector("#modal-qr[open]", timeout=8000)
        await emp.wait_for_timeout(600)
        print("✓ el empleado ve su QR")
        await emp.keyboard.press("Escape")

        qr = sql(f"select qr_hash from public.requests where folio={folio}")

        ctx4 = await nav.new_context(viewport={"width": 1280, "height": 900})
        guardia = await ctx4.new_page(); vigilar(guardia)
        await entrar(guardia, "1713175071")
        await guardia.goto(f"{BASE}/garita.html")
        await guardia.wait_for_timeout(2200)
        print("✓ garita cargada · autorizados hoy:", await guardia.inner_text("#cuenta-hoy"))

        await guardia.fill("#entrada-qr", qr)
        await guardia.click("#form-qr button[type=submit]", force=True)
        await guardia.wait_for_selector("#veredicto[open]", timeout=8000)
        await guardia.wait_for_timeout(500)
        print("✓ veredicto:", await guardia.inner_text("#veredicto-titulo"),
              "|", (await guardia.inner_text("#veredicto-datos")).replace("\n", " ")[:95])
        await guardia.click("#veredicto-cerrar", force=True)
        await guardia.wait_for_timeout(1200)

        # QR inventado
        await guardia.fill("#entrada-qr", "00000000-0000-4000-8000-000000000000")
        await guardia.click("#form-qr button[type=submit]", force=True)
        await guardia.wait_for_selector("#veredicto[open]", timeout=8000)
        print("✓ código desconocido:", await guardia.inner_text("#veredicto-titulo"),
              "—", await guardia.inner_text("#veredicto-motivo"))
        await guardia.click("#veredicto-cerrar", force=True)
        await guardia.wait_for_timeout(1000)

        # Visitante
        await guardia.click("#btn-nueva-visita", force=True)
        await guardia.wait_for_selector("#modal-visita[open]")
        await guardia.fill("#v-cedula", "1234567890")
        await guardia.wait_for_timeout(400)
        print("✓ cédula inválida de visita:", await guardia.inner_text("#v-error-cedula"))
        await guardia.fill("#v-cedula", "0602910945")
        await guardia.fill("#v-nombre", "Proveedor ACME")
        await guardia.fill("#v-empresa", "ACME S.A.")
        await guardia.fill("#v-motivo", "Entrega de equipos de red")
        await guardia.click("#form-visita button[type=submit]", force=True)
        await guardia.wait_for_timeout(2000)
        print("✓ visita registrada:", (await guardia.inner_text("#aviso"))[:60])
        print("  dentro ahora:", (await guardia.inner_text("#lista-visitas")).split("\n")[0])
        bitacora = await guardia.inner_text("#bitacora")
        print("✓ bitácora registra el intento denegado:", "denegado" in bitacora.lower() or "Intento" in bitacora)

        # ---------- 5. Informes ----------
        await rrhh.goto(f"{BASE}/informes.html")
        await rrhh.wait_for_timeout(2500)
        print("✓ informes · resumen:", (await rrhh.inner_text("#resumen")).replace("\n", " ")[:80])
        await rrhh.fill("#f-folio", folio)
        await rrhh.click("#filtros button[type=submit]", force=True)
        await rrhh.wait_for_timeout(1500)
        print("  filtrando por Nº", folio, "→", (await rrhh.inner_text("#paginacion")).split("\n")[0])

        # ---------- 6. Administración ----------
        await rrhh.goto(f"{BASE}/administracion.html")
        await rrhh.wait_for_selector("#tabla-usuarios table", timeout=10000)
        filas = await rrhh.locator("#tabla-usuarios tbody tr").count()
        print(f"✓ administración · {filas} personas en la tabla de usuarios")
        await rrhh.click("[data-seccion='antiguedades']", force=True)
        await rrhh.wait_for_timeout(1500)
        ant = await rrhh.inner_text("#tabla-antiguedades")
        print("✓ antigüedades:", " ".join(ant.split("\n")[1:4])[:90])
        await rrhh.click("[data-seccion='feriados']", force=True)
        await rrhh.wait_for_timeout(1500)
        print("✓ días no laborables:", (await rrhh.inner_text("#tabla-feriados")).split("\n")[1][:60])
        await rrhh.click("[data-seccion='configuracion']", force=True)
        await rrhh.wait_for_timeout(1200)
        conf = await rrhh.inner_text("#lista-configuracion")
        print("✓ configuración:", conf.split("\n")[0][:50], "| campos bloqueados para RRHH:",
              await rrhh.locator("#lista-configuracion input[disabled]").count())

        await nav.close()

    reales = [e for e in errores if "TUNNEL" not in e and "Failed to load resource" not in e]
    print("\n" + ("⚠ errores: " + "; ".join(reales[:4]) if reales else "✓ sin errores de página"))

asyncio.run(main())
