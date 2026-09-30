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
  // Horas y jornadas, no dinero. El sistema sabe cuánto estuvo cada operario
  // porque la garita lo presenció; cuánto se le paga sale del contrato del
  // proveedor y esa cuenta la hace Finanzas. Un total en dólares impreso aquí
  // se tomaría por la cifra buena, y el día que cambie la tarifa seguiría
  // saliendo igual de convincente y ya equivocado.
  $("semana-horas").textContent = `${numero(semana.total_horas)} h`;
  $("semana-jornadas").textContent = semana.total_jornadas;

  const aviso = $("semana-aviso");
  aviso.classList.toggle("hidden", !semana.aviso);
  if (semana.aviso) aviso.textContent = semana.aviso;

  $("semana-lista").innerHTML = semana.personas.length
    ? semana.personas.map((p) => `
      <div class="flex items-center justify-between gap-2 border-b border-slate-100 py-1.5 text-sm last:border-0">
        <div class="min-w-0">
          <p class="truncate">${esc(p.nombre)}</p>
          <p class="text-xs text-slate-500">
            ${p.jornadas} jornada(s)${
              p.sin_cerrar ? ` · <span class="text-rose-600">${p.sin_cerrar} sin cerrar</span>` : ""}
          </p>
        </div>
        <p class="shrink-0 font-medium tabular-nums">${numero(p.horas)} h</p>
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
  try {
    const r = await api.crearTemporal({
      cedula: $("t-cedula").value.trim(),
      nombre: $("t-nombre").value.trim(),
      labor: $("t-labor").value.trim() || null,
      proveedor: $("t-proveedor").value.trim() || null,
      telefono: $("t-telefono").value.trim() || null,
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

/* ----------------------------------------------- informe para Finanzas

   Talento Humano necesita presentar a Finanzas qué operarios vinieron, qué
   días y cuántas horas, para que autoricen el pago. Hasta ahora solo había
   un enlace a Excel de la semana en curso: ni un rango, ni una persona
   suelta, ni un proveedor.

   Lo que se filtra en pantalla es lo que sale en el archivo, y el filtro va
   escrito dentro: un informe que no dice de qué está hablando no sustenta
   nada tres meses después.

   El total se recalcula al tocar cualquier filtro. Bajar un archivo para
   descubrir que estaba vacío, o que traía media planilla, es la forma más
   rápida de perderle la confianza a un botón de descarga. */

const informe = { opciones: null, elegidos: new Set() };

function filtroActual() {
  return {
    desde: $("i-desde").value || null,
    hasta: $("i-hasta").value || null,
    temporales: informe.elegidos.size ? [...informe.elegidos] : null,
    proveedor: $("i-proveedor").value || null,
    labor: $("i-labor").value || null,
    incluir_inactivos: $("i-inactivos").checked,
    solo_sin_cerrar: $("i-sin-cerrar").checked,
    detalle: $("i-detalle").checked,
  };
}

function pintarPersonasInforme() {
  const aguja = normalizar($("i-buscar").value.trim());
  const gente = (informe.opciones?.personas || []).filter((p) =>
    !aguja || normalizar(`${p.nombre} ${p.cedula} ${p.labor || ""} ${p.proveedor || ""}`)
      .includes(aguja));

  $("i-personas").innerHTML = gente.length ? gente.map((p) => `
    <label class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-white">
      <input type="checkbox" data-operario="${esc(p.id)}"
             ${informe.elegidos.has(p.id) ? "checked" : ""} class="rounded border-slate-300">
      <span class="min-w-0 flex-1 truncate ${p.activo ? "" : "text-slate-400"}">
        ${esc(p.nombre)}
        <span class="text-xs text-slate-500">· ${esc(p.cedula)}${
          p.labor ? " · " + esc(p.labor) : ""}${p.activo ? "" : " · inactivo"}</span>
      </span>
    </label>`).join("")
    : `<p class="px-2 py-3 text-center text-sm text-slate-500">Nadie coincide.</p>`;

  $("i-personas").querySelectorAll("[data-operario]").forEach((c) =>
    c.addEventListener("change", () => {
      if (c.checked) informe.elegidos.add(c.dataset.operario);
      else informe.elegidos.delete(c.dataset.operario);
      previsualizarInforme();
    }));
}

let temporizadorInforme;
function previsualizarInforme() {
  clearTimeout(temporizadorInforme);
  temporizadorInforme = setTimeout(async () => {
    $("i-resumen").textContent = "Calculando…";
    try {
      const d = await api.informeTemporal(filtroActual());
      $("i-resumen").innerHTML = d.total_jornadas
        ? `<strong>${d.personas}</strong> operario(s) · <strong>${d.total_jornadas}</strong>
           jornada(s) · <strong>${numero(d.total_horas)}</strong> horas`
        : "Con estos filtros no hay ninguna jornada. Revise el rango de fechas.";
      $("i-aviso").classList.toggle("hidden", !d.aviso);
      if (d.aviso) $("i-aviso").textContent = d.aviso;
      document.querySelectorAll("[data-bajar]").forEach((b) => {
        b.disabled = !d.total_jornadas;
        b.classList.toggle("opacity-40", !d.total_jornadas);
      });
    } catch (e) {
      $("i-resumen").textContent = e.message || "No se pudo calcular.";
    }
  }, 250);
}

async function abrirInforme() {
  if (!informe.opciones) {
    try {
      informe.opciones = await api.opcionesInformeTemporal();
    } catch (e) {
      return avisar(e.message || "No se pudieron cargar las opciones.", true);
    }
    const llenar = (id, valores, vacio) => {
      $(id).innerHTML = `<option value="">${vacio}</option>` +
        valores.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    };
    llenar("i-proveedor", informe.opciones.proveedores, "Todos");
    llenar("i-labor", informe.opciones.labores, "Todas");

    // Del lunes de esta semana a hoy: es el rango con el que se liquida, y
    // así el primer informe que alguien abre ya trae algo.
    const hoy = new Date();
    const lunes = new Date(hoy);
    lunes.setDate(hoy.getDate() - ((hoy.getDay() + 6) % 7));
    $("i-desde").value = lunes.toISOString().slice(0, 10);
    $("i-hasta").value = hoy.toISOString().slice(0, 10);
  }
  pintarPersonasInforme();
  previsualizarInforme();
  $("modal-informe").showModal();
}

$("btn-informe").addEventListener("click", abrirInforme);
$("i-buscar").addEventListener("input", pintarPersonasInforme);
$("i-todos").addEventListener("click", () => {
  (informe.opciones?.personas || []).forEach((p) => informe.elegidos.add(p.id));
  pintarPersonasInforme(); previsualizarInforme();
});
$("i-ninguno").addEventListener("click", () => {
  informe.elegidos.clear();
  pintarPersonasInforme(); previsualizarInforme();
});
["i-desde", "i-hasta", "i-proveedor", "i-labor", "i-detalle", "i-sin-cerrar", "i-inactivos"]
  .forEach((id) => $(id).addEventListener("change", previsualizarInforme));

document.querySelectorAll("#modal-informe [data-cerrar]").forEach((b) =>
  b.addEventListener("click", () => $("modal-informe").close()));

document.querySelectorAll("[data-bajar]").forEach((boton) =>
  boton.addEventListener("click", async () => {
    boton.disabled = true;
    const original = boton.textContent;
    boton.textContent = "…";
    try {
      await api.bajarInformeTemporal(boton.dataset.bajar, filtroActual());
    } catch (e) {
      avisar(e.message || "No se pudo bajar el informe.", true);
    } finally {
      boton.disabled = false;
      boton.textContent = original;
    }
  }));
