/* Ficha inicial: lo que se pide antes de usar el sistema.

   Solo se muestran las secciones que faltan. Lo que la persona no puede
   cambiar sola —su fecha de ingreso, su jefe, su cargo— no se cambia aquí:
   si dice que no es correcto, va como pedido a Talento Humano y mientras
   tanto rige lo registrado. */
import { api, sesion, esc, fecha, ErrorApi } from "./api.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");

const elegido = (grupo) => document.querySelector(`input[name="${grupo}"]:checked`)?.value || null;
const soloDigitos = (e) => { e.target.value = e.target.value.replace(/\D/g, "").slice(0, 13); };
let pendientes = [];
let jefaturas = [], catalogo = { cargos: [], areas: [] }, persona = {};
let jefeElegido = null;            // id de la jefatura elegida de la lista

/* Para comparar sin tildes ni mayúsculas, y con las palabras en cualquier
   orden: «narvaez edu» encuentra a «Eduardo José Narváez». */
const normal = (t) => (t || "").toString().normalize("NFD").replace(/[\u0300-\u036f]/g, "")
  .toLowerCase().trim();
const coincide = (texto, consulta) => {
  const t = normal(texto);
  return normal(consulta).split(/\s+/).filter(Boolean).every((p) => t.includes(p));
};

/* Sugerencias bajo un campo: se filtran con cada letra. */
function sugerir(lista, items, alElegir) {
  const ul = $(lista);
  ul.innerHTML = items.map((it, i) => `
    <li><button type="button" data-i="${i}"
        class="block w-full px-3 py-2 text-left text-sm hover:bg-slate-50">${it.html}</button></li>`).join("");
  ul.classList.toggle("hidden", !items.length);
  ul.querySelectorAll("[data-i]").forEach((b) =>
    b.addEventListener("mousedown", (e) => { e.preventDefault(); alElegir(items[+b.dataset.i]); }));
}

function error(texto) {
  $("b-error").textContent = texto;
  $("b-error").classList.toggle("hidden", !texto);
  if (texto) $("b-error").scrollIntoView({ block: "center", behavior: "smooth" });
}

[["ingreso-ok", "b-ingreso-otra"], ["jefe-ok", "b-jefe-otro"], ["cargo-ok", "b-cargo-otro"]]
  .forEach(([grupo, caja]) => document.querySelectorAll(`input[name="${grupo}"]`).forEach((r) =>
    r.addEventListener("change", () => $(caja).classList.toggle("hidden", elegido(grupo) !== "no"))));
["b-telefono", "b-emer-telefono"].forEach((id) => $(id).addEventListener("input", soloDigitos));

/* ---- jefe: buscar entre las jefaturas registradas, o escribir uno nuevo ---- */
function estadoJefe(texto, tono = "text-slate-500") {
  $("b-jefe-estado").className = `mt-1.5 text-xs ${tono}`;
  $("b-jefe-estado").textContent = texto;
}

$("b-jefe-buscar").addEventListener("input", (e) => {
  jefeElegido = null;
  const q = e.target.value;
  if (normal(q).length < 2) {
    sugerir("b-jefe-sugerencias", [], null);
    return estadoJefe("Mientras escribe le mostramos las jefaturas registradas.");
  }
  const hallados = jefaturas.filter((j) => coincide(`${j.nombre} ${j.cargo || ""} ${j.departamento || ""}`, q))
    .slice(0, 8);
  sugerir("b-jefe-sugerencias", hallados.map((j) => ({
    j, html: `<b>${esc(j.nombre)}</b><span class="block text-xs text-slate-500">${
      esc([j.cargo, j.departamento].filter(Boolean).join(" · "))}</span>` })), ({ j }) => {
    jefeElegido = j.id;
    $("b-jefe-buscar").value = j.nombre;
    sugerir("b-jefe-sugerencias", [], null);
    estadoJefe(`✓ Registrado en el sistema: ${j.nombre}. Talento Humano lo confirmará.`, "text-emerald-700");
  });
  estadoJefe(hallados.length
    ? "Elija a su jefe de la lista."
    : "No está registrado. Escriba nombres y apellidos completos: Talento Humano lo registrará.",
    hallados.length ? "text-slate-500" : "text-amber-700");
});
$("b-jefe-buscar").addEventListener("blur", () =>
  setTimeout(() => sugerir("b-jefe-sugerencias", [], null), 150));

/* ---- cargo y área: sugerencias de los que existen en la empresa ---- */
function areaElegida() {
  return $("b-area").value === "__otra" ? $("b-area-otra").value.trim() : $("b-area").value;
}
$("b-area").addEventListener("change", () => {
  $("b-area-otra").classList.toggle("hidden", $("b-area").value !== "__otra");
});
$("b-cargo-nuevo").addEventListener("input", (e) => {
  const q = e.target.value;
  const area = areaElegida() || persona.departamento || "";
  const vistos = new Set();
  const hallados = catalogo.cargos
    .filter((c) => normal(q).length >= 1 && coincide(c.cargo, q))
    // Primero los del área elegida.
    .sort((a, b) => (normal(b.area) === normal(area)) - (normal(a.area) === normal(area)))
    .filter((c) => !vistos.has(normal(c.cargo)) && vistos.add(normal(c.cargo)))
    .slice(0, 8);
  sugerir("b-cargo-sugerencias", hallados.map((c) => ({
    c, html: `${esc(c.cargo)}${c.area ? `<span class="block text-xs text-slate-500">${esc(c.area)}</span>` : ""}` })),
    ({ c }) => { $("b-cargo-nuevo").value = c.cargo; sugerir("b-cargo-sugerencias", [], null); });
});
$("b-cargo-nuevo").addEventListener("blur", () =>
  setTimeout(() => sugerir("b-cargo-sugerencias", [], null), 150));

async function cargar() {
  const d = await api.fichaInicial();
  pendientes = d.pendientes || [];
  if (!pendientes.length) {
    sesion.actualizarPerfil({ pendientes: [] });
    return location.replace("dashboard.html");
  }
  const p = d.persona || {};
  $("b-nombre").textContent = p.nombre ? `, ${p.nombre}` : "";
  $("b-ingreso-actual").textContent = p.fecha_ingreso ? fecha(p.fecha_ingreso) : "Sin fecha registrada";
  $("b-jefe-actual").textContent = p.jefe_nombre
    ? [p.jefe_nombre, p.jefe_cargo].filter(Boolean).join(" · ") : "Sin jefe registrado";
  $("b-cargo-actual").textContent =
    [p.cargo, p.departamento].filter(Boolean).join(" · ") || "Sin cargo registrado";
  persona = p;
  jefaturas = d.jefaturas || [];
  if (pendientes.includes("cargo")) {
    try { catalogo = await api.catalogoCargos(); } catch { /* sin sugerencias, igual se escribe */ }
    $("b-area").insertAdjacentHTML("beforeend",
      catalogo.areas.map((a) => `<option value="${esc(a)}">${esc(a)}</option>`).join("")
      + '<option value="__otra">Otra (escribirla)…</option>');
  }

  // Sin jefe o sin cargo no hay nada que confirmar: se pregunta cuál es.
  if (!p.jefe_nombre) document.querySelector('input[name="jefe-ok"][value="no"]').click();
  if (!p.cargo) document.querySelector('input[name="cargo-ok"][value="no"]').click();

  document.querySelectorAll("[data-seccion]").forEach((s) =>
    s.classList.toggle("hidden", !pendientes.includes(s.dataset.seccion)));
}

$("form-bienvenida").addEventListener("submit", async (e) => {
  e.preventDefault();
  error("");
  const pide = (c) => pendientes.includes(c);
  const datos = {};

  if (pide("fecha_nacimiento")) {
    if (!$("b-nacimiento").value) return error("Escriba su fecha de nacimiento.");
    datos.fecha_nacimiento = $("b-nacimiento").value;
  }
  if (pide("fecha_ingreso")) {
    const ok = elegido("ingreso-ok");
    if (!ok) return error("Indique si su fecha de ingreso es correcta.");
    datos.fecha_ingreso_correcta = ok === "si";
    if (ok === "no") {
      if (!$("b-ingreso-propuesta").value) return error("Indique la fecha de ingreso que usted considera.");
      datos.fecha_ingreso_propuesta = $("b-ingreso-propuesta").value;
      datos.fecha_ingreso_motivo = $("b-ingreso-motivo").value.trim() || null;
    }
  }
  if (pide("jefe")) {
    const ok = elegido("jefe-ok");
    if (!ok) return error("Indique si su jefe inmediato es correcto.");
    datos.jefe_correcto = ok === "si";
    if (ok === "no") {
      const escrito = $("b-jefe-buscar").value.trim().replace(/\s+/g, " ");
      if (jefeElegido) datos.jefe_propuesto_id = jefeElegido;
      else if (escrito.split(" ").length >= 2) datos.jefe_nombre_propuesto = escrito;
      else return error("Elija a su jefe de la lista o escriba sus nombres y apellidos.");
    }
  }
  if (pide("cargo")) {
    const ok = elegido("cargo-ok");
    if (!ok) return error("Indique si su cargo es correcto.");
    datos.cargo_correcto = ok === "si";
    if (ok === "no") {
      const cargo = $("b-cargo-nuevo").value.trim(), area = areaElegida();
      if (!cargo && !area) return error("Escriba su cargo o elija su área.");
      datos.cargo_propuesto = cargo || null;
      datos.departamento_propuesto = area || null;
    }
  }
  if (pide("telefono")) {
    if ($("b-telefono").value.length < 7) return error("Escriba su teléfono personal.");
    datos.telefono = $("b-telefono").value;
  }
  if (pide("emergencia")) {
    if ($("b-emer-nombre").value.trim().length < 3 || $("b-emer-telefono").value.length < 7) {
      return error("Complete el contacto de emergencia: nombre y teléfono.");
    }
    datos.emergencia_nombre = $("b-emer-nombre").value.trim();
    datos.emergencia_parentesco = $("b-emer-parentesco").value || null;
    datos.emergencia_telefono = $("b-emer-telefono").value;
  }

  $("b-enviar").disabled = true;
  $("b-enviar").textContent = "Guardando…";
  try {
    const r = await api.guardarFichaInicial(datos);
    sesion.actualizarPerfil({ pendientes: r.pendientes || [] });
    if (r.pendientes?.length) {
      await cargar();
      return error("Aún falta completar algo. Revise lo marcado.");
    }
    location.replace("dashboard.html");
  } catch (err) {
    error(err instanceof ErrorApi ? err.message : "No se pudieron guardar sus datos.");
  } finally {
    $("b-enviar").disabled = false;
    $("b-enviar").textContent = "Guardar y continuar";
  }
});

$("b-salir").addEventListener("click", async () => {
  try { await api.cerrarSesion(); } catch { /* igual se cierra aquí */ }
  sesion.borrar();
  location.replace("index.html");
});

cargar().catch((err) => error(err.message || "No se pudo cargar su ficha."));
