/* Exportar datos: qué, de quién, para qué. Ver servidor/app/routers/exportaciones.py. */
import { api, sesion, esc, fechaHora } from "./api.js";
import { montarNavegacion } from "./navegacion.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");
if (!["rrhh", "admin"].includes(sesion.perfil?.rol)) location.replace("dashboard.html");
montarNavegacion($("barra"), { activo: "informes" });

let temporizador;
const avisar = (texto, error = false) => {
  $("aviso-texto").textContent = texto;
  $("aviso-texto").className = `mx-auto max-w-md rounded-2xl px-4 py-3 text-center text-sm shadow-lg ${
    error ? "bg-rose-600 text-white" : "bg-slate-900 text-white"}`;
  $("aviso").classList.remove("hidden");
  clearTimeout(temporizador);
  temporizador = setTimeout(() => $("aviso").classList.add("hidden"), 5000);
};

const CONTRATO = { indefinido: "Indefinido", eventual: "Eventual", ocasional: "Ocasional",
  temporada: "Temporada", obra_cierta: "Obra cierta", prueba: "Prueba", aprendizaje: "Aprendizaje",
  pasantia: "Pasantía" };
const estado = { opciones: null, tipo: "personas", personas: new Map(),
                 multi: { areas: new Set(), cargos: new Set(), ciudades: new Set() } };

/* ---------------------------------------------------------- selección múltiple
   Un campo con sugerencias: se escribe, se elige y queda como etiqueta. */
function montarMulti(caja, opciones) {
  const clave = caja.dataset.multi;
  const id = `ex-${clave}`;
  caja.innerHTML = `
    <label class="block text-xs font-medium uppercase tracking-wide text-slate-500" for="${id}">${esc(caja.dataset.titulo)}</label>
    <input id="${id}" list="${id}-lista" autocomplete="off" placeholder="Escriba y elija…"
           class="mt-1 w-full rounded-xl border-0 bg-slate-50 px-3 py-2 text-sm ring-1 ring-slate-300 focus:bg-white focus:ring-2 focus:ring-[#1c58d7]">
    <datalist id="${id}-lista">${opciones.map((o) => `<option value="${esc(o)}">`).join("")}</datalist>
    <div data-chips="${clave}" class="mt-2 flex flex-wrap gap-1.5"></div>`;
  const entrada = caja.querySelector("input");
  const agregar = () => {
    const v = entrada.value.trim();
    if (!v || !opciones.includes(v)) return;
    estado.multi[clave].add(v);
    entrada.value = "";
    pintarChips(clave);
    previa();
  };
  entrada.addEventListener("change", agregar);
  entrada.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); agregar(); } });
}

function pintarChips(clave) {
  const caja = document.querySelector(`[data-chips="${clave}"]`);
  const valores = clave === "personas"
    ? [...estado.personas.entries()].map(([id, n]) => [id, n])
    : [...estado.multi[clave]].map((v) => [v, v]);
  caja.innerHTML = valores.map(([v, t]) => `
    <span class="inline-flex items-center gap-1 rounded-full bg-[#1c58d7]/10 px-2.5 py-1 text-xs font-medium text-[#1c58d7]">
      ${esc(t)}<button type="button" data-quitar="${esc(v)}" class="ml-0.5 text-[#1c58d7]/70 hover:text-[#1c58d7]" aria-label="Quitar">✕</button></span>`).join("");
  caja.querySelectorAll("[data-quitar]").forEach((b) => b.addEventListener("click", () => {
    if (clave === "personas") estado.personas.delete(b.dataset.quitar);
    else estado.multi[clave].delete(b.dataset.quitar);
    pintarChips(clave);
    previa();
  }));
}

/* ------------------------------------------------------------- personas */
let busqueda;
$("ex-persona").addEventListener("input", () => {
  clearTimeout(busqueda);
  const q = $("ex-persona").value.trim();
  if (q.length < 2) return $("ex-persona-res").classList.add("hidden");
  busqueda = setTimeout(async () => {
    try {
      const lista = await api.buscarPersona(q);
      $("ex-persona-res").innerHTML = lista.length ? lista.map((p) => `
        <button type="button" data-id="${esc(p.id)}" data-nombre="${esc(p.nombre)}"
                class="block w-full px-3 py-2 text-left text-sm hover:bg-slate-50">
          <b>${esc(p.nombre)}</b> <span class="text-xs text-slate-500">${esc(p.cedula)} · ${esc(p.cargo || "")}</span></button>`).join("")
        : '<p class="px-3 py-2 text-sm text-slate-500">Nadie coincide.</p>';
      $("ex-persona-res").classList.remove("hidden");
    } catch (err) { avisar(err.message, true); }
  }, 250);
});
$("ex-persona-res").addEventListener("click", (e) => {
  const b = e.target.closest("[data-id]");
  if (!b) return;
  estado.personas.set(b.dataset.id, b.dataset.nombre);
  $("ex-persona").value = "";
  $("ex-persona-res").classList.add("hidden");
  pintarChips("personas");
  previa();
});

/* -------------------------------------------------------------- filtros */
function filtros() {
  const marcados = (id) => [...document.querySelectorAll(`#${id} input:checked`)].map((c) => c.value);
  const tipo = estado.opciones.tipos.find((t) => t.clave === estado.tipo);
  return {
    personas: [...estado.personas.keys()],
    areas: [...estado.multi.areas], cargos: [...estado.multi.cargos], ciudades: [...estado.multi.ciudades],
    sedes: marcados("ex-sedes"), contratos: marcados("ex-contratos"),
    jefe_id: $("ex-jefe").value || null, estado: $("ex-estado").value,
    desde: tipo.periodo ? $("ex-desde").value || null : null,
    hasta: tipo.periodo ? $("ex-hasta").value || null : null,
  };
}

let temporizadorPrevia;
function previa() {
  clearTimeout(temporizadorPrevia);
  temporizadorPrevia = setTimeout(async () => {
    try {
      const r = await api.exportacionPrevia({ tipo: estado.tipo, filtros: filtros() });
      $("ex-cuenta").textContent = `${r.filas.toLocaleString("es-EC")} fila(s)${r.excede ? " · se exportan las primeras 20.000" : ""}`;
      $("ex-previa").innerHTML = r.muestra.length ? `
        <table class="w-full text-left text-xs">
          <thead class="bg-[#1c58d7] text-white"><tr>${r.columnas.map((c) => `<th class="whitespace-nowrap px-3 py-2 font-medium">${esc(c)}</th>`).join("")}</tr></thead>
          <tbody class="divide-y divide-slate-100">${r.muestra.map((f) => `<tr>${f.map((v) =>
            `<td class="whitespace-nowrap px-3 py-1.5">${esc(v == null ? "" : String(v).replace(/T.*$/, ""))}</td>`).join("")}</tr>`).join("")}</tbody>
        </table>
        ${r.filas > r.muestra.length ? `<p class="px-5 py-2 text-xs text-slate-500">Y ${r.filas - r.muestra.length} fila(s) más en el archivo.</p>` : ""}`
        : '<p class="px-5 py-8 text-center text-sm text-slate-500">No hay datos con estos filtros.</p>';
    } catch (err) {
      $("ex-previa").innerHTML = `<p class="px-5 py-6 text-center text-sm text-rose-700">${esc(err.message)}</p>`;
    }
  }, 300);
}

function pintarTipos() {
  $("ex-tipos").innerHTML = estado.opciones.tipos.map((t) => `
    <label class="block cursor-pointer">
      <input type="radio" name="tipo" value="${esc(t.clave)}" ${t.clave === estado.tipo ? "checked" : ""} class="peer sr-only">
      <span class="block h-full rounded-xl p-3 ring-1 ring-slate-200 transition peer-checked:bg-[#1c58d7]/5 peer-checked:ring-2 peer-checked:ring-[#1c58d7]">
        <span class="block font-medium">${esc(t.titulo)}</span>
        <span class="mt-0.5 block text-xs text-slate-600">${esc(t.descripcion)}</span>
      </span>
    </label>`).join("");
  $("ex-tipos").querySelectorAll('input[name="tipo"]').forEach((r) => r.addEventListener("change", () => {
    estado.tipo = r.value;
    mostrarPeriodo();
    previa();
  }));
}

function mostrarPeriodo() {
  const tipo = estado.opciones.tipos.find((t) => t.clave === estado.tipo);
  $("ex-periodo").classList.toggle("hidden", !tipo.periodo);
}

async function cargarHistorial() {
  const lista = await api.exportacionesHistorial();
  $("ex-historial").innerHTML = lista.length ? lista.map((e) => `
    <tr class="hover:bg-slate-50">
      <td class="px-3 py-2 font-mono text-xs">${esc(e.folio)}</td>
      <td class="whitespace-nowrap px-3 py-2 text-slate-600">${fechaHora(e.created_at)}</td>
      <td class="px-3 py-2">${esc(e.por || "—")}</td>
      <td class="px-3 py-2">${esc(e.titulo)} <span class="text-xs uppercase text-slate-500">${esc(e.formato)}</span></td>
      <td class="px-3 py-2 text-right tabular-nums">${e.filas}</td>
      <td class="px-3 py-2 text-slate-600">${esc(e.motivo)}</td>
      <td class="px-3 py-2 font-mono text-[11px] text-slate-400" title="${esc(e.sha256)}">${esc(e.sha256.slice(0, 12))}…</td>
    </tr>`).join("") : '<tr><td colspan="7" class="px-3 py-6 text-center text-slate-500">Todavía no se exportó nada.</td></tr>';
}

$("ex-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const motivo = $("ex-motivo").value.trim();
  if (motivo.length < 10) return avisar("Escriba para qué se exporta (mínimo 10 caracteres).", true);
  const boton = e.submitter;
  boton.disabled = true;
  try {
    const r = await api.exportar({ tipo: estado.tipo, formato: document.querySelector('input[name="formato"]:checked').value,
                                   filtros: filtros(), motivo });
    $("ex-resultado").innerHTML = `Descargado <b>${esc(r.nombre)}</b><br>Folio <b>${esc(r.folio)}</b> · huella ${esc((r.sha256 || "").slice(0, 16))}…`;
    $("ex-resultado").classList.remove("hidden");
    await cargarHistorial();
  } catch (err) { avisar(err.message, true); }
  finally { boton.disabled = false; }
});

(async () => {
  try {
    estado.opciones = await api.exportacionesOpciones();
    const o = estado.opciones;
    pintarTipos();
    document.querySelectorAll("[data-multi]").forEach((c) => montarMulti(c, o[c.dataset.multi] || []));
    $("ex-sedes").innerHTML = o.sedes.map((s) => `<label class="flex items-center gap-1.5">
      <input type="checkbox" value="${esc(s.codigo)}" class="h-4 w-4"> ${esc(s.sede)}</label>`).join("");
    $("ex-contratos").innerHTML = o.contratos.map((c) => `<label class="flex items-center gap-1.5">
      <input type="checkbox" value="${esc(c)}" class="h-4 w-4"> ${esc(CONTRATO[c] || c)}</label>`).join("");
    $("ex-jefe").insertAdjacentHTML("beforeend", o.jefes.map((j) => `<option value="${esc(j.id)}">${esc(j.nombre)}</option>`).join(""));
    ["ex-sedes", "ex-contratos"].forEach((id) => $(id).addEventListener("change", previa));
    ["ex-jefe", "ex-estado", "ex-desde", "ex-hasta"].forEach((id) => $(id).addEventListener("change", previa));
    const hoy = new Date();
    $("ex-desde").value = `${hoy.getFullYear()}-01-01`;
    $("ex-hasta").value = hoy.toISOString().slice(0, 10);
    mostrarPeriodo();
    previa();
    await cargarHistorial();
  } catch (err) { avisar(err.message, true); }
})();
