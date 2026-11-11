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
