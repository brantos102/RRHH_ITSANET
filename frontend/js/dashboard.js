/* Panel del empleado: perfil, saldo, alertas, solicitudes y firma. */
import { api, sesion, fecha, fechaHora, esc, ESTADOS, ErrorApi } from "./api.js";
import { PanelFirma } from "./firma.js";

const $ = (id) => document.getElementById(id);
const estado = { tipos: [], firma: null, adjuntos: [], tipoActual: null, saldo: null };

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

  const [saldo, notificaciones, solicitudes, tipos, firma] = await Promise.all([
    api.saldo().catch(() => null),
    api.notificaciones().catch(() => []),
    api.misSolicitudes().catch(() => []),
    api.tiposPermiso().catch(() => []),
    api.miFirma().catch(() => ({ registrada: false })),
  ]);

  estado.tipos = tipos;
  estado.firma = firma;
  estado.saldo = saldo;

  pintarResumen(perfil, saldo);
  pintarAlertas(notificaciones);
  pintarNotificaciones(notificaciones);
  pintarLogros(perfil.logros);
  pintarSolicitudes(solicitudes);
  pintarFirma(firma);
  llenarTiposPermiso(tipos);
}

function pintarResumen(perfil, saldo) {
  $("saldo-dias").textContent = Number(perfil.dias_vacaciones).toFixed(1).replace(/\.0$/, "");
  $("antiguedad").textContent =
    perfil.anios_servicio === 1 ? "1 año" : `${perfil.anios_servicio} años`;
  $("fecha-ingreso").textContent = `Ingresó el ${fecha(perfil.fecha_ingreso)}`;
  $("fds-pendientes").textContent = saldo ? saldo.fines_semana_pendientes : "—";
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
function pintarSolicitudes(solicitudes) {
  const caja = $("lista-solicitudes");
  if (!solicitudes.length) {
    caja.innerHTML = `<p class="rounded-2xl bg-white p-5 text-sm text-slate-500 ring-1 ring-slate-200">
        Todavía no ha enviado ninguna solicitud.</p>`;
    return;
  }

  caja.innerHTML = solicitudes
    .map((s) => {
      const e = ESTADOS[s.estado] || { etiqueta: s.estado, clase: "bg-slate-100 text-slate-600 ring-slate-200" };
      const rango =
        s.fecha_inicio === s.fecha_fin ? fecha(s.fecha_inicio) : `${fecha(s.fecha_inicio, false)} – ${fecha(s.fecha_fin)}`;
      const horas = s.hora_inicio ? ` · ${s.hora_inicio.slice(0, 5)} a ${s.hora_fin?.slice(0, 5)}` : "";
      const cancelable = ["pendiente_jefe", "pendiente_rrhh", "aprobado"].includes(s.estado);

      return `
      <article class="rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200">
        <div class="flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="font-medium">${s.tipo === "vacacion" ? "🏖️ Vacaciones" : "📄 " + esc(s.categoria || "Permiso")}</p>
            <p class="mt-0.5 text-sm text-slate-600">${rango}${horas} · ${Number(s.dias_solicitados)} día(s)</p>
          </div>
          <span class="rounded-full px-2.5 py-1 text-xs font-medium ring-1 ${e.clase}">${e.etiqueta}</span>
        </div>

        <p class="mt-2 text-sm text-slate-600">${esc(s.descripcion)}</p>
        ${s.es_adelanto ? `<p class="mt-1.5 text-xs text-amber-700">Incluye días adelantados</p>` : ""}
        ${s.motivo_rechazo ? `<p class="mt-2 rounded-lg bg-rose-50 p-2.5 text-sm text-rose-800">Motivo: ${esc(s.motivo_rechazo)}</p>` : ""}

        <div class="mt-3 flex flex-wrap items-center gap-3 text-xs text-slate-500">
          <span>Enviada ${fechaHora(s.created_at)}</span>
          ${s.adjuntos ? `<span>📎 ${s.adjuntos} adjunto(s)</span>` : ""}
          ${s.firmas ? `<span>✍️ firmada</span>` : ""}
          ${s.qr_hash ? `<span class="font-medium text-emerald-700">✅ QR emitido</span>` : ""}
          ${cancelable ? `<button data-cancelar="${s.id}" class="ml-auto font-medium text-rose-600 hover:underline">Cancelar</button>` : ""}
        </div>
      </article>`;
    })
    .join("");
}

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
    caja.className = `rounded-xl p-3 text-sm ${tono}`;
    caja.innerHTML =
      `<p><strong>${Number(p.dias)} día(s)</strong>` +
      (p.fines_semana_incluidos ? ` · ${p.fines_semana_incluidos} fin(es) de semana` : "") +
      ` · saldo después: <strong>${Number(p.saldo_despues)}</strong></p>` +
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

cargar().catch((err) => avisar(err.message || "No se pudo cargar su panel.", "error"));
