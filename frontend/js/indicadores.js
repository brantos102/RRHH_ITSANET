/* El tablero de indicadores, por bloques que se encienden y se apagan.

   Lo que se muestra son AGREGADOS. Ningún nombre: «cuántos están de
   vacaciones» es un número, y quién está es el calendario del equipo, que
   tiene sus propios permisos. Un tablero que enseña nombres a quien no le
   toca es una fuga de datos con buena presentación.

   Cada cifra lleva debajo la pregunta que contesta. Un indicador que hay que
   ir a preguntar qué mide no se usa: se mira una vez y se ignora el resto
   del año. */
import { api, sesion, esc, fechaHora } from "./api.js";
import { montarNavegacion } from "./navegacion.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");
if (!["rrhh", "admin"].includes(sesion.perfil?.rol)) location.replace("dashboard.html");

montarNavegacion($("barra"), { activo: "indicadores" });

let temporizador;
const avisar = (texto, error = false) => {
  const caja = $("aviso");
  $("aviso-texto").textContent = texto;
  $("aviso-texto").className =
    `mx-auto max-w-md rounded-2xl px-4 py-3 text-center text-sm shadow-lg ${
      error ? "bg-rose-600 text-white" : "bg-slate-900 text-white"}`;
  caja.classList.remove("hidden");
  clearTimeout(temporizador);
  temporizador = setTimeout(() => caja.classList.add("hidden"), 4500);
};

document.addEventListener("click", (e) => {
  if (e.target.closest("[data-cerrar]")) e.target.closest("dialog")?.close();
});

const numero = (n) =>
  n === null || n === undefined ? "—" : Number(n).toLocaleString("es-EC");

/* «1 personas» en un tablero de dirección se lee como descuido, y el
   descuido se contagia a la confianza en la cifra de al lado. */
const plural = (n, singular, pluralTexto) =>
  `${numero(n)} ${Number(n) === 1 ? singular : pluralTexto}`;

/* Cómo se lee cada indicador debajo de su cifra. Es lo que convierte un
   número en una decisión: «15 sin jefe» no dice nada; «15 de 351, y 2 con
   solicitudes esperando» dice qué hacer esta semana. */
const DETALLE = {
  ausentes_hoy: (d) =>
    [`${numero(d.vacaciones)} de vacaciones`, `${numero(d.permisos)} con permiso`,
     `de ${numero(d.de)} activos`],
  activos: (d) =>
    [`${numero(d.altas)} altas en ${d.meses} meses`, `${numero(d.bajas)} bajas`],
  por_aprobar: (d) => [
    `${numero(d.con_jefe)} esperan al jefe`,
    `${numero(d.en_rrhh)} en Talento Humano`,
    d.sin_jefe
      ? `${numero(d.sin_jefe)} sin jefe asignado: ${d.sin_jefe === 1 ? "la resuelve" : "las resuelve"} usted`
      : null,
    d.atrasadas ? `${numero(d.atrasadas)} llevan más de ${d.dias_alerta} días` : null,
    d.la_mas_vieja ? `la más vieja, ${numero(d.la_mas_vieja)} días` : null,
  ],
  sin_jefe: (d) => [
    `de ${numero(d.de)} activos`,
    d.con_solicitudes_abiertas
      ? plural(d.con_solicitudes_abiertas, "solicitud suya está esperando",
               "solicitudes suyas están esperando")
      : "ninguna solicitud suya está esperando",
  ],
  pasivo: (d) => [
    plural(d.personas, "persona con saldo", "personas con saldo"),
    `${numero(d.promedio)} de promedio`,
    `${numero(d.pasan_del_umbral)} pasan de ${numero(d.umbral)} días`,
    `el más alto, ${numero(d.el_mas_alto)}`,
  ],
  crecimiento: (d) => {
    const meses = d.meses || [];
    const ultimo = meses[meses.length - 1];
    return [
      `${meses.length} meses`,
      ultimo ? `último mes: ${numero(ultimo.altas)} altas, ${numero(ultimo.bajas)} bajas` : null,
    ];
  },
  por_area: (d) => (d.areas || []).slice(0, 4).map(
    (a) => `${a.area}: ${plural(a.personas, "persona", "personas")} · ` +
           `${plural(a.dias, "día", "días")}`),
  expedientes: (d) => [
    `${numero(d.sin_correo)} sin correo que reciba avisos`,
    `${numero(d.sin_jefe)} sin jefe`,
    `${numero(d.ficha_incompleta)} con la ficha sin completar`,
    `de ${numero(d.de)} activos`,
  ],
  papeles: (d) => [
    `${numero(d.trazabilidad)} constancias de goce`,
    `${numero(d.solicitud)} formularios de solicitud`,
    `de ${numero(d.emitidos)} emitidos`,
  ],
};

/* Una barra por mes para el crecimiento. Sin librería: son doce barras y
   traer un gráficador entero para esto sería cargar 200 kB en una red de
   bodega para dibujar doce rectángulos. */
function barras(meses) {
  const tope = Math.max(1, ...meses.map((m) => Math.max(m.altas, m.bajas)));
  return `
    <div class="mt-3 flex items-end gap-1" style="height:72px">
      ${meses.map((m) => `
        <div class="flex flex-1 flex-col items-center gap-0.5" title="${esc(m.mes)}: ${m.altas} altas, ${m.bajas} bajas">
          <div class="flex w-full items-end justify-center gap-px" style="height:56px">
            <div class="w-1/2 rounded-t bg-slate-900" style="height:${(m.altas / tope) * 100}%"></div>
            <div class="w-1/2 rounded-t bg-rose-400" style="height:${(m.bajas / tope) * 100}%"></div>
          </div>
          <span class="text-[9px] text-slate-400">${esc(m.mes.slice(5))}</span>
        </div>`).join("")}
    </div>
    <p class="mt-1 text-xs text-slate-400">
      <span class="inline-block h-2 w-2 rounded-sm bg-slate-900"></span> altas ·
      <span class="inline-block h-2 w-2 rounded-sm bg-rose-400"></span> bajas</p>`;
}

function tarjeta(b) {
  const d = b.detalle || {};
  const lineas = (DETALLE[b.clave]?.(d) || []).filter(Boolean);
  return `
    <article class="rounded-2xl bg-white p-5 shadow-sm ring-1 ring-slate-200
                    ${b.clave === "crecimiento" ? "sm:col-span-2" : ""}">
      <p class="text-sm font-medium text-slate-600">${esc(b.titulo)}</p>
      <p class="mt-1 text-3xl font-semibold tabular-nums">${numero(b.cifra)}</p>
      <p class="mt-0.5 text-xs text-slate-400">${esc(b.pregunta)}</p>
      ${b.error
        ? `<p class="mt-2 text-xs text-rose-700">${esc(b.error)}</p>`
        : `<ul class="mt-3 space-y-1 text-sm text-slate-600">
             ${lineas.map((l) => `<li>${esc(l)}</li>`).join("")}
           </ul>`}
      ${b.clave === "crecimiento" && (d.meses || []).length ? barras(d.meses) : ""}
    </article>`;
}

async function cargar() {
  try {
    const r = await api.tablero();
    $("calculado-en").textContent = `· ${fechaHora(r.calculado_en)}`;
    $("tablero").innerHTML = r.bloques.length
      ? r.bloques.map(tarjeta).join("")
      : `<p class="rounded-2xl bg-white p-8 text-center text-sm text-slate-500 ring-1 ring-slate-200
                   sm:col-span-2 lg:col-span-3">
           No hay ningún indicador encendido. Pulse «Configurar» para elegir cuáles ver.</p>`;
  } catch (err) {
    $("tablero").innerHTML =
      `<p class="rounded-2xl bg-white p-8 text-center text-sm text-rose-700 ring-1 ring-rose-200
                 sm:col-span-2 lg:col-span-3">${esc(err.message)}</p>`;
  }
}

/* ------------------------------------------------------------ configurar */
const AJUSTES = {
  activos: { meses: ["Meses de historia", 1, 60] },
  por_aprobar: { dias_alerta: ["Días para considerarla atrasada", 1, 90] },
  pasivo: { umbral_persona: ["Días a partir de los cuales preocupa", 1, 400] },
  crecimiento: { meses: ["Meses de historia", 1, 60] },
  por_area: { cuantas: ["Cuántas áreas listar", 1, 50] },
};

async function cargarConfiguracion() {
  const bloques = await api.tableroConfiguracion();
  $("lista-config").innerHTML = bloques.map((b) => `
    <div class="px-5 py-4">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="min-w-0 flex-1">
          <label class="flex items-start gap-2.5">
            <input type="checkbox" data-visible="${esc(b.clave)}" ${b.visible ? "checked" : ""}
                   class="mt-0.5 h-4 w-4 rounded border-slate-300">
            <span>
              <span class="font-medium">${esc(b.titulo)}</span>
              <span class="mt-0.5 block text-sm text-slate-600">${esc(b.descripcion)}</span>
            </span>
          </label>
        </div>
        <input type="number" data-orden="${esc(b.clave)}" value="${b.orden}" min="0" max="999"
               title="Orden en la pantalla"
               class="w-20 rounded-xl border-0 bg-slate-50 px-3 py-2 text-right text-sm
                      ring-1 ring-slate-300 focus:bg-white focus:ring-2 focus:ring-slate-900">
      </div>
      ${Object.entries(AJUSTES[b.clave] || {}).map(([nombre, [etiqueta, min, max]]) => `
        <label class="mt-2.5 flex items-center gap-2 pl-7 text-sm text-slate-600">
          ${esc(etiqueta)}
          <input type="number" data-ajuste="${esc(b.clave)}" data-nombre="${esc(nombre)}"
                 value="${esc(b.ajustes?.[nombre] ?? "")}" min="${min}" max="${max}"
                 class="w-24 rounded-xl border-0 bg-slate-50 px-3 py-1.5 text-right
                        ring-1 ring-slate-300 focus:bg-white focus:ring-2 focus:ring-slate-900">
        </label>`).join("")}
      ${b.actualizado_en
        ? `<p class="mt-2 pl-7 text-xs text-slate-400">
             Lo cambió ${esc(b.actualizado_por || "alguien que ya no está")}
             el ${fechaHora(b.actualizado_en)}.</p>`
        : ""}
    </div>`).join("");

  const guardar = async (clave, cambio) => {
    try {
      avisar((await api.cambiarBloqueTablero(clave, cambio)).mensaje);
      await Promise.all([cargar(), cargarConfiguracion()]);
    } catch (err) {
      avisar(err.message, true);
      await cargarConfiguracion();
    }
  };

  $("lista-config").querySelectorAll("[data-visible]").forEach((c) =>
    c.addEventListener("change", () => guardar(c.dataset.visible, { visible: c.checked })));
  $("lista-config").querySelectorAll("[data-orden]").forEach((c) =>
    c.addEventListener("change", () => guardar(c.dataset.orden, { orden: Number(c.value) })));
  $("lista-config").querySelectorAll("[data-ajuste]").forEach((c) =>
    c.addEventListener("change", () =>
      guardar(c.dataset.ajuste, { ajustes: { [c.dataset.nombre]: Number(c.value) } })));
}

$("btn-configurar").addEventListener("click", async () => {
  await cargarConfiguracion();
  $("modal-configurar").showModal();
});
$("btn-recalcular").addEventListener("click", () => cargar());

cargar();
