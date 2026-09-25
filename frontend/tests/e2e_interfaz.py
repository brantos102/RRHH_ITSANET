"""Verifica la interfaz: folio, desglose de días, reemplazo, calendario del
equipo, pestañas por rol, filtro de solicitudes y etiqueta de quién rechazó.

Requiere, como las otras pruebas de extremo a extremo:
    cd backend && EMAIL_BACKEND=console APP_URL=http://localhost:8100 \
        uvicorn app.main:app --port 8099
    cd frontend && python -m http.server 8100   # config.js apuntando a :8099

    python frontend/tests/e2e_interfaz.py

Los clics usan force=True para no depender de animaciones ni de la posición
exacta de cada elemento. Los estilos se compilan localmente
(frontend/vendor/tailwind.css), así que la página se ve como en producción.
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
        ctx = await nav.new_context(viewport={"width": 390, "height": 844})
        pg = await ctx.new_page()
        pg.on("pageerror", lambda e: errores.append(str(e)))
        pg.on("console", lambda m: errores.append(m.text) if m.type == "error" and "TUNNEL" not in m.text else None)

        # ---- Empleado ----
        await entrar(pg, "0926687856")
        print("✓ panel cargado:", await pg.inner_text("#cab-nombre"))
        print("  períodos:", await pg.inner_text("#periodos-resumen"))

        cal = await pg.inner_text("#calendario")
        print("✓ calendario del equipo:", cal.split("\n")[0][:70], "…")
        celdas = await pg.locator("#calendario td div").count()
        print(f"  {celdas} días pintados | leyenda dice el motivo:",
              "no el motivo" in cal or "no el motivo." in cal)

        # ---- Nueva solicitud: desglose ----
        # El reemplazo ya no se pide aquí: lo asigna el jefe al aprobar.
        await pg.click("[data-nueva='vacacion']", force=True)
        await pg.wait_for_selector("#modal-solicitud[open]")
        assert await pg.locator("#reemplazo").count() == 0, \
            "el solicitante no debe poder elegir quién lo cubre"
        print("✓ el formulario del colaborador ya no pide reemplazo")

        # Una semana con feriado dentro, para ver el desglose
        hoy = dt.date.today()
        feriado = dt.date(hoy.year if hoy < dt.date(hoy.year,11,2) else hoy.year+1, 11, 2)
        ini = feriado - dt.timedelta(days=feriado.weekday())
        await pg.fill("#fecha-inicio", str(ini))
        await pg.fill("#fecha-fin", str(ini + dt.timedelta(days=6)))
        await pg.wait_for_timeout(1400)
        previa = await pg.inner_text("#previsualizacion")
        print("✓ desglose:", previa.replace("\n", " | ")[:170])
        assert "a descontar" in previa
        assert "Feriados en el rango" in previa, "debe nombrar los feriados"

        await pg.fill("#descripcion", "Descanso con feriado incluido")
        await pg.click("#btn-enviar-solicitud", force=True)
        await pg.wait_for_function("!document.getElementById('modal-solicitud').open", timeout=12000)
        await pg.wait_for_timeout(1800)

        lista = await pg.inner_text("#lista-solicitudes")
        folio = re.search(r"Nº (\d+)", lista)
        print(f"✓ solicitud creada con folio {folio.group(1)}")

        # ---- Filtro ----
        await pg.fill("#filtro-solicitudes", "zzzz")
        await pg.wait_for_timeout(400)
        print("✓ filtro:", (await pg.inner_text("#lista-solicitudes")).strip()[:60])
        await pg.fill("#filtro-solicitudes", folio.group(1))
        await pg.wait_for_timeout(400)
        print("  al buscar el Nº vuelve a aparecer:",
              "Nº " + folio.group(1) in await pg.inner_text("#lista-solicitudes"))
        await pg.fill("#filtro-solicitudes", "")

        # ---- Jefe: pestañas + rechazo con etapa ----
        ctx2 = await nav.new_context(viewport={"width": 1280, "height": 900})
        jefe = await ctx2.new_page()
        jefe.on("pageerror", lambda e: errores.append(str(e)))
        await entrar(jefe, "1710034065")
        visible = await jefe.locator("#pestanas").is_visible()
        print(f"✓ el jefe ve las pestañas: {visible}; pendientes:",
              await jefe.inner_text("#cuenta-pendientes"))

        await jefe.click("[data-pestana='aprobaciones']", force=True)
        await jefe.wait_for_timeout(700)
        bandeja = await jefe.inner_text("#vista-aprobaciones")
        print("✓ bandeja muestra el Nº:", bool(re.search(r"Nº \d+", bandeja)))

        # Aprobar abre el diálogo donde el jefe elige quién cubre el puesto
        await jefe.click("[data-aprobar]", force=True)
        await jefe.wait_for_selector("#modal-reemplazo[open]", timeout=8000)
        await jefe.wait_for_timeout(1200)
        candidatos = await jefe.locator("#reemplazo-jefe option").count()
        print(f"✓ el jefe elige el reemplazo al aprobar: {candidatos} opción(es)")
        await jefe.click("#modal-reemplazo [data-cerrar]", force=True)
        await jefe.wait_for_timeout(400)

        await jefe.click("[data-rechazar]", force=True)
        await jefe.wait_for_selector("#modal-rechazo[open]")
        print("  encabezado del rechazo:", await jefe.inner_text("#rechazo-de"))
        await jefe.fill("#motivo-rechazo", "Coincide con el cierre contable del mes")
        await jefe.click("#form-rechazo button[type=submit]", force=True)
        await jefe.wait_for_timeout(2500)

        # ---- El empleado ve quién rechazó ----
        await pg.reload()
        await pg.wait_for_timeout(2200)
        lista = await pg.inner_text("#lista-solicitudes")
        etiqueta = re.search(r"Rechazada por [^\n]+", lista)
        print("✓ el empleado ve quién rechazó:", etiqueta.group(0) if etiqueta else "NO APARECE")
        assert etiqueta, "debe decir quién rechazó"

        await nav.close()
    print("\n" + ("⚠ errores: " + "; ".join(errores[:3]) if errores else "✓ sin errores de página"))

asyncio.run(main())
