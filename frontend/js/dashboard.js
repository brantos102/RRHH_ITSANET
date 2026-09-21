/* Panel del empleado: perfil, saldo, alertas, solicitudes y firma. */
import { api, sesion, fecha, fechaHora, esc, ESTADOS, ErrorApi } from "./api.js";
import { PanelFirma } from "./firma.js";

const $ = (id) => document.getElementById(id);
const estado = {
  tipos: [], firma: null, adjuntos: [], tipoActual: null, saldo: null,
  solicitudes: [], pendientes: [], companeros: [], calendario: [],
  mes: new Date(new Date().getFullYear(), new Date().getMonth(), 1),
};

if (!sesion.vigente) location.replace("index.html");

/* ------------------------------------------------------------------ avisos */
let temporizadorAviso;
function avisar(texto, tono = "neutro") {
  const el = $("aviso-texto");
  el.textContent = texto;
  el.className =
    "max-w-sm rounded-xl px-4 py-3 text-center text-sm shadow-lg " +
    (tono === "error" ? "bg-rose-600 text-white" : "bg-slate-900 text-white");
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => el.classList.add("hidden"), 4000);
}

/* ------------------------------------------------------------------ modales */
function abrir(id) { $(id).showModal(); }
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-cerrar]")) e.target.closest("dialog")?.close();
});
// Cerrar al pulsar fuera del cuadro
document.querySelectorAll("dialog").forEach((d) =>
  d.addEventListener("click", (e) => { if (e.target === d) d.close(); })
);

/* ------------------------------------------------------------------- carga */
async function cargar() {
  const perfil = sesion.perfil;
  $("cab-nombre").textContent = perfil.nombre;
  $("cab-cargo").textContent = [perfil.cargo, perfil.departamento].filter(Boolean).join(" · ") || perfil.rol;

  // Quien aprueba cambia de sombrero sin cambiar de página
  const aprueba = ["jefe", "rrhh", "admin"].includes(perfil.rol);
  $("pestanas").classList.toggle("hidden", !aprueba);

  const [saldo, notificaciones, solicitudes, tipos, firma, companeros, calendario, pendientes] =
    await Promise.all([
      api.saldo().catch(() => null),
      api.notificaciones().catch(() => []),
      api.misSolicitudes().catch(() => []),
      api.tiposPermiso().catch(() => []),
      api.miFirma().catch(() => ({ registrada: false })),
      api.companeros().catch(() => []),
      api.calendario().catch(() => []),
      aprueba ? api.pendientes().catch(() => []) : Promise.resolve([]),
    ]);

  Object.assign(estado, { tipos, firma, saldo, solicitudes, companeros, calendario, pendientes });

  pintarResumen(perfil, saldo);
  pintarAlertas(notificaciones);
  pintarNotificaciones(notificaciones);
  pintarLogros(perfil.logros);
  pintarSolicitudes();
  pintarFirma(firma);
  llenarTiposPermiso(tipos);
  llenarCompaneros(companeros);
  pintarCalendario();
  pintarPendientes();
}

/* ------------------------------------------------------------- pestañas */
document.querySelectorAll("[data-pestana]").forEach((boton) =>
  boton.addEventListener("click", () => mostrarPestana(boton.dataset.pestana))
);

function mostrarPestana(cual) {
  document.querySelectorAll("[data-pestana]").forEach((b) => {
    const activa = b.dataset.pestana === cual;
    b.className = activa
      ? "border-b-2 border-slate-900 px-4 py-3 text-sm font-medium"
      : "border-b-2 border-transparent px-4 py-3 text-sm font-medium text-slate-500 hover:text-slate-900";
  });
  $("vista-panel").classList.toggle("hidden", cual !== "panel");
  $("vista-aprobaciones").classList.toggle("hidden", cual !== "aprobaciones");
  location.hash = cual === "panel" ? "" : "#aprobaciones";
}

function pintarResumen(perfil, saldo) {
  $("saldo-dias").textContent = Number(perfil.dias_vacaciones).toFixed(1).replace(/\.0$/, "");
  $("antiguedad").textContent =
    perfil.anios_servicio === 1 ? "1 año" : `${perfil.anios_servicio} años`;
  $("fecha-ingreso").textContent = `Ingresó el ${fecha(perfil.fecha_ingreso)}`;
  $("fds-pendientes").textContent = saldo ? saldo.fines_semana_pendientes : "—";

  // De qué períodos vienen esos días: es lo que RRHH audita
  const vigentes = (saldo?.periodos || []).filter((p) => !p.caducado && Number(p.saldo) > 0);
  $("periodos-resumen").textContent = vigentes.length
    ? `De ${vigentes.length} período(s): ` +
      vigentes.map((p) => `año ${p.periodo} (${Number(p.saldo)})`).join(", ")
    : "Sin días acumulados disponibles";
}

/* ------------------------------------------------------------------ alertas */
const TONOS = {
  critica: "bg-rose-50 text-rose-900 ring-rose-200",
  advertencia: "bg-amber-50 text-amber-900 ring-amber-200",
  info: "bg-sky-50 text-sky-900 ring-sky-200",
};

function pintarAlertas(notificaciones) {
  const importantes = notificaciones.filter(
    (n) => !n.leida_en && ["critica", "advertencia"].includes(n.severidad)
  );
  const caja = $("alertas");
  caja.classList.toggle("hidden", importantes.length === 0);
  caja.innerHTML = importantes
    .slice(0, 3)
    .map(
      (n) => `
      <article class="rounded-2xl px-4 py-3 ring-1 ${TONOS[n.severidad] || TONOS.info}">
        <p class="font-medium">${esc(n.titulo)}</p>
        <p class="mt-1 text-sm leading-relaxed">${esc(n.mensaje)}</p>
        ${n.articulo ? `<p class="mt-2 text-xs opacity-75">${esc(n.norma)} · ${esc(n.articulo)}</p>` : ""}
      </article>`
    )
    .join("");
}

function pintarNotificaciones(notificaciones) {
  const sinLeer = notificaciones.filter((n) => !n.leida_en).length;
  $("punto-campana").classList.toggle("hidden", sinLeer === 0);

  $("contenido-notificaciones").innerHTML = notificaciones.length
    ? notificaciones
        .map(
          (n) => `
        <article class="px-5 py-4 ${n.leida_en ? "opacity-60" : ""}">
          <div class="flex items-start gap-3">
            <span class="mt-1.5 h-2 w-2 shrink-0 rounded-full ${
              n.severidad === "critica" ? "bg-rose-500" : n.severidad === "advertencia" ? "bg-amber-500" : "bg-sky-500"
            }"></span>
            <div class="min-w-0">
              <p class="font-medium">${esc(n.titulo)}</p>
              <p class="mt-1 text-sm leading-relaxed text-slate-600">${esc(n.mensaje)}</p>
              ${
                n.articulo_texto
                  ? `<details class="mt-2">
                       <summary class="cursor-pointer text-xs font-medium text-slate-500">
                         ${esc(n.norma)} · ${esc(n.articulo)}
                       </summary>
                       <p class="mt-1.5 rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-600">
                         ${esc(n.articulo_texto)}
                       </p>
                     </details>`
                  : ""
              }
              <p class="mt-1.5 text-xs text-slate-400">${fechaHora(n.created_at)}</p>
            </div>
          </div>
        </article>`
        )
        .join("")
    : `<p class="px-5 py-8 text-center text-sm text-slate-500">No tiene notificaciones.</p>`;
}

function pintarLogros(logros) {
  if (!logros?.length) return;
  $("seccion-logros").classList.remove("hidden");
  $("lista-logros").innerHTML = logros
    .map(
      (l) => `
      <li class="flex items-start gap-3 rounded-xl bg-amber-50 px-3 py-2.5">
        <span class="text-lg">🏅</span>
        <span>
          <span class="block text-sm font-medium">${esc(l.titulo)}</span>
          <span class="block text-xs text-slate-600">${esc(l.detalle || "")} ${l.fecha ? "· " + fecha(l.fecha) : ""}</span>
        </span>
      </li>`
    )
    .join("");
}

/* -------------------------------------------------------------- solicitudes */
function pintarSolicitudes() {
  const termino = ($("filtro-solicitudes").value || "").trim().toLowerCase();
  const solicitudes = termino
    ? estado.solicitudes.filter((s) =>
        [String(s.folio), s.tipo, s.categoria, s.descripcion, etiquetaEstado(s)]
          .filter(Boolean).join(" ").toLowerCase().includes(termino))
    : estado.solicitudes;

  const caja = $("lista-solicitudes");
  if (!solicitudes.length) {
    caja.innerHTML = `<p class="rounded-2xl bg-white p-5 text-sm text-slate-500 ring-1 ring-slate-200">
        ${termino ? "Ninguna solicitud coincide con la búsqueda." : "Todavía no ha enviado ninguna solicitud."}</p>`;
    return;
  }

  caja.innerHTML = solicitudes
    .map((s) => {
      const e = ESTADOS[s.estado] || { etiqueta: s.estado, clase: "bg-slate-100 text-slate-600 ring-slate-200" };
      const etiqueta = etiquetaEstado(s);
      const rango =
        s.fecha_inicio === s.fecha_fin ? fecha(s.fecha_inicio) : `${fecha(s.fecha_inicio, false)} – ${fecha(s.fecha_fin)}`;
      const horas = s.hora_inicio ? ` · ${s.hora_inicio.slice(0, 5)} a ${s.hora_fin?.slice(0, 5)}` : "";
      const cancelable = ["pendiente_jefe", "pendiente_rrhh", "aprobado"].includes(s.estado);

      return `
      <article class="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="font-medium">
              <span class="mr-1.5 rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600">Nº ${s.folio}</span>
              ${s.tipo === "vacacion" ? "🏖️ Vacaciones" : "📄 " + esc(s.categoria || "Permiso")}
            </p>
            <p class="mt-0.5 text-sm text-slate-600">${rango}${horas} · ${Number(s.dias_solicitados)} día(s)</p>
          </div>
          <span class="rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${e.clase}">${esc(etiqueta)}</span>
        </div>

        <p class="mt-2 text-sm text-slate-600">${esc(s.descripcion)}</p>
        ${s.es_adelanto ? `<p class="mt-1.5 text-xs text-amber-700">Incluye días adelantados</p>` : ""}
        ${s.motivo_rechazo ? `<p class="mt-2 rounded-lg bg-rose-50 p-2.5 text-sm text-rose-800">Motivo: ${esc(s.motivo_rechazo)}</p>` : ""}

        <div class="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
          <span>Enviada ${fechaHora(s.created_at)}</span>
          ${s.reemplazo ? `<span>🔁 Lo cubre ${esc(s.reemplazo)}</span>` : ""}
          ${s.adjuntos ? `<span>📎 ${s.adjuntos} adjunto(s)</span>` : ""}
          ${s.firmas ? `<span>✍️ firmada</span>` : ""}
          ${s.qr_hash && s.estado === "aprobado"
            ? `<button data-qr="${s.id}" data-hasta="${s.fecha_fin}"
                       class="font-medium text-emerald-700 hover:underline">Ver código QR</button>`
            : s.qr_hash ? `<span class="text-slate-400">QR anulado</span>` : ""}
          ${cancelable ? `<button data-cancelar="${s.id}" class="ml-auto font-medium text-rose-600 hover:underline">Cancelar</button>` : ""}
        </div>
      </article>`;
    })
    .join("");
}

/* ---- Código QR ---- */
document.addEventListener("click", async (e) => {
  const boton = e.target.closest("[data-qr]");
  if (!boton) return;

  // La imagen va protegida por token, así que se pide con fetch y se
  // muestra desde un blob: un <img src> normal no lleva la cabecera.
  try {
    const respuesta = await fetch(api.qrUrl(boton.dataset.qr), {
      headers: { Authorization: `Bearer ${sesion.token}` },
    });
    if (!respuesta.ok) throw new Error("No se pudo obtener el código.");
    const previo = $("imagen-qr").src;
    if (previo.startsWith("blob:")) URL.revokeObjectURL(previo);
    $("imagen-qr").src = URL.createObjectURL(await respuesta.blob());
    $("qr-vigencia").textContent = `Válido hasta el ${fecha(boton.dataset.hasta)}`;
    abrir("modal-qr");
  } catch (err) {
    avisar(err.message, "error");
  }
});

/** El estado dice además QUIÉN decidió: no es lo mismo que rechace el jefe o RRHH. */
function etiquetaEstado(s) {
  const base = (ESTADOS[s.estado] || {}).etiqueta || s.estado;
  if (s.estado !== "rechazado") return base;
  return s.rechazado_en_etapa === "jefe"
    ? "Rechazada por su jefe"
    : s.rechazado_en_etapa === "rrhh"
      ? "Rechazada por Talento Humano"
      : base;
}

$("filtro-solicitudes").addEventListener("input", () => pintarSolicitudes());

document.addEventListener("click", async (e) => {
  const boton = e.target.closest("[data-cancelar]");
  if (!boton) return;
  if (!confirm("¿Seguro que desea cancelar esta solicitud?")) return;
  try {
    await api.cancelar(boton.dataset.cancelar);
    avisar("Solicitud cancelada.");
    await cargar();
  } catch (err) {
    avisar(err.message, "error");
  }
});

/* -------------------------------------------------------------- calendario */
const DIAS_CORTOS = ["L", "M", "M", "J", "V", "S", "D"];
const NOMBRE_MES = ["enero","febrero","marzo","abril","mayo","junio",
                    "julio","agosto","septiembre","octubre","noviembre","diciembre"];

function pintarCalendario() {
  const inicio = estado.mes;
  const fin = new Date(inicio.getFullYear(), inicio.getMonth() + 1, 0);
  $("mes-actual").textContent = `${NOMBRE_MES[inicio.getMonth()]} ${inicio.getFullYear()}`;

  const totalDias = fin.getDate();
  const dias = Array.from({ length: totalDias }, (_, i) =>
    new Date(inicio.getFullYear(), inicio.getMonth(), i + 1));

  // Una fila por persona con alguna ausencia este mes
  const porPersona = new Map();
  for (const a of estado.calendario) {
    const desde = new Date(a.fecha_inicio + "T12:00");
    const hasta = new Date(a.fecha_fin + "T12:00");
    if (hasta < inicio || desde > fin) continue;
    if (!porPersona.has(a.user_id)) porPersona.set(a.user_id, { nombre: a.nombre, tramos: [] });
    porPersona.get(a.user_id).tramos.push({ desde, hasta, estado: a.estado, motivo: a.motivo_general });
  }

  const caja = $("calendario");
  if (!porPersona.size) {
    caja.innerHTML = `<p class="rounded-xl bg-slate-50 p-4 text-center text-sm text-slate-500">
        Nadie de su equipo tiene ausencias registradas en ${NOMBRE_MES[inicio.getMonth()]}.</p>`;
    return;
  }

  const hoy = new Date().toDateString();
  const cabecera = dias.map((d) => {
    const finde = d.getDay() === 0 || d.getDay() === 6;
    return `<th class="w-6 px-0 pb-1 text-center text-[10px] font-medium
                 ${finde ? "text-slate-300" : "text-slate-400"}
                 ${d.toDateString() === hoy ? "text-slate-900" : ""}">
              ${d.getDate()}<br><span class="text-[9px]">${DIAS_CORTOS[(d.getDay() + 6) % 7]}</span>
            </th>`;
  }).join("");

  const filas = [...porPersona.values()].map((p) => {
    const celdas = dias.map((d) => {
      const tramo = p.tramos.find((t) => d >= t.desde && d <= t.hasta);
      const finde = d.getDay() === 0 || d.getDay() === 6;
      if (!tramo) return `<td class="h-7 border border-slate-100 ${finde ? "bg-slate-50" : ""}"></td>`;
      const color = tramo.estado === "aprobado"
        ? "bg-emerald-400"
        : "bg-amber-300";
      return `<td class="h-7 border border-slate-100 p-0">
                <div class="h-full w-full ${color}" title="${esc(p.nombre)} · ${esc(tramo.motivo)} · ${
                  tramo.estado === "aprobado" ? "aprobada" : "en trámite"}"></div>
              </td>`;
    }).join("");
    return `<tr>
      <th class="sticky left-0 z-10 bg-white pr-3 text-left text-xs font-medium whitespace-nowrap">
        ${esc(p.nombre)}</th>${celdas}</tr>`;
  }).join("");

  caja.innerHTML = `
    <table class="border-separate border-spacing-0 text-xs">
      <thead><tr><th class="sticky left-0 z-10 bg-white"></th>${cabecera}</tr></thead>
      <tbody>${filas}</tbody>
    </table>
    <div class="mt-3 flex flex-wrap gap-4 text-xs text-slate-500">
      <span class="flex items-center gap-1.5"><i class="inline-block h-3 w-3 rounded-sm bg-emerald-400"></i> Aprobada</span>
      <span class="flex items-center gap-1.5"><i class="inline-block h-3 w-3 rounded-sm bg-amber-300"></i> En trámite</span>
      <span>Solo se muestra quién falta y cuándo, no el motivo.</span>
    </div>`;
}

$("mes-anterior").addEventListener("click", () => cambiarMes(-1));
$("mes-siguiente").addEventListener("click", () => cambiarMes(1));

async function cambiarMes(delta) {
  estado.mes = new Date(estado.mes.getFullYear(), estado.mes.getMonth() + delta, 1);
  const fin = new Date(estado.mes.getFullYear(), estado.mes.getMonth() + 1, 0);
  const iso = (d) => d.toISOString().slice(0, 10);
  try {
    estado.calendario = await api.calendario(iso(estado.mes), iso(fin));
  } catch { /* se mantiene lo ya cargado */ }
  pintarCalendario();
}

/* ------------------------------------------------------------ aprobaciones */
function pintarPendientes() {
  const caja = $("vista-aprobaciones");
  const cuenta = $("cuenta-pendientes");
  cuenta.textContent = estado.pendientes.length;
  cuenta.classList.toggle("hidden", estado.pendientes.length === 0);

  if (!estado.pendientes.length) {
    caja.innerHTML = `<p class="rounded-2xl bg-white p-8 text-center text-sm text-slate-500 ring-1 ring-slate-200">
        No tiene solicitudes por aprobar. 🎉</p>`;
    return;
  }

  caja.innerHTML = estado.pendientes.map((s) => {
    const rango = s.fecha_inicio === s.fecha_fin
      ? fecha(s.fecha_inicio)
      : `${fecha(s.fecha_inicio, false)} – ${fecha(s.fecha_fin)}`;
    const horas = s.hora_inicio ? ` · ${s.hora_inicio} a ${s.hora_fin}` : "";

    const banderas = [];
    if (s.es_adelanto) banderas.push(["amber", "Supera su saldo: días adelantados"]);
    if (s.tipo === "permiso" && !s.adjuntos) banderas.push(["rose", "Sin respaldo adjunto"]);
    if (s.tipo === "permiso" && !s.firmas) banderas.push(["rose", "Sin firma del solicitante"]);
    if (!s.reemplazo) banderas.push(["slate", "Sin reemplazo asignado"]);

    return `
    <article class="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="font-semibold">
            <span class="mr-1.5 rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600">Nº ${s.folio}</span>
            ${esc(s.empleado)}
          </p>
          <p class="text-sm text-slate-500">${esc(s.cedula)}${s.departamento ? " · " + esc(s.departamento) : ""}</p>
        </div>
        <span class="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
          ${s.tipo === "vacacion" ? "🏖️ Vacaciones" : "📄 " + esc(s.categoria || "Permiso")}
        </span>
      </div>

      <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
        <div><dt class="text-xs text-slate-500">Fechas</dt><dd class="font-medium">${rango}${horas}</dd></div>
        <div><dt class="text-xs text-slate-500">Días</dt><dd class="font-medium">${s.dias_solicitados}</dd></div>
        <div><dt class="text-xs text-slate-500">Saldo</dt><dd class="font-medium">${s.saldo_actual} días</dd></div>
        <div><dt class="text-xs text-slate-500">Lo cubre</dt>
             <dd class="font-medium">${s.reemplazo ? esc(s.reemplazo) : "—"}</dd></div>
      </dl>

      <p class="mt-3 text-sm text-slate-700">${esc(s.descripcion)}</p>
      ${s.justificacion
        ? `<p class="mt-2 rounded-xl bg-slate-50 p-3 text-sm text-slate-600">
             <span class="font-medium">Justificación:</span> ${esc(s.justificacion)}</p>` : ""}

      ${banderas.length
        ? `<div class="mt-3 flex flex-wrap gap-2">${banderas.map(([t, texto]) =>
            `<span class="rounded-lg px-2.5 py-1 text-xs font-medium ${
              t === "amber" ? "bg-amber-50 text-amber-800 ring-1 ring-amber-200"
              : t === "rose" ? "bg-rose-50 text-rose-800 ring-1 ring-rose-200"
              : "bg-slate-50 text-slate-600 ring-1 ring-slate-200"}">${esc(texto)}</span>`
          ).join("")}</div>` : ""}

      <div class="mt-4 flex gap-3">
        <button data-rechazar="${s.id}" data-nombre="${esc(s.empleado)}" data-folio="${s.folio}"
                class="flex-1 rounded-xl bg-white px-4 py-2.5 font-medium text-rose-700 ring-1 ring-rose-200 hover:bg-rose-50">
          Rechazar
        </button>
        <button data-aprobar="${s.id}"
                class="flex-1 rounded-xl bg-emerald-600 px-4 py-2.5 font-medium text-white hover:bg-emerald-700">
          Aprobar
        </button>
      </div>
    </article>`;
  }).join("");
}

document.addEventListener("click", async (e) => {
  const aprobar = e.target.closest("[data-aprobar]");
  if (aprobar) {
    aprobar.disabled = true;
    aprobar.textContent = "Aprobando…";
    try {
      avisar((await api.decidir(aprobar.dataset.aprobar, "aprobar", null)).mensaje);
    } catch (err) {
      avisar(err.message, "error");
    }
    await cargar();
    mostrarPestana("aprobaciones");
    return;
  }

  const rechazar = e.target.closest("[data-rechazar]");
  if (rechazar) {
    $("form-rechazo").dataset.id = rechazar.dataset.rechazar;
    $("rechazo-de").textContent = `Solicitud Nº ${rechazar.dataset.folio} de ${rechazar.dataset.nombre}`;
    $("motivo-rechazo").value = "";
    abrir("modal-rechazo");
    $("motivo-rechazo").focus();
  }
});

$("form-rechazo").addEventListener("submit", async (e) => {
  e.preventDefault();
  const motivo = $("motivo-rechazo").value.trim();
  if (motivo.length < 5) return $("motivo-rechazo").focus();
  $("modal-rechazo").close();
  try {
    avisar((await api.decidir($("form-rechazo").dataset.id, "rechazar", motivo)).mensaje);
  } catch (err) {
    avisar(err.message, "error");
  }
  await cargar();
  mostrarPestana("aprobaciones");
});

/* --------------------------------------------------------------- del saldo */
$("btn-detalle-saldo").addEventListener("click", () => {
  const d = estado.saldo;
  if (!d) return avisar("No se pudo obtener el detalle.", "error");

  $("contenido-saldo").innerHTML = `
    <section class="rounded-xl bg-slate-50 p-4">
      <p class="text-sm leading-relaxed text-slate-700">${esc(d.regla_antiguedad)}</p>
      <p class="mt-2 text-sm leading-relaxed text-slate-700">${esc(d.regla_fines_semana)}</p>
    </section>

    ${
      d.proximo_vencimiento
        ? `<section class="rounded-xl bg-amber-50 p-4 ring-1 ring-amber-200">
             <p class="text-sm text-amber-900">
               Su período ${d.proximo_vencimiento.periodo} vence el
               <strong>${fecha(d.proximo_vencimiento.vence_en)}</strong> con
               <strong>${Number(d.proximo_vencimiento.dias_en_riesgo)} día(s)</strong> en riesgo.
             </p>
           </section>`
        : ""
    }

    <section>
      <h3 class="mb-2 text-sm font-medium">Sus períodos</h3>
      <div class="overflow-x-auto rounded-xl ring-1 ring-slate-200">
        <table class="w-full text-left text-sm">
          <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th class="px-3 py-2">Año</th><th class="px-3 py-2">Asignados</th>
              <th class="px-3 py-2">Usados</th><th class="px-3 py-2">Saldo</th><th class="px-3 py-2">Estado</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100">
            ${d.periodos
              .map(
                (p) => `<tr class="${p.caducado ? "text-slate-400 line-through" : ""}">
                  <td class="px-3 py-2">${p.periodo}</td>
                  <td class="px-3 py-2 tabular-nums">${Number(p.asignados)}</td>
                  <td class="px-3 py-2 tabular-nums">${Number(p.consumidos)}</td>
                  <td class="px-3 py-2 font-medium tabular-nums">${Number(p.saldo)}</td>
                  <td class="px-3 py-2 text-xs">${esc(p.explicacion)}</td>
                </tr>`
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </section>

    <section>
      <h3 class="mb-2 text-sm font-medium">Base legal</h3>
      <div class="space-y-2">
        ${d.base_legal
          .map(
            (a) => `<details class="rounded-xl bg-slate-50 p-3">
              <summary class="cursor-pointer text-sm font-medium">${esc(a.articulo)} — ${esc(a.titulo)}</summary>
              <p class="mt-2 text-xs leading-relaxed text-slate-600">${esc(a.texto)}</p>
              <p class="mt-1.5 text-xs text-slate-400">${esc(a.norma)}</p>
            </details>`
          )
          .join("")}
      </div>
    </section>`;
  abrir("modal-saldo");
});

$("btn-campana").addEventListener("click", () => abrir("modal-notificaciones"));

/* ------------------------------------------------------------------- firma */
let panel = null;

function pintarFirma(firma) {
  if (firma?.registrada) {
    $("estado-firma").textContent = `Registrada el ${fecha(firma.created_at)}`;
    $("btn-firma").textContent = "Cambiar firma";
    if (firma.contenido) {
      $("vista-firma").src = firma.contenido;
      $("vista-firma").classList.remove("hidden");
    }
  } else {
    $("estado-firma").textContent = "Aún no ha registrado su firma";
    $("btn-firma").textContent = "Registrar firma";
    $("vista-firma").classList.add("hidden");
  }
}

$("btn-firma").addEventListener("click", () => {
  abrir("modal-firma");
  if (!panel) {
    panel = new PanelFirma($("lienzo-firma"), (hayTrazo) =>
      $("guia-firma").classList.toggle("hidden", hayTrazo)
    );
  }
  panel.ajustar();
  $("error-firma").classList.add("hidden");
});

$("btn-limpiar-firma").addEventListener("click", () => panel?.limpiar());

$("btn-guardar-firma").addEventListener("click", async () => {
  if (!panel?.tieneTrazo) {
    $("error-firma").textContent = "Dibuje su firma antes de guardar.";
    $("error-firma").classList.remove("hidden");
    return;
  }
  $("btn-guardar-firma").disabled = true;
  try {
    await api.guardarFirma(panel.aDataURI());
    estado.firma = await api.miFirma();
    pintarFirma(estado.firma);
    $("modal-firma").close();
    avisar("Firma registrada.");
  } catch (err) {
    $("error-firma").textContent = err.message;
    $("error-firma").classList.remove("hidden");
  } finally {
    $("btn-guardar-firma").disabled = false;
  }
});

$("archivo-firma").addEventListener("change", async (e) => {
  const archivo = e.target.files[0];
  if (!archivo) return;
  try {
    await api.subirFirma(archivo);
    estado.firma = await api.miFirma();
    pintarFirma(estado.firma);
    $("modal-firma").close();
    avisar("Firma registrada.");
  } catch (err) {
    $("error-firma").textContent = err.message;
    $("error-firma").classList.remove("hidden");
  } finally {
    e.target.value = "";
  }
});

/* -------------------------------------------------------- nueva solicitud */
function llenarCompaneros(companeros) {
  $("reemplazo").innerHTML =
    `<option value="">Nadie asignado</option>` +
    companeros.map((c) => `<option value="${c.id}">${esc(c.nombre)}${
      c.cargo ? " · " + esc(c.cargo) : ""}</option>`).join("");
  $("campo-reemplazo").classList.toggle("hidden", companeros.length === 0);
}

function llenarTiposPermiso(tipos) {
  $("tipo-permiso").innerHTML =
    `<option value="">Seleccione…</option>` +
    tipos.map((t) => `<option value="${t.id}">${esc(t.nombre)}</option>`).join("");
}

document.querySelectorAll("[data-nueva]").forEach((boton) =>
  boton.addEventListener("click", () => abrirFormulario(boton.dataset.nueva))
);

function abrirFormulario(tipo) {
  const f = $("form-solicitud");
  f.reset();
  f.dataset.tipo = tipo;
  estado.adjuntos = [];
  estado.tipoActual = null;

  $("titulo-solicitud").textContent = tipo === "vacacion" ? "Solicitar vacaciones" : "Solicitar permiso";
  $("campo-tipo-permiso").classList.toggle("hidden", tipo !== "permiso");
  $("campo-firma").classList.toggle("hidden", tipo !== "permiso");
  $("campo-firma").classList.toggle("flex", tipo === "permiso");
  $("campo-horas").classList.add("hidden");
  $("campo-horas").classList.remove("grid");
  $("campo-adjuntos").classList.add("hidden");
  $("campo-justificacion").classList.add("hidden");
  $("info-permiso").classList.add("hidden");
  $("previsualizacion").classList.add("hidden");
  $("error-solicitud").classList.add("hidden");
  $("lista-adjuntos").innerHTML = "";
  $("contador-desc").textContent = "0/200";

  const manana = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  $("fecha-inicio").min = manana;
  $("fecha-fin").min = manana;

  $("reemplazo").value = "";
  $("aviso-sin-firma").classList.toggle("hidden", !!estado.firma?.registrada);
  $("firmar").checked = !!estado.firma?.registrada;

  abrir("modal-solicitud");
}

$("descripcion").addEventListener("input", (e) => {
  $("contador-desc").textContent = `${e.target.value.length}/200`;
});

$("tipo-permiso").addEventListener("change", (e) => {
  const tipo = estado.tipos.find((t) => String(t.id) === e.target.value);
  estado.tipoActual = tipo || null;

  const info = $("info-permiso");
  if (!tipo) {
    info.classList.add("hidden");
    $("campo-adjuntos").classList.add("hidden");
    return;
  }

  const requisitos = [
    tipo.requiere_adjunto ? "exige adjuntar respaldo" : null,
    tipo.requiere_justificacion ? "exige justificación" : null,
    tipo.requiere_firma ? "exige su firma" : null,
    tipo.descuenta_vacaciones ? "se descuenta de sus vacaciones" : null,
    tipo.max_dias ? `máximo ${Number(tipo.max_dias)} día(s)` : null,
    tipo.max_horas ? `máximo ${Number(tipo.max_horas)} hora(s)` : null,
  ].filter(Boolean);

  info.innerHTML =
    `<strong>Este permiso ${requisitos.join(", ")}.</strong>` +
    (tipo.articulo ? `<br><span class="text-slate-500">${esc(tipo.norma)} · ${esc(tipo.articulo)}</span>` : "");
  info.classList.remove("hidden");

  $("campo-adjuntos").classList.toggle("hidden", !tipo.requiere_adjunto);
  $("campo-justificacion").classList.toggle("hidden", !tipo.requiere_justificacion);
  $("campo-horas").classList.toggle("hidden", !tipo.max_horas);
  $("campo-horas").classList.toggle("grid", !!tipo.max_horas);
  previsualizar();
});

/* ---- Previsualización en vivo ---- */
let esperando;
["fecha-inicio", "fecha-fin"].forEach((id) =>
  $(id).addEventListener("change", () => {
    clearTimeout(esperando);
    esperando = setTimeout(previsualizar, 250);
  })
);

async function previsualizar() {
  const inicio = $("fecha-inicio").value, fin = $("fecha-fin").value;
  const caja = $("previsualizacion");
  if (!inicio || !fin) return caja.classList.add("hidden");

  try {
    const p = await api.previsualizar({
      tipo: $("form-solicitud").dataset.tipo,
      fecha_inicio: inicio,
      fecha_fin: fin,
      permission_type_id: estado.tipoActual?.id ?? null,
    });

    const necesitaJustificar = p.requiere_justificacion;
    $("campo-justificacion").classList.toggle("hidden", !necesitaJustificar);

    const tono = p.valido ? "bg-slate-50 text-slate-700" : "bg-amber-50 text-amber-900 ring-1 ring-amber-200";
    const d = p.desglose || {};
    // Desglose explícito: de dónde sale el número de días que se descuenta
    const lineas = [
      `${d.total_calendario ?? Number(p.dias)} día(s) en el rango`,
      d.fines_de_semana ? `${d.fines_de_semana} de fin de semana` : null,
      d.dias_no_laborables ? `${d.dias_no_laborables} no laborable(s)` : null,
    ].filter(Boolean);

    caja.className = `rounded-xl p-3 text-sm ${tono}`;
    caja.innerHTML =
      `<p><strong>${Number(p.dias)} día(s) a descontar</strong>` +
      ` · saldo después: <strong>${Number(p.saldo_despues)}</strong></p>` +
      `<p class="mt-1 text-xs opacity-75">${esc(lineas.join(" · "))}</p>` +
      ((d.feriados || []).length
        ? `<p class="mt-1.5 text-xs">Feriados en el rango: ${
            d.feriados.map((f) => `${esc(f.nombre)} (${fecha(f.fecha, false)})`).join(", ")}</p>`
        : "") +
      (p.avisos?.length
        ? `<ul class="mt-2 list-disc space-y-1 pl-4">${p.avisos.map((a) => `<li>${esc(a)}</li>`).join("")}</ul>`
        : "") +
      (!p.valido && p.rango_sugerido?.fin !== fin
        ? `<button type="button" id="btn-corregir"
                   class="mt-2 rounded-lg bg-amber-900 px-3 py-1.5 text-xs font-medium text-white">
             Usar ${fecha(p.rango_sugerido.inicio, false)} – ${fecha(p.rango_sugerido.fin)}
           </button>`
        : "");
    caja.classList.remove("hidden");

    $("btn-corregir")?.addEventListener("click", () => {
      $("fecha-inicio").value = p.rango_sugerido.inicio;
      $("fecha-fin").value = p.rango_sugerido.fin;
      previsualizar();
    });
  } catch {
    caja.classList.add("hidden");
  }
}

/* ---- Adjuntos ---- */
$("adjuntos").addEventListener("change", (e) => {
  estado.adjuntos = [...e.target.files];
  $("lista-adjuntos").innerHTML = estado.adjuntos
    .map(
      (a) => `<li class="flex items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-sm">
        <span>📎</span><span class="truncate">${esc(a.name)}</span>
        <span class="ml-auto shrink-0 text-xs text-slate-500">${(a.size / 1024).toFixed(0)} KB</span>
      </li>`
    )
    .join("");
});

/* ---- Envío ---- */
$("form-solicitud").addEventListener("submit", async (e) => {
  e.preventDefault();
  const boton = $("btn-enviar-solicitud");
  const error = $("error-solicitud");
  error.classList.add("hidden");

  const tipo = $("form-solicitud").dataset.tipo;
  const solicitudId = crypto.randomUUID();

  boton.disabled = true;
  boton.textContent = "Enviando…";
  try {
    // Los adjuntos se suben primero: la solicitud viaja con sus rutas y la
    // base valida el conjunto completo al confirmar.
    const adjuntosSubidos = [];
    for (const archivo of estado.adjuntos) {
      adjuntosSubidos.push(await api.subirAdjunto(solicitudId, archivo));
    }

    const respuesta = await api.crearSolicitud({
      id: solicitudId,
      tipo,
      permission_type_id: estado.tipoActual?.id ?? null,
      fecha_inicio: $("fecha-inicio").value,
      fecha_fin: $("fecha-fin").value,
      hora_inicio: $("hora-inicio").value || null,
      hora_fin: $("hora-fin").value || null,
      descripcion: $("descripcion").value.trim(),
      justificacion: $("justificacion").value.trim() || null,
      reemplazo_id: $("reemplazo").value || null,
      adjuntos: adjuntosSubidos,
      firmar: $("firmar").checked,
    });

    $("modal-solicitud").close();
    avisar(respuesta.mensaje);
    await cargar();
  } catch (err) {
    error.innerHTML = esc(err.message);
    // Si la base sugiere otras fechas, se ofrecen con un clic
    if (err instanceof ErrorApi && err.detalle?.rango_sugerido) {
      const { inicio, fin } = err.detalle.rango_sugerido;
      error.innerHTML += `<button type="button" id="btn-aplicar-sugerido"
          class="mt-2 block rounded-lg bg-rose-900 px-3 py-1.5 text-xs font-medium text-white">
          Usar ${fecha(inicio, false)} – ${fecha(fin)}</button>`;
      error.classList.remove("hidden");
      $("btn-aplicar-sugerido").addEventListener("click", () => {
        $("fecha-inicio").value = inicio;
        $("fecha-fin").value = fin;
        error.classList.add("hidden");
        previsualizar();
      });
      return;
    }
    error.classList.remove("hidden");
  } finally {
    boton.disabled = false;
    boton.textContent = "Enviar solicitud";
  }
});

/* ------------------------------------------------------------------- salir */
$("btn-salir").addEventListener("click", async () => {
  try { await api.cerrarSesion(); } catch { /* el token se descarta igual */ }
  sesion.borrar();
  location.href = "index.html";
});

cargar()
  .then(() => {
    if (location.hash === "#aprobaciones" && !$("pestanas").classList.contains("hidden")) {
      mostrarPestana("aprobaciones");
    }
  })
  .catch((err) => avisar(err.message || "No se pudo cargar su panel.", "error"));
