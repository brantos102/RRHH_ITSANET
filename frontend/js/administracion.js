/* Administración: personal, tipos de solicitud, feriados, parámetros y bitácora. */
import { api, sesion, esc, fecha, fechaHora, validarCedula, llenarSedes, sedesActivas, olvidarSedes } from "./api.js";
import { montarNavegacion, ROL_TEXTO } from "./navegacion.js";
import { montarBuscador } from "./buscador.js";
import { prepararImpresion } from "./firmante.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");
if (!["rrhh", "admin"].includes(sesion.perfil?.rol)) location.replace("dashboard.html");

montarNavegacion($("barra"), { activo: "admin" });

const esAdmin = sesion.perfil.rol === "admin";
// `jefes` arranca en nulo y no en lista vacía: una lista vacía es un valor
// verdadero, y con ella el catálogo no se pedía la primera vez.
const estado = { usuarios: [], jefes: null, jefaturas: [], candidato: null,
                 talento: [], candidatoTH: null };

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
  bitacora: cargarBitacora, cotejo: cargarCotejo, papeles: cargarPapelesFirmados,
  "cambios-ficha": cargarCambiosFicha, lineamientos: cargarLineamientos,
  jefaturas: cargarJefaturasAdmin, "talento-humano": cargarTalentoHumano,
  depuracion: cargarDepuracion, "ingreso-firmas": cargarIngresoFirmas,
  pendientes: cargarPendientes, asistente: cargarAsistente, sedes: cargarSedes,
  actualizaciones: cargarActualizaciones,
};

// Lo que es solo del administrador no se le ofrece a Talento Humano.
if (!esAdmin) document.querySelectorAll("[data-solo-admin]").forEach((b) => b.remove());

/* El selector del celular se arma con el mismo menú de escritorio: los
   títulos de grupo pasan a ser <optgroup>. Una sola lista que mantener. */
(() => {
  const sel = $("adm-selector");
  if (!sel) return;
  let grupo = null;
  for (const el of $("adm-menu").children) {
    if (el.tagName === "P") {
      grupo = document.createElement("optgroup");
      grupo.label = el.textContent.trim();
      sel.appendChild(grupo);
    } else if (el.dataset.seccion) {
      const o = new Option(el.textContent.trim(), el.dataset.seccion);
      (grupo || sel).appendChild(o);
    }
  }
  sel.addEventListener("change", () => mostrar(sel.value));
})();

function mostrar(seccion) {
  if ($("adm-selector")) $("adm-selector").value = seccion;
  document.querySelectorAll("[data-seccion]").forEach((b) => {
    const activa = b.dataset.seccion === seccion;
    b.className = `shrink-0 rounded-lg px-3 py-1.5 text-left text-sm font-medium ${
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
              <!-- Al expediente: historial de vacaciones, solicitudes y
                   períodos en una pantalla. Desde aquí se administra la
                   ficha; para ver qué ha tomado hay que ir a su expediente. -->
              <a href="persona.html?id=${encodeURIComponent(u.id)}"
                 class="font-medium text-slate-900 underline decoration-slate-300
                        underline-offset-4 hover:decoration-slate-900">${esc(u.nombre)}</a>
              <p class="text-xs text-slate-500">${
                esc(u.email || "sin correo registrado")}</p>
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
              <button data-cerrar-sesiones="${u.id}" data-nombre="${esc(u.nombre)}"
                      title="Para quien perdió o le robaron el celular o la computadora"
                      class="ml-2 text-xs font-medium text-rose-700 hover:underline">Cerrar sesiones</button>
              <button data-activo="${u.id}" data-valor="${u.activo ? 0 : 1}"
                      class="ml-2 text-xs font-medium ${u.activo ? "text-rose-600" : "text-emerald-700"} hover:underline">
                ${u.activo ? "Desactivar" : "Reactivar"}</button>
            </td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

/* La lista de jefes NO sale del resultado de la búsqueda.

   Salía, y por eso al buscar una cédula para editar a esa persona el
   desplegable de «Jefe inmediato» quedaba con una sola opción: «Sin jefe
   asignado». La búsqueda devolvía una fila, esa fila no era jefe, y de ahí
   se sacaba la lista. Cuanto más preciso el filtro, menos jefes había donde
   elegir; buscar por cédula —que es lo que uno hace para editar a alguien—
   los dejaba todos fuera.

   Ahora viene del catálogo, que es una consulta aparte y trae a quien de
   verdad puede serlo: los roles de mando y, además, cualquiera que ya tenga
   gente a cargo aunque figure como empleado. */
async function cargarJefaturas() {
  try {
    estado.jefes = await api.jefaturas();
  } catch {
    estado.jefes = [];
  }
  const opciones = estado.jefes.map((j) => {
    const detalle = [j.cargo, j.departamento].filter(Boolean).join(" · ");
    return `<option value="${j.id}">${esc(j.nombre)}${
      detalle ? ` — ${esc(detalle)}` : ""}${
      j.a_cargo ? ` (${j.a_cargo} a cargo)` : ""}</option>`;
  }).join("");
  $("u-jefe").innerHTML = `<option value="">Sin jefe asignado</option>` + opciones;

  // Si no hay ninguno, decirlo: un desplegable con una sola opción parece
  // roto, y de hecho lo estaba.
  if (!estado.jefes.length) {
    $("u-jefe").innerHTML =
      `<option value="">No hay jefaturas registradas todavía</option>`;
  }
}

async function cargarUsuarios() {
  estado.usuarios = await api.adminUsuarios($("buscar-usuario").value, $("ver-inactivos").checked);
  $("tabla-usuarios").innerHTML = tablaUsuarios(estado.usuarios);
  // El catálogo se pide una vez, no en cada tecla del buscador.
  if (!estado.jefes) await cargarJefaturas();
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
  $("u-ficha-completa").classList.add("hidden");
  delete $("u-region").dataset.original;
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
    cargarCatalogo();
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
    $("u-region").value = u.region || "sierra";
    $("u-region").dataset.original = u.region || "sierra";
    $("u-ficha-completa").href = `persona.html?id=${encodeURIComponent(u.id)}`;
    $("u-ficha-completa").classList.remove("hidden");
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
    // Reactivar es un clic. Dar de baja NO: sin la causa, el expediente
    // queda sin lo primero que se pregunta al revisarlo.
    if (activo.dataset.valor === "1") {
      try {
        avisar((await api.editarUsuario(activo.dataset.activo, { activo: true })).mensaje);
        await cargarUsuarios();
      } catch (err) { avisar(err.message, true); }
    } else {
      abrirBaja(activo.dataset.activo);
    }
  }
});

/* ---------------------------------------------------------------- bajas */
let enBaja = null;
let motivosSalida = null;

async function abrirBaja(id) {
  const persona = estado.usuarios.find((u) => String(u.id) === String(id));
  enBaja = { id, nombre: persona?.nombre || "" };

  $("baja-quien").textContent = persona
    ? `${persona.nombre} · ${persona.cargo || "sin cargo"} · ${persona.departamento || "sin área"}`
    : "";
  $("baja-error").classList.add("hidden");
  $("baja-detalle").value = "";
  $("baja-fecha").value = new Date().toISOString().slice(0, 10);
  $("baja-fecha").max = new Date().toISOString().slice(0, 10);

  if (!motivosSalida) {
    try { motivosSalida = await api.motivosSalida(); }
    catch { motivosSalida = []; }
  }
  $("baja-motivo").innerHTML = `<option value="">Elija la causa…</option>` +
    motivosSalida.map((m) => `<option value="${esc(m.codigo)}">${esc(m.nombre)}${
      m.articulo ? ` · ${esc(m.articulo)}` : ""}</option>`).join("");
  $("baja-ayuda").classList.add("hidden");
  $("modal-baja").showModal();
}

$("baja-motivo").addEventListener("change", () => {
  const elegido = (motivosSalida || []).find((m) => m.codigo === $("baja-motivo").value);
  $("baja-ayuda").textContent = elegido
    ? `${elegido.ayuda}${elegido.articulo ? ` (Código del Trabajo, ${elegido.articulo})` : ""}`
    : "";
  $("baja-ayuda").classList.toggle("hidden", !elegido);
});

$("form-baja").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!enBaja) return;
  try {
    const r = await api.darDeBaja(enBaja.id, {
      fecha_salida: $("baja-fecha").value,
      motivo: $("baja-motivo").value,
      detalle: $("baja-detalle").value.trim() || null,
    });
    $("modal-baja").close();
    /* Lo que queda abierto a su nombre se dice AHORA, no se descubre
       semanas después cuando alguien busca a un jefe que ya no está. */
    const pendiente = [
      r.personas_a_cargo ? `${r.personas_a_cargo} persona(s) le reportaban` : null,
      r.solicitudes_pendientes ? `${r.solicitudes_pendientes} solicitud(es) en trámite` : null,
    ].filter(Boolean);
    avisar(r.mensaje + (pendiente.length ? ` Queda por resolver: ${pendiente.join(" y ")}.` : ""));
    enBaja = null;
    await cargarUsuarios();
  } catch (err) {
    $("baja-error").textContent = err.message;
    $("baja-error").classList.remove("hidden");
  }
});

$("modal-baja").querySelectorAll("[data-cerrar]").forEach((b) =>
  b.addEventListener("click", () => $("modal-baja").close()));

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
    region: $("u-region").value,
  };
  // Al editar, la sede va solo si cambió: cambiarla mueve la ciudad y lo que
  // está en trámite, y no tiene sentido hacerlo por reenviar el mismo valor.
  if (id && datos.region === $("u-region").dataset.original) delete datos.region;

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
    // Si cambió el rol, la lista de jefaturas cambió con él: quien acaba de
    // ser nombrado jefe tiene que poder elegirse en la siguiente edición sin
    // recargar la pantalla.
    estado.jefes = null;
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
          <th class="px-3 py-2.5">Tipo</th><th class="px-3 py-2.5 text-center">Sugiere respaldo</th>
          <th class="px-3 py-2.5 text-center">Justificación</th>
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
  await Promise.all([cargarParametros(), cargarBaseLegal()]);
}

async function cargarParametros() {
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
        await cargarParametros();
      } catch (err) {
        campo.value = original;
        avisar(err.message, true);
      }
    });
  });
}

/* ------------------------------------------------------------ base legal
   Citar la ley es obligación de la empresa; citarla suelta es lo que arma la
   discusión en el mostrador. El Art. 75 leído a secas parece una invitación a
   acumular, y el Art. 76 un derecho a cobrar en lugar de descansar, cuando
   opera sobre la liquidación. De ahí los tres modos.

   Lo que no se ofrece es borrar el artículo de la base: ocultarlo quita la
   constancia de que la empresa informó el derecho, no el derecho. */
const MODOS = {
  completo: "Texto completo de la norma",
  resumen: "Resumen en lenguaje llano",
  oculto: "No se le muestra",
};

async function cargarBaseLegal() {
  const articulos = await api.baseLegal();
  $("lista-base-legal").innerHTML = articulos.map((a) => {
    const mostrado = a.visibilidad === "resumen" ? (a.resumen || "") : a.texto;
    return `
    <div class="px-5 py-4" data-articulo="${esc(a.codigo)}">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0 flex-1">
          <p class="font-medium">${esc(a.articulo)} — ${esc(a.titulo)}
            ${a.sale_en_el_panel
              ? `<span class="ml-1 rounded-full bg-slate-900 px-2 py-0.5 text-xs font-normal text-white">
                   en el panel</span>` : ""}</p>
          <p class="mt-0.5 text-xs text-slate-500">${esc(a.norma)}</p>
        </div>
        <select data-modo="${esc(a.codigo)}" ${esAdmin ? "" : "disabled"}
                class="rounded-xl border-0 bg-slate-50 px-3 py-2 text-sm ring-1 ring-slate-300
                       focus:bg-white focus:ring-2 focus:ring-slate-900 disabled:opacity-60">
          ${Object.entries(MODOS).map(([v, n]) =>
            `<option value="${v}" ${a.visibilidad === v ? "selected" : ""}>${n}</option>`).join("")}
        </select>
      </div>

      <p class="mt-2 rounded-lg bg-slate-50 p-2.5 text-xs leading-relaxed
                ${a.visibilidad === "oculto" ? "text-slate-400 line-through" : "text-slate-600"}">
        ${esc(mostrado || "Sin resumen escrito.")}</p>

      <details class="mt-2" ${a.visibilidad === "resumen" ? "open" : ""}>
        <summary class="cursor-pointer text-xs font-medium text-slate-500">
          Resumen en lenguaje llano</summary>
        <textarea data-resumen="${esc(a.codigo)}" rows="3" maxlength="600"
                  ${esAdmin ? "" : "disabled"}
                  placeholder="Diga el derecho y su límite en una frase. Sin esto no se puede usar el modo resumen."
                  class="mt-1.5 w-full rounded-xl border-0 bg-slate-50 px-3 py-2 text-xs leading-relaxed
                         ring-1 ring-slate-300 focus:bg-white focus:ring-2 focus:ring-slate-900
                         disabled:opacity-60">${esc(a.resumen || "")}</textarea>
      </details>

      ${a.visibilidad_en
        ? `<p class="mt-1.5 text-xs text-slate-400">
             Lo cambió ${esc(a.visibilidad_por || "alguien que ya no está")}
             el ${fechaHora(a.visibilidad_en)}.</p>` : ""}
    </div>`;
  }).join("");

  if (!esAdmin) return;

  // El resumen se guarda al salir del campo, antes de cambiar el modo: así
  // elegir «resumen» no choca con la regla de que el resumen no puede estar
  // vacío.
  $("lista-base-legal").querySelectorAll("[data-resumen]").forEach((campo) => {
    const original = campo.value;
    campo.addEventListener("change", async () => {
      if (campo.value.trim() === original.trim()) return;
      try {
        await api.cambiarArticulo(campo.dataset.resumen, { resumen: campo.value.trim() });
        avisar("Resumen guardado.");
        await cargarBaseLegal();
      } catch (err) {
        campo.value = original;
        avisar(err.message, true);
      }
    });
  });

  $("lista-base-legal").querySelectorAll("[data-modo]").forEach((sel) => {
    const original = sel.value;
    sel.addEventListener("change", async () => {
      const codigo = sel.dataset.modo;
      if (sel.value === "oculto" && !confirm(
            "Ocultarlo no quita el derecho: quita la constancia de que la empresa lo informó.\n\n" +
            "¿Prefiere el modo resumen? Cancele y elíjalo. ¿Ocultar de todos modos?")) {
        sel.value = original;
        return;
      }
      // Si hay un resumen escrito y sin guardar, va primero.
      const texto = $("lista-base-legal")
        .querySelector(`[data-resumen="${codigo}"]`)?.value.trim();
      try {
        const cambio = { visibilidad: sel.value };
        if (texto) cambio.resumen = texto;
        avisar((await api.cambiarArticulo(codigo, cambio)).mensaje);
        await cargarBaseLegal();
      } catch (err) {
        sel.value = original;
        avisar(err.message, true);
      }
    });
  });
}


/* --------------------------------------------------------- papeles firmados
   Lo emitido, quién lo imprimió y cuántas veces. Y el único sitio desde donde
   se autoriza una segunda constancia de goce.

   La reemisión no corrige ni reemplaza a la anterior: la anterior está
   firmada y sigue siendo un documento válido. La nueva nace con su folio y
   con el nombre de quien la autorizó impreso en el pie, que es lo que hace
   falta para poder explicar en una auditoría por qué hay dos. */
const TIPO_PAPEL = {
  trazabilidad: "Constancia de goce",
  solicitud: "Solicitud de vacaciones",
};

async function cargarPapelesFirmados() {
  const tipo = $("filtro-papel-tipo").value;
  const q = ($("buscar-papel").value || "").trim();
  const partes = [];
  if (tipo) partes.push(`tipo=${encodeURIComponent(tipo)}`);
  if (q) partes.push(`q=${encodeURIComponent(q)}`);
  const papeles = await api.papelesDeTodos(partes.length ? `?${partes.join("&")}` : "");

  $("papeles-vacio").classList.toggle("hidden", papeles.length > 0);
  if (!papeles.length) {
    $("papeles-vacio").textContent = q || tipo
      ? "Ningún papel coincide con esa búsqueda."
      : "Todavía no se ha emitido ninguno. Salen solos al pedir vacaciones.";
    $("tabla-papeles").innerHTML = "";
    return;
  }

  $("tabla-papeles").innerHTML = `
    <table class="w-full text-left text-sm">
      <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
        <tr><th class="px-3 py-2.5">Colaborador</th><th class="px-3 py-2.5">Documento</th>
            <th class="px-3 py-2.5">Folio</th><th class="px-3 py-2.5">Emitido</th>
            <th class="px-3 py-2.5">Impresiones</th><th class="px-3 py-2.5"></th></tr>
      </thead>
      <tbody class="divide-y divide-slate-100">
        ${papeles.map((p) => `
          <tr class="hover:bg-slate-50 ${p.es_el_vigente ? "" : "text-slate-400"}">
            <td class="px-3 py-2.5">
              <div class="font-medium">${esc(p.nombre)}</div>
              <div class="text-xs text-slate-500">${esc(p.cedula)}
                ${p.departamento ? " · " + esc(p.departamento) : ""}</div>
            </td>
            <td class="px-3 py-2.5">
              ${esc(TIPO_PAPEL[p.tipo] || p.tipo)}
              ${p.es_reemision
                ? `<div class="text-xs text-amber-700">reemisión · ${esc(p.autorizado_por || "")}</div>
                   <div class="text-xs text-slate-500">${esc(p.autorizacion_motivo || "")}</div>`
                : ""}
              ${p.solicitud_folio ? `<div class="text-xs text-slate-500">solicitud N.º ${esc(p.solicitud_folio)}</div>` : ""}
            </td>
            <td class="px-3 py-2.5 font-mono text-xs">${esc(p.folio)}</td>
            <td class="px-3 py-2.5 whitespace-nowrap text-slate-500">${fechaHora(p.emitido_en)}</td>
            <td class="px-3 py-2.5 tabular-nums">
              ${Number(p.impresiones) || 0}
              ${p.ultima_impresion
                ? `<div class="text-xs text-slate-400">última: ${fechaHora(p.ultima_impresion)}</div>`
                : `<div class="text-xs text-rose-700">sin imprimir</div>`}
            </td>
            <td class="px-3 py-2.5 text-right whitespace-nowrap">
              ${p.firmado_en
                ? `<span class="mr-1 text-xs text-emerald-700">firmado ${fecha(p.firmado_en)}</span>`
                : `<button type="button" data-firmado="${esc(p.id)}" data-folio="${esc(p.folio)}"
                           data-nombre="${esc(p.nombre)}"
                           class="rounded-lg px-2.5 py-1.5 text-xs font-medium text-emerald-700 hover:bg-emerald-50">
                     Registrar firma</button>`}
              ${p.tiene_escaneo
                ? `<button type="button" data-ver-escaneo="${esc(p.id)}" title="SHA-256 ${esc(p.escaneo_sha256 || "")}"
                           class="rounded-lg bg-emerald-50 px-2.5 py-1.5 text-xs font-medium text-emerald-800 ring-1 ring-emerald-200 hover:bg-emerald-100">
                     📎 Ver firmado</button>
                   <button type="button" data-subir-escaneo="${esc(p.id)}" data-folio="${esc(p.folio)}" data-reemplazo="1"
                           class="rounded-lg px-2 py-1.5 text-xs text-slate-500 hover:bg-slate-100">Reemplazar</button>`
                : `<button type="button" data-subir-escaneo="${esc(p.id)}" data-folio="${esc(p.folio)}"
                           class="rounded-lg px-2.5 py-1.5 text-xs font-medium text-sky-700 ring-1 ring-sky-200 hover:bg-sky-50">
                     ⬆ Subir escaneo firmado</button>`}
              <button type="button" data-ver-papel="${esc(p.id)}" data-region="${esc(p.region || "sierra")}"
                      class="rounded-lg px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-200">
                Imprimir</button>
              ${p.tipo === "trazabilidad" && p.es_el_vigente
                ? `<button type="button" data-reemitir="${esc(p.user_id || "")}"
                           data-nombre="${esc(p.nombre)}"
                           class="rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs font-medium text-white">
                     Reemitir</button>`
                : ""}
            </td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

document.addEventListener("click", async (e) => {
  const ver = e.target.closest("[data-ver-papel]");
  if (ver) {
    try {
      const op = await prepararImpresion(ver.dataset.verPapel, ver.dataset.region);
      if (op === null) return;
      await api.abrirPapel(ver.dataset.verPapel, op.firmante, op);
    } catch (err) {
      avisar(err.message, true);
    }
    return;
  }

  const verEscaneo = e.target.closest("[data-ver-escaneo]");
  if (verEscaneo) {
    try {
      const integridad = await api.abrirEscaneo(verEscaneo.dataset.verEscaneo);
      if (integridad && integridad !== "ok") {
        avisar("¡Atención! El archivo no coincide con la huella registrada: pudo ser alterado.", true);
      }
    } catch (err) { avisar(err.message, true); }
    return;
  }

  const subirEscaneo = e.target.closest("[data-subir-escaneo]");
  if (subirEscaneo) {
    let motivo = "";
    if (subirEscaneo.dataset.reemplazo) {
      motivo = prompt(`El documento ${subirEscaneo.dataset.folio} ya tiene escaneo. El anterior se ` +
                      "conserva en el servidor y en la bitácora.\n\n¿Por qué se reemplaza? (mínimo 10 caracteres)") || "";
      if (motivo.trim().length < 10) return avisar("Indique el motivo del reemplazo.", true);
    }
    const entrada = document.createElement("input");
    entrada.type = "file";
    entrada.accept = "application/pdf,image/jpeg,image/png";
    entrada.addEventListener("change", async () => {
      const archivo = entrada.files[0];
      if (!archivo) return;
      if (archivo.size > 15 * 1024 * 1024) return avisar("El escaneo debe pesar menos de 15 MB.", true);
      try {
        avisar((await api.subirEscaneo(subirEscaneo.dataset.subirEscaneo, archivo, motivo.trim())).mensaje);
        cargarPapelesFirmados();
      } catch (err) { avisar(err.message, true); }
    });
    entrada.click();
    return;
  }

  const cortar = e.target.closest("[data-cerrar-sesiones]");
  if (cortar) {
    if (!confirm(`¿Cerrar todas las sesiones abiertas de ${cortar.dataset.nombre}? ` +
                 "Tendrá que volver a ingresar con el código de su correo.")) return;
    try { avisar((await api.cerrarSesionesDe(cortar.dataset.cerrarSesiones)).mensaje); }
    catch (err) { avisar(err.message, true); }
    return;
  }

  const firmado = e.target.closest("[data-firmado]");
  if (firmado) {
    if (!confirm(`¿${firmado.dataset.nombre} ya firmó el documento ${firmado.dataset.folio} ` +
                 "y está en el expediente? Con esto el trámite queda concluido.")) return;
    try {
      avisar((await api.registrarFirma(firmado.dataset.firmado)).mensaje);
      cargarPapelesFirmados();
    } catch (err) {
      avisar(err.message, true);
    }
    return;
  }

  const reemitir = e.target.closest("[data-reemitir]");
  if (!reemitir) return;
  const motivo = prompt(
    `Nueva constancia de goce para ${reemitir.dataset.nombre}.\n\n` +
    "La anterior está firmada y sigue siendo válida; esta nace con su propio " +
    "folio y con su nombre como quien la autorizó.\n\n" +
    "¿Por qué se reemite? (mínimo 15 caracteres)",
    "El colaborador extravió el ejemplar firmado.");
  if (motivo === null) return;
  if (motivo.trim().length < 15) {
    return avisar("Explique el motivo en al menos 15 caracteres.", true);
  }
  try {
    avisar((await api.reemitirTrazabilidad(reemitir.dataset.reemitir, motivo.trim())).mensaje);
    await cargarPapelesFirmados();
  } catch (err) {
    avisar(err.message, true);
  }
});

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

// Esta búsqueda va al servidor y no sobre lo pintado: la consulta trae como
// mucho doscientos papeles, y filtrar solo esos escondería el resto.
let temporizadorPapeles;
["buscar-papel", "filtro-papel-tipo"].forEach((id) =>
  $(id).addEventListener("input", () => {
    clearTimeout(temporizadorPapeles);
    temporizadorPapeles = setTimeout(() => cargarPapelesFirmados(), 300);
  }));

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
  { campo: "buscar-articulo", contenedor: "lista-base-legal",
    filas: ":scope > *", vacio: "articulos-vacio" },
].forEach(montarBuscador);

document.querySelectorAll("[data-cotejo]").forEach((b) =>
  b.addEventListener("click", () => descargarCotejo(b.dataset.cotejo)));

// (El arranque está al final del archivo: así ya existen todas las secciones.)

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

/* --------------------------------------------------------------- depuración

   Después de una carga inicial siempre queda algo que revisar a mano, y
   revisarlo escribiendo SQL contra la planilla real no es razonable como
   rutina. Aquí sale lo mismo que consultan los archivos de
   `supabase/depuracion/`, ordenado por lo que impide trabajar.

   Esta pantalla no corrige nada. Señala, y cada fila lleva al expediente de
   la persona: se corrige por las pantallas de siempre, que dejan constancia
   de quién cambió qué. */

const GRUPOS_DEP = [
  ["cuentas_de_prueba", "Cuentas de prueba", "rose",
   "Correos del dominio itsanet.test, que no existe. Al probar esto sobre la "
   + "planilla real aparecieron pegadas a personas de verdad: no pueden recibir "
   + "su código de acceso, y algunas cargan con roles de mando que nadie les dio."],
  ["sin_entrada", "No pueden entrar", "rose",
   "Sin correo y sin los datos que pide el primer ingreso. No les queda ninguna "
   + "puerta, y la pantalla de acceso no se lo dice."],
  ["jerarquia", "Jerarquía", "amber",
   "Quién reporta a quién, y dónde está roto. Un empleado sin jefe deja sus "
   + "solicitudes sin quien las autorice."],
  ["fichas_incompletas", "Fichas incompletas", "amber",
   "Lo que falta, ordenado por gravedad. Un teléfono en blanco no rompe nada; "
   + "un empleado sin jefe sí."],
  ["historicas_imposibles", "Vacaciones imposibles", "slate",
   "Anotadas antes de la fecha de ingreso de la persona, o con fecha futura. "
   + "Casi siempre es un error de tecleo en la hoja; cada una trae su número de fila."],
];

const TONO_DEP = {
  rose: ["bg-rose-50 ring-rose-200", "text-rose-800"],
  amber: ["bg-amber-50 ring-amber-200", "text-amber-800"],
  slate: ["bg-slate-50 ring-slate-200", "text-slate-700"],
};

function filaDep(clave, f) {
  const alExpediente = (texto) => f.user_id
    ? `<a href="persona.html?id=${encodeURIComponent(f.user_id)}"
          class="font-medium text-slate-900 underline decoration-slate-300
                 underline-offset-4 hover:decoration-slate-900">${esc(texto)}</a>`
    : `<span class="font-medium">${esc(texto)}</span>`;

  if (clave === "cuentas_de_prueba") {
    return `<td class="px-3 py-2.5">${alExpediente(f.nombre)}
              <p class="text-xs text-slate-500">${esc(f.cedula)} · ${esc(f.email || "")}</p></td>
            <td class="px-3 py-2.5"><span class="rounded-full bg-slate-900 px-2 py-0.5 text-xs
                font-medium text-white">${esc(f.rol)}</span></td>
            <td class="px-3 py-2.5 text-right tabular-nums">${f.a_cargo}</td>
            <td class="px-3 py-2.5 text-right tabular-nums">${f.solicitudes} · ${f.historicas}</td>
            <td class="px-3 py-2.5 text-sm text-slate-600">${esc(f.que_hacer)}</td>`;
  }
  if (clave === "historicas_imposibles") {
    return `<td class="px-3 py-2.5">${alExpediente(f.nombre)}
              <p class="text-xs text-slate-500">ingresó el ${fecha(f.fecha_ingreso)}</p></td>
            <td class="px-3 py-2.5 whitespace-nowrap">${fecha(f.fecha_inicio)} — ${fecha(f.fecha_fin)}</td>
            <td class="px-3 py-2.5 text-right tabular-nums">${f.dias}</td>
            <td class="px-3 py-2.5 text-right tabular-nums text-slate-500">${f.fila_origen ?? "—"}</td>
            <td class="px-3 py-2.5 text-sm text-slate-600">${esc(f.problema)}</td>`;
  }
  if (clave === "jerarquia") {
    return `<td class="px-3 py-2.5">${alExpediente(f.nombre)}
              <p class="text-xs text-slate-500">${esc(f.cargo || "")} · ${esc(f.departamento || "")}</p></td>
            <td class="px-3 py-2.5">${esc(f.rol)}</td>
            <td class="px-3 py-2.5">${esc(f.jefe_nombre || "—")}</td>
            <td class="px-3 py-2.5 text-right tabular-nums">${f.a_cargo}</td>
            <td class="px-3 py-2.5 text-sm text-slate-600">${esc(f.problema)}</td>`;
  }
  if (clave === "sin_entrada") {
    return `<td class="px-3 py-2.5"><span class="font-medium">${esc(f.nombre)}</span>
              <p class="text-xs text-slate-500">${esc(f.cedula)}</p></td>
            <td class="px-3 py-2.5">${esc(f.departamento || "—")}</td>
            <td class="px-3 py-2.5 text-sm text-slate-600">${esc(f.motivo)}</td>
            <td class="px-3 py-2.5 text-sm text-slate-600">${esc(f.que_hacer)}</td>`;
  }
  // fichas_incompletas
  const falta = [
    f.sin_jefe && "jefe", f.sin_correo && "correo", f.sin_cargo && "cargo",
    f.sin_departamento && "departamento", f.sin_nacimiento && "nacimiento",
    f.sin_telefono && "teléfono",
  ].filter(Boolean).join(", ");
  return `<td class="px-3 py-2.5">${alExpediente(f.nombre)}
            <p class="text-xs text-slate-500">${esc(f.cedula)}</p></td>
          <td class="px-3 py-2.5">${esc(f.departamento || "—")}</td>
          <td class="px-3 py-2.5 text-right tabular-nums">${f.huecos}</td>
          <td class="px-3 py-2.5 text-sm text-slate-600">${esc(falta)}</td>
          <td class="px-3 py-2.5 text-sm text-slate-600">${esc(f.lo_principal)}</td>`;
}

const CABECERAS_DEP = {
  cuentas_de_prueba: ["Persona", "Rol", "A cargo", "Solicitudes · históricas", "Qué hacer"],
  sin_entrada: ["Persona", "Departamento", "Motivo", "Qué hacer"],
  jerarquia: ["Persona", "Rol", "Jefe", "A cargo", "Problema"],
  fichas_incompletas: ["Persona", "Departamento", "Huecos", "Qué falta", "Lo principal"],
  historicas_imposibles: ["Persona", "Fechas", "Días", "Fila de la hoja", "Problema"],
};

async function cargarDepuracion() {
  const d = await api.depuracion();

  $("dep-resumen").innerHTML = GRUPOS_DEP.map(([clave, titulo, tono]) => {
    const n = d.resumen[clave] || 0;
    const [fondo, tinta] = n ? TONO_DEP[tono] : TONO_DEP.slate;
    return `<article class="rounded-2xl p-4 ring-1 ${fondo}">
      <p class="text-2xl font-semibold tabular-nums ${n ? tinta : "text-slate-400"}">${n}</p>
      <p class="mt-0.5 text-xs leading-snug text-slate-600">${esc(titulo)}</p>
    </article>`;
  }).join("");

  $("dep-detalle").innerHTML = GRUPOS_DEP.map(([clave, titulo, , explicacion]) => {
    const filas = d[clave] || [];
    if (!filas.length) {
      return `<section class="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
        <h2 class="font-medium">${esc(titulo)}</h2>
        <p class="mt-1 text-sm text-emerald-700">Nada que revisar aquí.</p>
      </section>`;
    }
    return `<section class="rounded-2xl bg-white shadow-sm ring-1 ring-slate-200">
      <header class="border-b border-slate-200 px-5 py-3.5">
        <h2 class="font-medium">${esc(titulo)} <span class="text-slate-400">(${filas.length})</span></h2>
        <p class="mt-0.5 text-sm leading-relaxed text-slate-600">${esc(explicacion)}</p>
      </header>
      <div class="overflow-x-auto">
        <table class="w-full text-left text-sm">
          <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"><tr>
            ${CABECERAS_DEP[clave].map((c) => `<th class="px-3 py-2.5">${c}</th>`).join("")}
          </tr></thead>
          <tbody class="divide-y divide-slate-100">
            ${filas.slice(0, 100).map((f) => `<tr class="hover:bg-slate-50">${filaDep(clave, f)}</tr>`).join("")}
          </tbody>
        </table>
      </div>
      ${filas.length > 100
        ? `<p class="border-t border-slate-100 px-5 py-2.5 text-xs text-slate-500">
             Se muestran las primeras 100 de ${filas.length}.</p>` : ""}
    </section>`;
  }).join("");
}


/* ------------------------------------------------------------- jefaturas
   Nombrar a alguien jefatura es un cambio de rol, y eso ya se podía hacer
   desde Usuarios. Quitárselo no: la gente que le reporta sigue apuntándole
   en su ficha, así que pide permiso y el pedido no le llega a nadie. Nada
   en la pantalla lo advertía. Aquí la baja empieza por la pregunta que
   hay que contestar: a quién pasan. */

function filaJefatura(j) {
  const propio = String(j.id) === String(sesion.perfil.id);
  const alerta = !j.puede_entrar
    ? `<span class="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700
                    ring-1 ring-amber-200">no puede entrar</span>` : "";
  return `<tr class="border-t border-slate-100 hover:bg-slate-50">
    <td class="px-5 py-2.5">
      <a href="persona.html?id=${esc(j.id)}" class="font-medium hover:underline">${esc(j.nombre)}</a>${alerta}
      ${j.reporta_a ? `<div class="text-xs text-slate-500">reporta a ${esc(j.reporta_a)}</div>` : ""}
    </td>
    <td class="px-3 py-2.5 text-slate-600" data-area-de="${esc(j.id)}">
      <button type="button" data-editar-area="${esc(j.id)}" data-area="${esc(j.departamento || "")}"
              title="Cambiar el área"
              class="rounded-lg px-1.5 py-0.5 text-left hover:bg-slate-100 ${j.departamento ? "" : "text-sky-700 underline"}">
        ${j.departamento ? esc(j.departamento) : "Asignar área"}</button>
    </td>
    <td class="px-3 py-2.5 text-slate-600">${esc(ROL_TEXTO[j.rol] || j.rol)}</td>
    <td class="px-3 py-2.5 text-right font-medium">${j.a_cargo}</td>
    <td class="px-3 py-2.5 text-right ${j.esperando ? "font-medium text-amber-700" : "text-slate-500"}">
      ${j.esperando}</td>
    <td class="px-3 py-2.5 text-right">
      ${propio
        ? `<span class="text-xs text-slate-400">es usted</span>`
        : `<button type="button" data-quitar-jefatura="${esc(j.id)}"
                   class="rounded-lg px-2.5 py-1.5 text-sm text-rose-700 hover:bg-rose-50">
             Quitar</button>`}
    </td>
  </tr>`;
}

function pintarJefaturas() {
  const filtro = ($("jef-filtro").value || "").trim().toLowerCase();
  const lista = filtro
    ? estado.jefaturas.filter((j) =>
        `${j.nombre} ${j.departamento || ""} ${j.cargo || ""}`.toLowerCase().includes(filtro))
    : estado.jefaturas;

  const gente = estado.jefaturas.reduce((s, j) => s + j.a_cargo, 0);
  const sinGente = estado.jefaturas.filter((j) => !j.a_cargo).length;
  $("jef-cuantas").textContent =
    `${estado.jefaturas.length} jefatura(s) para ${gente} persona(s)` +
    (sinGente ? ` · ${sinGente} sin nadie a cargo` : "");

  $("jef-tabla").innerHTML = lista.length
    ? lista.map(filaJefatura).join("")
    : `<tr><td colspan="6" class="px-5 py-10 text-center text-sm text-slate-500">
         Nadie coincide con el filtro.</td></tr>`;

  $("jef-tabla").querySelectorAll("[data-quitar-jefatura]").forEach((b) =>
    b.addEventListener("click", () => abrirBajaJefatura(b.dataset.quitarJefatura)));
  $("jef-tabla").querySelectorAll("[data-editar-area]").forEach((b) =>
    b.addEventListener("click", () => editarAreaJefatura(b)));
}

/* El área de una jefatura, editada en la misma fila: con sugerencias de las
   áreas que ya existen, para escribirlas siempre igual. */
function editarAreaJefatura(boton) {
  cargarCatalogo();
  const celda = boton.closest("td");
  const id = boton.dataset.editarArea;
  celda.innerHTML = `
    <form class="flex items-center gap-1" data-form-area>
      <input list="lista-areas" maxlength="80" value="${esc(boton.dataset.area)}" autocomplete="off"
             class="w-40 rounded-lg border-0 bg-white px-2 py-1 text-sm ring-1 ring-slate-300 focus:ring-2 focus:ring-slate-900">
      <button class="rounded-lg bg-slate-900 px-2 py-1 text-xs font-medium text-white">Guardar</button>
      <button type="button" data-cancelar class="rounded-lg px-2 py-1 text-xs text-slate-500 hover:bg-slate-100">✕</button>
    </form>`;
  const entrada = celda.querySelector("input");
  entrada.focus();
  celda.querySelector("[data-cancelar]").addEventListener("click", () => pintarJefaturas());
  celda.querySelector("[data-form-area]").addEventListener("submit", async (e) => {
    e.preventDefault();
    const area = entrada.value.trim().replace(/\s+/g, " ");
    if (!area) return avisar("Escriba el área.", true);
    try {
      await api.editarUsuario(id, { departamento: area });
      const j = estado.jefaturas.find((x) => String(x.id) === String(id));
      if (j) j.departamento = area;
      estado.catalogoCargado = false;          // por si es un área nueva
      avisar(`Área guardada: ${area}.`);
      pintarJefaturas();
      pintarJefesDelEquipo();
    } catch (err) { avisar(err.message, true); }
  });
}

/* Las áreas y cargos que ya existen, como sugerencias: «Operaciones» y
   «operaciones » serían dos áreas distintas para los informes. */
async function cargarCatalogo() {
  // En `estado` y no en un `let` propio: la pestaña puede cargarse antes de
  // que el módulo llegue a esta línea, y un `let` todavía no existiría.
  if (estado.catalogoCargado) return;
  try {
    const c = await api.catalogoCargos();
    $("lista-areas").innerHTML = c.areas.map((a) => `<option value="${esc(a)}">`).join("");
    $("lista-cargos").innerHTML = [...new Set(c.cargos.map((x) => x.cargo))]
      .map((x) => `<option value="${esc(x)}">`).join("");
    estado.catalogoCargado = true;
  } catch { /* sin sugerencias se escribe igual */ }
}

async function cargarJefaturasAdmin() {
  cargarCatalogo();
  estado.jefaturas = await api.adminJefaturas();
  pintarJefaturas();
  pintarJefesDelEquipo();
}

/* ---- asignar equipo en bloque ---- */
const equipo = { gente: [], marcados: new Set() };

function pintarJefesDelEquipo() {
  const actual = $("eq-jefe").value;
  $("eq-jefe").innerHTML = '<option value="">Elija la jefatura…</option>' + estado.jefaturas.map((j) =>
    `<option value="${esc(j.id)}">${esc(j.nombre)}${j.departamento ? " · " + esc(j.departamento) : ""} (${j.a_cargo})</option>`).join("");
  if (actual) $("eq-jefe").value = actual;
  actualizarBotonEquipo();
}

function actualizarBotonEquipo() {
  const n = equipo.marcados.size;
  $("eq-asignar").disabled = !n || !$("eq-jefe").value;
  $("eq-asignar").textContent = n ? `Asignar ${n} persona(s)` : "Asignar";
  $("eq-cuantos").textContent = equipo.gente.length ? `${equipo.gente.length} mostrada(s)` : "";
}

function pintarEquipo() {
  const jefe = $("eq-jefe").value;
  const visibles = equipo.gente.filter((u) => String(u.id) !== jefe
    && (!$("eq-sin-jefe").checked || !u.jefe_id));
  $("eq-lista").innerHTML = visibles.map((u) => `
    <li><label class="flex items-start gap-2 px-3 py-2 text-sm hover:bg-slate-50">
      <input type="checkbox" data-eq="${esc(u.id)}" ${equipo.marcados.has(String(u.id)) ? "checked" : ""} class="mt-0.5 h-4 w-4">
      <span class="min-w-0 flex-1"><b>${esc(u.nombre)}</b>
        <span class="block text-xs text-slate-500">${esc([u.cargo, u.departamento].filter(Boolean).join(" · ") || "—")}
          · jefe actual: ${u.jefe_nombre ? esc(u.jefe_nombre) : '<span class="text-rose-700">sin jefe</span>'}</span></span>
    </label></li>`).join("");
  $("eq-lista").querySelectorAll("[data-eq]").forEach((c) => c.addEventListener("change", () => {
    c.checked ? equipo.marcados.add(c.dataset.eq) : equipo.marcados.delete(c.dataset.eq);
    actualizarBotonEquipo();
  }));
  equipo.visibles = visibles;
  actualizarBotonEquipo();
}

let temporizadorEquipo;
async function buscarEquipo() {
  try {
    equipo.gente = await api.adminUsuarios($("eq-buscar").value.trim(), false);
    pintarEquipo();
  } catch (err) { avisar(err.message, true); }
}
$("eq-buscar").addEventListener("input", () => {
  clearTimeout(temporizadorEquipo);
  temporizadorEquipo = setTimeout(buscarEquipo, 300);
});
$("eq-sin-jefe").addEventListener("change", () => (equipo.gente.length ? pintarEquipo() : buscarEquipo()));
$("eq-jefe").addEventListener("change", () => (equipo.gente.length ? pintarEquipo() : actualizarBotonEquipo()));
$("eq-todos").addEventListener("click", () => {
  (equipo.visibles || []).forEach((u) => equipo.marcados.add(String(u.id)));
  pintarEquipo();
});
$("eq-ninguno").addEventListener("click", () => { equipo.marcados.clear(); pintarEquipo(); });
$("eq-asignar").addEventListener("click", async () => {
  const jefe = $("eq-jefe").selectedOptions[0]?.textContent || "";
  const area = $("eq-area").value.trim();
  if (!confirm(`¿Asignar ${equipo.marcados.size} persona(s) a ${jefe}?` +
               (area ? `\nY dejarlas en el área «${area}».` : ""))) return;
  try {
    avisar((await api.asignarEquipo($("eq-jefe").value, [...equipo.marcados],
                                    area || null, $("eq-area-jefe").checked)).mensaje);
    equipo.marcados.clear();
    await cargarJefaturasAdmin();
    await buscarEquipo();
  } catch (err) { avisar(err.message, true); }
});

$("jef-filtro").addEventListener("input", () => {
  if (estado.jefaturas.length) pintarJefaturas();
});

/* Nombrar: se busca entre quienes todavía no tienen mando. */
let temporizadorJef;
$("jef-buscar").addEventListener("input", () => {
  clearTimeout(temporizadorJef);
  estado.candidato = null;
  $("jef-nombrar").disabled = true;
  const texto = $("jef-buscar").value.trim();
  if (texto.length < 3) { $("jef-candidatos").innerHTML = ""; return; }
  temporizadorJef = setTimeout(async () => {
    try {
      const gente = await api.adminUsuarios(texto, false);
      const conMando = new Set(estado.jefaturas.map((j) => String(j.id)));
      const libres = gente.filter((u) => !conMando.has(String(u.id))).slice(0, 8);
      $("jef-candidatos").innerHTML = libres.length
        ? libres.map((u) => `
            <li><button type="button" data-candidato="${esc(u.id)}" data-nombre="${esc(u.nombre)}"
                        class="w-full rounded-xl px-3 py-2 text-left text-sm hover:bg-slate-100">
              <span class="font-medium">${esc(u.nombre)}</span>
              <span class="text-slate-500"> · ${esc(u.cargo || "sin cargo")}
                · ${esc(u.departamento || "sin área")}</span>
            </button></li>`).join("")
        : `<li class="px-3 py-2 text-sm text-slate-500">
             Nadie más coincide; quien ya tiene mando no aparece aquí.</li>`;
      $("jef-candidatos").querySelectorAll("[data-candidato]").forEach((b) =>
        b.addEventListener("click", () => {
          estado.candidato = { id: b.dataset.candidato, nombre: b.dataset.nombre };
          $("jef-buscar").value = b.dataset.nombre;
          $("jef-candidatos").innerHTML = "";
          $("jef-nombrar").disabled = false;
        }));
    } catch (err) { avisar(err.message, true); }
  }, 300);
});

$("jef-nombrar").addEventListener("click", async () => {
  if (!estado.candidato) return;
  try {
    const r = await api.crearJefatura(estado.candidato.id);
    avisar(r.mensaje);
    $("jef-buscar").value = "";
    $("jef-nombrar").disabled = true;
    estado.candidato = null;
    estado.jefes = null;            // el catálogo de la ficha cambió con esto
    await cargarJefaturasAdmin();
  } catch (err) { avisar(err.message, true); }
});

/* Quitar: el diálogo se abre ya sabiendo cuánta gente hay que trasladar. */
let jefaturaEnBaja = null;

function abrirBajaJefatura(id) {
  const j = estado.jefaturas.find((x) => String(x.id) === String(id));
  if (!j) return;
  jefaturaEnBaja = j;

  $("jef-quien").textContent = `${j.nombre} · ${j.departamento || "sin área"}`;
  $("jef-error").classList.add("hidden");

  const hayGente = j.a_cargo > 0 || j.esperando > 0;
  $("jef-aviso").textContent = hayGente
    ? `Tiene ${j.a_cargo} persona(s) a cargo y ${j.esperando} solicitud(es) esperando su autorización. ` +
      "Todo eso pasa a la jefatura que elija, en un solo movimiento."
    : "No tiene gente a cargo ni solicitudes esperando. Se le quita el mando y nada más se mueve.";
  $("jef-aviso").className = hayGente
    ? "rounded-xl bg-amber-50 p-3 text-sm leading-relaxed text-amber-900 ring-1 ring-amber-200"
    : "rounded-xl bg-slate-50 p-3 text-sm leading-relaxed text-slate-600";

  $("jef-destino-caja").classList.toggle("hidden", j.a_cargo === 0);
  $("jef-destino").innerHTML = estado.jefaturas
    .filter((x) => String(x.id) !== String(j.id))
    .map((x) => `<option value="${esc(x.id)}">${esc(x.nombre)}${
      x.departamento ? ` · ${esc(x.departamento)}` : ""} (${x.a_cargo} a cargo)</option>`)
    .join("");
  $("jef-rol").value = j.rol === "rrhh" || j.rol === "admin" ? "rrhh" : "empleado";
  $("modal-jefatura").showModal();
}

$("form-jefatura").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!jefaturaEnBaja) return;
  try {
    const r = await api.quitarJefatura(jefaturaEnBaja.id, {
      nuevo_jefe_id: jefaturaEnBaja.a_cargo > 0 ? $("jef-destino").value : null,
      rol_destino: $("jef-rol").value,
    });
    $("modal-jefatura").close();
    avisar(r.mensaje);
    jefaturaEnBaja = null;
    estado.jefes = null;
    await cargarJefaturasAdmin();
  } catch (err) {
    $("jef-error").textContent = err.message;
    $("jef-error").classList.remove("hidden");
  }
});

$("modal-jefatura").querySelectorAll("[data-cerrar]").forEach((b) =>
  b.addEventListener("click", () => $("modal-jefatura").close()));


/* ------------------------------------------------------- Talento Humano
   El rol dice qué puede hacer alguien; esto dice a quién le llega el
   trabajo. La baja importa tanto como el alta: quien deja el departamento
   y conserva el rol sigue viendo los expedientes de toda su región, y ese
   es el permiso que nadie revisa hasta que hay un problema. */

const REGION_TEXTO = { sierra: "Sierra · Quito", costa: "Costa · Guayaquil" };

function filaTalento(p) {
  const propio = String(p.id) === String(sesion.perfil.id);
  const alerta = !p.puede_recibir
    ? `<span class="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700
                    ring-1 ring-amber-200">no recibe avisos</span>` : "";
  return `<tr class="border-t border-slate-100 hover:bg-slate-50">
    <td class="px-5 py-2.5">
      <a href="persona.html?id=${esc(p.id)}" class="font-medium hover:underline">${esc(p.nombre)}</a>${alerta}
      ${p.cargo ? `<div class="text-xs text-slate-500">${esc(p.cargo)}</div>` : ""}
    </td>
    <td class="px-3 py-2.5 text-slate-600">${esc(REGION_TEXTO[p.region] || p.region)}</td>
    <td class="px-3 py-2.5 text-slate-600">${esc(ROL_TEXTO[p.rol] || p.rol)}</td>
    <td class="px-3 py-2.5 text-right ${p.esperando_en_su_region ? "font-medium text-amber-700" : "text-slate-500"}">
      ${p.esperando_en_su_region}</td>
    <td class="px-3 py-2.5 text-right">
      ${propio
        ? `<span class="text-xs text-slate-400">es usted</span>`
        : `<button type="button" data-retirar-th="${esc(p.id)}" data-nombre="${esc(p.nombre)}"
                   class="rounded-lg px-2.5 py-1.5 text-sm text-rose-700 hover:bg-rose-50">
             Retirar</button>`}
    </td>
  </tr>`;
}

async function cargarTalentoHumano() {
  const datos = await api.talentoHumano();
  estado.talento = datos.integrantes;
  $("correo-rrhh-sierra").value = datos.correos.sierra || "";
  $("correo-rrhh-costa").value = datos.correos.costa || "";

  const porRegion = (r) => estado.talento.filter((p) => p.region === r).length;
  const sinCorreo = estado.talento.filter((p) => !p.puede_recibir).length;
  $("th-cuantos").textContent =
    `${estado.talento.length} persona(s) · ${porRegion("sierra")} en la Sierra, ` +
    `${porRegion("costa")} en la Costa` +
    (sinCorreo ? ` · ${sinCorreo} sin correo que reciba avisos` : "");

  $("th-tabla").innerHTML = estado.talento.length
    ? estado.talento.map(filaTalento).join("")
    : `<tr><td colspan="5" class="px-5 py-10 text-center text-sm text-slate-500">
         Nadie integra el departamento todavía.</td></tr>`;

  $("th-tabla").querySelectorAll("[data-retirar-th]").forEach((b) =>
    b.addEventListener("click", () => retirarDeTalento(b.dataset.retirarTh, b.dataset.nombre)));
}

$("form-correos-rrhh").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await api.correosTalentoHumano({
      sierra: $("correo-rrhh-sierra").value.trim(),
      costa: $("correo-rrhh-costa").value.trim(),
    });
    avisar(r.mensaje);
  } catch (err) { avisar(err.message, true); }
});

let temporizadorTH;
$("th-buscar").addEventListener("input", () => {
  clearTimeout(temporizadorTH);
  estado.candidatoTH = null;
  $("th-integrar").disabled = true;
  const texto = $("th-buscar").value.trim();
  if (texto.length < 3) { $("th-candidatos").innerHTML = ""; return; }
  temporizadorTH = setTimeout(async () => {
    try {
      const gente = await api.adminUsuarios(texto, false);
      const dentro = new Set(estado.talento.map((p) => String(p.id)));
      const fuera = gente.filter((u) => !dentro.has(String(u.id))).slice(0, 8);
      $("th-candidatos").innerHTML = fuera.length
        ? fuera.map((u) => `
            <li><button type="button" data-candidato-th="${esc(u.id)}" data-nombre="${esc(u.nombre)}"
                        class="w-full rounded-xl px-3 py-2 text-left text-sm hover:bg-slate-100">
              <span class="font-medium">${esc(u.nombre)}</span>
              <span class="text-slate-500"> · ${esc(u.cargo || "sin cargo")}
                · ${esc(u.departamento || "sin área")}</span>
            </button></li>`).join("")
        : `<li class="px-3 py-2 text-sm text-slate-500">
             Nadie más coincide; quien ya lo integra no aparece aquí.</li>`;
      $("th-candidatos").querySelectorAll("[data-candidato-th]").forEach((b) =>
        b.addEventListener("click", () => {
          estado.candidatoTH = { id: b.dataset.candidatoTh, nombre: b.dataset.nombre };
          $("th-buscar").value = b.dataset.nombre;
          $("th-candidatos").innerHTML = "";
          $("th-integrar").disabled = false;
        }));
    } catch (err) { avisar(err.message, true); }
  }, 300);
});

$("th-integrar").addEventListener("click", async () => {
  if (!estado.candidatoTH) return;
  try {
    const r = await api.integrarTalentoHumano(estado.candidatoTH.id, $("th-region").value);
    avisar(r.mensaje);
    $("th-buscar").value = "";
    $("th-integrar").disabled = true;
    estado.candidatoTH = null;
    await cargarTalentoHumano();
  } catch (err) { avisar(err.message, true); }
});

async function retirarDeTalento(id, nombre) {
  if (!confirm(`¿Retirar a ${nombre} de Talento Humano?\n\n` +
               "Dejará de ver las fichas y las solicitudes de su región. " +
               "Su cuenta y sus datos no se tocan.")) return;
  try {
    const r = await api.retirarTalentoHumano(id, "empleado");
    avisar(r.mensaje);
    await cargarTalentoHumano();
  } catch (err) { avisar(err.message, true); }
}


/* ------------------------------------------------- primer ingreso y firmas */
async function cargarIngresoFirmas() {
  const [cfg, fir] = await Promise.all([api.ingresoConfig(), api.firmantes()]);
  const c = cfg.cobertura;
  const tarjeta = (titulo, n, pct, nota = "") => `
    <div class="rounded-xl bg-slate-50 p-3">
      <p class="text-xs text-slate-500">${titulo}</p>
      <p class="text-xl font-semibold tabular-nums">${pct}%</p>
      <p class="text-xs text-slate-500">${n} de ${c.activos} activos${nota}</p>
    </div>`;
  $("ing-cobertura").innerHTML =
    tarjeta("Con fecha de nacimiento", c.con_nacimiento, c.pct_nacimiento,
            c.pct_nacimiento >= 90 ? " · ya puede pasar a verificar con ella" : "") +
    tarjeta("Con correo confirmado", c.con_correo, c.pct_correo) +
    tarjeta("Fecha de ingreso confirmada", c.ingreso_confirmado, c.pct_ingreso_confirmado);
  document.querySelectorAll('input[name="ing-modo"]').forEach((r) => { r.checked = r.value === cfg.modo; });
  $("ing-campos").innerHTML = cfg.disponibles.map((d) => `
    <label class="flex items-center gap-2"><input type="checkbox" data-ing-campo="${esc(d.campo)}"
      ${cfg.campos.includes(d.campo) ? "checked" : ""} class="h-4 w-4"> ${esc(d.etiqueta)}</label>`).join("");

  $("fir-persona").innerHTML = fir.candidatos.length
    ? fir.candidatos.map((p) => `<option value="${esc(p.id)}" data-region="${esc(p.region)}">${
        esc([p.nombre, p.cargo].filter(Boolean).join(" · "))}</option>`).join("")
    : '<option value="">Nadie con rol de Talento Humano</option>';
  $("fir-lista").innerHTML = fir.sedes.map((s) => {
    const de = fir.firmantes.filter((f) => f.region === s.region);
    return `<div>
      <h3 class="text-xs font-medium uppercase tracking-wide text-slate-500">${esc(s.sede)}</h3>
      ${de.length ? `<ul class="mt-1 divide-y divide-slate-100 rounded-xl ring-1 ring-slate-200">${de.map((f) => `
        <li class="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
          <span class="min-w-0 flex-1"><b>${esc(f.nombre)}</b> · ${esc(f.firma_como)}
            ${f.principal ? '<span class="ml-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">cabeza del departamento</span>' : ""}</span>
          ${f.principal ? "" : `<button type="button" data-fir-principal="${f.id}"
             class="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium hover:bg-slate-200">Hacer cabeza</button>`}
          <button type="button" data-fir-quitar="${f.id}"
             class="rounded-lg px-2.5 py-1 text-xs font-medium text-rose-700 hover:bg-rose-50">Quitar</button>
        </li>`).join("")}</ul>`
        : '<p class="mt-1 text-sm text-slate-500">Nadie asignado: el documento sale con la firma de Talento Humano en blanco.</p>'}
    </div>`;
  }).join("");
  $("fir-lista").querySelectorAll("[data-fir-principal]").forEach((b) => b.addEventListener("click", async () => {
    try { avisar((await api.cambiarFirmante(b.dataset.firPrincipal, { principal: true })).mensaje); cargarIngresoFirmas(); }
    catch (err) { avisar(err.message, true); }
  }));
  $("fir-lista").querySelectorAll("[data-fir-quitar]").forEach((b) => b.addEventListener("click", async () => {
    try { avisar((await api.quitarFirmante(b.dataset.firQuitar)).mensaje); cargarIngresoFirmas(); }
    catch (err) { avisar(err.message, true); }
  }));
}

$("fir-persona")?.addEventListener("change", (e) => {
  const region = e.target.selectedOptions[0]?.dataset.region;
  if (region) $("fir-region").value = region;
});

$("form-ingreso")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const modo = document.querySelector('input[name="ing-modo"]:checked')?.value;
  const campos = [...document.querySelectorAll("[data-ing-campo]:checked")].map((c) => c.dataset.ingCampo);
  try {
    avisar((await api.guardarIngresoConfig({ modo, campos })).mensaje);
    cargarIngresoFirmas();
  } catch (err) { avisar(err.message, true); }
});

$("form-firmante")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!$("fir-persona").value) return avisar("Elija a la persona.", true);
  try {
    avisar((await api.agregarFirmante({
      user_id: $("fir-persona").value, region: $("fir-region").value,
      cargo_firma: $("fir-cargo").value.trim() || null, principal: $("fir-principal").checked,
    })).mensaje);
    $("fir-cargo").value = ""; $("fir-principal").checked = false;
    cargarIngresoFirmas();
  } catch (err) { avisar(err.message, true); }
});


/* ------------------------------------------------------ pendientes por sede */
const TIPO_PENDIENTE = {
  solicitud: ["Solicitudes", "bg-sky-50 text-sky-800"],
  cambio_ficha: ["Cambios de ficha", "bg-violet-50 text-violet-800"],
  chat: ["Consultas del chat", "bg-emerald-50 text-emerald-800"],
  firma: ["Por firmar", "bg-amber-50 text-amber-800"],
};
let ultimoPendientes = [];
let sedePendientes = (() => { try { return localStorage.getItem("rrhh_sede_pend") || "mia"; } catch { return "mia"; } })();

function hace(minutos) {
  if (minutos == null) return "";
  if (minutos < 1) return "ahora";
  if (minutos < 60) return `hace ${minutos} min`;
  return `hace ${Math.floor(minutos / 60)} h`;
}

/* Los botones de sede salen del catálogo: una sede nueva aparece sola. */
let botonesSedeListos = false;
async function botonesSedePendientes() {
  if (botonesSedeListos) return;
  botonesSedeListos = true;
  const sedes = await sedesActivas();
  $("pen-sedes").innerHTML = [["mia", "Mi sede"], ...sedes.map((x) => [x.codigo, x.sede]), ["todas", "Todas"]]
    .map(([c, t]) => `<button data-sede="${esc(c)}" class="rounded-lg px-3 py-1.5 font-medium">${esc(t)}</button>`)
    .join("");
}

async function cargarPendientes() {
  await botonesSedePendientes();
  document.querySelectorAll("#pen-sedes [data-sede]").forEach((b) => {
    b.className = `rounded-lg px-3 py-1.5 font-medium ${b.dataset.sede === sedePendientes
      ? "bg-white text-slate-900 shadow-sm" : "text-slate-600 hover:text-slate-900"}`;
  });
  const d = await api.pendientesRRHH(sedePendientes);
  ultimoPendientes = d.items;
  $("pen-conteo").innerHTML = Object.entries(TIPO_PENDIENTE).map(([t, [nombre, tono]]) => `
    <div class="rounded-xl p-3 ${tono}">
      <p class="text-xs">${nombre}</p>
      <p class="text-2xl font-semibold tabular-nums">${d.conteo[t] || 0}</p>
    </div>`).join("");
  $("pen-lista").innerHTML = d.items.length ? d.items.map((i) => {
    const [nombre, tono] = TIPO_PENDIENTE[i.tipo];
    const a = i.atencion;
    const estadoAt = !a
      ? '<span class="text-xs text-slate-500">Sin tomar</span>'
      : a.propio
        ? `<span class="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-medium text-emerald-800">Lo revisa usted</span>`
        : `<span class="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">En revisión por ${esc(a.por)} ${hace(a.minutos)}</span>`;
    const boton = i.tipo === "chat" ? "" : !a
      ? `<button data-tomar="${esc(i.tipo)}|${esc(i.id)}" class="rounded-lg bg-slate-900 px-2.5 py-1 text-xs font-medium text-white">Tomar</button>`
      : a.propio
        ? `<button data-soltar="${esc(i.tipo)}|${esc(i.id)}" class="rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium">Soltar</button>`
        : `<button data-tomar="${esc(i.tipo)}|${esc(i.id)}" data-forzar="1" data-de="${esc(a.por)}" class="rounded-lg px-2.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100">Tomarlo yo</button>`;
    return `<li class="flex flex-wrap items-center gap-3 px-5 py-3">
      <span class="rounded-md px-2 py-0.5 text-xs font-medium ${tono}">${nombre}</span>
      <div class="min-w-0 flex-1">
        <p class="text-sm font-medium">${esc(i.persona)} <span class="text-xs font-normal text-slate-500">· ${esc(i.sede)} · ${fechaHora(i.desde)}</span></p>
        <p class="truncate text-sm text-slate-600">${esc(i.detalle)}</p>
      </div>
      ${estadoAt} ${boton}
      <button data-atender="${esc(i.tipo)}|${esc(i.id)}" class="rounded-lg bg-sky-600 px-2.5 py-1 text-xs font-medium text-white hover:bg-sky-700">Atender</button>
    </li>`;
  }).join("") : '<li class="px-5 py-10 text-center text-sm text-slate-500">Nada pendiente en esta sede. 🎉</li>';
  $("pen-hoy").innerHTML = d.atendidos_hoy.length ? d.atendidos_hoy.map((a) => `
    <li class="flex flex-wrap gap-2 py-2"><span class="text-slate-500">${fechaHora(a.cuando)}</span>
      <b>${esc(a.persona)}</b> · ${esc(a.detalle)} · <span class="text-slate-500">${esc(a.sede)}</span>
      <span class="ml-auto text-emerald-700">por ${esc(a.por || "—")}</span></li>`).join("")
    : '<li class="py-3 text-slate-500">Todavía nada hoy.</li>';
}

$("pen-sedes").addEventListener("click", (e) => {
  const b = e.target.closest("[data-sede]");
  if (!b) return;
  sedePendientes = b.dataset.sede;
  try { localStorage.setItem("rrhh_sede_pend", sedePendientes); } catch { /* sin preferencia */ }
  cargarPendientes().catch((err) => avisar(err.message, true));
});

$("pen-lista").addEventListener("click", async (e) => {
  const atender = e.target.closest("[data-atender]");
  if (atender) {
    const [tipo, id] = atender.dataset.atender.split("|");
    const item = ultimoPendientes.find((x) => x.tipo === tipo && String(x.id) === id);
    if (item) abrirAtender(item);
    return;
  }
  const tomar = e.target.closest("[data-tomar]"), soltar = e.target.closest("[data-soltar]");
  if (!tomar && !soltar) return;
  const [tipo, id] = (tomar || soltar).dataset[tomar ? "tomar" : "soltar"].split("|");
  try {
    if (tomar?.dataset.forzar && !confirm(`${tomar.dataset.de} lo está revisando. ¿Tomarlo usted?`)) return;
    const r = tomar ? await api.tomarPendiente(tipo, id, !!tomar.dataset.forzar)
                    : await api.soltarPendiente(tipo, id);
    avisar(r.mensaje);
  } catch (err) { avisar(err.message, true); }
  cargarPendientes().catch(() => {});
});

// Con la pantalla abierta, lo que toman los demás se ve sin recargar.
setInterval(() => {
  if (location.hash === "#pendientes" && !document.hidden) cargarPendientes().catch(() => {});
}, 30000);

/* ----------------------------------------------------------------- asistente */
let respuestasAsistente = [];

function limpiarAsistente() {
  $("form-asis").reset();
  $("asis-id").value = "";
  $("asis-activo").checked = true;
}

async function cargarAsistente() {
  const d = await api.asistenteAdmin();
  respuestasAsistente = d.respuestas;
  $("asis-lista").innerHTML = d.respuestas.length ? d.respuestas.map((r) => `
    <li class="flex flex-wrap items-start gap-2 px-3 py-2.5 text-sm ${r.activo ? "" : "opacity-50"}">
      <div class="min-w-0 flex-1"><b>${esc(r.titulo)}</b>
        <span class="block text-xs text-slate-500">${esc(r.palabras_clave)}</span>
        <span class="block text-slate-700">${esc(r.respuesta)}</span></div>
      <button data-asis-editar="${r.id}" class="rounded-lg px-2 py-1 text-xs font-medium hover:bg-slate-100">Editar</button>
      <button data-asis-borrar="${r.id}" class="rounded-lg px-2 py-1 text-xs font-medium text-rose-700 hover:bg-rose-50">Quitar</button>
    </li>`).join("") : '<li class="px-3 py-3 text-sm text-slate-500">Todavía no hay respuestas propias.</li>';
  $("asis-sin").innerHTML = d.sin_respuesta.length ? d.sin_respuesta.map((x) => `
    <li><button data-asis-desde="${esc(x.texto)}" class="flex w-full gap-2 py-2 text-left hover:bg-slate-50">
      <span class="min-w-0 flex-1">${esc(x.texto)}</span><span class="text-slate-500">${x.veces} vez/veces</span></button></li>`).join("")
    : '<li class="py-3 text-slate-500">Nada por ahora.</li>';
  const NOMBRE_TEMA = { saldo: "Saldo", solicitudes: "Estado de solicitudes", pedir_vacaciones: "Cómo pedir vacaciones",
    permisos: "Permisos", jefe: "Jefe", documentos: "Documentos", feriados: "Feriados", garita: "Garita y QR",
    mis_datos: "Mis datos", dispositivos: "Sesiones", talento_humano: "Hablar con TH", sin_respuesta: "Sin respuesta" };
  $("asis-temas").innerHTML = d.temas.length ? d.temas.map((t) => `
    <li class="flex py-1.5"><span class="flex-1">${esc(NOMBRE_TEMA[t.tema] || (t.tema.startsWith("rrhh:") ? "Respuesta propia" : t.tema))}</span>
      <b class="tabular-nums">${t.veces}</b></li>`).join("") : '<li class="py-3 text-slate-500">Sin consultas todavía.</li>';
}

$("asis-nueva").addEventListener("click", limpiarAsistente);
$("form-asis").addEventListener("submit", async (e) => {
  e.preventDefault();
  const datos = {
    titulo: $("asis-titulo").value.trim(), palabras_clave: $("asis-claves").value.trim(),
    respuesta: $("asis-respuesta").value.trim(), enlace_texto: $("asis-enlace-texto").value.trim() || null,
    enlace_url: $("asis-enlace").value.trim() || null, activo: $("asis-activo").checked,
  };
  try {
    const id = $("asis-id").value;
    avisar((id ? await api.asistenteCambiar(id, datos) : await api.asistenteCrear(datos)).mensaje);
    limpiarAsistente();
    cargarAsistente();
  } catch (err) { avisar(err.message, true); }
});
document.addEventListener("click", async (e) => {
  const ed = e.target.closest("[data-asis-editar]");
  if (ed) {
    const r = respuestasAsistente.find((x) => String(x.id) === ed.dataset.asisEditar);
    if (!r) return;
    $("asis-id").value = r.id; $("asis-titulo").value = r.titulo; $("asis-claves").value = r.palabras_clave;
    $("asis-respuesta").value = r.respuesta; $("asis-enlace-texto").value = r.enlace_texto || "";
    $("asis-enlace").value = r.enlace_url || ""; $("asis-activo").checked = r.activo;
    $("form-asis").scrollIntoView({ behavior: "smooth", block: "center" });
    return;
  }
  const bo = e.target.closest("[data-asis-borrar]");
  if (bo) {
    if (!confirm("¿Quitar esta respuesta del asistente?")) return;
    try { avisar((await api.asistenteBorrar(bo.dataset.asisBorrar)).mensaje); cargarAsistente(); }
    catch (err) { avisar(err.message, true); }
    return;
  }
  const desde = e.target.closest("[data-asis-desde]");
  if (desde) {
    limpiarAsistente();
    $("asis-claves").value = desde.dataset.asisDesde;
    $("asis-titulo").focus();
    $("form-asis").scrollIntoView({ behavior: "smooth", block: "center" });
  }
});


/* ---------------------------------------------------------------- atender
   Resolver cada pendiente aquí mismo, sin ir a otra pantalla ni buscarlo:
   desde la lista o directo desde la campana (…?atender=persona:<id>).
   Al abrirlo se toma —los demás lo ven «en revisión»— y al resolverlo
   desaparece de la lista de todos. */
const CLASE_BTN = "rounded-xl px-4 py-2 text-sm font-medium";

function dialogoAtender(titulo, subtitulo) {
  document.getElementById("modal-atender")?.remove();
  const d = document.createElement("dialog");
  d.id = "modal-atender";
  d.className = "w-[min(100vw-1.5rem,40rem)] rounded-2xl p-0";
  d.innerHTML = `
    <div class="flex items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
      <div><h2 class="font-semibold">${esc(titulo)}</h2>
        <p class="mt-0.5 text-sm text-slate-500">${esc(subtitulo || "")}</p></div>
      <button type="button" data-cerrar-atender class="rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-100">✕</button>
    </div>
    <div data-cuerpo class="max-h-[65vh] space-y-3 overflow-y-auto px-5 py-4 text-sm"></div>
    <p data-msg class="hidden px-5 pb-3 text-sm"></p>`;
  document.body.appendChild(d);
  d.querySelector("[data-cerrar-atender]").addEventListener("click", () => d.close());
  d.addEventListener("close", () => { d.remove(); cargarPendientes().catch(() => {}); });
  d.showModal();
  const msg = (t, error = false) => {
    const p = d.querySelector("[data-msg]");
    p.textContent = t;
    p.className = `px-5 pb-3 text-sm ${error ? "text-rose-700" : "text-emerald-700"}`;
  };
  return { d, cuerpo: d.querySelector("[data-cuerpo]"), msg };
}

async function tomarAlAbrir(tipo, id, msg) {
  if (tipo === "chat" || tipo === "persona") return;
  try { await api.tomarPendiente(tipo, id); }
  catch (err) { msg(`${err.message} Puede seguir, pero coordínelo para no duplicar.`, true); }
}

async function abrirAtender(item) {
  if (item.tipo === "cambio_ficha") return atenderCambios(item.persona_id, item.persona);
  if (item.tipo === "solicitud") return atenderSolicitud(item);
  if (item.tipo === "chat") return atenderChat(item);
  if (item.tipo === "firma") return atenderFirma(item);
}

async function atenderCambios(personaId, nombre = "") {
  const v = dialogoAtender("Cambios de ficha por revisar", nombre);
  async function pintar() {
    const todos = await api.cambiosFichaPendientes();
    const suyos = todos.filter((c) => String(c.user_id) === String(personaId));
    if (!suyos.length) {
      v.cuerpo.innerHTML = '<p class="text-emerald-700">No quedan pedidos pendientes de esta persona.</p>';
      return;
    }
    if (!nombre) v.d.querySelector("h2 + p").textContent = suyos[0].persona;
    v.cuerpo.innerHTML = suyos.map((c) => `
      <article class="rounded-xl p-3 ring-1 ring-slate-200">
        <p class="font-medium">${esc(c.etiqueta)}</p>
        <p class="mt-1"><span class="text-slate-500 line-through">${esc(c.anterior_legible || "—")}</span>
          → <b>${esc(c.nuevo_legible || c.valor_nuevo)}</b></p>
        ${c.motivo ? `<p class="mt-1 text-xs text-slate-500">${esc(c.motivo)}</p>` : ""}
        ${c.campo === "jefe_por_registrar" ? `<p class="mt-1 text-xs text-amber-800">
          Primero nombre a esa persona en <a class="underline" href="#jefaturas" data-cerrar-y-ir>Jefaturas</a>
          y asígnela; luego márquelo como atendido.</p>` : ""}
        <div class="mt-2 flex gap-2">
          <button data-rechazar-cambio="${c.id}" class="${CLASE_BTN} bg-white text-rose-700 ring-1 ring-rose-200 hover:bg-rose-50">Rechazar</button>
          <button data-aprobar-cambio="${c.id}" class="${CLASE_BTN} bg-emerald-600 text-white hover:bg-emerald-700">
            ${c.campo === "jefe_por_registrar" ? "Marcar atendido" : "Aprobar"}</button>
        </div>
      </article>`).join("");
  }
  v.cuerpo.addEventListener("click", async (e) => {
    if (e.target.closest("[data-cerrar-y-ir]")) { v.d.close(); return; }
    const ap = e.target.closest("[data-aprobar-cambio]"), re = e.target.closest("[data-rechazar-cambio]");
    if (!ap && !re) return;
    let motivo = null;
    if (re) {
      motivo = prompt("¿Por qué se rechaza? La persona lo verá para corregirlo.");
      if (motivo === null) return;
      if (motivo.trim().length < 5) return v.msg("Explique el motivo (mínimo 5 caracteres).", true);
    }
    try {
      await api.resolverCambioFicha((ap || re).dataset[ap ? "aprobarCambio" : "rechazarCambio"],
                                    ap ? "aprobar" : "rechazar", motivo);
      v.msg(ap ? "Aprobado: el dato ya rige." : "Rechazado: se le avisó a la persona.");
      await pintar();
    } catch (err) { v.msg(err.message, true); }
  });
  await pintar().catch((err) => v.msg(err.message, true));
}

async function atenderSolicitud(item) {
  const v = dialogoAtender("Solicitud por decidir", item.persona);
  await tomarAlAbrir("solicitud", item.id, v.msg);
  let s;
  try { s = (await api.pendientes()).find((x) => String(x.id) === String(item.id)); }
  catch (err) { return v.msg(err.message, true); }
  if (!s) { v.cuerpo.innerHTML = '<p class="text-emerald-700">Esta solicitud ya fue resuelta.</p>'; return; }
  v.cuerpo.innerHTML = `
    <dl class="grid grid-cols-2 gap-x-4 gap-y-2">
      <div><dt class="text-xs text-slate-500">Nº</dt><dd class="font-medium">${esc(s.folio)}</dd></div>
      <div><dt class="text-xs text-slate-500">Tipo</dt><dd class="font-medium">${s.tipo === "vacacion" ? "Vacaciones" : esc(s.categoria || "Permiso")}</dd></div>
      <div><dt class="text-xs text-slate-500">Fechas</dt><dd class="font-medium">${fecha(s.fecha_inicio)} al ${fecha(s.fecha_fin)}</dd></div>
      <div><dt class="text-xs text-slate-500">Días</dt><dd class="font-medium">${esc(s.dias_solicitados)}</dd></div>
      <div><dt class="text-xs text-slate-500">Saldo actual</dt><dd class="font-medium">${esc(s.saldo_actual)} días</dd></div>
      <div><dt class="text-xs text-slate-500">Lo cubre</dt><dd class="font-medium">${esc(s.reemplazo || "Sin reemplazo")}</dd></div>
      <div class="col-span-2"><dt class="text-xs text-slate-500">Jefe</dt><dd>${esc(s.jefe_nombre || "Sin jefe: decide Talento Humano")}</dd></div>
    </dl>
    <p class="rounded-xl bg-slate-50 p-3">${esc(s.descripcion || "")}</p>
    ${s.es_adelanto ? '<p class="text-amber-800">Supera su saldo: días adelantados.</p>' : ""}
    <div class="flex flex-wrap gap-2 pt-1">
      ${s.tipo === "vacacion" ? `<button data-docs class="${CLASE_BTN} bg-slate-100 hover:bg-slate-200">📄 Documentos</button>` : ""}
      <a href="dashboard.html#aprobaciones" class="${CLASE_BTN} bg-slate-100 hover:bg-slate-200">Asignar reemplazo…</a>
      <span class="flex-1"></span>
      <button data-rechazar class="${CLASE_BTN} bg-white text-rose-700 ring-1 ring-rose-200 hover:bg-rose-50">Rechazar</button>
      <button data-aprobar class="${CLASE_BTN} bg-emerald-600 text-white hover:bg-emerald-700">Aprobar</button>
    </div>`;
  v.cuerpo.addEventListener("click", async (e) => {
    try {
      if (e.target.closest("[data-docs]")) {
        const papel = await api.papelDeLaSolicitud(s.id);
        const op = await prepararImpresion(papel.id, s.region || item.region);
        if (op !== null) await api.abrirPapel(papel.id, op.firmante, op);
      } else if (e.target.closest("[data-aprobar]")) {
        const r = await api.decidir(s.id, "aprobar");
        v.cuerpo.innerHTML = `<p class="text-emerald-700">${esc(r.mensaje)}</p>`;
      } else if (e.target.closest("[data-rechazar]")) {
        const motivo = prompt("¿Por qué se rechaza? El colaborador lo verá.");
        if (motivo === null) return;
        if (motivo.trim().length < 5) return v.msg("Explique el motivo.", true);
        const r = await api.decidir(s.id, "rechazar", motivo.trim());
        v.cuerpo.innerHTML = `<p class="text-emerald-700">${esc(r.mensaje)}</p>`;
      }
    } catch (err) { v.msg(err.message, true); }
  });
}

async function atenderChat(item) {
  const v = dialogoAtender("Consulta del chat", `${item.persona} · ${item.sede}`);
  async function pintar() {
    const h = await api.leerConversacion(item.id);
    v.cuerpo.innerHTML = `
      <div class="space-y-2">${(h.mensajes || []).slice(-15).map((m) => `
        <div class="max-w-[85%] rounded-2xl px-3 py-2 ${m.es_rrhh
          ? "ml-auto bg-slate-900 text-white" : "bg-slate-100"}">
          <p class="whitespace-pre-line">${esc(m.texto)}</p>
          <p class="mt-0.5 text-[11px] opacity-60">${esc(m.autor || "")} · ${fechaHora(m.created_at)}</p>
        </div>`).join("")}</div>
      <form data-responder class="flex gap-2 pt-2">
        <textarea rows="2" maxlength="2000" required placeholder="Responder…"
                  class="flex-1 rounded-xl border-0 bg-slate-50 px-3 py-2 text-sm ring-1 ring-slate-300 focus:bg-white focus:ring-2 focus:ring-slate-900"></textarea>
        <button class="${CLASE_BTN} bg-slate-900 text-white hover:bg-slate-800">Enviar</button>
      </form>
      <button data-resuelta class="text-xs font-medium text-slate-500 hover:text-slate-900">Dar por resuelta</button>`;
    v.cuerpo.scrollTop = v.cuerpo.scrollHeight;
  }
  v.cuerpo.addEventListener("submit", async (e) => {
    e.preventDefault();
    const t = e.target.querySelector("textarea").value.trim();
    if (!t) return;
    try { await api.enviarMensaje({ conversacion_id: item.id, texto: t }); await pintar(); v.msg("Respuesta enviada; se le avisó por correo."); }
    catch (err) { v.msg(err.message, true); }
  });
  v.cuerpo.addEventListener("click", async (e) => {
    if (!e.target.closest("[data-resuelta]")) return;
    try { await api.cerrarConversacion(item.id); v.cuerpo.innerHTML = '<p class="text-emerald-700">Consulta resuelta.</p>'; }
    catch (err) { v.msg(err.message, true); }
  });
  await pintar().catch((err) => v.msg(err.message, true));
}

async function atenderFirma(item) {
  const v = dialogoAtender("Documento por firmar", item.persona);
  await tomarAlAbrir("firma", item.id, v.msg);
  v.cuerpo.innerHTML = `
    <p>${esc(item.detalle)}</p>
    <ol class="list-decimal space-y-1 pl-5 text-slate-600">
      <li>Imprímalo (elija la fecha y quién firma por Talento Humano).</li>
      <li>Hágalo firmar por el colaborador y archive el original en su expediente físico.</li>
      <li><b>El mismo día</b>, escanéelo y súbalo: con eso el registro de vacaciones queda concluido.</li>
    </ol>
    <div class="flex flex-wrap gap-2">
      <button data-imprimir class="${CLASE_BTN} bg-slate-100 hover:bg-slate-200">🖨️ Imprimir</button>
      <button data-escaneo class="${CLASE_BTN} bg-emerald-600 text-white hover:bg-emerald-700">⬆ Subir escaneo firmado</button>
      <button data-firmado class="${CLASE_BTN} bg-white text-slate-700 ring-1 ring-slate-300 hover:bg-slate-50">Solo registrar la firma (escaneo después)</button>
    </div>`;
  v.cuerpo.addEventListener("click", async (e) => {
    try {
      if (e.target.closest("[data-imprimir]")) {
        const op = await prepararImpresion(item.id, item.region);
        if (op !== null) await api.abrirPapel(item.id, op.firmante, op);
      } else if (e.target.closest("[data-escaneo]")) {
        const entrada = Object.assign(document.createElement("input"),
          { type: "file", accept: "application/pdf,image/jpeg,image/png" });
        entrada.addEventListener("change", async () => {
          const archivo = entrada.files[0];
          if (!archivo) return;
          try {
            const r = await api.subirEscaneo(item.id, archivo);
            v.cuerpo.innerHTML = `<p class="text-emerald-700">${esc(r.mensaje)} El registro de vacaciones quedó concluido.</p>`;
          } catch (err) { v.msg(err.message, true); }
        });
        entrada.click();
      } else if (e.target.closest("[data-firmado]")) {
        if (!confirm(`¿${item.persona} ya firmó y el original está en su expediente? ` +
                     "El pendiente sigue abierto hasta subir el escaneo.")) return;
        const r = await api.registrarFirma(item.id);
        v.cuerpo.insertAdjacentHTML("beforeend",
          `<p class="text-emerald-700">${esc(r.mensaje)} Falta subir el escaneo.</p>`);
      }
    } catch (err) { v.msg(err.message, true); }
  });
}

/* Desde la campana: administracion.html?atender=persona:<id> o tipo:<id>. */
(() => {
  const pedido = new URLSearchParams(location.search).get("atender");
  if (!pedido) return;
  const [tipo, id] = pedido.split(":");
  history.replaceState(null, "", `administracion.html${location.hash}`);
  if (tipo === "persona") return void atenderCambios(id);
  setTimeout(async () => {
    try {
      const d = await api.pendientesRRHH("todas");
      const item = d.items.find((x) => x.tipo === tipo && String(x.id) === id);
      if (item) abrirAtender(item); else avisar("Ese pendiente ya fue atendido.");
    } catch (err) { avisar(err.message, true); }
  }, 300);
})();

/* ---------------------------------------------------------- actualizaciones */
/* Markdown mínimo y seguro: se escapa todo primero y después se dan formato
   títulos, listas, tablas, código y negritas. Nada del archivo se ejecuta. */
function markdown(texto) {
  const lineas = esc(texto).split("\n");
  const html = [];
  let enCodigo = false, lista = null, tabla = [];
  const enLinea = (t) => t.replace(/`([^`]+)`/g, '<code class="rounded bg-slate-100 px-1 text-[0.85em]">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/«([^»]+)»/g, "«$1»");
  const cerrar = () => {
    if (lista) { html.push(`</${lista}>`); lista = null; }
    if (tabla.length) {
      const filas = tabla.filter((f) => !/^\|\s*-/.test(f)).map((f) => f.replace(/^\||\|$/g, "").split("|"));
      html.push(`<div class="my-2 overflow-x-auto"><table class="w-full text-left text-xs">${filas.map((f, i) =>
        `<tr class="${i ? "border-t border-slate-100" : "bg-slate-50 font-medium"}">${f.map((c) =>
          `<td class="px-2 py-1">${enLinea(c.trim())}</td>`).join("")}</tr>`).join("")}</table></div>`);
      tabla = [];
    }
  };
  for (const l of lineas) {
    if (l.startsWith("```")) {
      cerrar();
      html.push(enCodigo ? "</pre>" : '<pre class="my-2 overflow-x-auto rounded-xl bg-slate-900 p-3 font-mono text-xs text-slate-100">');
      enCodigo = !enCodigo;
      continue;
    }
    if (enCodigo) { html.push(l + "\n"); continue; }
    if (/^\|/.test(l)) { tabla.push(l); continue; }
    // La continuación de un punto de la lista (línea con sangría) va en el mismo punto.
    if (lista && /^\s{2,}\S/.test(l) && !/^\s*(?:[-*]|\d+\.) /.test(l) && html[html.length - 1].endsWith("</li>")) {
      html[html.length - 1] = html[html.length - 1].replace(/<\/li>$/, ` ${enLinea(l.trim())}</li>`);
      continue;
    }
    const t = l.match(/^(#{1,4}) (.*)/);
    const li = l.match(/^\s*(?:[-*]|\d+\.) (.*)/);
    if (t) { cerrar(); html.push(`<h${t[1].length + 2} class="mt-4 font-semibold text-slate-900">${enLinea(t[2])}</h${t[1].length + 2}>`); }
    else if (li) {
      const tipo = /^\s*\d+\./.test(l) ? "ol" : "ul";
      if (lista !== tipo) { cerrar(); lista = tipo; html.push(`<${tipo} class="${tipo === "ol" ? "list-decimal" : "list-disc"} my-1 space-y-0.5 pl-5">`); }
      html.push(`<li>${enLinea(li[1])}</li>`);
    } else if (!l.trim()) cerrar();
    else { if (lista) cerrar(); html.push(`<p class="my-1.5">${enLinea(l)}</p>`); }
  }
  cerrar();
  if (enCodigo) html.push("</pre>");
  return html.join("");
}

let notaActual = null;
async function cargarActualizaciones() {
  const d = await api.actualizaciones();
  const faltan = d.migraciones.faltan;
  $("act-estado").innerHTML = `
    <div class="rounded-xl bg-slate-50 p-3"><p class="text-xs text-slate-500">Versión instalada</p>
      <p class="font-mono text-lg font-semibold">${esc(d.version.commit || "—")}</p>
      <p class="text-xs text-slate-500">${esc(d.version.rama || "")}</p></div>
    <div class="rounded-xl p-3 ${faltan.length ? "bg-amber-50 ring-1 ring-amber-300" : "bg-emerald-50"}">
      <p class="text-xs text-slate-500">Base de datos</p>
      <p class="text-lg font-semibold">${d.migraciones.aplicadas} de ${d.migraciones.disponibles} migraciones</p>
      <p class="text-xs ${faltan.length ? "text-amber-800" : "text-emerald-800"}">${faltan.length
        ? `Faltan: ${faltan.map(esc).join(", ")}` : "Al día"}</p></div>
    <div class="rounded-xl bg-slate-50 p-3"><p class="text-xs text-slate-500">Notas de actualización</p>
      <p class="text-lg font-semibold">${d.notas.length}</p>
      <p class="text-xs text-slate-500">${d.notas[0] ? `La última: ${esc(d.notas[0].fecha)}` : ""}</p></div>`;
  $("act-comando").textContent = d.comando;
  $("act-notas").innerHTML = d.notas.map((n, i) => `
    <li><button type="button" data-nota="${esc(n.archivo)}"
        class="w-full rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-100">
        <span class="block text-xs text-slate-500">${esc(n.fecha)}${i === 0 ? " · la más reciente" : ""}</span>
        ${esc(n.titulo)}</button></li>`).join("") || '<li class="px-3 py-2 text-sm text-slate-500">Sin notas.</li>';
  if (d.notas[0]) abrirNota(d.notas[0].archivo);
}

async function abrirNota(archivo) {
  notaActual = archivo;
  document.querySelectorAll("[data-nota]").forEach((b) => b.classList.toggle("bg-slate-100", b.dataset.nota === archivo));
  const texto = await api.notaActualizacion(archivo);
  $("act-titulo").textContent = (texto.match(/^# (.*)$/m) || [, archivo])[1];
  $("act-texto").innerHTML = markdown(texto.replace(/^# .*\n/, ""));
  $("act-descargar").classList.remove("hidden");
}

$("act-notas")?.addEventListener("click", (e) => {
  const b = e.target.closest("[data-nota]");
  if (b) abrirNota(b.dataset.nota).catch((err) => avisar(err.message, true));
});
$("act-descargar")?.addEventListener("click", () =>
  api.descargarNota(notaActual).catch((err) => avisar(err.message, true)));
$("act-copiar")?.addEventListener("click", async () => {
  // El portapapeles solo existe por HTTPS: por http en la red interna no
  // está, y se dice en vez de fallar callado.
  if (!window.isSecureContext || !navigator.clipboard) {
    return avisar("Copiar solo funciona entrando por https. Selecciónelo a mano.", true);
  }
  try {
    await navigator.clipboard.writeText(`cd ~/bryan/RRHH_ITSANET && ${$("act-comando").textContent}`);
    avisar("Comando copiado.");
  } catch { avisar("No se pudo copiar: selecciónelo a mano.", true); }
});

/* --------------------------------------------------------- sedes y regiones */
const NATURAL = { costa: "Costa", sierra: "Sierra", amazonia: "Amazonía", insular: "Galápagos" };
const datosSedes = { sedes: [], ciudades: [] };

async function cargarSedes() {
  const d = await api.sedesAdmin();
  Object.assign(datosSedes, d);
  const nombreSede = Object.fromEntries(d.sedes.map((x) => [x.codigo, x.sede]));
  $("sedes-tarjetas").innerHTML = d.sedes.map((x) => `
    <article class="rounded-xl p-4 ring-1 ${x.activo ? "ring-slate-200" : "bg-slate-50 opacity-70 ring-slate-200"}">
      <div class="flex items-start justify-between gap-2">
        <div>
          <p class="text-lg font-semibold">${esc(x.sede)}</p>
          <p class="text-sm text-slate-600">${esc(x.nombre)}${x.activo ? "" : " · desactivada"}</p>
        </div>
        <button type="button" data-editar-sede="${esc(x.codigo)}"
                class="rounded-lg px-2.5 py-1 text-xs font-medium text-slate-700 ring-1 ring-slate-300 hover:bg-slate-100">Editar</button>
      </div>
      <div class="mt-2 flex flex-wrap gap-1">
        ${(x.regiones_naturales || []).map((r) => `<span class="rounded-full bg-sky-100 px-2 py-0.5 text-xs text-sky-800">${esc(NATURAL[r] || r)}</span>`).join("")
          || '<span class="text-xs text-amber-700">Sin regiones asignadas</span>'}
      </div>
      <dl class="mt-3 grid grid-cols-4 gap-2 text-center text-xs">
        <div><dt class="text-slate-500">Personas</dt><dd class="text-base font-semibold tabular-nums">${x.personas}</dd></div>
        <div><dt class="text-slate-500">Ciudades</dt><dd class="text-base font-semibold tabular-nums">${x.ciudades}</dd></div>
        <div><dt class="text-slate-500">T. Humano</dt><dd class="text-base font-semibold tabular-nums ${x.talento_humano ? "" : "text-rose-600"}">${x.talento_humano}</dd></div>
        <div><dt class="text-slate-500">Firmantes</dt><dd class="text-base font-semibold tabular-nums ${x.firmantes ? "" : "text-rose-600"}">${x.firmantes}</dd></div>
      </dl>
      ${x.correo ? `<p class="mt-2 truncate text-xs text-slate-500">Buzón: ${esc(x.correo)}</p>` : ""}
      ${x.activo && !x.talento_humano ? '<p class="mt-2 text-xs text-rose-700">Nadie de Talento Humano en esta sede: sus avisos llegan a todo el equipo. Asígnelo en «Talento Humano».</p>' : ""}
    </article>`).join("");
  $("sedes-sin-ciudad").classList.toggle("hidden", !d.sin_ciudad.length);
  $("sedes-sin-lista").innerHTML = d.sin_ciudad.map((c) => `
    <li><button type="button" data-ciudad-nueva="${esc(c.ciudad === "(sin ciudad)" ? "" : c.ciudad)}"
        class="rounded-full bg-white px-3 py-1 ring-1 ring-amber-300 hover:bg-amber-100">
        ${esc(c.ciudad)} <b>${c.personas}</b></button></li>`).join("");
  pintarCiudades(nombreSede);
}

function pintarCiudades(nombreSede = Object.fromEntries(datosSedes.sedes.map((x) => [x.codigo, x.sede]))) {
  const aguja = ($("ciu-buscar").value || "").trim().toLowerCase();
  const filas = datosSedes.ciudades.filter((c) => !aguja
    || `${c.ciudad} ${c.provincia || ""}`.toLowerCase().includes(aguja));
  $("ciu-tabla").innerHTML = filas.map((c) => `
    <tr class="hover:bg-slate-50">
      <td class="px-3 py-2 font-medium">${esc(c.ciudad)}</td>
      <td class="px-3 py-2">${esc(c.provincia || "—")}</td>
      <td class="px-3 py-2">${esc(NATURAL[c.region_natural] || "—")}</td>
      <td class="px-3 py-2">${esc(nombreSede[c.region] || c.region)}</td>
      <td class="px-3 py-2 text-right tabular-nums">${c.personas}</td>
      <td class="px-3 py-2 text-right whitespace-nowrap">
        <button type="button" data-editar-ciudad="${esc(c.ciudad)}" class="rounded-lg px-2 py-1 text-xs hover:bg-slate-100">Editar</button>
        ${c.personas ? "" : `<button type="button" data-quitar-ciudad="${esc(c.ciudad)}" class="rounded-lg px-2 py-1 text-xs text-rose-700 hover:bg-rose-50">Quitar</button>`}
      </td>
    </tr>`).join("") || '<tr><td colspan="6" class="px-3 py-6 text-center text-slate-500">Nada coincide.</td></tr>';
}

$("ciu-buscar")?.addEventListener("input", () => pintarCiudades());

$("form-ciudad")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const ciudad = $("ciu-nombre").value.trim();
  const sede = $("ciu-sede").value;
  const previa = datosSedes.ciudades.find((c) => c.ciudad === ciudad.toUpperCase());
  if (previa && previa.region !== sede && previa.personas &&
      !confirm(`${previa.personas} persona(s) de ${previa.ciudad} pasarán a la sede ` +
               `${$("ciu-sede").selectedOptions[0].textContent}, con sus trámites en curso. ¿Continuar?`)) return;
  try {
    const r = await api.guardarCiudad({ ciudad, region: sede,
      provincia: $("ciu-provincia").value.trim() || null, region_natural: $("ciu-natural").value || null });
    avisar(r.mensaje);
    $("form-ciudad").reset();
    await cargarSedes();
  } catch (err) { avisar(err.message, true); }
});

function abrirSede(codigo = null) {
  const x = datosSedes.sedes.find((s) => s.codigo === codigo);
  $("sede-titulo").textContent = x ? `Editar sede ${x.sede}` : "Nueva sede";
  $("sede-codigo").value = x?.codigo || "";
  $("sede-ciudad").value = x?.sede || "";
  $("sede-nombre").value = x?.nombre || "";
  $("sede-correo").value = x?.correo || "";
  $("sede-descripcion").value = x?.descripcion || "";
  document.querySelectorAll('input[name="sede-rn"]').forEach((c) => {
    c.checked = (x?.regiones_naturales || []).includes(c.value);
  });
  $("sede-activa-caja").classList.toggle("hidden", !x);
  $("sede-activa-caja").classList.toggle("flex", !!x);
  $("sede-activa").checked = x ? x.activo : true;
  $("dlg-sede").showModal();
}

$("sede-nueva")?.addEventListener("click", () => abrirSede());
$("sede-cancelar")?.addEventListener("click", () => $("dlg-sede").close());
$("form-sede")?.addEventListener("submit", async (e) => {
  e.preventDefault();
  const codigo = $("sede-codigo").value;
  const datos = {
    sede: $("sede-ciudad").value.trim(), nombre: $("sede-nombre").value.trim() || null,
    descripcion: $("sede-descripcion").value.trim() || null,
    regiones_naturales: [...document.querySelectorAll('input[name="sede-rn"]:checked')].map((c) => c.value),
  };
  const correo = $("sede-correo").value.trim();
  try {
    const r = codigo
      ? await api.cambiarSede(codigo, { ...datos, correo, activo: $("sede-activa").checked })
      : await api.crearSede({ ...datos, correo: correo || null });
    avisar(r.mensaje);
    $("dlg-sede").close();
    olvidarSedes();
    botonesSedeListos = false;
    await cargarSedes();
    document.querySelectorAll("select[data-sedes]").forEach((sel) => llenarSedes(sel));
  } catch (err) { avisar(err.message, true); }
});

$("sedes-tarjetas")?.addEventListener("click", (e) => {
  const b = e.target.closest("[data-editar-sede]");
  if (b) abrirSede(b.dataset.editarSede);
});
$("sedes-sin-lista")?.addEventListener("click", (e) => {
  const b = e.target.closest("[data-ciudad-nueva]");
  if (!b) return;
  $("ciu-nombre").value = b.dataset.ciudadNueva;
  $("ciu-nombre").focus();
});
$("ciu-tabla")?.addEventListener("click", async (e) => {
  const editar = e.target.closest("[data-editar-ciudad]");
  if (editar) {
    const c = datosSedes.ciudades.find((x) => x.ciudad === editar.dataset.editarCiudad);
    $("ciu-nombre").value = c.ciudad;
    $("ciu-provincia").value = c.provincia || "";
    $("ciu-natural").value = c.region_natural || "";
    $("ciu-sede").value = c.region;
    $("ciu-nombre").scrollIntoView({ block: "center" });
    return;
  }
  const quitar = e.target.closest("[data-quitar-ciudad]");
  if (quitar && confirm(`¿Quitar ${quitar.dataset.quitarCiudad} de la lista?`)) {
    try { avisar((await api.quitarCiudad(quitar.dataset.quitarCiudad)).mensaje); await cargarSedes(); }
    catch (err) { avisar(err.message, true); }
  }
});

document.querySelectorAll("select[data-sedes]").forEach((sel) => llenarSedes(sel));

/* ---------------------------------------------------------------- arranque
   Al final a propósito: la sección inicial usa variables declaradas en todo
   el archivo, y llamarla antes las encontraba sin inicializar. */
mostrar(seccionInicial in CARGADORES ? seccionInicial : "pendientes");
