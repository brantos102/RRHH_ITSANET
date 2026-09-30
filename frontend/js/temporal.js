/* Personal temporal: registrar la jornada y liquidar la semana.

   La pantalla la usan dos perfiles con necesidades distintas. El guardia
   registra entradas y salidas, y para él lo único que importa es tocar el
   botón correcto rápido, sin leer. Talento Humano da de alta a la gente,
   cierra lo que quedó abierto y mira cuánto se debe pagar.

   Por eso el botón de cada persona es uno solo y cambia según lo que
   corresponda ahora: «Entró», «Salió» o «Listo». Un guardia que tiene que
   elegir entre dos botones se equivoca; uno que tiene uno, no. */
import { api, sesion, esc, fechaHora } from "./api.js";
import { montarNavegacion } from "./navegacion.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");
if (!["guardia", "rrhh", "admin"].includes(sesion.perfil?.rol)) location.replace("dashboard.html");

const ES_RRHH = ["rrhh", "admin"].includes(sesion.perfil?.rol);
montarNavegacion($("barra"), { activo: "temporal" });

const estado = { gente: [], jornada: null, sondeo: null };

let temporizador;
const avisar = (texto, error = false) => {
  const el = $("aviso");
  el.textContent = texto;
  el.className = `max-w-sm rounded-xl px-4 py-3 text-center text-sm shadow-lg ${
    error ? "bg-rose-600 text-white" : "bg-slate-900 text-white"}`;
  clearTimeout(temporizador);
  temporizador = setTimeout(() => el.classList.add("hidden"), 5000);
};

const normalizar = (t) =>
  (t || "").toString().normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

const hora = (v) => v ? new Date(v).toLocaleTimeString("es-EC",
  { hour: "2-digit", minute: "2-digit" }) : "—";
const numero = (v) => Number(v || 0).toLocaleString("es-EC",
  { minimumFractionDigits: 0, maximumFractionDigits: 2 });

/* ------------------------------------------------------------ la gente */

const ESTADO = {
  dentro:        ["Salió", "bg-amber-500 hover:bg-amber-600", "Dentro desde"],
  sin_registrar: ["Entró", "bg-emerald-600 hover:bg-emerald-700", "Sin registrar hoy"],
  completo:      ["Listo", "bg-slate-200 text-slate-500 cursor-default", "Jornada cumplida"],
};

function pintarGente() {
  const aguja = normalizar($("buscar-temporal").value.trim());
  const visibles = aguja
    ? estado.gente.filter((p) => normalizar(
        `${p.nombre} ${p.cedula} ${p.labor || ""} ${p.proveedor || ""}`).includes(aguja))
    : estado.gente;

  const dentro = estado.gente.filter((p) => p.estado_hoy === "dentro").length;
  const completos = estado.gente.filter((p) => p.estado_hoy === "completo").length;
  $("resumen-temporal").textContent = estado.gente.length
    ? `${estado.gente.length} registrado(s) · ${dentro} dentro ahora · ${completos} con jornada cumplida hoy`
    : "Todavía no hay personal temporal registrado.";

  $("lista-temporal").innerHTML = visibles.length
    ? visibles.map((p) => {
        const [texto, tono, leyenda] = ESTADO[p.estado_hoy];
        return `
        <article class="flex flex-wrap items-center gap-3 px-5 py-3">
          <div class="min-w-0 flex-1">
            <p class="font-medium">${esc(p.nombre)}</p>
            <p class="text-xs text-slate-500">
              ${esc(p.cedula)}${p.labor ? ` · ${esc(p.labor)}` : ""}${
                p.proveedor ? ` · ${esc(p.proveedor)}` : ""}
            </p>
            <p class="mt-0.5 text-xs ${p.estado_hoy === "dentro" ? "font-medium text-amber-700" : "text-slate-400"}">
              ${leyenda}${p.entrada_en ? ` ${hora(p.entrada_en)}` : ""}${
                p.salida_en ? ` hasta ${hora(p.salida_en)} · ${numero(p.horas)} h` : ""}
            </p>
          </div>
          <button type="button" data-mover="${esc(p.id)}" data-accion="${p.estado_hoy}"
                  ${p.estado_hoy === "completo" ? "disabled" : ""}
                  class="w-24 shrink-0 rounded-xl px-4 py-2.5 text-sm font-semibold text-white ${tono}">
            ${texto}
          </button>
        </article>`;
      }).join("")
    : `<p class="px-5 py-10 text-center text-sm text-slate-500">${
         aguja ? "Nadie coincide con esa búsqueda." : "Todavía no hay personal temporal registrado."}</p>`;

  $("lista-temporal").querySelectorAll("[data-mover]").forEach((b) =>
    b.addEventListener("click", () => mover(b.dataset.mover, b.dataset.accion)));
}

async function mover(id, accionActual) {
  const ruta = accionActual === "dentro" ? "salida" : "entrada";
  try {
    const r = ruta === "salida"
      ? await api.temporalSalida(id)
      : await api.temporalEntrada(id);
    avisar(r.mensaje);
    await cargar();
  } catch (err) {
    avisar(err.message, true);
  }
}

/* ------------------------------------------------- lo que quedó abierto */

function pintarSinCerrar(pendientes) {
  $("caja-sin-cerrar").classList.toggle("hidden", !pendientes.length);
  $("lista-sin-cerrar").innerHTML = pendientes.map((j) => `
    <div class="flex flex-wrap items-center gap-3 rounded-xl bg-white p-3 ring-1 ring-rose-200">
      <div class="min-w-0 flex-1">
        <p class="text-sm font-medium">${esc(j.nombre)}</p>
        <p class="text-xs text-slate-500">
          Entró el ${fechaHora(j.entrada_en)} · ${j.dias_sin_cerrar} día(s) sin cerrar
        </p>
      </div>
      ${ES_RRHH ? `<button type="button" data-cerrar-jornada="${esc(j.jornada_id)}"
              data-nombre="${esc(j.nombre)}" data-entrada="${esc(j.entrada_en)}"
              class="rounded-lg bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700">
        Registrar salida
      </button>` : `<span class="text-xs text-slate-500">Lo cierra Talento Humano</span>`}
    </div>`).join("");

  $("lista-sin-cerrar").querySelectorAll("[data-cerrar-jornada]").forEach((b) =>
    b.addEventListener("click", () => abrirCierre(b.dataset)));
}

function abrirCierre({ cerrarJornada, nombre, entrada }) {
  estado.jornada = cerrarJornada;
  $("cerrar-quien").textContent = `${nombre}, que entró el ${fechaHora(entrada)}.`;
  $("c-salida").value = "";
  $("c-motivo").value = "";
  $("c-error").classList.add("hidden");
  $("modal-cerrar").showModal();
}

/* ------------------------------------------------------------ la semana */

function pintarSemana(semana) {
  $("semana-horas").textContent = `${numero(semana.total_horas)} h`;
  // Cero es un total, no la ausencia de un total: mostrar «—» cuando nadie ha
  // acumulado horas todavía hace dudar de si el dato falta o si de verdad es
  // cero. El guion «—» queda solo para cuando nadie tiene valor por hora.
  const hayTarifa = semana.personas.some((p) => p.valor_hora !== null);
  $("semana-total").textContent = hayTarifa ? `$ ${numero(semana.total_pagar)}` : "—";

  const aviso = $("semana-aviso");
  aviso.classList.toggle("hidden", !semana.aviso);
  if (semana.aviso) aviso.textContent = semana.aviso;

  $("semana-lista").innerHTML = semana.personas.length
    ? semana.personas.map((p) => `
      <div class="flex items-center justify-between gap-2 border-b border-slate-100 py-1.5 text-sm last:border-0">
        <div class="min-w-0">
          <p class="truncate">${esc(p.nombre)}</p>
          <p class="text-xs text-slate-500">
            ${p.dias} día(s) · ${numero(p.horas)} h${
              p.sin_cerrar ? ` · <span class="text-rose-600">${p.sin_cerrar} sin cerrar</span>` : ""}
          </p>
        </div>
        <p class="shrink-0 font-medium tabular-nums">${
          p.total === null ? '<span class="text-xs font-normal text-slate-400">por obra</span>'
                           : "$ " + numero(p.total)}</p>
      </div>`).join("")
    : `<p class="py-6 text-center text-sm text-slate-500">Nadie trabajó esta semana todavía.</p>`;
}

/* ------------------------------------------------------------- arranque */

async function cargar() {
  try {
    const [gente, pendientes] = await Promise.all([
      api.temporales($("buscar-temporal").value),
      api.temporalesSinCerrar(),
    ]);
    estado.gente = gente;
    pintarGente();
    pintarSinCerrar(pendientes);

    if (ES_RRHH) {
      $("caja-semana").classList.remove("hidden");
      $("btn-nuevo-temporal").classList.remove("hidden");
      pintarSemana(await api.temporalSemana());
    }
  } catch (err) {
    avisar(err.message, true);
  }
}

$("buscar-temporal").addEventListener("input", pintarGente);

$("btn-nuevo-temporal").addEventListener("click", () => {
  $("form-temporal").reset();
  $("t-error").classList.add("hidden");
  $("modal-temporal").showModal();
});

document.addEventListener("click", (e) => {
  if (e.target.closest("[data-cerrar]")) e.target.closest("dialog")?.close();
});

$("form-temporal").addEventListener("submit", async (e) => {
  e.preventDefault();
  const valor = $("t-valor").value.trim().replace(",", ".");
  try {
    const r = await api.crearTemporal({
      cedula: $("t-cedula").value.trim(),
      nombre: $("t-nombre").value.trim(),
      labor: $("t-labor").value.trim() || null,
      proveedor: $("t-proveedor").value.trim() || null,
      telefono: $("t-telefono").value.trim() || null,
      valor_hora: valor === "" ? null : Number(valor),
    });
    $("modal-temporal").close();
    avisar(r.mensaje);
    await cargar();
  } catch (err) {
    $("t-error").textContent = err.message;
    $("t-error").classList.remove("hidden");
  }
});

$("form-cerrar").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await api.cerrarJornadaTemporal(estado.jornada, {
      // El campo da hora local; el servidor la guarda con su zona.
      salida: new Date($("c-salida").value).toISOString(),
      motivo: $("c-motivo").value.trim(),
    });
    $("modal-cerrar").close();
    avisar(r.mensaje);
    await cargar();
  } catch (err) {
    $("c-error").textContent = err.message;
    $("c-error").classList.remove("hidden");
  }
});

cargar();
// La garita y Talento Humano suelen tener esta pantalla abierta todo el día.
estado.sondeo = setInterval(cargar, 60000);
