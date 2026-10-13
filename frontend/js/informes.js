/* Informes: filtros combinables, tabla ordenable y descarga en CSV. */
import { api, sesion, esc, fecha } from "./api.js";
import { montarNavegacion } from "./navegacion.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");
if (!["jefe", "rrhh", "admin"].includes(sesion.perfil?.rol)) location.replace("dashboard.html");

montarNavegacion($("barra"), { activo: "informes" });

const estado = { filas: [], pagina: 1, orden: "folio", ascendente: false };

let temporizador;
const avisar = (texto, error = false) => {
  const el = $("aviso");
  el.textContent = texto;
  el.className = `max-w-sm rounded-xl px-4 py-3 text-center text-sm shadow-lg ${
    error ? "bg-rose-600 text-white" : "bg-slate-900 text-white"}`;
  clearTimeout(temporizador);
  temporizador = setTimeout(() => el.classList.add("hidden"), 4000);
};

const ESTADO_TEXTO = {
  pendiente_jefe: "Pendiente del jefe",
  pendiente_rrhh: "Pendiente de Talento Humano",
  pendiente_anulacion: "Anulación en trámite",
  aprobado: "Autorizado",
  rechazado: "Rechazado",
  cancelado: "Anulado",
};

const COLUMNAS = [
  { clave: "folio", titulo: "Nº", ancho: "w-16" },
  { clave: "fecha_solicitud", titulo: "Solicitada", formato: (v) => fecha(v) },
  { clave: "solicitante", titulo: "Solicitante" },
  { clave: "cedula", titulo: "Cédula" },
  { clave: "departamento", titulo: "Departamento" },
  { clave: "cargo", titulo: "Cargo" },
  { clave: "tipo_detalle", titulo: "Tipo" },
  { clave: "fecha_inicio", titulo: "Desde", formato: (v) => fecha(v, false) },
  { clave: "fecha_fin", titulo: "Hasta", formato: (v) => fecha(v) },
  { clave: "dias_solicitados", titulo: "Días", numerico: true },
  { clave: "jefe", titulo: "Jefe" },
  { clave: "rrhh", titulo: "Talento Humano" },
  { clave: "estado", titulo: "Estado", chip: true },
];

/* ------------------------------------------------------------ dimensiones */
function llenar(select, valores, etiqueta = (v) => v, valor = (v) => v) {
  select.innerHTML = valores
    .map((v) => `<option value="${esc(String(valor(v)))}">${esc(String(etiqueta(v)))}</option>`)
    .join("");
}

async function cargarDimensiones() {
  try {
    const d = await api.dimensiones();
    llenar($("f-campo"), d.campos_fecha, (c) => c.etiqueta, (c) => c.valor);
    llenar($("f-estado"), d.estados, (e) => ESTADO_TEXTO[e] || e);
    llenar($("f-tipo"), d.tipos, (t) => (t === "vacacion" ? "Vacaciones" : "Permisos"));
    llenar($("f-departamento"), d.departamentos);
    llenar($("f-cargo"), d.cargos);
    llenar($("f-solicitante"), d.personas, (p) => p.nombre, (p) => p.nombre);
    llenar($("f-jefe"), d.jefes, (p) => p.nombre, (p) => p.nombre);
  } catch (err) {
    avisar(err.message, true);
  }
}

/* ---------------------------------------------------------------- filtros */
function elegidos(id) {
  return [...$(id).selectedOptions].map((o) => o.value);
}

function construirParametros() {
  const p = new URLSearchParams();
  const folio = $("f-folio").value.trim();
  if (folio) {
    p.set("folio", folio);
    return p;                       // el número manda sobre el resto
  }
  p.set("campo_fecha", $("f-campo").value);
  if ($("f-desde").value) p.set("desde", $("f-desde").value);
  if ($("f-hasta").value) p.set("hasta", $("f-hasta").value);
  if ($("f-cedula").value.trim()) p.set("cedula", $("f-cedula").value.trim());
  for (const [campo, id] of [
    ["estado", "f-estado"], ["tipo", "f-tipo"], ["departamento", "f-departamento"],
    ["cargo", "f-cargo"], ["solicitante", "f-solicitante"], ["jefe", "f-jefe"],
  ]) {
    elegidos(id).forEach((v) => p.append(campo, v));
  }
  return p;
}

$("filtros").addEventListener("submit", async (e) => {
  e.preventDefault();
  const parametros = construirParametros();
  try {
    const r = await api.informe(parametros.toString());
    estado.filas = r.filas;
    estado.pagina = 1;
    pintarResumen(r.resumen);
    pintarTabla();
  } catch (err) {
    avisar(err.message, true);
  }
});

$("btn-limpiar").addEventListener("click", () => {
  $("filtros").reset();
  [...document.querySelectorAll("select[multiple]")].forEach(
    (s) => [...s.options].forEach((o) => (o.selected = false))
  );
});

/* La descarga lleva el token, así que se pide con fetch y se guarda como blob:
   un enlace normal iría sin cabecera de sesión y el servidor lo rechazaría.

   Los tres formatos salen del mismo informe filtrado, para que lo descargado
   sea exactamente lo que se está viendo. */
const NOMBRE_FORMATO = { pdf: "PDF", xlsx: "Excel", csv: "CSV" };

async function descargar(formato) {
  const boton = document.querySelector(`[data-descargar="${formato}"]`);
  const antes = boton.textContent;
  boton.disabled = true;
  boton.textContent = "…";
  try {
    const respuesta = await fetch(
      `${api.base}/informes/solicitudes.${formato}?${construirParametros()}`,
      { headers: { Authorization: `Bearer ${sesion.token}` } });
    if (!respuesta.ok) throw new Error("No se pudo generar el archivo.");

    // El nombre lo pone el servidor, que sabe la fecha y el tipo de informe.
    const cabecera = respuesta.headers.get("content-disposition") || "";
    const nombre = /filename="([^"]+)"/.exec(cabecera)?.[1]
      || `solicitudes-${new Date().toISOString().slice(0, 10)}.${formato}`;

    const url = URL.createObjectURL(await respuesta.blob());
    const enlace = Object.assign(document.createElement("a"), { href: url, download: nombre });
    enlace.click();
    URL.revokeObjectURL(url);
    avisar(`${NOMBRE_FORMATO[formato]} descargado: ${nombre}`);
  } catch (err) {
    avisar(err.message, true);
  } finally {
    boton.disabled = false;
    boton.textContent = antes;
  }
}

document.querySelectorAll("[data-descargar]").forEach((boton) =>
  boton.addEventListener("click", () => descargar(boton.dataset.descargar)));

/* ---------------------------------------------------------------- resumen */
function pintarResumen(r) {
  const tarjetas = [
    ["Solicitudes", r.total, "text-slate-900"],
    ["Autorizadas", r.aprobadas, "text-emerald-700"],
    ["Rechazadas", r.rechazadas, "text-rose-700"],
    ["Días autorizados", r.dias_aprobados, "text-slate-900"],
  ];
  $("resumen").className = "mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4";
  $("resumen").innerHTML = tarjetas
    .map(([titulo, valor, color]) => `
      <article class="rounded-2xl bg-white p-4 ring-1 ring-slate-200">
        <p class="text-xs font-medium uppercase tracking-wide text-slate-500">${esc(titulo)}</p>
        <p class="mt-1 text-2xl font-semibold tabular-nums ${color}">${valor}</p>
      </article>`).join("");
}

/* ------------------------------------------------------------------ tabla */
function filasVisibles() {
  const termino = ($("buscar-tabla").value || "").trim().toLowerCase();
  let filas = termino
    ? estado.filas.filter((f) =>
        Object.values(f).some((v) => String(v ?? "").toLowerCase().includes(termino)))
    : [...estado.filas];

  filas.sort((a, b) => {
    const x = a[estado.orden], y = b[estado.orden];
    const cmp = x === y ? 0 : (x ?? "") > (y ?? "") ? 1 : -1;
    return estado.ascendente ? cmp : -cmp;
  });
  return filas;
}

function pintarTabla() {
  const filas = filasVisibles();
  const porPagina = Number($("por-pagina").value);
  const paginas = Math.max(1, Math.ceil(filas.length / porPagina));
  estado.pagina = Math.min(estado.pagina, paginas);
  const desde = (estado.pagina - 1) * porPagina;
  const pagina = filas.slice(desde, desde + porPagina);

  if (!estado.filas.length) {
    $("tabla").innerHTML = `<p class="px-5 py-10 text-center text-sm text-slate-500">
        Elija los filtros y pulse «Filtrar».</p>`;
    $("paginacion").innerHTML = "";
    return;
  }

  $("tabla").innerHTML = `
    <table class="w-full text-left text-sm">
      <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
        <tr>${COLUMNAS.map((c) => `
          <th class="whitespace-nowrap px-3 py-2.5 ${c.ancho || ""}">
            <button data-ordenar="${c.clave}" class="flex items-center gap-1 hover:text-slate-900">
              ${esc(c.titulo)}
              <span class="opacity-40">${estado.orden === c.clave ? (estado.ascendente ? "▲" : "▼") : "⇅"}</span>
            </button>
          </th>`).join("")}</tr>
      </thead>
      <tbody class="divide-y divide-slate-100">
        ${pagina.map((f) => `<tr class="hover:bg-slate-50">
          ${COLUMNAS.map((c) => {
            const valor = f[c.clave];
            if (c.chip) {
              const tono = valor === "aprobado" ? "bg-emerald-100 text-emerald-800"
                : valor === "rechazado" ? "bg-rose-100 text-rose-800"
                : valor === "cancelado" ? "bg-slate-100 text-slate-600"
                : "bg-amber-100 text-amber-800";
              return `<td class="px-3 py-2.5"><span class="whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${tono}">
                        ${esc(ESTADO_TEXTO[valor] || valor)}</span></td>`;
            }
            const texto = c.formato ? c.formato(valor) : (valor ?? "—");
            return `<td class="px-3 py-2.5 ${c.numerico ? "tabular-nums" : ""} whitespace-nowrap">${esc(String(texto))}</td>`;
          }).join("")}
        </tr>`).join("")}
      </tbody>
    </table>`;

  $("paginacion").innerHTML = `
    <p class="text-sm text-slate-500">
      Mostrando ${filas.length ? desde + 1 : 0}–${Math.min(desde + porPagina, filas.length)} de ${filas.length}
    </p>
    <div class="flex items-center gap-1">
      <button data-pagina="${estado.pagina - 1}" ${estado.pagina === 1 ? "disabled" : ""}
              class="rounded-lg px-3 py-1.5 text-sm ring-1 ring-slate-200 disabled:opacity-40">Anterior</button>
      <span class="px-2 text-sm text-slate-600">${estado.pagina} / ${paginas}</span>
      <button data-pagina="${estado.pagina + 1}" ${estado.pagina >= paginas ? "disabled" : ""}
              class="rounded-lg px-3 py-1.5 text-sm ring-1 ring-slate-200 disabled:opacity-40">Siguiente</button>
    </div>`;
}

document.addEventListener("click", (e) => {
  const ordenar = e.target.closest("[data-ordenar]");
  if (ordenar) {
    const clave = ordenar.dataset.ordenar;
    estado.ascendente = estado.orden === clave ? !estado.ascendente : true;
    estado.orden = clave;
    return pintarTabla();
  }
  const pagina = e.target.closest("[data-pagina]");
  if (pagina && !pagina.disabled) {
    estado.pagina = Number(pagina.dataset.pagina);
    pintarTabla();
  }
});

$("buscar-tabla").addEventListener("input", () => { estado.pagina = 1; pintarTabla(); });
$("por-pagina").addEventListener("change", () => { estado.pagina = 1; pintarTabla(); });

/* --------------------------------------------------------------- arranque */
const hoy = new Date();
$("f-hasta").value = hoy.toISOString().slice(0, 10);
$("f-desde").value = new Date(hoy.getFullYear(), 0, 1).toISOString().slice(0, 10);

cargarDimensiones().then(() => $("filtros").requestSubmit());
pintarTabla();

/* ------------------------------------------------- informe por departamento

   Estaba en el menú de Informes y no existía: el enlace llevaba a esta
   pantalla y no pasaba nada, que es peor que no tener la opción. El backend
   ya servía el resumen desde hacía tiempo y ninguna pantalla lo consumía.

   Responde a la pregunta que se hace al planificar el año: en qué meses se
   vacía cada área. Por eso es una cuadrícula de departamentos por meses y no
   una lista: lo que se busca son las casillas cargadas, y eso se ve de un
   vistazo o no se ve. */

const MES_CORTO = ["ene", "feb", "mar", "abr", "may", "jun",
                   "jul", "ago", "sep", "oct", "nov", "dic"];

async function pintarDepartamentos() {
  const anio = Number($("anio-departamentos").value) || new Date().getFullYear();
  const caja = $("tabla-departamentos");
  caja.innerHTML = `<p class="px-5 py-10 text-center text-sm text-slate-500">Cargando…</p>`;

  let filas;
  try {
    filas = await api.resumenDepartamentos(anio);
  } catch (e) {
    caja.innerHTML = `<p class="px-5 py-10 text-center text-sm text-rose-600">${
      esc(e.message || "No se pudo cargar el resumen.")}</p>`;
    return;
  }

  if (!filas.length) {
    caja.innerHTML = `<p class="px-5 py-10 text-center text-sm text-slate-500">
      No hay ausencias aprobadas en ${anio}.</p>`;
    return;
  }

  const areas = [...new Set(filas.map((f) => f.departamento))].sort();
  const porArea = new Map(areas.map((a) => [a, new Array(12).fill(0)]));
  for (const f of filas) {
    const mes = Number(String(f.mes).slice(5, 7)) - 1;
    if (mes >= 0 && mes < 12) porArea.get(f.departamento)[mes] += Number(f.dias || 0);
  }

  const totalMes = new Array(12).fill(0);
  for (const dias of porArea.values()) dias.forEach((d, i) => { totalMes[i] += d; });
  const mayor = Math.max(1, ...[...porArea.values()].flat());

  // El tono crece con los días: una tabla de números iguales no enseña dónde
  // está el problema, y lo que se busca aquí es precisamente el mes cargado.
  const tono = (d) => {
    if (!d) return "";
    const parte = d / mayor;
    if (parte > 0.66) return "bg-amber-200 font-semibold text-amber-900";
    if (parte > 0.33) return "bg-amber-100 text-amber-900";
    return "bg-amber-50 text-slate-700";
  };
  const num = (d) => d ? Number(d).toLocaleString("es-EC",
    { minimumFractionDigits: 0, maximumFractionDigits: 1 }) : "";

  caja.innerHTML = `
    <table class="w-full text-sm">
      <thead class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
        <tr>
          <th class="sticky left-0 z-10 bg-slate-50 px-3 py-2.5 text-left">Departamento</th>
          ${MES_CORTO.map((m) => `<th class="px-2 py-2.5 text-center">${m}</th>`).join("")}
          <th class="px-3 py-2.5 text-right">Total</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-slate-100">
        ${areas.map((a) => {
          const dias = porArea.get(a);
          const total = dias.reduce((s, d) => s + d, 0);
          return `<tr class="hover:bg-slate-50">
            <th scope="row" class="sticky left-0 z-10 bg-white px-3 py-2 text-left font-medium
                                   hover:bg-slate-50">${esc(a)}</th>
            ${dias.map((d, i) => `<td class="px-2 py-2 text-center tabular-nums ${tono(d)}"
                 title="${esc(a)} · ${MES_CORTO[i]} ${anio}${d ? ` · ${num(d)} días` : ""}"
                 >${num(d)}</td>`).join("")}
            <td class="px-3 py-2 text-right font-semibold tabular-nums">${num(total)}</td>
          </tr>`;
        }).join("")}
      </tbody>
      <tfoot class="border-t-2 border-slate-200 bg-slate-50 text-sm font-medium">
        <tr>
          <th scope="row" class="sticky left-0 z-10 bg-slate-50 px-3 py-2.5 text-left">Todos</th>
          ${totalMes.map((d) => `<td class="px-2 py-2.5 text-center tabular-nums">${num(d)}</td>`).join("")}
          <td class="px-3 py-2.5 text-right tabular-nums">${
            num(totalMes.reduce((s, d) => s + d, 0))}</td>
        </tr>
      </tfoot>
    </table>
    <p class="px-5 py-3 text-xs text-slate-500">
      Días de ausencia aprobados. Cuanto más cargado el tono, más se vacía esa área ese mes.
    </p>`;
}

/* Se llega por «Informes → Por departamento», que es un enlace con «#». Hay
   que atender también el cambio de fragmento: estando ya en esta pantalla, el
   navegador no recarga nada y el enlace no haría absolutamente nada. */
function mostrarDepartamentos(mostrar) {
  $("departamentos").classList.toggle("hidden", !mostrar);
  // El detalle se esconde mientras tanto: son dos informes distintos y verlos
  // a la vez obliga a desplazar para entender cuál se está mirando.
  document.querySelectorAll("main > section").forEach((s) => {
    if (s.id !== "departamentos") s.classList.toggle("hidden", mostrar);
  });
  if (mostrar) pintarDepartamentos();
  else if (location.hash === "#departamentos") history.replaceState(null, "", location.pathname);
}

(function montarDepartamentos() {
  const anio = new Date().getFullYear();
  $("anio-departamentos").innerHTML = [anio, anio - 1, anio - 2, anio - 3]
    .map((a) => `<option value="${a}">${a}</option>`).join("");
  $("anio-departamentos").addEventListener("change", pintarDepartamentos);
  $("btn-cerrar-departamentos").addEventListener("click", () => mostrarDepartamentos(false));

  const revisar = () => mostrarDepartamentos(location.hash === "#departamentos");
  window.addEventListener("hashchange", revisar);
  revisar();
})();
