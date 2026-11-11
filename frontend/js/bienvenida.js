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

function error(texto) {
  $("b-error").textContent = texto;
  $("b-error").classList.toggle("hidden", !texto);
  if (texto) $("b-error").scrollIntoView({ block: "center", behavior: "smooth" });
}

[["ingreso-ok", "b-ingreso-otra"], ["jefe-ok", "b-jefe-nuevo"], ["cargo-ok", "b-cargo-nuevo"]]
  .forEach(([grupo, caja]) => document.querySelectorAll(`input[name="${grupo}"]`).forEach((r) =>
    r.addEventListener("change", () => $(caja).classList.toggle("hidden", elegido(grupo) !== "no"))));
["b-telefono", "b-emer-telefono"].forEach((id) => $(id).addEventListener("input", soloDigitos));

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
  $("b-jefe-nuevo").insertAdjacentHTML("beforeend", (d.jefaturas || []).map((j) =>
    `<option value="${esc(j.id)}">${esc([j.nombre, j.cargo].filter(Boolean).join(" · "))}</option>`).join(""));

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
      if (!$("b-jefe-nuevo").value) return error("Elija quién es su jefe inmediato.");
      datos.jefe_propuesto_id = $("b-jefe-nuevo").value;
    }
  }
  if (pide("cargo")) {
    const ok = elegido("cargo-ok");
    if (!ok) return error("Indique si su cargo es correcto.");
    datos.cargo_correcto = ok === "si";
    if (ok === "no") {
      if (!$("b-cargo-nuevo").value.trim()) return error("Escriba su cargo.");
      datos.cargo_propuesto = $("b-cargo-nuevo").value.trim();
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
