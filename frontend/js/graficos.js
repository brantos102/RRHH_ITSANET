/* Gráficos del tablero, sin librería: barras, línea, tabla y cifra.

   Una sola serie por gráfico (una medida por una dimensión), así que un solo
   color y sin leyenda: el título dice qué se mide. Las cifras van en tinta
   de texto, no en el color de la marca. Cada marca muestra su valor al
   pasar el cursor o al tocarla, y todo gráfico tiene su vista de tabla. */
import { esc } from "./api.js";

const COLOR = "#0369a1";          // sky-700: una sola serie
const numero = (n) => Number(n ?? 0).toLocaleString("es-EC", { maximumFractionDigits: 1 });

let tooltip;
function verTooltip(e, texto) {
  if (!tooltip) {
    tooltip = document.createElement("div");
    tooltip.className = "pointer-events-none fixed z-50 rounded-lg bg-slate-900 px-2.5 py-1.5 text-xs text-white shadow-lg";
    document.body.appendChild(tooltip);
  }
  tooltip.textContent = texto;
  tooltip.style.display = "block";
  const x = Math.min(e.clientX + 12, window.innerWidth - tooltip.offsetWidth - 8);
  tooltip.style.left = `${x}px`;
  tooltip.style.top = `${e.clientY - 34}px`;
}
function ocultarTooltip() { if (tooltip) tooltip.style.display = "none"; }

/* Barras horizontales: las etiquetas largas (áreas, cargos) se leen enteras. */
function barras(datos) {
  const tope = Math.max(...datos.map((d) => d.valor), 0) || 1;
  return `<div class="space-y-1.5">${datos.map((d) => `
    <div class="grid grid-cols-[minmax(6rem,40%)_1fr_auto] items-center gap-2 text-xs" data-punto
         data-texto="${esc(`${d.etiqueta}: ${numero(d.valor)}`)}">
      <span class="truncate text-slate-600" title="${esc(d.etiqueta)}">${esc(d.etiqueta)}</span>
      <span class="h-4 rounded-r" style="width:${Math.max((d.valor / tope) * 100, d.valor ? 1.5 : 0)}%;
            background:${COLOR}; border-radius:0 4px 4px 0"></span>
      <span class="tabular-nums font-medium text-slate-800">${numero(d.valor)}</span>
    </div>`).join("")}</div>`;
}

/* Línea por mes: SVG con su eje en cero y marcadores para el cursor. */
function linea(datos, ancho = 600) {
  const alto = 180, mx = 36, my = 16;
  const tope = Math.max(...datos.map((d) => d.valor), 0) || 1;
  const paso = datos.length > 1 ? (ancho - mx * 2) / (datos.length - 1) : 0;
  const x = (i) => mx + i * paso;
  const y = (v) => alto - my - (v / tope) * (alto - my * 2);
  const puntos = datos.map((d, i) => `${x(i)},${y(d.valor)}`).join(" ");
  const cada = Math.ceil(datos.length / Math.max(2, Math.floor(ancho / 80)));
  return `<svg viewBox="0 0 ${ancho} ${alto + 18}" width="100%" height="${alto + 18}" role="img" aria-label="Gráfico de línea">
    <line x1="${mx}" x2="${ancho - mx}" y1="${y(0)}" y2="${y(0)}" stroke="#cbd5e1" stroke-width="1"/>
    <line x1="${mx}" x2="${ancho - mx}" y1="${y(tope)}" y2="${y(tope)}" stroke="#e2e8f0" stroke-dasharray="3 3"/>
    <text x="${mx - 6}" y="${y(tope) + 4}" text-anchor="end" font-size="11" fill="#64748b">${numero(tope)}</text>
    <text x="${mx - 6}" y="${y(0) + 4}" text-anchor="end" font-size="11" fill="#64748b">0</text>
    <polyline points="${puntos}" fill="none" stroke="${COLOR}" stroke-width="2" stroke-linejoin="round"/>
    ${datos.map((d, i) => `
      ${datos.length <= 24 ? `<circle cx="${x(i)}" cy="${y(d.valor)}" r="4" fill="${COLOR}" stroke="#fff" stroke-width="2"/>` : ""}
      <rect x="${x(i) - Math.max(paso / 2, 8)}" y="0" width="${Math.max(paso, 16)}" height="${alto}"
            fill="transparent" data-punto data-texto="${esc(`${d.etiqueta}: ${numero(d.valor)}`)}"/>
      ${i % cada === 0 || i === datos.length - 1
        ? `<text x="${x(i)}" y="${alto + 12}" text-anchor="middle" font-size="11" fill="#64748b">${esc(d.etiqueta)}</text>` : ""}`).join("")}
  </svg>`;
}

function tabla(datos, titulos) {
  return `<div class="max-h-72 overflow-y-auto"><table class="w-full text-left text-sm">
    <thead class="sticky top-0 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
      <tr><th class="px-2 py-1.5">${esc(titulos.dimension)}</th><th class="px-2 py-1.5 text-right">${esc(titulos.medida)}</th></tr></thead>
    <tbody class="divide-y divide-slate-100">${datos.map((d) => `
      <tr><td class="px-2 py-1.5">${esc(d.etiqueta)}</td><td class="px-2 py-1.5 text-right tabular-nums">${numero(d.valor)}</td></tr>`).join("")}
    </tbody></table></div>`;
}

function cifra(r) {
  const valor = r.total ?? (r.datos.length === 1 ? r.datos[0].valor : null);
  return `<p class="text-4xl font-semibold tabular-nums">${valor === null ? "—" : numero(valor)}</p>
    ${r.datos.length > 1 ? `<p class="mt-1 text-xs text-slate-500">${r.datos.length} grupos</p>` : ""}`;
}

export function dibujar(caja, r, tipo = "barras") {
  if (!r.datos.length) {
    caja.innerHTML = '<p class="py-6 text-center text-sm text-slate-500">Sin datos con estos filtros.</p>';
    return;
  }
  const titulos = { dimension: r.titulo_dimension, medida: r.titulo_medida };
  caja.innerHTML = tipo === "linea" ? linea(r.datos, Math.max(caja.clientWidth || 600, 280))
    : tipo === "tabla" ? tabla(r.datos, titulos)
      : tipo === "cifra" ? cifra(r) : barras(r.datos);
  caja.querySelectorAll("[data-punto]").forEach((el) => {
    el.addEventListener("mousemove", (e) => verTooltip(e, el.dataset.texto));
    el.addEventListener("mouseleave", ocultarTooltip);
    el.addEventListener("click", (e) => verTooltip(e, el.dataset.texto));
  });
}

/* CSV de lo que se ve, para llevarlo a Excel. Son agregados: no hay datos
   personales en el archivo. */
export function csv(r) {
  const filas = [[r.titulo_dimension, r.titulo_medida], ...r.datos.map((d) => [d.etiqueta, d.valor])];
  return filas.map((f) => f.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(";")).join("\r\n");
}
