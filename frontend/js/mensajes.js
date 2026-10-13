/* Bandeja de Talento Humano: el otro extremo de la burbuja de chat.

   El backend servía /chat/bandeja desde el primer día, pero ninguna pantalla
   lo consumía: los mensajes llegaban y nadie podía leerlos. Peor que no tener
   chat es tenerlo y que la consulta caiga en un pozo.

   Se ve por región —quien atiende Costa no lee lo de Sierra— salvo el
   administrador, que ve todo. Esa separación la aplica el backend; aquí solo
   se muestra de quién es la bandeja para que nadie crea que falta gente. */
import { api, sesion, esc, fechaHora } from "./api.js";
import { montarNavegacion } from "./navegacion.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");
if (!["rrhh", "admin"].includes(sesion.perfil?.rol)) location.replace("dashboard.html");

montarNavegacion($("barra"), { activo: "rrhh" });

const estado = { filtro: "abierta", hilos: [], abierta: null, sondeo: null };

let temporizador;
const avisar = (texto, error = false) => {
  const el = $("aviso");
  el.textContent = texto;
  el.className = `max-w-sm rounded-xl px-4 py-3 text-center text-sm shadow-lg ${
    error ? "bg-rose-600 text-white" : "bg-slate-900 text-white"}`;
  clearTimeout(temporizador);
  temporizador = setTimeout(() => el.classList.add("hidden"), 4000);
};

/* La búsqueda ignora tildes: nadie escribe «Muñoz» con tilde en un buscador,
   y «cedula» debe encontrar «cédula». */
const normalizar = (t) =>
  (t || "").toString().normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/* ------------------------------------------------------------- la lista */

function pintarLista() {
  const aguja = normalizar($("buscar-hilo").value.trim());
  const visibles = aguja
    ? estado.hilos.filter((h) =>
        normalizar(`${h.persona} ${h.cedula} ${h.departamento || ""} ${h.cargo || ""} ` +
                   `${h.ciudad || ""} ${h.asunto || ""} ${h.ultimo_mensaje || ""}`).includes(aguja))
    : estado.hilos;

  const caja = $("lista-hilos");
  if (!visibles.length) {
    caja.innerHTML = `<p class="px-5 py-10 text-center text-sm text-slate-500">${
      aguja ? "Nada coincide con esa búsqueda."
            : estado.filtro === "abierta"
              ? "No hay consultas esperando respuesta."
              : "No hay consultas cerradas."}</p>`;
    return;
  }

  caja.innerHTML = visibles.map((h) => `
    <button type="button" data-hilo="${esc(h.id)}"
            class="block w-full px-4 py-3 text-left hover:bg-slate-50 ${
              estado.abierta === h.id ? "bg-slate-100" : ""}">
      <div class="flex items-start justify-between gap-2">
        <p class="min-w-0 truncate text-sm font-medium">${esc(h.persona)}</p>
        ${h.sin_leer
          ? `<span class="shrink-0 rounded-full bg-rose-500 px-1.5 text-[11px] font-bold text-white">${h.sin_leer}</span>`
          : ""}
      </div>
      <p class="mt-0.5 truncate text-xs text-slate-500">
        ${esc(h.cedula)}${h.departamento ? ` · ${esc(h.departamento)}` : ""}
      </p>
      <p class="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-600">
        ${esc(h.ultimo_mensaje || "(sin mensajes)")}
      </p>
      <p class="mt-1 text-[11px] text-slate-400">
        ${fechaHora(h.updated_at)}${h.atendida_por ? ` · atiende ${esc(h.atendida_por)}` : ""}
      </p>
    </button>`).join("");

  caja.querySelectorAll("[data-hilo]").forEach((b) =>
    b.addEventListener("click", () => abrirHilo(b.dataset.hilo)));
}

async function cargarBandeja({ silencioso = false } = {}) {
  try {
    estado.hilos = await api.bandejaChat(estado.filtro);
  } catch (err) {
    if (!silencioso) avisar(err.message, true);
    return;
  }
  const pendientes = estado.hilos.reduce((n, h) => n + (h.sin_leer || 0), 0);
  $("sub-bandeja").textContent = estado.filtro === "abierta"
    ? `${estado.hilos.length} consulta(s) abierta(s)` +
      (pendientes ? ` · ${pendientes} mensaje(s) sin leer` : " · todo respondido")
    : `${estado.hilos.length} consulta(s) cerrada(s)`;
  pintarLista();
}

/* -------------------------------------------------------- la conversación */

function pintarMensajes(mensajes) {
  const caja = $("hilo-mensajes");
  caja.innerHTML = mensajes.map((m) => `
    <div class="flex ${m.es_rrhh ? "justify-end" : "justify-start"}">
      <div class="max-w-[80%] rounded-2xl px-3.5 py-2.5 text-sm ${m.es_rrhh
        ? "bg-slate-900 text-white"
        : "bg-white text-slate-800 ring-1 ring-slate-200"}">
        <p class="mb-0.5 text-[11px] font-medium ${m.es_rrhh ? "text-slate-400" : "text-slate-500"}">
          ${esc(m.autor)}</p>
        <p class="whitespace-pre-wrap leading-relaxed">${esc(m.texto)}</p>
        <p class="mt-1 text-[10px] text-slate-400">${fechaHora(m.created_at)}</p>
      </div>
    </div>`).join("");
  caja.scrollTop = caja.scrollHeight;
}

async function abrirHilo(id) {
  estado.abierta = id;
  pintarLista();
  const ficha = estado.hilos.find((h) => h.id === id) || {};

  $("cabecera-hilo").classList.remove("hidden");
  $("cabecera-hilo").classList.add("flex");
  $("hilo-persona").textContent = ficha.persona || "";
  $("hilo-detalle").textContent = [ficha.cedula, ficha.cargo, ficha.departamento, ficha.ciudad]
    .filter(Boolean).join(" · ");
  $("hilo-mensajes").innerHTML =
    `<p class="py-16 text-center text-sm text-slate-400">Cargando…</p>`;

  try {
    const hilo = await api.leerConversacion(id);
    pintarMensajes(hilo.mensajes);

    const cerrada = hilo.estado === "cerrada";
    const marca = $("hilo-estado");
    marca.textContent = cerrada ? "Cerrada" : "Abierta";
    marca.className = `rounded-full px-2.5 py-1 text-xs font-medium ${
      cerrada ? "bg-slate-100 text-slate-600" : "bg-emerald-100 text-emerald-800"}`;
    $("btn-cerrar-hilo").classList.toggle("hidden", cerrada);
    // Responder una consulta cerrada la reabre por el lado del colaborador;
    // se deja escribir igual, porque a veces falta una precisión.
    $("form-responder").classList.remove("hidden");
    $("form-responder").classList.add("flex");

    // Ya se leyeron: el contador de esta fila deja de tener sentido.
    const fila = estado.hilos.find((h) => h.id === id);
    if (fila) { fila.sin_leer = 0; pintarLista(); }
    actualizarSubtitulo();
  } catch (err) {
    $("hilo-mensajes").innerHTML =
      `<p class="py-16 text-center text-sm text-rose-600">${esc(err.message)}</p>`;
  }
}

function actualizarSubtitulo() {
  if (estado.filtro !== "abierta") return;
  const pendientes = estado.hilos.reduce((n, h) => n + (h.sin_leer || 0), 0);
  $("sub-bandeja").textContent =
    `${estado.hilos.length} consulta(s) abierta(s)` +
    (pendientes ? ` · ${pendientes} mensaje(s) sin leer` : " · todo respondido");
}

async function responder(e) {
  e.preventDefault();
  const texto = $("texto-respuesta").value.trim();
  if (!texto || !estado.abierta) return;

  $("texto-respuesta").value = "";
  $("texto-respuesta").style.height = "auto";
  try {
    await api.enviarMensaje({ texto, conversacion_id: estado.abierta });
    const hilo = await api.leerConversacion(estado.abierta);
    pintarMensajes(hilo.mensajes);
    await cargarBandeja({ silencioso: true });
  } catch (err) {
    // El texto no se pierde: se devuelve al cuadro para reintentar.
    $("texto-respuesta").value = texto;
    avisar(err.message, true);
  }
}

/* ------------------------------------------------------------- arranque */

document.querySelectorAll("[data-estado]").forEach((b) =>
  b.addEventListener("click", () => {
    estado.filtro = b.dataset.estado;
    document.querySelectorAll("[data-estado]").forEach((otro) => {
      const activo = otro.dataset.estado === estado.filtro;
      otro.className = `rounded-lg px-3 py-1.5 ${
        activo ? "bg-white font-medium shadow-sm" : "text-slate-500"}`;
    });
    estado.abierta = null;
    $("cabecera-hilo").classList.add("hidden");
    $("cabecera-hilo").classList.remove("flex");
    $("form-responder").classList.add("hidden");
    $("form-responder").classList.remove("flex");
    $("hilo-mensajes").innerHTML =
      `<p class="py-16 text-center text-sm text-slate-500">Elija una consulta de la izquierda.</p>`;
    cargarBandeja();
  }));

$("buscar-hilo").addEventListener("input", pintarLista);
$("btn-refrescar").addEventListener("click", () => cargarBandeja());
$("form-responder").addEventListener("submit", responder);
$("texto-respuesta").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = `${Math.min(e.target.scrollHeight, 128)}px`;
});
$("texto-respuesta").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); responder(e); }
});

$("btn-cerrar-hilo").addEventListener("click", async () => {
  if (!estado.abierta) return;
  try {
    const r = await api.cerrarConversacion(estado.abierta);
    avisar(r.mensaje || "Consulta cerrada.");
    estado.abierta = null;
    $("cabecera-hilo").classList.add("hidden");
    $("cabecera-hilo").classList.remove("flex");
    $("form-responder").classList.add("hidden");
    $("form-responder").classList.remove("flex");
    $("hilo-mensajes").innerHTML =
      `<p class="py-16 text-center text-sm text-slate-500">Elija una consulta de la izquierda.</p>`;
    await cargarBandeja();
  } catch (err) {
    avisar(err.message, true);
  }
});

// El primer botón queda marcado sin duplicar las clases en el HTML.
document.querySelector('[data-estado="abierta"]').className =
  "rounded-lg bg-white px-3 py-1.5 font-medium shadow-sm";

cargarBandeja();
// Un minuto: el chat no pretende ser mensajería instantánea, pero nadie
// debería tener que recargar la página para ver que alguien escribió.
estado.sondeo = setInterval(() => cargarBandeja({ silencioso: true }), 60000);
