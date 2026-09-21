/* Administración: personal, tipos de solicitud, feriados, parámetros y bitácora. */
import { api, sesion, esc, fecha, fechaHora, validarCedula } from "./api.js";
import { montarNavegacion, ROL_TEXTO } from "./navegacion.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");
if (!["rrhh", "admin"].includes(sesion.perfil?.rol)) location.replace("dashboard.html");

montarNavegacion($("barra"), { activo: "admin" });

const esAdmin = sesion.perfil.rol === "admin";
const estado = { usuarios: [], jefes: [] };

let temporizador;
const avisar = (texto, error = false) => {
  const el = $("aviso");
  el.textContent = texto;
  el.className = `max-w-sm rounded-xl px-4 py-3 text-center text-sm shadow-lg ${
    error ? "bg-rose-600 text-white" : "bg-slate-900 text-white"}`;
  clearTimeout(temporizador);
  temporizador = setTimeout(() => el.classList.add("hidden"), 4500);
};

/* --------------------------------------------------------------- secciones */
const CARGADORES = {
  usuarios: cargarUsuarios, tipos: cargarTipos, feriados: cargarFeriados,
  antiguedades: cargarAntiguedades, configuracion: cargarConfiguracion, bitacora: cargarBitacora,
};

function mostrar(seccion) {
  document.querySelectorAll("[data-seccion]").forEach((b) => {
    const activa = b.dataset.seccion === seccion;
    b.className = `shrink-0 rounded-xl px-4 py-2 text-sm font-medium ${
      activa ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"}`;
  });
  document.querySelectorAll("[data-panel]").forEach((p) =>
    p.classList.toggle("hidden", p.dataset.panel !== seccion)
  );
  location.hash = seccion;
  CARGADORES[seccion]?.().catch((err) => avisar(err.message, true));
}

document.querySelectorAll("[data-seccion]").forEach((b) =>
  b.addEventListener("click", () => mostrar(b.dataset.seccion))
);

/* --------------------------------------------------------------- usuarios */
function tablaUsuarios(usuarios) {
  if (!usuarios.length) {
    return `<p class="px-5 py-10 text-center text-sm text-slate-500">Nadie coincide con la búsqueda.</p>`;
  }
  return `
    <table class="w-full text-left text-sm">
      <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th class="px-3 py-2.5">Nombre</th><th class="px-3 py-2.5">Cédula</th>
          <th class="px-3 py-2.5">Rol</th><th class="px-3 py-2.5">Cargo</th>
          <th class="px-3 py-2.5">Jefe</th><th class="px-3 py-2.5">Ingreso</th>
          <th class="px-3 py-2.5 text-right">Saldo</th><th class="px-3 py-2.5"></th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-100">
        ${usuarios.map((u) => `
          <tr class="${u.activo ? "" : "opacity-50"} hover:bg-slate-50">
            <td class="px-3 py-2.5">
              <p class="font-medium">${esc(u.nombre)}</p>
              <p class="text-xs text-slate-500">${esc(u.email)}</p>
            </td>
            <td class="px-3 py-2.5 font-mono text-xs">${esc(u.cedula)}</td>
            <td class="px-3 py-2.5"><span class="whitespace-nowrap rounded-full bg-slate-100 px-2 py-0.5 text-xs">
              ${esc(ROL_TEXTO[u.rol] || u.rol)}</span></td>
            <td class="px-3 py-2.5 text-slate-600">${esc(u.cargo || "—")}</td>
            <td class="px-3 py-2.5 text-slate-600">${esc(u.jefe_nombre || "—")}</td>
            <td class="px-3 py-2.5 whitespace-nowrap text-slate-600">${fecha(u.fecha_ingreso)}</td>
            <td class="px-3 py-2.5 text-right tabular-nums font-medium">${Number(u.dias_vacaciones)}</td>
            <td class="px-3 py-2.5 whitespace-nowrap text-right">
              <button data-editar="${u.id}" class="text-xs font-medium text-slate-700 hover:underline">Editar</button>
              <button data-saldo="${u.id}" data-nombre="${esc(u.nombre)}"
                      class="ml-2 text-xs font-medium text-slate-700 hover:underline">Saldo</button>
              <button data-activo="${u.id}" data-valor="${u.activo ? 0 : 1}"
                      class="ml-2 text-xs font-medium ${u.activo ? "text-rose-600" : "text-emerald-700"} hover:underline">
                ${u.activo ? "Desactivar" : "Reactivar"}</button>
            </td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

async function cargarUsuarios() {
  estado.usuarios = await api.adminUsuarios($("buscar-usuario").value, $("ver-inactivos").checked);
  estado.jefes = estado.usuarios.filter((u) => ["jefe", "rrhh", "admin"].includes(u.rol));
  $("tabla-usuarios").innerHTML = tablaUsuarios(estado.usuarios);
  $("u-jefe").innerHTML = `<option value="">Sin jefe asignado</option>` +
    estado.jefes.map((j) => `<option value="${j.id}">${esc(j.nombre)}</option>`).join("");
}

let buscando;
$("buscar-usuario").addEventListener("input", () => {
  clearTimeout(buscando);
  buscando = setTimeout(() => cargarUsuarios().catch((e) => avisar(e.message, true)), 300);
});
$("ver-inactivos").addEventListener("change", () => cargarUsuarios());

$("btn-nuevo-usuario").addEventListener("click", () => {
  $("form-usuario").reset();
  delete $("form-usuario").dataset.id;
  $("titulo-usuario").textContent = "Nuevo usuario";
  $("u-cedula").disabled = false;
  $("campo-saldo").classList.remove("hidden");
  $("u-error").classList.add("hidden");
  $("modal-usuario").showModal();
  $("u-cedula").focus();
});

document.addEventListener("click", async (e) => {
  if (e.target.closest("[data-cerrar]")) return e.target.closest("dialog")?.close();

  const editar = e.target.closest("[data-editar]");
  if (editar) {
    const u = estado.usuarios.find((x) => x.id === editar.dataset.editar);
    if (!u) return;
    $("form-usuario").dataset.id = u.id;
    $("titulo-usuario").textContent = `Editar a ${u.nombre}`;
    $("u-cedula").value = u.cedula;
    $("u-cedula").disabled = true;            // la cédula identifica: no se cambia
    $("u-nombre").value = u.nombre;
    $("u-email").value = u.email;
    $("u-rol").value = u.rol;
    $("u-telefono").value = u.telefono || "";
    $("u-cargo").value = u.cargo || "";
    $("u-departamento").value = u.departamento || "";
    $("u-jefe").value = u.jefe_id || "";
    $("u-ingreso").value = String(u.fecha_ingreso).slice(0, 10);
    $("campo-saldo").classList.add("hidden");  // el saldo se ajusta aparte
    $("u-error").classList.add("hidden");
    $("modal-usuario").showModal();
    return;
  }

  const saldo = e.target.closest("[data-saldo]");
  if (saldo) {
    const valor = prompt(`Saldo de vacaciones de ${saldo.dataset.nombre} según planilla:`);
    if (valor === null) return;
    const dias = Number(valor.replace(",", "."));
    if (Number.isNaN(dias) || dias < 0) return avisar("Indique un número de días válido.", true);
    try {
      avisar((await api.ajustarSaldo(saldo.dataset.saldo, dias)).mensaje);
      await cargarUsuarios();
    } catch (err) { avisar(err.message, true); }
    return;
  }

  const activo = e.target.closest("[data-activo]");
  if (activo) {
    try {
      avisar((await api.editarUsuario(activo.dataset.activo,
                                      { activo: activo.dataset.valor === "1" })).mensaje);
      await cargarUsuarios();
    } catch (err) { avisar(err.message, true); }
  }
});

$("u-cedula").addEventListener("input", (e) => {
  e.target.value = e.target.value.replace(/\D/g, "").slice(0, 10);
  const error = $("u-error-cedula");
  const malo = e.target.value.length === 10 && !validarCedula(e.target.value);
  error.textContent = malo ? "Esta cédula no es válida." : "";
  error.classList.toggle("hidden", !malo);
});

$("form-usuario").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("form-usuario").dataset.id;
  const datos = {
    nombre: $("u-nombre").value.trim(),
    email: $("u-email").value.trim(),
    telefono: $("u-telefono").value.trim() || null,
    rol: $("u-rol").value,
    cargo: $("u-cargo").value.trim() || null,
    departamento: $("u-departamento").value.trim() || null,
    jefe_id: $("u-jefe").value || null,
  };

  try {
    if (id) {
      avisar((await api.editarUsuario(id, datos)).mensaje);
    } else {
      if (!validarCedula($("u-cedula").value)) throw new Error("La cédula no es válida.");
      const saldo = $("u-saldo").value.trim();
      avisar((await api.crearUsuario({
        ...datos, cedula: $("u-cedula").value, fecha_ingreso: $("u-ingreso").value,
        saldo_inicial: saldo ? Number(saldo) : null,
      })).mensaje);
    }
    $("modal-usuario").close();
    await cargarUsuarios();
  } catch (err) {
    $("u-error").textContent = err.message;
    $("u-error").classList.remove("hidden");
  }
});

/* ------------------------------------------------------------------ tipos */
async function cargarTipos() {
  const tipos = await api.adminTipos();
  const casilla = (t, campo) =>
    `<input type="checkbox" data-tipo="${t.id}" data-campo="${campo}" ${t[campo] ? "checked" : ""}
            class="h-4 w-4 rounded border-slate-300">`;

  $("tabla-tipos").innerHTML = `
    <table class="w-full text-left text-sm">
      <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th class="px-3 py-2.5">Tipo</th><th class="px-3 py-2.5 text-center">Adjunto</th>
          <th class="px-3 py-2.5 text-center">Justificación</th><th class="px-3 py-2.5 text-center">Firma</th>
          <th class="px-3 py-2.5 text-center">Descuenta</th><th class="px-3 py-2.5 text-right">Máx. días</th>
          <th class="px-3 py-2.5 text-right">Máx. horas</th><th class="px-3 py-2.5 text-center">Activo</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-100">
        ${tipos.map((t) => `
          <tr class="hover:bg-slate-50">
            <td class="px-3 py-2.5">
              <p class="font-medium">${esc(t.nombre)}</p>
              ${t.articulo ? `<p class="text-xs text-slate-500">${esc(t.norma)} · ${esc(t.articulo)}</p>` : ""}
            </td>
            <td class="px-3 py-2.5 text-center">${casilla(t, "requiere_adjunto")}</td>
            <td class="px-3 py-2.5 text-center">${casilla(t, "requiere_justificacion")}</td>
            <td class="px-3 py-2.5 text-center">${casilla(t, "requiere_firma")}</td>
            <td class="px-3 py-2.5 text-center">${casilla(t, "descuenta_vacaciones")}</td>
            <td class="px-3 py-2.5 text-right tabular-nums">${t.max_dias ?? "—"}</td>
            <td class="px-3 py-2.5 text-right tabular-nums">${t.max_horas ?? "—"}</td>
            <td class="px-3 py-2.5 text-center">${casilla(t, "activo")}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;

  $("tabla-tipos").querySelectorAll("input[data-tipo]").forEach((c) =>
    c.addEventListener("change", async () => {
      try {
        avisar((await api.editarTipo(c.dataset.tipo, { [c.dataset.campo]: c.checked })).mensaje);
      } catch (err) {
        c.checked = !c.checked;                 // se revierte si el servidor no lo aceptó
        avisar(err.message, true);
      }
    })
  );
}

/* --------------------------------------------------------------- feriados */
async function cargarFeriados() {
  if (!$("anio-feriados").value) $("anio-feriados").value = new Date().getFullYear();
  const feriados = await api.adminFeriados($("anio-feriados").value);
  $("tabla-feriados").innerHTML = feriados.length
    ? `<table class="w-full text-left text-sm">
         <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
           <tr><th class="px-3 py-2.5">Fecha</th><th class="px-3 py-2.5">Día</th>
               <th class="px-3 py-2.5">Nombre</th><th class="px-3 py-2.5"></th></tr>
         </thead>
         <tbody class="divide-y divide-slate-100">
           ${feriados.map((f) => {
             const d = new Date(f.fecha + "T12:00");
             const dia = ["domingo","lunes","martes","miércoles","jueves","viernes","sábado"][d.getDay()];
             return `<tr class="${f.activo ? "" : "opacity-40"} hover:bg-slate-50">
               <td class="px-3 py-2.5 whitespace-nowrap font-medium">${fecha(f.fecha)}</td>
               <td class="px-3 py-2.5 text-slate-600">${dia}</td>
               <td class="px-3 py-2.5">${esc(f.nombre)}</td>
               <td class="px-3 py-2.5 text-right">
                 ${f.activo
                   ? `<button data-quitar="${f.fecha}" class="text-xs font-medium text-rose-600 hover:underline">Quitar</button>`
                   : `<span class="text-xs text-slate-400">inactivo</span>`}
               </td></tr>`;
           }).join("")}
         </tbody>
       </table>`
    : `<p class="px-5 py-10 text-center text-sm text-slate-500">Sin días no laborables registrados este año.</p>`;

  $("tabla-feriados").querySelectorAll("[data-quitar]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm("¿Quitar este día no laborable? Los cálculos pasados no cambian.")) return;
      try {
        avisar((await api.quitarFeriado(b.dataset.quitar)).mensaje);
        await cargarFeriados();
      } catch (err) { avisar(err.message, true); }
    })
  );
}

$("anio-feriados").addEventListener("change", () => cargarFeriados());
$("btn-nuevo-feriado").addEventListener("click", async () => {
  const f = prompt("Fecha del día no laborable (AAAA-MM-DD):");
  if (!f) return;
  const nombre = prompt("¿Cómo se llama? (Ej.: Fiestas de Quito)");
  if (!nombre) return;
  try {
    avisar((await api.crearFeriado({ fecha: f.trim(), nombre: nombre.trim() })).mensaje);
    await cargarFeriados();
  } catch (err) { avisar(err.message, true); }
});

/* ----------------------------------------------------------- antigüedades */
async function cargarAntiguedades() {
  const gente = await api.antiguedades();
  $("tabla-antiguedades").innerHTML = `
    <table class="w-full text-left text-sm">
      <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
        <tr><th class="px-3 py-2.5">Nombre</th><th class="px-3 py-2.5">Departamento</th>
            <th class="px-3 py-2.5">Ingreso</th><th class="px-3 py-2.5 text-right">Años</th>
            <th class="px-3 py-2.5 text-right">Días por año</th><th class="px-3 py-2.5 text-right">Saldo</th>
            <th class="px-3 py-2.5 text-center">Caducados</th></tr>
      </thead>
      <tbody class="divide-y divide-slate-100">
        ${gente.map((p) => `
          <tr class="hover:bg-slate-50">
            <td class="px-3 py-2.5 font-medium">${esc(p.nombre)}</td>
            <td class="px-3 py-2.5 text-slate-600">${esc(p.departamento || "—")}</td>
            <td class="px-3 py-2.5 whitespace-nowrap text-slate-600">${fecha(p.fecha_ingreso)}</td>
            <td class="px-3 py-2.5 text-right tabular-nums">${p.anios}</td>
            <td class="px-3 py-2.5 text-right tabular-nums font-medium">${Number(p.dias_por_anio)}</td>
            <td class="px-3 py-2.5 text-right tabular-nums">${Number(p.saldo)}</td>
            <td class="px-3 py-2.5 text-center">
              ${p.periodos_caducados
                ? `<span class="rounded-full bg-rose-100 px-2 py-0.5 text-xs font-medium text-rose-700">
                     ${p.periodos_caducados}</span>`
                : `<span class="text-slate-300">—</span>`}
            </td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

/* -------------------------------------------------------- configuración */
async function cargarConfiguracion() {
  const parametros = await api.adminConfiguracion();
  $("lista-configuracion").innerHTML = parametros.map((p) => `
    <div class="flex flex-wrap items-center gap-4 px-5 py-4">
      <div class="min-w-0 flex-1">
        <p class="font-medium">${esc(p.clave)}</p>
        <p class="mt-0.5 text-sm text-slate-600">${esc(p.descripcion || "")}</p>
        ${p.articulo ? `<details class="mt-1.5">
            <summary class="cursor-pointer text-xs font-medium text-slate-500">
              ${esc(p.norma)} · ${esc(p.articulo)}</summary>
            <p class="mt-1 rounded-lg bg-slate-50 p-2.5 text-xs leading-relaxed text-slate-600">
              ${esc(p.articulo_texto || "")}</p></details>` : ""}
      </div>
      <div class="flex items-center gap-2">
        <input value="${esc(p.valor)}" data-parametro="${esc(p.clave)}" ${esAdmin ? "" : "disabled"}
               class="w-24 rounded-xl border-0 bg-slate-50 px-3 py-2 text-right font-mono ring-1 ring-slate-300
                      focus:bg-white focus:ring-2 focus:ring-slate-900 disabled:opacity-60">
      </div>
    </div>`).join("");

  if (!esAdmin) return;
  $("lista-configuracion").querySelectorAll("[data-parametro]").forEach((campo) => {
    const original = campo.value;
    campo.addEventListener("change", async () => {
      if (campo.value === original) return;
      if (!confirm(`Cambiar «${campo.dataset.parametro}» de ${original} a ${campo.value}?\n` +
                   "Afecta el cálculo de derechos de toda la plantilla.")) {
        campo.value = original;
        return;
      }
      try {
        avisar((await api.cambiarParametro(campo.dataset.parametro, campo.value)).mensaje);
        await cargarConfiguracion();
      } catch (err) {
        campo.value = original;
        avisar(err.message, true);
      }
    });
  });
}

/* ------------------------------------------------------------- bitácora */
async function cargarBitacora() {
  const registros = await api.bitacora(100);
  const termino = ($("filtro-bitacora").value || "").trim().toLowerCase();
  const filtrados = termino
    ? registros.filter((r) => (r.accion + r.quien).toLowerCase().includes(termino))
    : registros;

  $("tabla-bitacora").innerHTML = filtrados.length
    ? `<table class="w-full text-left text-sm">
         <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
           <tr><th class="px-3 py-2.5">Cuándo</th><th class="px-3 py-2.5">Quién</th>
               <th class="px-3 py-2.5">Acción</th><th class="px-3 py-2.5">Sobre</th>
               <th class="px-3 py-2.5">IP</th></tr>
         </thead>
         <tbody class="divide-y divide-slate-100">
           ${filtrados.map((r) => `
             <tr class="hover:bg-slate-50">
               <td class="px-3 py-2.5 whitespace-nowrap text-slate-500">${fechaHora(r.created_at)}</td>
               <td class="px-3 py-2.5">${esc(r.quien)}</td>
               <td class="px-3 py-2.5"><code class="rounded bg-slate-100 px-1.5 py-0.5 text-xs">
                 ${esc(r.accion)}</code></td>
               <td class="px-3 py-2.5 text-slate-600">${esc(r.entidad || "—")}</td>
               <td class="px-3 py-2.5 font-mono text-xs text-slate-400">${esc(r.ip || "—")}</td>
             </tr>`).join("")}
         </tbody>
       </table>`
    : `<p class="px-5 py-10 text-center text-sm text-slate-500">Sin registros.</p>`;
}

$("filtro-bitacora").addEventListener("input", () => cargarBitacora());

/* --------------------------------------------------------------- arranque */
const seccionInicial = location.hash.slice(1);
mostrar(seccionInicial in CARGADORES ? seccionInicial : "usuarios");
