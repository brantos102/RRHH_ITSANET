/* Administración: personal, tipos de solicitud, feriados, parámetros y bitácora. */
import { api, sesion, esc, fecha, fechaHora, validarCedula } from "./api.js";
import { montarNavegacion, ROL_TEXTO } from "./navegacion.js";
import { montarBuscador } from "./buscador.js";

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
  antiguedades: cargarAntiguedades, configuracion: cargarConfiguracion,
  bitacora: cargarBitacora, cotejo: cargarCotejo,
  "cambios-ficha": cargarCambiosFicha, lineamientos: cargarLineamientos,
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

/* Y cuando cambia el fragmento de la dirección.

   Sin esto, los enlaces de la barra lateral —«Lineamientos», «Cambios de
   ficha», «Días no laborables»— solo funcionaban viniendo de otra pantalla.
   Estando ya en administración, el navegador cambiaba el «#» y no recargaba
   nada, así que pulsarlos no hacía absolutamente nada y parecía que esas
   opciones estaban puestas de adorno. */
window.addEventListener("hashchange", () => {
  const seccion = location.hash.slice(1);
  if (seccion && seccion in CARGADORES) mostrar(seccion);
});

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

  // Vacío es «sin tope». Se distingue de cero, que prohibiría el tipo entero.
  const tope = (t, campo, unidad) =>
    `<input type="text" inputmode="decimal" data-tope="${t.id}" data-campo="${campo}"
            value="${t[campo] == null ? "" : dias(t[campo])}" placeholder="sin tope"
            aria-label="Máximo de ${unidad} de ${esc(t.nombre)}"
            class="w-20 rounded-lg border-0 bg-slate-50 px-2 py-1 text-right text-sm tabular-nums
                   ring-1 ring-slate-300 placeholder:text-xs placeholder:text-slate-400
                   focus:bg-white focus:ring-2 focus:ring-slate-900">`;

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
            <td class="px-3 py-2.5 text-right">${tope(t, "max_dias", "días")}</td>
            <td class="px-3 py-2.5 text-right">${tope(t, "max_horas", "horas")}</td>
            <td class="px-3 py-2.5 text-center">${casilla(t, "activo")}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;

  /* Los topes se editan escribiendo encima, no en otro formulario.

     Un tope mal puesto bloquea solicitudes legítimas —«Cita médica» con un
     máximo de 1 día impide pedir dos días de reposo—, y hasta ahora la única
     salida era tocar la base a mano. Se guarda al salir del campo, no en cada
     tecla: escribir «10» pasaría por «1» y guardaría eso primero.

     Vacío significa «sin tope», que es distinto de cero: cero prohibiría el
     tipo entero. */
  $("tabla-tipos").querySelectorAll("input[data-tope]").forEach((campo) => {
    const original = campo.value;
    campo.addEventListener("change", async () => {
      const texto = campo.value.trim().replace(",", ".");
      const valor = texto === "" ? null : Number(texto);
      if (valor !== null && (!Number.isFinite(valor) || valor <= 0)) {
        campo.value = original;
        return avisar("El tope debe ser un número mayor que cero, o quedar vacío "
                      + "si ese tipo no tiene límite.", true);
      }
      try {
        const r = await api.editarTipo(campo.dataset.tope, { [campo.dataset.campo]: valor });
        avisar(r.mensaje);
        await cargarTipos();
      } catch (err) {
        campo.value = original;
        avisar(err.message, true);
      }
    });
  });

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
            <th class="px-3 py-2.5 text-right">Períodos</th></tr>
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
            <td class="px-3 py-2.5 text-right">
              <button type="button" data-periodos="${p.id}" data-nombre="${esc(p.nombre)}"
                      class="rounded-lg px-2.5 py-1 text-xs font-medium text-slate-600
                             ring-1 ring-slate-300 hover:bg-slate-100">Ver</button>
            </td>
          </tr>`).join("")}
      </tbody>
    </table>`;

  $("tabla-antiguedades").querySelectorAll("[data-periodos]").forEach((b) =>
    b.addEventListener("click", () => abrirPeriodos(b.dataset.periodos, b.dataset.nombre)));
}

/* ------------------------------------------- períodos y fines de semana
   El panel del empleado puede decirle «le faltan 2 fines de semana» a quien
   ya los tomó antes de que existiera el sistema, y entonces la regla le
   bloquea unas vacaciones normales por un dato que no refleja la realidad.
   Solo Talento Humano lo corrige, y queda constancia de por qué. */
/* Un período ya gozado por completo no tiene fines de semana que confirmar:
   se fueron con los días. Antes ofrecía «corregir» igual, y eso mandaba a
   Talento Humano a revisar a mano algo que la propia tabla ya respondía. */
const agotado = (p) => Number(p.dias_saldo) <= 0 && Number(p.dias_asignados) > 0;

/* Con coma decimal y sin ceros de relleno: 15 · 8,75 · 1,25. Aquí sí se
   muestran los decimales —es la pantalla de quien lleva la cuenta— y la
   cabecera de cada columna explica de dónde salen. */
const dias = (v) => Number(v || 0).toLocaleString("es-EC",
  { minimumFractionDigits: 0, maximumFractionDigits: 2 });

async function abrirPeriodos(userId, nombre) {
  $("periodos-persona").textContent = nombre;
  $("periodos-cuerpo").innerHTML =
    `<p class="py-6 text-center text-sm text-slate-500">Cargando…</p>`;
  $("modal-periodos").showModal();

  try {
    const periodos = await api.periodosDe(userId);
    $("periodos-cuerpo").innerHTML = periodos.length ? `
      <table class="w-full text-left text-sm">
        <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th class="px-3 py-2" title="Año de servicio contado desde la fecha de ingreso">Año</th>
            <th class="px-3 py-2">Desde</th>
            <th class="px-3 py-2">Hasta</th>
            <th class="px-3 py-2 text-right"
                title="Días que le corresponden por ese año (Art. 69). Del año en curso se acumulan 1,25 por mes.">
              Le tocan</th>
            <th class="px-3 py-2 text-right"
                title="Días de ese año que ya gozó">Gozó</th>
            <th class="px-3 py-2 text-right"
                title="Lo que queda de ese año">Le queda</th>
            <th class="px-3 py-2 text-center"
                title="Fines de semana obligatorios dentro del descanso, consumidos sobre el total">
              Fines de semana</th>
            <th class="px-3 py-2">Estado</th></tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          ${periodos.map((p) => `
            <tr class="${p.caducado ? "opacity-50" : ""}">
              <td class="px-3 py-2 font-medium">${p.periodo}</td>
              <td class="px-3 py-2 whitespace-nowrap text-slate-600">${fecha(p.fecha_desde)}</td>
              <td class="px-3 py-2 whitespace-nowrap text-slate-600">${fecha(p.fecha_hasta)}</td>
              <td class="px-3 py-2 text-right tabular-nums">${dias(p.dias_asignados)}</td>
              <td class="px-3 py-2 text-right tabular-nums text-slate-600">${dias(p.dias_consumidos)}</td>
              <td class="px-3 py-2 text-right font-medium tabular-nums">${dias(p.dias_saldo)}</td>
              <td class="px-3 py-2 text-center">
                ${p.fines_semana_obligatorios ? `
                  <span class="tabular-nums">${p.fines_semana_consumidos}/${p.fines_semana_obligatorios}</span>
                  ${(p.caducado || agotado(p)) ? "" : `
                    <button type="button" data-fds="${p.periodo}"
                            data-user="${userId}" data-tope="${p.fines_semana_obligatorios}"
                            data-actual="${p.fines_semana_consumidos}"
                            class="ml-1.5 rounded px-1.5 py-0.5 text-xs font-medium text-slate-500
                                   ring-1 ring-slate-300 hover:bg-slate-100">corregir</button>`}`
                  : `<span class="text-slate-300">—</span>`}
              </td>
              <td class="px-3 py-2 text-xs">
                ${p.caducado ? '<span class="text-rose-600">caducado</span>'
                  : agotado(p) ? '<span class="text-slate-500">gozado completo</span>'
                  : p.devengado ? '<span class="text-emerald-700">disponible</span>'
                  : '<span class="text-sky-700">en curso</span>'}
              </td>
            </tr>`).join("")}
        </tbody>
      </table>`
      : `<p class="py-6 text-center text-sm text-slate-500">Sin períodos generados.</p>`;

    $("periodos-cuerpo").querySelectorAll("[data-fds]").forEach((b) =>
      b.addEventListener("click", () => corregirFDS(b.dataset)));
  } catch (err) {
    $("periodos-cuerpo").innerHTML =
      `<p class="py-6 text-center text-sm text-rose-700">${esc(err.message)}</p>`;
  }
}

async function corregirFDS({ user, fds, tope, actual }) {
  const valor = prompt(
    `Fines de semana obligatorios ya consumidos en el período ${fds} (de 0 a ${tope}):`,
    actual);
  if (valor === null) return;
  const consumidos = Number(valor);
  if (!Number.isInteger(consumidos) || consumidos < 0 || consumidos > Number(tope)) {
    return avisar(`Debe ser un número entero entre 0 y ${tope}.`, true);
  }

  const motivo = prompt(
    "¿Por qué se corrige? Queda como constancia (mínimo 15 caracteres):",
    "Los tomó antes de que el sistema existiera, según el registro de Talento Humano");
  if (motivo === null) return;
  if (motivo.trim().length < 15) {
    return avisar("Explique la corrección en al menos 15 caracteres.", true);
  }

  try {
    const r = await api.corregirFinesSemana(user, {
      periodo: Number(fds), consumidos, motivo: motivo.trim(),
    });
    avisar(r.mensaje);
    await abrirPeriodos(user, $("periodos-persona").textContent);
  } catch (err) {
    avisar(err.message, true);
  }
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

/* ----------------------------------------------------------- lineamientos

   Lo que el colaborador lee antes de enviar una solicitud. Estaba escrito
   dentro del HTML, que es tanto como decir que para cambiar una coma hacía
   falta un programador. Son reglas internas de la empresa —cuántos días de
   anticipación, si el período se toma entero— y cambian por una circular.

   Se guarda al salir del campo y no con un botón por renglón: con ocho
   lineamientos, ocho botones de guardar es una pantalla de botones. */

const AMBITO = {
  vacacion: ["Vacaciones", "bg-sky-100 text-sky-800 ring-sky-200"],
  permiso:  ["Permisos", "bg-violet-100 text-violet-800 ring-violet-200"],
  ambos:    ["Los dos", "bg-slate-100 text-slate-700 ring-slate-200"],
};

async function cargarLineamientos() {
  const lista = await api.lineamientos();
  $("lista-lineamientos").innerHTML = lista.length ? lista.map((l) => {
    const [texto, clase] = AMBITO[l.ambito] || AMBITO.ambos;
    return `
    <div class="flex flex-wrap items-start gap-3 px-5 py-3" data-lineamiento="${l.id}">
      <span class="mt-1.5 shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${clase}">
        ${texto}
      </span>
      <textarea data-texto rows="1" maxlength="400"
                class="min-w-0 flex-1 resize-none rounded-lg border-0 bg-transparent px-2 py-1.5
                       text-sm ring-1 ring-transparent hover:ring-slate-200
                       focus:bg-white focus:ring-2 focus:ring-slate-900 ${
                         l.activo ? "" : "text-slate-400 line-through"}"
                >${esc(l.texto)}</textarea>
      <label class="mt-1 flex shrink-0 items-center gap-1.5 text-xs text-slate-600">
        <input type="checkbox" data-activo ${l.activo ? "checked" : ""}
               class="rounded border-slate-300">
        Se muestra
      </label>
      ${l.actualizado_por_nombre
        ? `<p class="w-full pl-2 text-xs text-slate-400">Último cambio: ${
             esc(l.actualizado_por_nombre)}</p>` : ""}
    </div>`;
  }).join("") : `<p class="px-5 py-10 text-center text-sm text-slate-500">
                   Sin lineamientos. El recuadro no aparecerá en el formulario.</p>`;

  // Los textos crecen con lo que se escribe: un renglón fijo esconde la
  // mitad de lo que uno acaba de teclear.
  $("lista-lineamientos").querySelectorAll("[data-texto]").forEach((campo) => {
    const ajustar = () => {
      campo.style.height = "auto";
      campo.style.height = `${campo.scrollHeight}px`;
    };
    ajustar();
    campo.addEventListener("input", ajustar);
    campo.addEventListener("change", async () => {
      const id = campo.closest("[data-lineamiento]").dataset.lineamiento;
      const texto = campo.value.trim();
      if (texto.length < 5) {
        avisar("El lineamiento es demasiado corto. Se dejó como estaba.", true);
        return cargarLineamientos();
      }
      try {
        await api.cambiarLineamiento(id, { texto });
        avisar("Guardado.");
      } catch (e) {
        avisar(e.message || "No se pudo guardar.", true);
        cargarLineamientos();
      }
    });
  });

  $("lista-lineamientos").querySelectorAll("[data-activo]").forEach((casilla) =>
    casilla.addEventListener("change", async () => {
      const id = casilla.closest("[data-lineamiento]").dataset.lineamiento;
      try {
        await api.cambiarLineamiento(id, { activo: casilla.checked });
        cargarLineamientos();
      } catch (e) {
        avisar(e.message || "No se pudo guardar.", true);
        cargarLineamientos();
      }
    }));
}

$("btn-nuevo-lineamiento").addEventListener("click", async () => {
  const texto = $("nuevo-lineamiento").value.trim();
  if (texto.length < 5) return avisar("Escriba el lineamiento.", true);
  try {
    await api.crearLineamiento({ texto, ambito: $("nuevo-lineamiento-ambito").value });
    $("nuevo-lineamiento").value = "";
    await cargarLineamientos();
    avisar("Agregado. Ya se ve en el formulario.");
  } catch (e) {
    avisar(e.message || "No se pudo agregar.", true);
  }
});

/* --------------------------------------------------------------- arranque */
const seccionInicial = location.hash.slice(1);
/* --------------------------------------------- cotejo de la carga inicial
   Con trescientas cincuenta personas, revisar la carga dentro del sistema —de
   una en una— no es viable. Aquí se baja la tabla entera para compararla con
   el archivo del que salió. */
async function cargarCotejo() {
  const usuarios = await api.adminUsuarios("");
  const total = usuarios.length;
  const sinCorreo = usuarios.filter((u) => u.correo_pendiente).length;
  const sinJefe = usuarios.filter((u) => !u.jefe_nombre && u.rol === "empleado").length;

  const tarjeta = (etiqueta, valor, pista, alerta = false) => `
    <article class="rounded-xl p-3.5 ring-1 ${alerta && valor > 0
      ? "bg-amber-50 ring-amber-200" : "bg-slate-50 ring-slate-200"}">
      <p class="text-xs uppercase tracking-wide text-slate-500">${etiqueta}</p>
      <p class="mt-1 text-2xl font-semibold tabular-nums">${valor}</p>
      <p class="mt-0.5 text-xs leading-snug text-slate-500">${pista}</p>
    </article>`;

  $("cotejo-resumen").innerHTML =
    tarjeta("Personas activas", total, "cargadas en el sistema") +
    tarjeta("Sin correo real", sinCorreo, "completan su ficha al primer ingreso", true) +
    tarjeta("Sin jefe asignado", sinJefe, "sus solicitudes no avisan a nadie", true) +
    tarjeta("Saldos descuadrados", "—", "se comprueban al bajar el archivo");

  // El departamento se llena con lo que hay, no con una lista fija: así
  // acompaña a la planilla que esté cargada.
  const select = $("cotejo-departamento");
  if (select.options.length <= 1) {
    const areas = [...new Set(usuarios.map((u) => u.departamento).filter(Boolean))].sort();
    select.insertAdjacentHTML("beforeend",
      areas.map((a) => `<option value="${esc(a)}">${esc(a)}</option>`).join(""));
  }
}

async function descargarCotejo(formato) {
  const boton = document.querySelector(`[data-cotejo="${formato}"]`);
  const antes = boton.textContent;
  boton.disabled = true;
  boton.textContent = "…";
  try {
    const parametros = new URLSearchParams();
    if ($("cotejo-solo-revisar").checked) parametros.set("solo_revisar", "true");
    if ($("cotejo-departamento").value) parametros.set("departamento", $("cotejo-departamento").value);

    const respuesta = await fetch(`${api.base}/admin/cotejo.${formato}?${parametros}`,
                                  { headers: { Authorization: `Bearer ${sesion.token}` } });
    if (!respuesta.ok) throw new Error("No se pudo generar el archivo.");

    const cabecera = respuesta.headers.get("content-disposition") || "";
    const nombre = /filename="([^"]+)"/.exec(cabecera)?.[1] || `cotejo.${formato}`;
    const url = URL.createObjectURL(await respuesta.blob());
    Object.assign(document.createElement("a"), { href: url, download: nombre }).click();
    URL.revokeObjectURL(url);
    avisar(`Descargado: ${nombre}`);
  } catch (err) {
    avisar(err.message, true);
  } finally {
    boton.disabled = false;
    boton.textContent = antes;
  }
}

/* --------------------------------------------------------------- búsqueda
   Cada pestaña con su buscador. Filtra sobre lo ya pintado, así que se vuelve
   a aplicar solo cuando la tabla se recarga —sin eso, al recargar reaparecían
   las filas que el usuario acababa de descartar. */
[
  { campo: "buscar-tipo", contenedor: "tabla-tipos", vacio: "tipos-vacio" },
  { campo: "buscar-feriado", contenedor: "tabla-feriados", vacio: "feriados-vacio" },
  { campo: "buscar-antiguedad", contenedor: "tabla-antiguedades", vacio: "antiguedades-vacio" },
  { campo: "buscar-parametro", contenedor: "lista-configuracion",
    filas: ":scope > *", vacio: "parametros-vacio" },
].forEach(montarBuscador);

document.querySelectorAll("[data-cotejo]").forEach((b) =>
  b.addEventListener("click", () => descargarCotejo(b.dataset.cotejo)));

mostrar(seccionInicial in CARGADORES ? seccionInicial : "usuarios");

/* ------------------------------------------------- cambios de ficha
   Lo que un colaborador pidió corregir de su propio expediente. La mayoría
   serán cargos y jefes mal cargados desde el Excel de origen: el sistema no
   puede aplicarlos solo porque de quién depende cada quien decide a dónde va
   su solicitud a autorizarse. */
let cambiosFicha = [];

const sinTildes = (t) =>
  (t || "").toString().normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

function pintarCambiosFicha() {
  const aguja = sinTildes($("cf-buscar").value.trim());
  const visibles = aguja
    ? cambiosFicha.filter((c) => sinTildes(
        `${c.persona} ${c.cedula} ${c.departamento || ""} ${c.etiqueta} ` +
        `${c.anterior_legible || ""} ${c.nuevo_legible}`).includes(aguja))
    : cambiosFicha;

  $("cf-resumen").textContent = cambiosFicha.length
    ? `${cambiosFicha.length} pedido(s) esperando confirmación`
    : "No hay nada por confirmar.";

  $("cf-lista").innerHTML = visibles.length
    ? visibles.map((c) => `
      <article class="px-5 py-4" data-cambio="${c.id}">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="font-medium">${esc(c.persona)}</p>
            <p class="text-xs text-slate-500">
              ${esc(c.cedula)}${c.departamento ? ` · ${esc(c.departamento)}` : ""}
              ${c.ciudad ? ` · ${esc(c.ciudad)}` : ""}
            </p>
          </div>
          <span class="shrink-0 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-medium text-amber-800">
            ${esc(c.etiqueta)}
          </span>
        </div>
        <p class="mt-2 text-sm">
          <span class="text-slate-500">${esc(c.anterior_legible || "sin dato")}</span>
          <span class="mx-1.5">→</span>
          <strong>${esc(c.nuevo_legible)}</strong>
        </p>
        ${c.motivo ? `<p class="mt-1 text-xs text-slate-500">${esc(c.motivo)}</p>` : ""}
        <div class="mt-3 flex flex-wrap gap-2">
          <button data-aprobar="${c.id}"
                  class="rounded-lg bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-800">
            Confirmar
          </button>
          <button data-rechazar="${c.id}"
                  class="rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-medium hover:bg-slate-200">
            Rechazar
          </button>
        </div>
      </article>`).join("")
    : `<p class="px-5 py-10 text-center text-sm text-slate-500">${
         aguja ? "Nada coincide con esa búsqueda." : "No hay cambios por confirmar."}</p>`;

  $("cf-lista").querySelectorAll("[data-aprobar]").forEach((b) =>
    b.addEventListener("click", () => resolverFicha(b.dataset.aprobar, "aprobar")));
  $("cf-lista").querySelectorAll("[data-rechazar]").forEach((b) =>
    b.addEventListener("click", () => resolverFicha(b.dataset.rechazar, "rechazar")));
}

async function resolverFicha(id, accion) {
  let motivo = null;
  if (accion === "rechazar") {
    motivo = prompt("¿Por qué no procede? La persona verá este texto.");
    if (motivo === null) return;
    if (motivo.trim().length < 5) {
      return avisar("Indique por qué se rechaza: la persona debe saber qué corregir.", true);
    }
  }
  try {
    const r = await api.resolverCambioFicha(Number(id), accion, motivo);
    avisar(r.mensaje);
    await cargarCambiosFicha();
  } catch (err) {
    avisar(err.message, true);
  }
}

async function cargarCambiosFicha() {
  // Los nombres los resuelve el servidor: el catálogo de jefaturas excluye a
  // quien lo consulta, así que traducirlos aquí fallaba justo cuando el jefe
  // señalado era la propia persona que estaba revisando.
  cambiosFicha = await api.cambiosFichaPendientes();
  pintarCambiosFicha();
}

$("cf-buscar").addEventListener("input", pintarCambiosFicha);
