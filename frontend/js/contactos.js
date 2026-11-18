/* Contactos de emergencia: verlos, agregarlos, corregirlos y quitarlos.

   Uno solo para dos pantallas —«Mi ficha» (la propia persona) y el
   expediente (Talento Humano)—, para que funcionen igual. Antes los
   contactos se guardaban en la bienvenida y no se mostraban en ninguna
   parte: quien los había registrado no podía comprobarlo. */
import { esc } from "./api.js";

const PARENTESCO = {
  conyuge: "Cónyuge", conviviente: "Conviviente", madre: "Madre", padre: "Padre", hijo: "Hijo/a",
  hermano: "Hermano/a", abuelo: "Abuelo/a", nieto: "Nieto/a", suegro: "Suegro/a",
  cunado: "Cuñado/a", otro: "Otro",
};
const IN = "w-full rounded-xl border-0 bg-slate-50 px-3 py-2 text-sm ring-1 ring-slate-300 focus:bg-white focus:ring-2 focus:ring-slate-900";

/* api: { listar(), guardar(id|null, datos), quitar(id) } — cada una devuelve
   { mensaje, contactos } salvo listar, que devuelve la lista. */
export function montarContactos(caja, api, avisar) {
  let contactos = [];

  const formulario = (c = {}) => `
    <form data-form-contacto="${esc(c.id || "")}" class="mt-2 grid gap-2 rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200 sm:grid-cols-2">
      <input name="nombre" required minlength="3" maxlength="120" placeholder="Nombre completo"
             value="${esc(c.nombre || "")}" class="${IN} sm:col-span-2">
      <select name="parentesco" class="${IN}">
        ${Object.entries(PARENTESCO).map(([v, t]) =>
          `<option value="${v}" ${c.parentesco === v ? "selected" : ""}>${t}</option>`).join("")}
      </select>
      <input name="telefono" required inputmode="numeric" maxlength="13" placeholder="Teléfono"
             value="${esc(c.telefono || "")}" class="${IN}">
      <input name="telefono_alternativo" inputmode="numeric" maxlength="13" placeholder="Otro teléfono (opcional)"
             value="${esc(c.telefono_alternativo || "")}" class="${IN}">
      <label class="flex items-center gap-2 text-sm"><input type="checkbox" name="es_principal"
             ${c.es_principal ? "checked" : ""} class="h-4 w-4"> Contacto principal</label>
      <div class="flex gap-2 sm:col-span-2">
        <button class="rounded-xl bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800">Guardar</button>
        <button type="button" data-cancelar-contacto class="rounded-xl bg-white px-4 py-2 text-sm font-medium ring-1 ring-slate-300 hover:bg-slate-100">Cancelar</button>
      </div>
    </form>`;

  function pintar(editando = null) {
    caja.innerHTML = `
      ${contactos.length ? `<ul class="divide-y divide-slate-100 rounded-xl ring-1 ring-slate-200">${contactos.map((c) =>
        editando === c.id ? `<li class="p-2">${formulario(c)}</li>` : `
        <li class="flex flex-wrap items-center gap-2 px-3 py-2.5 text-sm">
          <span class="min-w-0 flex-1"><b>${esc(c.nombre)}</b> · ${esc(PARENTESCO[c.parentesco] || c.parentesco)}
            ${c.es_principal ? '<span class="ml-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">principal</span>' : ""}
            <span class="block text-slate-600">${esc(c.telefono)}${c.telefono_alternativo ? " · " + esc(c.telefono_alternativo) : ""}</span></span>
          <button type="button" data-editar-contacto="${esc(c.id)}" class="rounded-lg px-2 py-1 text-xs font-medium hover:bg-slate-100">Editar</button>
          <button type="button" data-quitar-contacto="${esc(c.id)}" class="rounded-lg px-2 py-1 text-xs font-medium text-rose-700 hover:bg-rose-50">Quitar</button>
        </li>`).join("")}</ul>`
        : '<p class="rounded-xl bg-amber-50 p-3 text-sm text-amber-900 ring-1 ring-amber-200">No hay contacto de emergencia registrado.</p>'}
      ${editando === "nuevo" ? formulario() : `<button type="button" data-nuevo-contacto
          class="mt-2 rounded-xl bg-slate-100 px-3 py-2 text-sm font-medium hover:bg-slate-200">+ Agregar contacto</button>`}`;
  }

  caja.addEventListener("click", async (e) => {
    if (e.target.closest("[data-nuevo-contacto]")) return pintar("nuevo");
    if (e.target.closest("[data-cancelar-contacto]")) return pintar();
    const ed = e.target.closest("[data-editar-contacto]");
    if (ed) return pintar(ed.dataset.editarContacto);
    const qu = e.target.closest("[data-quitar-contacto]");
    if (qu) {
      if (!confirm("¿Quitar este contacto de emergencia?")) return;
      try { const r = await api.quitar(qu.dataset.quitarContacto); contactos = r.contactos; avisar(r.mensaje); pintar(); }
      catch (err) { avisar(err.message, true); }
    }
  });
  caja.addEventListener("input", (e) => {
    if (e.target.name?.startsWith("telefono")) e.target.value = e.target.value.replace(/\D/g, "").slice(0, 13);
  });
  caja.addEventListener("submit", async (e) => {
    const f = e.target.closest("[data-form-contacto]");
    if (!f) return;
    e.preventDefault();
    const d = Object.fromEntries(new FormData(f));
    const datos = { nombre: d.nombre.trim(), parentesco: d.parentesco, telefono: d.telefono,
                    telefono_alternativo: d.telefono_alternativo || null, es_principal: !!d.es_principal };
    if (datos.telefono.length < 7) return avisar("El teléfono debe tener al menos 7 dígitos.", true);
    try {
      const r = await api.guardar(f.dataset.formContacto || null, datos);
      contactos = r.contactos; avisar(r.mensaje); pintar();
    } catch (err) { avisar(err.message, true); }
  });

  return {
    async cargar() {
      try { contactos = await api.listar(); pintar(); }
      catch (err) { caja.innerHTML = `<p class="text-sm text-rose-700">${esc(err.message)}</p>`; }
    },
  };
}
