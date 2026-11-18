"""Calendario del equipo y ajuste de una ausencia por Talento Humano.

Cubre lo que no tocan los otros guiones:
  * el jefe ve a su equipo mes a mes, con los bloques de ausencia pintados
  * Talento Humano extiende una ausencia ya aprobada y queda el historial
  * el jefe ve las fechas nuevas, no las originales

Requiere lo mismo que las demás pruebas de extremo a extremo:
    cd backend && EMAIL_BACKEND=console APP_URL=http://localhost:8100 \
        uvicorn app.main:app --port 8000
    cd frontend && python -m http.server 8100   # el frontend deduce la API sola

    python frontend/tests/e2e_equipo_ajuste.py

Los clics usan force=True para no depender de animaciones ni de la posición
exacta de cada elemento. Los estilos se compilan localmente
(frontend/vendor/tailwind.css), así que la página se ve como en producción.
"""
import asyncio
import datetime as dt
import os
import re

from playwright.async_api import async_playwright

BASE = "http://localhost:8100"
CHROME = os.environ.get("CHROMIUM_PATH") or None
CED_JEFE, CED_RRHH = "1710034065", "0703886002"


def ultimo_codigo():
    log = open("/tmp/uvicorn.log").read()
    return re.findall(r"Asunto: Código de acceso: (\d{6})", log)[-1]


async def entrar(pagina, cedula):
    await pagina.goto(f"{BASE}/index.html")
    await pagina.fill("#cedula", cedula)
    await pagina.click("#btn-enviar", force=True)
    await pagina.wait_for_selector("#paso-codigo:not(.hidden)")
    await pagina.fill("#codigo", ultimo_codigo())
    await pagina.click("#btn-validar", force=True)
    await pagina.wait_for_url("**/dashboard.html", timeout=15000)
    await pagina.wait_for_timeout(900)


async def main():
    errores = []
    async with async_playwright() as p:
        nav = await p.chromium.launch(executable_path=CHROME)

        # ---------- 1. El jefe mira a su equipo ----------
        ctx = await nav.new_context(viewport={"width": 1400, "height": 950})
        jefe = await ctx.new_page()
        jefe.on("pageerror", lambda e: errores.append(str(e)))
        await entrar(jefe, CED_JEFE)

        await jefe.click('[data-abrir="jefe"]', force=True)
        await jefe.wait_for_timeout(400)
        await jefe.locator('[data-panel="jefe"] a', has_text="Calendario del equipo").click(force=True)
        await jefe.wait_for_url("**/equipo.html", timeout=10000)
        await jefe.wait_for_timeout(2200)

        filas = await jefe.locator("#rejilla tbody tr").count()
        assert filas > 0, "el jefe debe ver a su equipo aunque nadie falte"

        # Hacen falta dos cosas que antes se daban por supuestas.
        #
        # Una, que el mes mostrado tenga ausencias: las de los demás guiones
        # caen semanas más adelante, y esta prueba solo encontraba algo en el
        # mes en curso por los datos que quedaban de corridas anteriores.
        #
        # Y dos, que la ausencia esté APROBADA: solo lo aprobado se ajusta, y
        # el calendario pinta también lo pendiente. La rejilla distingue una de
        # otra por el tono —el tono fuerte es lo aprobado—, así que se busca
        # por ahí en vez de tomar la primera que aparezca y confiar en la
        # suerte, que es lo que fallaba.
        aprobadas = ("#rejilla [data-solicitud].bg-emerald-400, "
                     "#rejilla [data-solicitud].bg-sky-400")
        bloques = await jefe.locator(aprobadas).count()
        for _ in range(4):
            if bloques:
                break
            await jefe.click("#mes-siguiente", force=True)
            await jefe.wait_for_timeout(1200)
            bloques = await jefe.locator(aprobadas).count()
        mes = await jefe.inner_text("#mes-actual")
        assert bloques, (
            f"esta prueba necesita una ausencia aprobada en los próximos meses; "
            f"revisado hasta {mes}. Ejecute antes e2e_flujo_aprobacion.py.")
        print(f"✓ calendario del jefe: {filas} persona(s), "
              f"{bloques} día(s) de ausencia aprobada pintados en {mes}")
        leyenda = await jefe.inner_text("#rejilla ~ footer") if await jefe.locator("#rejilla ~ footer").count() else ""
        print("  la vista no revela el motivo:", "nunca el motivo" in (leyenda or ""))

        await jefe.locator(aprobadas).first.click(force=True)
        await jefe.wait_for_timeout(700)
        detalle_antes = await jefe.inner_text("#detalle")
        folio = re.search(r"Nº (\d+)", detalle_antes).group(1)
        print(f"✓ el jefe abre el detalle de la solicitud Nº {folio}")
        assert await jefe.locator("[data-ajustar]").count() == 0, \
            "un jefe no puede ajustar ausencias: es competencia de Talento Humano"
        print("  y no ve el botón de ajuste, que no le corresponde")

        # ---------- 2. Talento Humano extiende la ausencia ----------
        ctx2 = await nav.new_context(viewport={"width": 1400, "height": 950})
        rrhh = await ctx2.new_page()
        rrhh.on("pageerror", lambda e: errores.append(str(e)))
        await entrar(rrhh, CED_RRHH)
        await rrhh.goto(f"{BASE}/equipo.html")
        await rrhh.wait_for_timeout(2200)

        # Sin respaldo a `.first`: esta prueba ajustaba la primera ausencia de la
        # rejilla, que en una base con datos de corridas anteriores es otra
        # solicitud. El ajuste se guardaba —y el paso 3 lo confirmaba— sobre
        # una ajena, y el fallo aparecía después, al no encontrar el jefe
        # ningún ajuste en la suya. Mejor que falle aquí y diga cuál falta.
        celda = rrhh.locator(f'#rejilla [data-solicitud][title*="Nº {folio}"]').first
        for _ in range(4):
            if await celda.count():
                break
            await rrhh.click("#mes-siguiente", force=True)
            await rrhh.wait_for_timeout(1200)
        assert await celda.count(), (
            f"la rejilla de Talento Humano debe mostrar la solicitud Nº {folio}")
        await celda.click(force=True)
        await rrhh.wait_for_timeout(700)
        assert await rrhh.locator("[data-ajustar]").count() > 0, \
            "Talento Humano sí debe poder ajustar"
        await rrhh.locator("[data-ajustar]").first.click(force=True)
        await rrhh.wait_for_selector("#modal-ajuste[open]", timeout=8000)

        fin = await rrhh.input_value("#ajuste-fin")
        nuevo_fin = (dt.date.fromisoformat(fin) + dt.timedelta(days=3)).isoformat()
        await rrhh.fill("#ajuste-fin", nuevo_fin)
        await rrhh.fill("#ajuste-motivo",
                        "Asistio a su cita medica y el especialista le otorgo reposo por tres dias mas")
        await rrhh.fill("#ajuste-resolucion",
                        "Se extiende la ausencia con el certificado del IESS entregado en Talento Humano")
        await rrhh.click("#form-ajuste button[type=submit]", force=True)
        await rrhh.wait_for_timeout(3000)
        aviso = await rrhh.inner_text("#aviso")
        print("✓ ajuste guardado:", aviso[:80])
        assert "ajustada" in aviso.lower(), aviso

        # ---------- 3. Queda constancia y el jefe ve lo vigente ----------
        await rrhh.locator(
            f'#rejilla [data-solicitud][title*="Nº {folio}"]').first.click(force=True)
        await rrhh.wait_for_timeout(1500)
        detalle = await rrhh.inner_text("#detalle")
        assert "Historial de ajustes" in detalle, "el ajuste debe quedar registrado"
        assert "reposo" in detalle, "el historial debe conservar la explicación"
        print("✓ historial visible con el caso y la resolución")

        await jefe.reload()
        await jefe.wait_for_timeout(2500)
        # Tras el ajuste las fechas cambian: la celda de este folio puede
        # quedar en otro día del mes. Se espera a que aparezca en vez de
        # suponer que está donde estaba.
        celda_jefe = jefe.locator(f'#rejilla [data-solicitud][title*="Nº {folio}"]').first
        for _ in range(4):
            if await celda_jefe.count():
                break
            await jefe.click("#mes-siguiente", force=True)
            await jefe.wait_for_timeout(1200)
        await celda_jefe.wait_for(state="attached", timeout=8000)
        await celda_jefe.click(force=True)
        await jefe.wait_for_timeout(1200)
        detalle_jefe = await jefe.inner_text("#detalle")
        assert "ajustó estas fechas" in detalle_jefe, \
            "el jefe debe enterarse de que Talento Humano movió las fechas"
        print("✓ el jefe ve las fechas vigentes, no las originales")

        await nav.close()

    print("\n" + ("⚠ errores de página:\n    " + "\n    ".join(errores)
                  if errores else "✓ sin errores de página"))


asyncio.run(main())
