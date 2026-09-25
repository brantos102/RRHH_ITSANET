/* Calendario del equipo a cargo, mes a mes.

   Una fila por persona y una columna por día: es la forma en que un jefe
   mira de verdad la cobertura de su área —quién falta esta semana, quién
   queda, si se superponen—. Una lista de solicitudes no responde eso.

   Se muestra «Vacaciones» o «Permiso», nunca el subtipo: que alguien esté
   en cita médica es un dato de salud (LOPDP Art. 4) y no corresponde
   exhibirlo en una grilla. El jefe lo ve en la solicitud que autoriza. */
import { api, sesion, esc, fecha } from "./api.js";
import { montarNavegacion } from "./navegacion.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");
if (!["jefe", "rrhh", "admin"].includes(sesion.perfil?.rol)) location.replace("dashboard.html");

montarNavegacion($("barra"), { activo: "jefe" });

const esRRHH = ["rrhh", "admin"].includes(sesion.perfil.rol);
const DIAS = ["D", "L", "M", "M", "J", "V", "S"];
const estado = { mes: new Date(), datos: null, departamento: "" };

let temporizador;
function avisar(texto, error = false) {
  const el = $("aviso");
  el.textContent = texto;
  el.className = `fixed inset-x-0 bottom-5 z-50 mx-auto max-w-sm rounded-xl px-4 py-3 text-center text-sm shadow-lg ${
    error ? "bg-rose-600 text-white" : "bg-slate-900 text-white"}`;
  clearTimeout(temporizador);
  temporizador = setTimeout(() => el.classList.add("hidden"), 4500);
}

const iso = (d) => d.toISOString().slice(0, 10);
const primerDia = (d) => new Date(d.getFullYear(), d.getMonth(), 1);
const ultimoDia = (d) => new Date(d.getFullYear(), d.getMonth() + 1, 0);

async function cargar() {
  const desde = primerDia(estado.mes), hasta = ultimoDia(estado.mes);
  $("mes-actual").textContent = estado.mes.toLocaleDateString("es-EC", {
    month: "long", year: "numeric",
  });

  const params = new URLSearchParams({ desde: iso(desde), hasta: iso(hasta) });
  if (estado.departamento) params.set("departamento", estado.departamento);

  try {
    estado.datos = await api.calendarioEquipo(`?${params}`);
  } catch (err) {
    $("rejilla").innerHTML =
      `<p class="px-5 py-12 text-center text-sm text-rose-600">${esc(err.message)}</p>`;
    return;
  }

  if (esRRHH) llenarDepartamentos();
  pintar();
}

function llenarDepartamentos() {
  const select = $("departamento");
  if (select.options.length > 1) return;          // ya está llenado
  const areas = [...new Set((estado.datos.equipo || [])
    .map((p) => p.departamento).filter(Boolean))].sort();
  select.innerHTML = `<option value="">Todos los departamentos</option>` +
    areas.map((a) => `<option value="${esc(a)}">${esc(a)}</option>`).join("");
  $("filtro-departamento").classList.remove("hidden");
}

function pintar() {
  const { equipo, ausencias, feriados } = estado.datos;
  const desde = primerDia(estado.mes), hasta = ultimoDia(estado.mes);
  const total = hasta.getDate();
  const hoy = iso(new Date());
  const diasFeriados = new Map((feriados || []).map((f) => [f.fecha, f.nombre]));

  $("subtitulo").textContent = equipo.length
    ? `${equipo.length} persona(s) a su cargo · ${ausencias.length} ausencia(s) este mes`
    : "Todavía no hay nadie asignado a su cargo";

  if (!equipo.length) {
    $("rejilla").innerHTML =
      `<p class="px-5 py-12 text-center text-sm text-slate-500">
         Nadie tiene a esta persona registrada como jefe inmediato.
         Talento Humano lo asigna en Administración → Usuarios.</p>`;
    return;
  }

  // Ausencia por persona y día: se resuelve una vez, no por celda
  const porPersona = new Map(equipo.map((p) => [p.id, new Map()]));
  for (const a of ausencias) {
    const mapa = porPersona.get(a.user_id);
    if (!mapa) continue;
    const ini = new Date(`${a.fecha_inicio}T00:00:00`);
    const fin = new Date(`${a.fecha_fin}T00:00:00`);
    for (let d = new Date(ini); d <= fin; d.setDate(d.getDate() + 1)) {
      if (d >= desde && d <= hasta) mapa.set(iso(d), a);
    }
  }

  const color = (a) => {
    const aprobada = a.estado === "aprobado";
    if (a.motivo_general === "Vacaciones") return aprobada ? "bg-emerald-400" : "bg-emerald-200";
    return aprobada ? "bg-sky-400" : "bg-sky-200";
  };

  const encabezado = Array.from({ length: total }, (_, i) => {
    const d = new Date(desde.getFullYear(), desde.getMonth(), i + 1);
    const finDeSemana = d.getDay() === 0 || d.getDay() === 6;
    const feriado = diasFeriados.has(iso(d));
    return `<th class="px-0 py-1.5 text-center text-[11px] font-normal ${
      feriado ? "bg-slate-200 text-slate-600" : finDeSemana ? "bg-slate-50 text-slate-400" : "text-slate-500"
    }" ${feriado ? `title="${esc(diasFeriados.get(iso(d)))}"` : ""}>
      <span class="block font-medium ${iso(d) === hoy ? "text-cyan-600" : ""}">${i + 1}</span>
      <span class="block">${DIAS[d.getDay()]}</span></th>`;
  }).join("");

  const filas = equipo.map((persona) => {
    const mapa = porPersona.get(persona.id);
    const celdas = Array.from({ length: total }, (_, i) => {
      const clave = iso(new Date(desde.getFullYear(), desde.getMonth(), i + 1));
      const a = mapa.get(clave);
      const d = new Date(`${clave}T00:00:00`);
      const finDeSemana = d.getDay() === 0 || d.getDay() === 6;
      const fondo = a ? color(a)
        : diasFeriados.has(clave) ? "bg-slate-200"
        : finDeSemana ? "bg-slate-50" : "";
      return `<td class="border-l border-slate-100 p-0">
        <button type="button" class="block h-8 w-full ${fondo}"
                ${a ? `data-solicitud="${a.request_id}" title="${esc(persona.nombre)} · ${
                  esc(a.motivo_general)} · Nº ${a.folio}"` : "disabled"}></button></td>`;
    }).join("");

    return `<tr class="border-t border-slate-100">
      <th scope="row" class="sticky left-0 z-10 min-w-[11rem] bg-white px-3 py-1.5 text-left text-sm font-normal">
        <span class="block truncate font-medium text-slate-800">${esc(persona.nombre)}</span>
        <span class="block truncate text-xs text-slate-500">${esc(persona.cargo || "")}</span>
      </th>${celdas}</tr>`;
  }).join("");

  $("rejilla").innerHTML = `
    <table class="w-full border-collapse">
      <thead class="bg-white"><tr>
        <th class="sticky left-0 z-10 min-w-[11rem] bg-white px-3 py-1.5 text-left text-xs font-medium text-slate-500">
          Colaborador</th>${encabezado}
      </tr></thead>
      <tbody>${filas}</tbody>
    </table>`;
}

/* Al pulsar un bloque se muestra el detalle: el jefe necesita saber quién
   cubre y si Talento Humano ya lo ajustó, no solo que hay un hueco. */
$("rejilla").addEventListener("click", (e) => {
  const celda = e.target.closest("[data-solicitud]");
  if (!celda) return;
  const a = estado.datos.ausencias.find((x) => x.request_id === celda.dataset.solicitud);
  if (!a) return;

  const horas = a.hora_inicio ? ` · de ${a.hora_inicio} a ${a.hora_fin}` : "";
  $("detalle").innerHTML = `
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p class="font-semibold">${esc(a.nombre)}
          <span class="ml-1.5 rounded-md bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-slate-600">Nº ${a.folio}</span>
        </p>
        <p class="text-sm text-slate-500">${esc(a.cargo || "")}${
          a.departamento ? " · " + esc(a.departamento) : ""}</p>
      </div>
      <span class="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
        ${esc(a.motivo_general)} · ${esc(a.estado.replace("_", " "))}</span>
    </div>
    <dl class="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
      <div><dt class="text-xs text-slate-500">Desde</dt><dd class="font-medium">${fecha(a.fecha_inicio)}</dd></div>
      <div><dt class="text-xs text-slate-500">Hasta</dt><dd class="font-medium">${fecha(a.fecha_fin)}${horas}</dd></div>
      <div><dt class="text-xs text-slate-500">Días</dt><dd class="font-medium">${a.dias_solicitados}</dd></div>
      <div><dt class="text-xs text-slate-500">Lo cubre</dt>
           <dd class="font-medium">${a.reemplazo_nombre ? esc(a.reemplazo_nombre) : "— sin asignar"}</dd></div>
    </dl>
    ${a.ajustada_en
      ? `<p class="mt-3 rounded-xl bg-amber-50 p-3 text-xs text-amber-900 ring-1 ring-amber-200">
           Talento Humano ajustó estas fechas el ${fecha(a.ajustada_en)}. Las mostradas son las vigentes.</p>`
      : ""}
    <div id="historial-ajustes" class="mt-3"></div>
    ${esRRHH && a.estado === "aprobado"
      ? `<button type="button" data-ajustar="${a.request_id}"
                 class="mt-4 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-800">
           Ajustar esta ausencia
         </button>`
      : ""}`;
  $("detalle").classList.remove("hidden");
  $("detalle").scrollIntoView({ behavior: "smooth", block: "nearest" });
  if (a.ajustada_en) mostrarHistorial(a.request_id);
});

/* --------------------------------------------- ajustes de Talento Humano */
async function mostrarHistorial(solicitudId) {
  try {
    const ajustes = await api.ajustesDe(solicitudId);
    const caja = $("historial-ajustes");
    if (!caja || !ajustes.length) return;
    caja.innerHTML = `
      <p class="mb-1.5 text-xs font-medium text-slate-500">Historial de ajustes</p>
      <ul class="space-y-2">${ajustes.map((x) => `
        <li class="rounded-xl bg-slate-50 p-3 text-xs leading-relaxed text-slate-700">
          <span class="font-medium">${fecha(x.created_at)} · ${esc(x.ajustado_por)}</span><br>
          ${fecha(x.fecha_inicio_ant, false)} – ${fecha(x.fecha_fin_ant)}
          (${x.dias_ant} días) → ${fecha(x.fecha_inicio_nueva, false)} – ${fecha(x.fecha_fin_nueva)}
          (${x.dias_nuevos} días)<br>
          <span class="text-slate-500">Caso:</span> ${esc(x.motivo)}<br>
          <span class="text-slate-500">Resolución:</span> ${esc(x.resolucion)}
        </li>`).join("")}</ul>`;
  } catch { /* el historial es complementario: su ausencia no rompe la vista */ }
}

$("detalle").addEventListener("click", (e) => {
  const boton = e.target.closest("[data-ajustar]");
  if (!boton) return;
  const a = estado.datos.ausencias.find((x) => x.request_id === boton.dataset.ajustar);
  if (!a) return;

  $("form-ajuste").dataset.id = a.request_id;
  $("ajuste-de").textContent =
    `${a.nombre} · Nº ${a.folio} · hoy rige del ${fecha(a.fecha_inicio, false)} al ${fecha(a.fecha_fin)}`;
  $("ajuste-inicio").value = a.fecha_inicio;
  $("ajuste-fin").value = a.fecha_fin;
  $("ajuste-motivo").value = "";
  $("ajuste-resolucion").value = "";
  $("error-ajuste").classList.add("hidden");
  $("modal-ajuste").showModal();
});

document.querySelectorAll("[data-cerrar-ajuste]").forEach((b) =>
  b.addEventListener("click", () => $("modal-ajuste").close())
);

$("form-ajuste").addEventListener("submit", async (e) => {
  e.preventDefault();
  const error = $("error-ajuste");
  const motivo = $("ajuste-motivo").value.trim();
  const resolucion = $("ajuste-resolucion").value.trim();

  if (motivo.length < 15 || resolucion.length < 15) {
    error.textContent = "Explique el caso y la resolución: al menos 15 caracteres cada uno. " +
                        "Quien lea esto mañana necesita entender qué pasó.";
    return error.classList.remove("hidden");
  }

  try {
    const r = await api.ajustarAusencia($("form-ajuste").dataset.id, {
      fecha_inicio: $("ajuste-inicio").value,
      fecha_fin: $("ajuste-fin").value,
      motivo, resolucion,
    });
    $("modal-ajuste").close();
    avisar(r.mensaje);
    $("detalle").classList.add("hidden");
    await cargar();
  } catch (err) {
    error.textContent = err.message;
    error.classList.remove("hidden");
  }
});

$("mes-anterior").addEventListener("click", () => {
  estado.mes = new Date(estado.mes.getFullYear(), estado.mes.getMonth() - 1, 1);
  $("detalle").classList.add("hidden");
  cargar();
});
$("mes-siguiente").addEventListener("click", () => {
  estado.mes = new Date(estado.mes.getFullYear(), estado.mes.getMonth() + 1, 1);
  $("detalle").classList.add("hidden");
  cargar();
});
$("departamento").addEventListener("change", (e) => {
  estado.departamento = e.target.value;
  cargar();
});

cargar().catch((err) => avisar(err.message, true));
