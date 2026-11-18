/* Quién firma por Talento Humano en el documento que se va a imprimir.

   Por defecto, la cabeza del departamento en la sede del colaborador
   (Administración › Ingreso y firmas). Quien imprime puede elegir a otro
   integrante de esa sede o dejarlo en blanco para firmar a mano.

   Devuelve el id del firmante, "blanco", o null si se cancela. Si la sede no
   tiene firmantes configurados no pregunta nada: devuelve "" (el de por
   defecto, que es ninguno). */
import { api, esc } from "./api.js";

export async function elegirFirmante(region) {
  let lista = [];
  try { lista = await api.firmantesParaImprimir(region); } catch { return ""; }
  if (!lista.length) return "";

  return new Promise((resolver) => {
    const d = document.createElement("dialog");
    d.className = "w-[min(100vw-1.5rem,26rem)] rounded-2xl p-0";
    d.innerHTML = `
      <form method="dialog">
        <div class="border-b border-slate-200 px-5 py-4">
          <h2 class="font-semibold">¿Quién firma por Talento Humano?</h2>
          <p class="mt-0.5 text-sm text-slate-500">Su nombre sale impreso en el bloque de firma.</p>
        </div>
        <div class="space-y-2 px-5 py-4 text-sm">
          ${lista.map((f, i) => `
            <label class="flex items-start gap-2 rounded-xl p-2 hover:bg-slate-50">
              <input type="radio" name="firmante" value="${f.id}" ${i === 0 ? "checked" : ""} class="mt-0.5">
              <span><b>${esc(f.nombre)}</b> · ${esc(f.firma_como)}
                ${f.principal ? '<span class="ml-1 text-xs text-emerald-700">(cabeza del departamento)</span>' : ""}</span>
            </label>`).join("")}
          <label class="flex items-start gap-2 rounded-xl p-2 hover:bg-slate-50">
            <input type="radio" name="firmante" value="blanco" class="mt-0.5">
            <span>En blanco: se escribe a mano al firmar</span>
          </label>
        </div>
        <div class="flex gap-3 border-t border-slate-200 px-5 py-4">
          <button value="cancelar" class="flex-1 rounded-xl bg-slate-100 px-4 py-2.5 font-medium hover:bg-slate-200">Cancelar</button>
          <button value="ok" class="flex-1 rounded-xl bg-slate-900 px-4 py-2.5 font-medium text-white hover:bg-slate-800">Abrir documento</button>
        </div>
      </form>`;
    document.body.appendChild(d);
    d.addEventListener("close", () => {
      const valor = d.returnValue === "ok"
        ? d.querySelector('input[name="firmante"]:checked')?.value ?? "" : null;
      d.remove();
      resolver(valor);
    });
    d.showModal();
  });
}

/* Antes de imprimir (Talento Humano): quién firma y QUÉ FECHA lleva el
   documento. Por defecto, hoy. Una fecha anterior —para documentar
   vacaciones que se gozaron antes de que existiera el sistema— exige
   justificación y tiene un máximo por documento (3), que se muestra.

   Devuelve { firmante, fecha, justificacion } o null si se cancela. */
export async function prepararImpresion(informeId, region) {
  let lista = [];
  let fechas = null;
  try { lista = await api.firmantesParaImprimir(region); } catch { lista = []; }
  try { fechas = await api.fechasDelPapel(informeId); } catch { fechas = null; }
  const hoy = fechas?.hoy ? String(fechas.hoy).slice(0, 10) : new Date().toISOString().slice(0, 10);
  const minimo = fechas?.minimo ? String(fechas.minimo).slice(0, 10) : "";
  const restantes = fechas ? fechas.restantes : 0;
  const historial = (fechas?.historial || []).filter((h) => h.retroactiva);

  return new Promise((resolver) => {
    const d = document.createElement("dialog");
    d.className = "w-[min(100vw-1.5rem,30rem)] rounded-2xl p-0";
    d.innerHTML = `
      <form method="dialog">
        <div class="border-b border-slate-200 px-5 py-4">
          <h2 class="font-semibold">Imprimir documento</h2>
          <p class="mt-0.5 text-sm text-slate-500">Elija la fecha que llevará el documento y quién firma por Talento Humano.</p>
        </div>
        <div class="space-y-4 px-5 py-4 text-sm">
          <fieldset class="space-y-2">
            <legend class="text-xs font-medium uppercase tracking-wide text-slate-500">Fecha del documento</legend>
            <label class="flex items-start gap-2 rounded-xl p-2 hover:bg-slate-50">
              <input type="radio" name="cual" value="hoy" checked class="mt-0.5">
              <span><b>Hoy</b> · ${hoy.split("-").reverse().join("/")}</span>
            </label>
            <label class="flex items-start gap-2 rounded-xl p-2 ${restantes ? "hover:bg-slate-50" : "opacity-50"}">
              <input type="radio" name="cual" value="anterior" class="mt-0.5" ${restantes ? "" : "disabled"}>
              <span><b>Una fecha anterior</b> · le quedan <b>${restantes}</b> de ${fechas?.maximo ?? 3} para este documento.
                Exige justificación y queda en la bitácora; el pie del documento dirá la fecha real de impresión.</span>
            </label>
            <div data-anterior class="hidden space-y-2 pl-7">
              <input type="date" name="fecha" max="${hoy}" ${minimo ? `min="${minimo}"` : ""}
                     class="w-full rounded-xl border-0 bg-slate-50 px-3 py-2 ring-1 ring-slate-300">
              <textarea name="justificacion" rows="2" maxlength="400"
                        placeholder="Por qué va con esta fecha (mínimo 15 caracteres)"
                        class="w-full rounded-xl border-0 bg-slate-50 px-3 py-2 ring-1 ring-slate-300"></textarea>
              ${historial.length ? `<p class="text-xs text-slate-500">Usadas: ${historial.map((h) =>
                `${esc(String(h.fecha_documento).slice(0, 10).split("-").reverse().join("/"))} por ${esc(h.por || "—")}`).join(" · ")}</p>` : ""}
              <p data-error class="hidden text-xs text-rose-700"></p>
            </div>
          </fieldset>
          ${lista.length ? `<fieldset class="space-y-1">
            <legend class="text-xs font-medium uppercase tracking-wide text-slate-500">Firma por Talento Humano</legend>
            ${lista.map((f, i) => `
              <label class="flex items-start gap-2 rounded-xl p-2 hover:bg-slate-50">
                <input type="radio" name="firmante" value="${f.id}" ${i === 0 ? "checked" : ""} class="mt-0.5">
                <span><b>${esc(f.nombre)}</b> · ${esc(f.firma_como)}
                  ${f.principal ? '<span class="ml-1 text-xs text-emerald-700">(cabeza del departamento)</span>' : ""}</span>
              </label>`).join("")}
            <label class="flex items-start gap-2 rounded-xl p-2 hover:bg-slate-50">
              <input type="radio" name="firmante" value="blanco" class="mt-0.5">
              <span>En blanco: se escribe a mano al firmar</span>
            </label></fieldset>` : ""}
        </div>
        <div class="flex gap-3 border-t border-slate-200 px-5 py-4">
          <button value="cancelar" formnovalidate class="flex-1 rounded-xl bg-slate-100 px-4 py-2.5 font-medium hover:bg-slate-200">Cancelar</button>
          <button value="ok" class="flex-1 rounded-xl bg-slate-900 px-4 py-2.5 font-medium text-white hover:bg-slate-800">Abrir documento</button>
        </div>
      </form>`;
    document.body.appendChild(d);
    const anterior = () => d.querySelector('input[name="cual"]:checked')?.value === "anterior";
    d.querySelectorAll('input[name="cual"]').forEach((r) => r.addEventListener("change", () =>
      d.querySelector("[data-anterior]").classList.toggle("hidden", !anterior())));
    d.querySelector("form").addEventListener("submit", (e) => {
      if (e.submitter?.value !== "ok" || !anterior()) return;
      const f = d.querySelector('[name="fecha"]').value;
      const j = d.querySelector('[name="justificacion"]').value.trim();
      const error = !f ? "Elija la fecha." : f >= hoy ? "Para hoy use la primera opción."
        : (minimo && f < minimo) ? "No puede ser anterior al ingreso de la persona."
          : j.length < 15 ? "Explique el motivo en al menos 15 caracteres." : "";
      if (error) {
        e.preventDefault();
        const p = d.querySelector("[data-error]");
        p.textContent = error;
        p.classList.remove("hidden");
      }
    });
    d.addEventListener("close", () => {
      if (d.returnValue !== "ok") { d.remove(); return resolver(null); }
      const resultado = {
        firmante: d.querySelector('input[name="firmante"]:checked')?.value ?? "",
        fecha: anterior() ? d.querySelector('[name="fecha"]').value : "",
        justificacion: anterior() ? d.querySelector('[name="justificacion"]').value.trim() : "",
      };
      d.remove();
      resolver(resultado);
    });
    d.showModal();
  });
}
