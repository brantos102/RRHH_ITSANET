/* El tablero de indicadores, por bloques que se encienden y se apagan.

   Lo que se muestra son AGREGADOS. Ningún nombre: «cuántos están de
   vacaciones» es un número, y quién está es el calendario del equipo, que
   tiene sus propios permisos. Un tablero que enseña nombres a quien no le
   toca es una fuga de datos con buena presentación.

   Cada cifra lleva debajo la pregunta que contesta. Un indicador que hay que
   ir a preguntar qué mide no se usa: se mira una vez y se ignora el resto
   del año. */
import { api, sesion, esc, fechaHora } from "./api.js";
import { dibujar, csv } from "./graficos.js";
import { montarNavegacion } from "./navegacion.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");
if (!["rrhh", "admin"].includes(sesion.perfil?.rol)) location.replace("dashboard.html");

montarNavegacion($("barra"), { activo: "informes" });

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
  cuota_discapacidad: (d) => [
    `${numero(d.con_discapacidad)} con discapacidad · ${numero(d.sustitutos)} sustitutas`,
    d.requeridas ? `la ley pide ${numero(d.requeridas)} (${numero(d.porcentaje)} % de ${numero(d.de)})`
      : "menos de 25 trabajadores: no aplica la cuota",
    d.faltan ? `faltan ${numero(d.faltan)}` : (d.requeridas ? "cuota cumplida" : null),
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
            <div class="w-1/2 rounded-t bg-[#1c58d7]" style="height:${(m.altas / tope) * 100}%"></div>
            <div class="w-1/2 rounded-t bg-rose-400" style="height:${(m.bajas / tope) * 100}%"></div>
          </div>
          <span class="text-[9px] text-slate-400">${esc(m.mes.slice(5))}</span>
        </div>`).join("")}
    </div>
    <p class="mt-1 text-xs text-slate-400">
      <span class="inline-block h-2 w-2 rounded-sm bg-[#1c58d7]"></span> altas ·
      <span class="inline-block h-2 w-2 rounded-sm bg-rose-400"></span> bajas</p>`;
}

function tarjeta(b) {
  const d = b.detalle || {};
  const lineas = (DETALLE[b.clave]?.(d) || []).filter(Boolean);
  return `
    <article data-bloque="${esc(b.clave)}"
             class="group relative rounded-2xl border-t-4 border-[#1c58d7] bg-white p-5 shadow-sm ring-1 ring-slate-200 transition
                    ${b.clave === "crecimiento" ? "sm:col-span-2" : ""}">
      <button type="button" data-asa title="Arrastrar para ordenar" aria-label="Arrastrar para ordenar"
              class="absolute right-2 top-2 hidden cursor-grab rounded px-1.5 text-lg leading-none text-slate-300 hover:text-slate-600 lg:block">⠿</button>
      <p class="text-sm font-medium text-slate-600">${esc(b.titulo)}</p>
      <p class="mt-1 text-3xl font-semibold tabular-nums text-slate-900">${numero(b.cifra)}</p>
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
    arrastrable($("tablero"), "[data-bloque]", async (orden) => {
      try { await api.ordenarBloquesTablero(orden.map((el) => el.dataset.bloque)); }
      catch (err) { avisar(err.message, true); }
    });
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


/* ----------------------------------------------------------- arrastrar
   Tarjetas que se reordenan arrastrándolas por su asa (⠿), como en los
   tableros de Power BI o Grafana. Solo el asa inicia el arrastre: así se
   puede seguir seleccionando texto y haciendo clic en las barras. En el
   teléfono el arrastre no se usa: allí cada tarjeta tiene «↑». */
function arrastrable(contenedor, selector, alSoltar) {
  let arrastrada = null;
  contenedor.querySelectorAll(selector).forEach((el) => {
    const asa = el.querySelector("[data-asa]");
    if (!asa) return;
    asa.addEventListener("mousedown", () => { el.draggable = true; });
    el.addEventListener("dragstart", (e) => {
      arrastrada = el;
      e.dataTransfer.effectAllowed = "move";
      setTimeout(() => el.classList.add("opacity-40", "ring-2", "ring-[#1c58d7]"), 0);
    });
    el.addEventListener("dragend", async () => {
      el.draggable = false;
      el.classList.remove("opacity-40", "ring-2", "ring-[#1c58d7]");
      if (arrastrada) {
        arrastrada = null;
        await alSoltar([...contenedor.querySelectorAll(selector)]);
      }
    });
    el.addEventListener("dragover", (e) => {
      if (!arrastrada || arrastrada === el) return;
      e.preventDefault();
      const caja = el.getBoundingClientRect();
      const despues = (e.clientY - caja.top) / caja.height > 0.5
        || ((e.clientY - caja.top) / caja.height > 0.25 && (e.clientX - caja.left) / caja.width > 0.5);
      el.parentNode.insertBefore(arrastrada, despues ? el.nextSibling : el);
    });
  });
}

/* ------------------------------------------------------------ mis gráficos */
const exp = { catalogo: null, vistas: [] };
const TAMANO = {      // clases completas: el compilador de estilos las busca tal cual
  1: "lg:col-span-4", 2: "lg:col-span-6", 3: "lg:col-span-8", 4: "lg:col-span-12" };
const TAMANO_TEXTO = { 1: "pequeña", 2: "mediana", 3: "grande", 4: "ancho completo" };
const CRUZADAS = { sede: "sede", area: "area", ciudad: "ciudad", cargo: "cargo", contrato: "contrato" };

/* Los filtros del tablero se recuerdan en este navegador: es una
   preferencia de quien mira, no un dato de la empresa. */
const LLAVE_FILTROS = "rrhh.tablero.filtros";
let globales = (() => { try { return JSON.parse(localStorage.getItem(LLAVE_FILTROS)) || {}; } catch { return {}; } })();
function guardarGlobales() { try { localStorage.setItem(LLAVE_FILTROS, JSON.stringify(globales)); } catch { /* sin preferencia */ } }

const filtrosDe = () => ({
  sede: $("g-sede").value || null, area: $("g-area").value || null,
  desde: $("g-desde").value || null, hasta: $("g-hasta").value || null,
  tipo: $("g-tipo").value || null,
});
/* Lo guardado en el gráfico, con los filtros del tablero encima. */
const consulta = (v, comparar = false) => {
  const q = { medida: v.medida, dimension: v.dimension, ...(v.filtros || {}) };
  for (const [k, val] of Object.entries(globales)) if (val) q[k] = val;
  if (comparar) q.comparar = true;
  return q;
};

function nombreSede(codigo) {
  return exp.catalogo?.sedes.find((x) => x.codigo === codigo)?.sede || codigo;
}

function piePeriodo(r, f = {}) {
  const partes = [];
  if (r.periodo) partes.push(`${r.periodo.desde.split("-").reverse().join("/")} – ${r.periodo.hasta.split("-").reverse().join("/")}`);
  if (f.sede) partes.push(nombreSede(f.sede));
  for (const k of ["area", "ciudad", "cargo", "contrato"]) if (f[k]) partes.push(f[k]);
  if (r.total !== null && r.total !== undefined) partes.push(`total ${Number(r.total).toLocaleString("es-EC")}`);
  return partes.join(" · ");
}

async function catalogo() {
  if (exp.catalogo) return exp.catalogo;
  exp.catalogo = await api.explorador();
  $("g-medida").innerHTML = exp.catalogo.medidas.map((m) => `<option value="${esc(m.clave)}">${esc(m.titulo)}</option>`).join("");
  const sedes = exp.catalogo.sedes.map((x) => `<option value="${esc(x.codigo)}">${esc(x.sede)}</option>`).join("");
  const areas = exp.catalogo.areas.map((a) => `<option>${esc(a)}</option>`).join("");
  $("g-sede").insertAdjacentHTML("beforeend", sedes);
  $("g-area").insertAdjacentHTML("beforeend", areas);
  $("ft-sede").insertAdjacentHTML("beforeend", sedes);
  $("ft-area").insertAdjacentHTML("beforeend", areas);
  return exp.catalogo;
}

/* ------------------------------------------------------ filtros del tablero */
function pintarFiltrosGlobales() {
  $("ft-sede").value = globales.sede || "";
  $("ft-area").value = globales.area || "";
  $("ft-desde").value = globales.desde || "";
  $("ft-hasta").value = globales.hasta || "";
  const extra = ["ciudad", "cargo", "contrato"].filter((k) => globales[k]);
  $("ft-chips").innerHTML = extra.map((k) => `
    <span class="inline-flex items-center gap-1 rounded-full bg-[#1c58d7]/10 px-2.5 py-1 text-xs font-medium text-[#1c58d7]">
      ${esc({ ciudad: "Ciudad", cargo: "Cargo", contrato: "Contrato" }[k])}: ${esc(globales[k])}
      <button type="button" data-quitar-filtro="${k}" aria-label="Quitar filtro">✕</button></span>`).join("");
  const activos = Object.values(globales).some(Boolean);
  $("filtros-tablero").classList.toggle("ring-[#1c58d7]", activos);
  $("filtros-tablero").classList.toggle("ring-2", activos);
}

function cambiarGlobal(clave, valor) {
  globales[clave] = valor || null;
  guardarGlobales();
  pintarFiltrosGlobales();
  cargarMisGraficos().catch((err) => avisar(err.message, true));
}

[["ft-sede", "sede"], ["ft-area", "area"], ["ft-desde", "desde"], ["ft-hasta", "hasta"]].forEach(([id, k]) =>
  $(id).addEventListener("change", () => cambiarGlobal(k, $(id).value)));
$("ft-chips").addEventListener("click", (e) => {
  const b = e.target.closest("[data-quitar-filtro]");
  if (b) cambiarGlobal(b.dataset.quitarFiltro, null);
});
$("ft-limpiar").addEventListener("click", () => {
  globales = {};
  guardarGlobales();
  pintarFiltrosGlobales();
  cargarMisGraficos().catch((err) => avisar(err.message, true));
});

/* Clic en una barra: filtra todo el tablero por ese valor. */
function filtrarPor(v, etiqueta) {
  const clave = CRUZADAS[v.dimension];
  if (!clave || etiqueta.startsWith("(") || etiqueta.startsWith("Otros (")) return;
  const valor = clave === "sede"
    ? exp.catalogo?.sedes.find((x) => x.sede === etiqueta)?.codigo || null : etiqueta;
  if (!valor) return;
  avisar(`Tablero filtrado por ${etiqueta}. Quítelo en la barra de filtros.`);
  cambiarGlobal(clave, globales[clave] === valor ? null : valor);
}

/* ----------------------------------------------------------- diseñador */
function dimensionesPara(medida) {
  const m = exp.catalogo.medidas.find((x) => x.clave === medida);
  const actual = $("g-dimension").value;
  $("g-dimension").innerHTML = exp.catalogo.dimensiones
    .filter((d) => (!d.solo || d.solo === medida) && (!d.solo_con_periodo || m.con_periodo))
    .map((d) => `<option value="${esc(d.clave)}">${esc(d.titulo)}</option>`).join("");
  if ([...$("g-dimension").options].some((o) => o.value === actual)) $("g-dimension").value = actual;
  $("g-periodo").classList.toggle("hidden", !m.con_periodo);
  $("g-tipo-caja").classList.toggle("hidden", medida !== "solicitudes");
}

let previaTemporizador;
function previa() {
  clearTimeout(previaTemporizador);
  previaTemporizador = setTimeout(async () => {
    const v = { medida: $("g-medida").value, dimension: $("g-dimension").value, filtros: filtrosDe() };
    try {
      const q = { medida: v.medida, dimension: v.dimension, ...v.filtros };
      if ($("g-grafico").value === "cifra") q.comparar = true;
      const r = await api.explorar(q);
      $("g-previa-titulo").textContent = `${r.titulo_medida} por ${r.titulo_dimension.toLowerCase()}`;
      if (!$("g-nombre").dataset.tocado) $("g-nombre").value = $("g-previa-titulo").textContent;
      $("g-previa-pie").textContent = piePeriodo(r, v.filtros);
      dibujar($("g-previa"), r, $("g-grafico").value);
    } catch (err) {
      $("g-previa").innerHTML = `<p class="py-6 text-center text-sm text-rose-700">${esc(err.message)}</p>`;
    }
  }, 250);
}

async function abrirDisenador(v = null) {
  await catalogo();
  $("grafico-titulo").textContent = v ? "Editar gráfico" : "Nuevo gráfico";
  $("g-id").value = v?.id || "";
  $("g-nombre").value = v?.nombre || "";
  $("g-nombre").dataset.tocado = v ? "1" : "";
  $("g-medida").value = v?.medida || "personas";
  dimensionesPara($("g-medida").value);
  $("g-dimension").value = v?.dimension || "sede";
  $("g-grafico").value = v?.grafico || "barras";
  const f = v?.filtros || {};
  $("g-sede").value = f.sede || ""; $("g-area").value = f.area || "";
  $("g-desde").value = f.desde || ""; $("g-hasta").value = f.hasta || ""; $("g-tipo").value = f.tipo || "";
  $("g-ancho").value = String(v?.ancho || 2);
  $("g-compartida").checked = !!v?.compartida;
  $("modal-grafico").showModal();
  previa();
}

$("btn-nuevo-grafico").addEventListener("click", () => abrirDisenador().catch((e) => avisar(e.message, true)));
$("g-nombre").addEventListener("input", () => { $("g-nombre").dataset.tocado = "1"; });
$("g-medida").addEventListener("change", () => { dimensionesPara($("g-medida").value); previa(); });
["g-dimension", "g-grafico", "g-sede", "g-area", "g-desde", "g-hasta", "g-tipo"].forEach((id) =>
  $(id).addEventListener("change", previa));

$("form-grafico").addEventListener("submit", async (e) => {
  e.preventDefault();
  const datos = {
    nombre: $("g-nombre").value.trim(), medida: $("g-medida").value, dimension: $("g-dimension").value,
    grafico: $("g-grafico").value, ancho: Number($("g-ancho").value),
    compartida: $("g-compartida").checked,
    filtros: Object.fromEntries(Object.entries(filtrosDe()).filter(([, x]) => x)),
  };
  try {
    const id = $("g-id").value;
    avisar((id ? await api.cambiarVista(id, datos) : await api.guardarVista(datos)).mensaje);
    $("modal-grafico").close();
    await cargarMisGraficos();
  } catch (err) { avisar(err.message, true); }
});

/* -------------------------------------------------------------- tarjetas */
const BOTON = "rounded-md px-1.5 py-1 text-slate-500 hover:bg-slate-100 hover:text-slate-900";

function tarjetaGrafico(v, i) {
  return `
    <article data-vista="${v.id}" class="group relative flex min-w-0 flex-col rounded-2xl bg-white p-4 shadow-sm ring-1 ring-slate-200 transition ${TAMANO[v.ancho] || TAMANO[2]}">
      <header class="flex items-start gap-2">
        ${v.propia ? `<button type="button" data-asa title="Arrastrar para ordenar" aria-label="Arrastrar para ordenar"
          class="hidden cursor-grab rounded px-1 text-lg leading-none text-slate-300 hover:text-slate-600 lg:block">⠿</button>` : ""}
        <div class="min-w-0 flex-1">
          <h3 class="truncate font-medium" title="${esc(v.nombre)}">${esc(v.nombre)}</h3>
          <p data-pie="${v.id}" class="truncate text-xs text-slate-500">${v.propia ? "" : `de ${esc(v.de)} · `}</p>
        </div>
        ${v.compartida ? '<span class="shrink-0 rounded-full bg-[#1c58d7]/10 px-2 py-0.5 text-[11px] text-[#1c58d7]">compartido</span>' : ""}
        <div class="flex shrink-0 items-center rounded-lg bg-white text-xs transition lg:absolute lg:right-2 lg:top-2
                    lg:opacity-0 lg:shadow-md lg:ring-1 lg:ring-slate-200 lg:group-hover:opacity-100 lg:group-focus-within:opacity-100">
          ${v.propia && i > 0 ? `<button data-subir="${i}" title="Subir" class="${BOTON} lg:hidden">↑</button>` : ""}
          ${v.propia ? `<button data-tamano="${v.id}" title="Tamaño: ${TAMANO_TEXTO[v.ancho] || "mediana"}" class="${BOTON} hidden lg:inline">⤢</button>` : ""}
          <button data-ampliar="${v.id}" title="Ampliar" class="${BOTON}">⛶</button>
          ${v.propia
            ? `<button data-editar="${v.id}" title="Editar" class="${BOTON}">Editar</button>
               <button data-quitar="${v.id}" title="Quitar" class="${BOTON} hover:text-rose-700">✕</button>`
            : `<button data-copiar="${v.id}" class="${BOTON}">Copiar</button>`}
          <button data-csv="${v.id}" title="Descargar CSV" class="${BOTON}">CSV</button>
        </div>
      </header>
      <div data-grafico="${v.id}" class="mt-3 flex-1"><p class="py-6 text-center text-xs text-slate-400">Calculando…</p></div>
    </article>`;
}

async function cargarMisGraficos() {
  await catalogo();
  pintarFiltrosGlobales();
  exp.vistas = await api.vistasTablero();
  const caja = $("mis-graficos");
  if (!exp.vistas.length) {
    caja.innerHTML = `<div class="rounded-2xl border-2 border-dashed border-slate-300 p-8 text-center text-sm text-slate-500 lg:col-span-12">
      Todavía no tiene gráficos. Pruebe «Días de vacaciones por gozar» agrupado por área, o
      «Solicitudes» por mes en línea.</div>`;
    return;
  }
  caja.innerHTML = exp.vistas.map(tarjetaGrafico).join("");
  arrastrable(caja, "[data-vista]", async (orden) => {
    const ids = orden.map((el) => Number(el.dataset.vista))
      .filter((id) => exp.vistas.find((v) => v.id === id)?.propia);
    try { await api.ordenarVistas(ids); } catch (err) { avisar(err.message, true); }
  });
  await Promise.all(exp.vistas.map(async (v) => {
    const destino = caja.querySelector(`[data-grafico="${v.id}"]`);
    try {
      const r = await api.explorar(consulta(v, v.grafico === "cifra"));
      v.resultado = r;
      caja.querySelector(`[data-pie="${v.id}"]`).textContent += piePeriodo(r, { ...(v.filtros || {}), ...globales });
      dibujar(destino, r, v.grafico, CRUZADAS[v.dimension] ? (etiqueta) => filtrarPor(v, etiqueta) : null);
    } catch (err) {
      destino.innerHTML = `<p class="py-6 text-center text-sm text-rose-700">${esc(err.message)}</p>`;
    }
  }));
}

function ampliar(v) {
  if (!v?.resultado) return;
  $("amp-titulo").textContent = v.nombre;
  $("amp-pie").textContent = piePeriodo(v.resultado, { ...(v.filtros || {}), ...globales });
  $("modal-ampliar").showModal();
  dibujar($("amp-grafico"), v.resultado, v.grafico === "tabla" ? "barras" : v.grafico,
          CRUZADAS[v.dimension] ? (etiqueta) => { $("modal-ampliar").close(); filtrarPor(v, etiqueta); } : null);
  dibujar($("amp-tabla"), v.resultado, "tabla");
}

$("mis-graficos").addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b || b.dataset.asa !== undefined) return;
  const buscar = (id) => exp.vistas.find((x) => String(x.id) === String(id));
  try {
    if (b.dataset.editar) {
      await abrirDisenador(buscar(b.dataset.editar));
    } else if (b.dataset.ampliar) {
      ampliar(buscar(b.dataset.ampliar));
    } else if (b.dataset.tamano) {
      const v = buscar(b.dataset.tamano);
      const nuevo = (v.ancho % 4) + 1;
      await api.cambiarVista(v.id, { ancho: nuevo });
      v.ancho = nuevo;
      const tarjetaEl = b.closest("[data-vista]");
      Object.values(TAMANO).forEach((c) => tarjetaEl.classList.remove(c));
      tarjetaEl.classList.add(TAMANO[nuevo]);
      b.title = `Tamaño: ${TAMANO_TEXTO[nuevo]}`;
      if (v.grafico === "linea" && v.resultado) dibujar(tarjetaEl.querySelector("[data-grafico]"), v.resultado, "linea");
    } else if (b.dataset.quitar) {
      if (!confirm("¿Quitar este gráfico de su tablero?")) return;
      avisar((await api.quitarVista(b.dataset.quitar)).mensaje);
      await cargarMisGraficos();
    } else if (b.dataset.subir) {
      const i = Number(b.dataset.subir);
      const propias = exp.vistas.filter((x) => x.propia).map((x) => x.id);
      const [a, c] = [exp.vistas[i - 1].id, exp.vistas[i].id];
      const pa = propias.indexOf(a), pc = propias.indexOf(c);
      if (pa < 0 || pc < 0) return;
      [propias[pa], propias[pc]] = [propias[pc], propias[pa]];
      await api.ordenarVistas(propias);
      await cargarMisGraficos();
    } else if (b.dataset.copiar) {
      const v = buscar(b.dataset.copiar);
      avisar((await api.guardarVista({ nombre: v.nombre, medida: v.medida, dimension: v.dimension,
        grafico: v.grafico, filtros: v.filtros, ancho: v.ancho, compartida: false })).mensaje);
      await cargarMisGraficos();
    } else if (b.dataset.csv) {
      const v = buscar(b.dataset.csv);
      if (!v?.resultado) return;
      const url = URL.createObjectURL(new Blob(["﻿" + csv(v.resultado)], { type: "text/csv;charset=utf-8" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: `${v.nombre}.csv` });
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    }
  } catch (err) { avisar(err.message, true); }
});

cargarMisGraficos().catch((err) => avisar(err.message, true));
