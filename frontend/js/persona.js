/* El expediente de una persona, en una sola pantalla.

   Talento Humano y las jefaturas tenían los datos repartidos: la ficha en una
   pantalla, los períodos en otra, las solicitudes en una tercera y el
   historial de la hoja dentro de un diálogo del panel de cada quien. Para
   responder «¿cuándo tomó vacaciones Fulano y qué tiene pendiente?» había que
   ir a tres sitios y cruzarlos a mano.

   Se llega escribiendo el nombre en el buscador de la barra lateral. Quién
   puede ver a quién lo decide el servidor: un jefe ve a su gente y nada más,
   y probar direcciones a mano no le sirve de nada. */
import { api, sesion, esc, fecha, fechaHora, ESTADOS } from "./api.js";
import { montarNavegacion } from "./navegacion.js";
import { montarBuscador } from "./buscador.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");
if (!["jefe", "rrhh", "admin"].includes(sesion.perfil?.rol)) location.replace("dashboard.html");

montarNavegacion($("barra"), { activo: "panel" });

const ID = new URLSearchParams(location.search).get("id");

const numero = (v) => Number(v || 0).toLocaleString("es-EC",
  { minimumFractionDigits: 0, maximumFractionDigits: 2 });
const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

const PROCEDENCIA = {
  historico: ["Registro de Talento Humano", "bg-slate-100 text-slate-600 ring-slate-200"],
  solicitud: ["Solicitada aquí", "bg-emerald-50 text-emerald-700 ring-emerald-200"],
};

const TIPO = { vacacion: "Vacaciones", permiso: "Permiso" };

function pintarPersona(p, resumen, devengo) {
  $("iniciales").textContent =
    (p.nombre || "?").split(" ").map((x) => x[0]).slice(0, 2).join("");
  $("nombre").textContent = p.nombre;
  document.title = `${p.nombre} · Expediente`;
  $("puesto").textContent =
    [p.cargo, p.departamento].filter(Boolean).join(" · ") || "Sin cargo registrado";
  $("datos").textContent = [
    p.cedula,
    p.ciudad,
    p.jefe_nombre ? `Reporta a ${p.jefe_nombre}` : null,
    `Ingresó el ${fecha(p.fecha_ingreso)}`,
    // Que falte el correo no es un detalle: es quien no recibe avisos y
    // tiene que entrar por «primer ingreso».
    p.email || "Sin correo registrado",
  ].filter(Boolean).join(" · ");

  $("saldo").textContent = numero(p.saldo);
  $("saldo-pie").textContent = "días de vacaciones";
  $("antiguedad").textContent = plural(p.anios, "año", "años");
  $("veces").textContent = plural(resumen.veces, "vez", "veces");
  $("dias-gozados").textContent = `${numero(resumen.dias_gozados)} días en total`;
  $("en-tramite").textContent = plural(resumen.en_tramite, "solicitud", "solicitudes");
  $("fines-semana").textContent = p.fines_semana_pendientes ?? "—";

  if (devengo) {
    $("devengo").textContent =
      `Del año en curso lleva acumulados ${numero(devengo.devengado_hoja)} días: ` +
      `${devengo.meses_del_periodo} ${devengo.meses_del_periodo === 1 ? "mes" : "meses"} ` +
      `corridos a 1,25 al mes. De los años ya cumplidos tiene ` +
      `${numero(devengo.devengado_de_anios_cumplidos)} días asignados.`;
  }
}

function pintarVacaciones(lista) {
  if (!lista.length) {
    $("vacaciones").innerHTML =
      `<p class="rounded-xl bg-slate-50 p-4 text-center text-sm text-slate-500">
         No hay vacaciones registradas a su nombre.</p>`;
    return;
  }
  $("vacaciones").innerHTML = lista.map((v) => {
    const [etiqueta, clase] = PROCEDENCIA[v.procedencia] || PROCEDENCIA.historico;
    return `
    <div class="flex flex-wrap items-center gap-3 rounded-xl bg-slate-50 px-3 py-2.5">
      <div class="min-w-0 flex-1">
        <p class="text-sm font-medium">
          ${esc(fecha(v.fecha_inicio))} — ${esc(fecha(v.fecha_fin))}
        </p>
        <p class="text-xs text-slate-500">
          ${numero(v.dias)} ${v.dias === 1 ? "día" : "días"}${
            v.folio ? ` · solicitud Nº ${v.folio}` : ""}
        </p>
      </div>
      <span class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${clase}">
        ${etiqueta}
      </span>
    </div>`;
  }).join("");
}

function pintarSolicitudes(lista) {
  if (!lista.length) {
    $("solicitudes").innerHTML =
      `<p class="rounded-xl bg-slate-50 p-4 text-center text-sm text-slate-500">
         Todavía no ha pedido nada por el sistema.</p>`;
    return;
  }
  $("solicitudes").innerHTML = lista.map((s) => {
    const e = ESTADOS[s.estado] || { etiqueta: s.estado, clase: "bg-slate-100 text-slate-600 ring-slate-200" };
    const cuando = s.hora_inicio
      ? `${fecha(s.fecha_inicio)}, de ${String(s.hora_inicio).slice(0, 5)} a ${String(s.hora_fin).slice(0, 5)}`
      : `${fecha(s.fecha_inicio)} — ${fecha(s.fecha_fin)}`;
    return `
    <div class="flex flex-wrap items-center gap-3 rounded-xl bg-slate-50 px-3 py-2.5">
      <div class="min-w-0 flex-1">
        <p class="text-sm font-medium">
          Nº ${s.folio} · ${esc(TIPO[s.tipo] || s.tipo)}${
            s.subtipo ? ` · ${esc(s.subtipo)}` : ""}
        </p>
        <p class="text-xs text-slate-500">
          ${esc(cuando)}${s.dias_solicitados ? ` · ${numero(s.dias_solicitados)} días` : ""}
          · pedida el ${esc(fechaHora(s.created_at))}
        </p>
      </div>
      <span class="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ${e.clase}">
        ${esc(e.etiqueta)}
      </span>
    </div>`;
  }).join("");
}

function pintarPeriodos(lista) {
  if (!lista.length) {
    $("periodos").innerHTML = `<p class="text-sm text-slate-500">Sin períodos generados.</p>`;
    return;
  }
  $("periodos").innerHTML = `
    <table class="w-full text-sm">
      <thead>
        <tr class="border-b border-slate-200 text-left text-xs uppercase tracking-wide text-slate-500">
          <th class="py-2 pr-3">Año</th><th class="py-2 pr-3">Desde</th>
          <th class="py-2 pr-3">Hasta</th><th class="py-2 pr-3 text-right">Asignados</th>
          <th class="py-2 pr-3 text-right">Gozados</th><th class="py-2 text-right">Saldo</th>
        </tr>
      </thead>
      <tbody>
        ${lista.map((p) => `
          <tr class="border-b border-slate-100 ${p.caducado ? "text-slate-400" : ""}">
            <td class="py-2 pr-3 font-medium">${p.periodo}${
              p.devengado ? "" : ` <span class="text-xs font-normal text-slate-500">(en curso)</span>`}</td>
            <td class="py-2 pr-3">${esc(fecha(p.fecha_desde))}</td>
            <td class="py-2 pr-3">${esc(fecha(p.fecha_hasta))}</td>
            <td class="py-2 pr-3 text-right tabular-nums">${numero(p.dias_asignados)}</td>
            <td class="py-2 pr-3 text-right tabular-nums">${numero(p.dias_consumidos)}</td>
            <td class="py-2 text-right font-medium tabular-nums">${numero(p.dias_saldo)}</td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

async function cargar() {
  if (!ID) {
    $("cargando").classList.add("hidden");
    $("error").textContent = "No se indicó a quién abrir. Busque la persona en la barra lateral.";
    $("error").classList.remove("hidden");
    return;
  }
  try {
    const d = await api.expediente(ID);
    pintarPersona(d.persona, d.resumen, d.devengo);
    pintarVacaciones(d.vacaciones);
    pintarSolicitudes(d.solicitudes);
    pintarPeriodos(d.periodos);

    $("cargando").classList.add("hidden");
    $("contenido").classList.remove("hidden");

    montarBuscador({ campo: "buscar-vacaciones", contenedor: "vacaciones",
                     filas: ":scope > div", vacio: "vacaciones-vacio" });
    montarBuscador({ campo: "buscar-solicitudes", contenedor: "solicitudes",
                     filas: ":scope > div", vacio: "solicitudes-vacio" });
  } catch (e) {
    $("cargando").classList.add("hidden");
    $("error").textContent = e.message || "No se pudo abrir el expediente.";
    $("error").classList.remove("hidden");
  }
}

cargar();
