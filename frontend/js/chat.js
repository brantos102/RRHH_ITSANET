/* Caja de chat con Talento Humano, flotante en todas las pantallas.

   Las dudas cotidianas —cuántos días me quedan, por qué me rechazaron—
   hoy terminan en el WhatsApp personal de alguien de Talento Humano, fuera
   de todo registro. Aquí queda constancia y la consulta llega al equipo de
   la región, no a una persona que puede estar de vacaciones.

   Sobre los botones de llamada y videollamada: abren una sala de Google
   Meet, que la empresa ya tiene con Workspace. Montar WebRTC propio
   —señalización, TURN para atravesar los cortafuegos de las bodegas,
   grabación y su base legal— es un proyecto aparte, no un botón. */
import { api, sesion, esc, fechaHora } from "./api.js";

const $ = (id) => document.getElementById(id);
const estado = { abierto: false, conversacion: null, contactos: null, sede: null, sondeo: null };

const ES_RRHH = ["rrhh", "admin"].includes(sesion.perfil?.rol);

const PAGINA = location.pathname.split("/").pop() || "index.html";

export function montarChat() {
  if (!sesion.vigente) return;
  // Se monta desde la barra, que está en todas las pantallas; sin esta
  // guarda una segunda llamada dejaría dos burbujas superpuestas.
  if (document.getElementById("chat-burbuja")) return;
  // Talento Humano no se escribe a sí mismo: su burbuja lleva a la bandeja,
  // donde lee y responde. Antes no tenía nada —ni burbuja ni bandeja— y por
  // eso, entrando como administrador, el chat parecía no existir.
  if (ES_RRHH) return montarAtajoBandeja();

  const caja = document.createElement("div");
  caja.innerHTML = `
    <button id="chat-burbuja" aria-label="Escribir a Talento Humano"
            class="fixed bottom-5 right-5 z-40 grid h-14 w-14 place-items-center rounded-full
                   bg-slate-900 text-white shadow-lg transition hover:bg-slate-800">
      <svg class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round"
              d="M8 10.5h8M8 14h5m7-1.5a8.5 8.5 0 0 1-12.2 7.7L4 21l.9-3.6A8.5 8.5 0 1 1 20 12.5Z"/>
      </svg>
      <span id="chat-punto" class="absolute right-0 top-0 hidden h-3.5 w-3.5 rounded-full
            bg-rose-500 ring-2 ring-white"></span>
    </button>

    <section id="chat-panel"
             class="fixed bottom-5 right-5 z-50 hidden max-h-[min(80dvh,34rem)]
                    w-[min(100vw-2.5rem,22rem)] flex-col overflow-hidden rounded-2xl
                    bg-white shadow-2xl ring-1 ring-slate-200">
      <header class="flex items-center gap-2 bg-slate-900 px-4 py-3 text-white">
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium">Talento Humano</p>
          <p id="chat-sede" class="truncate text-xs text-slate-400"></p>
        </div>
        <button id="chat-llamar" title="Llamar por Meet"
                class="rounded-lg p-1.5 text-slate-300 hover:bg-slate-800 hover:text-white">
          <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.7" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round"
                  d="M2.5 5.5c0 8.3 6.7 15 15 15l2.5-3.5-4-2.5-2 2a13 13 0 0 1-5.5-5.5l2-2-2.5-4L4.5 3Z"/>
          </svg>
        </button>
        <button id="chat-video" title="Videollamada por Meet"
                class="rounded-lg p-1.5 text-slate-300 hover:bg-slate-800 hover:text-white">
          <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.7" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round"
                  d="M15 10.5 21 7v10l-6-3.5M4 6h9a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Z"/>
          </svg>
        </button>
        <button id="chat-cerrar" aria-label="Cerrar"
                class="rounded-lg p-1.5 text-slate-300 hover:bg-slate-800 hover:text-white">✕</button>
      </header>

      <!-- A qué sede va la consulta.

           Talento Humano está en Quito y en Guayaquil, y cada equipo atiende
           lo suyo. Antes la sede se deducía de la región de la persona y no
           se podía cambiar: quien trabaja en una región y tiene el expediente
           en la otra escribía a la bandeja equivocada, donde nadie esperaba
           su consulta. Solo se puede elegir al abrir el hilo: una conversación
           empezada no cambia de sede a mitad, porque ya hay alguien
           respondiéndola. -->
      <div id="chat-sedes" class="hidden items-center gap-1.5 border-b border-slate-200
                                  bg-white px-3 py-2"></div>

      <div id="chat-mensajes" class="min-h-[12rem] flex-1 space-y-2 overflow-y-auto
                                     bg-slate-50 px-3 py-3 sin-barra"></div>

      <form id="chat-form" class="flex items-end gap-2 border-t border-slate-200 p-2">
        <textarea id="chat-texto" rows="1" maxlength="2000" required
                  placeholder="Escriba su consulta"
                  class="max-h-28 min-h-[2.5rem] flex-1 resize-none rounded-xl border-0 bg-slate-50
                         px-3 py-2 text-sm ring-1 ring-slate-300 focus:bg-white
                         focus:ring-2 focus:ring-slate-900"></textarea>
        <button type="submit" aria-label="Enviar"
                class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-slate-900 text-white
                       hover:bg-slate-800">
          <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" d="m4 12 16-8-5 16-3-6-8-2Z"/>
          </svg>
        </button>
      </form>
    </section>`;
  document.body.appendChild(caja);

  $("chat-burbuja").addEventListener("click", alternar);
  $("chat-cerrar").addEventListener("click", alternar);
  $("chat-form").addEventListener("submit", enviar);
  $("chat-texto").addEventListener("input", (e) => {
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 112)}px`;
  });
  $("chat-texto").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); enviar(e); }
  });
  [["chat-llamar", "audio"], ["chat-video", "video"]].forEach(([id, modo]) =>
    $(id).addEventListener("click", () => abrirMeet(modo))
  );

  revisarSinLeer();
  estado.sondeo = setInterval(revisarSinLeer, 60000);
}

function alternar() {
  estado.abierto = !estado.abierto;
  $("chat-panel").classList.toggle("hidden", !estado.abierto);
  $("chat-panel").classList.toggle("flex", estado.abierto);
  $("chat-burbuja").classList.toggle("hidden", estado.abierto);
  if (estado.abierto) cargar();
}

async function cargar() {
  const caja = $("chat-mensajes");
  caja.innerHTML = `<p class="py-8 text-center text-sm text-slate-400">Cargando…</p>`;

  try {
    if (!estado.contactos) {
      estado.contactos = await api.chatContactos();
      estado.sede = estado.contactos.propia;
    }
    const hilos = await api.misConversaciones();
    if (!hilos.length) {
      estado.conversacion = null;
      pintarSedes();
      return pintar([]);
    }
    estado.conversacion = hilos[0].id;
    const hilo = await api.leerConversacion(estado.conversacion);
    pintarSedes();
    pintar(hilo.mensajes);
    $("chat-punto").classList.add("hidden");
  } catch (err) {
    caja.innerHTML = `<p class="py-8 text-center text-sm text-rose-600">${esc(err.message)}</p>`;
  }
}

/* A qué sede va la consulta.

   Dos botones y no un desplegable: son dos opciones, y un desplegable de dos
   se abre para elegir lo que ya se veía. Con el hilo abierto desaparecen: la
   sede quedó fijada al empezar y cambiarla a mitad dejaría la conversación
   partida entre dos bandejas. */
function pintarSedes() {
  const caja = $("chat-sedes");
  const sedes = estado.contactos?.sedes || [];
  const eligiendo = !estado.conversacion && sedes.length > 1;

  caja.classList.toggle("hidden", !eligiendo);
  caja.classList.toggle("flex", eligiendo);

  const actual = sedes.find((s) => s.codigo === estado.sede);
  $("chat-sede").textContent = actual
    ? `${actual.sede} (${actual.sigla}) · ${estado.contactos.equipo.length} persona(s)`
    : (estado.contactos?.region || "");

  if (!eligiendo) return;
  caja.innerHTML =
    `<span class="mr-0.5 text-xs text-slate-500">Escribo a:</span>` +
    sedes.map((s) => `
      <button type="button" data-sede="${esc(s.codigo)}"
              class="rounded-lg px-2.5 py-1 text-xs font-medium ring-1 transition ${
                s.codigo === estado.sede
                  ? "bg-slate-900 text-white ring-slate-900"
                  : "bg-white text-slate-600 ring-slate-300 hover:ring-slate-500"}">
        ${esc(s.sigla)}${s.es_la_suya ? " · su sede" : ""}
      </button>`).join("");

  caja.querySelectorAll("[data-sede]").forEach((b) =>
    b.addEventListener("click", async () => {
      estado.sede = b.dataset.sede;
      // El equipo que atiende cambia con la sede, y el pie de la cabecera lo
      // dice: quien escribe tiene derecho a saber a quién le está llegando.
      try { estado.contactos = await api.chatContactos(estado.sede); } catch { /* se queda el anterior */ }
      pintarSedes();
      pintar([]);
    }));
}

function pintar(mensajes) {
  const caja = $("chat-mensajes");
  if (!mensajes.length) {
    caja.innerHTML = `
      <div class="px-2 py-6 text-center">
        <p class="text-sm font-medium text-slate-700">¿En qué podemos ayudarle?</p>
        <p class="mx-auto mt-1 max-w-[16rem] text-xs leading-relaxed text-slate-500">
          Escriba su consulta y le responderá el equipo de Talento Humano de
          ${esc(estado.contactos?.sede || "su sede")}. Queda registrada.
        </p>
      </div>`;
    return;
  }

  caja.innerHTML = mensajes.map((m) => `
    <div class="flex ${m.es_rrhh ? "justify-start" : "justify-end"}">
      <div class="max-w-[85%] rounded-2xl px-3 py-2 text-sm ${m.es_rrhh
        ? "bg-white text-slate-800 ring-1 ring-slate-200"
        : "bg-slate-900 text-white"}">
        ${m.es_rrhh ? `<p class="mb-0.5 text-[11px] font-medium text-slate-500">${esc(m.autor)}</p>` : ""}
        <p class="whitespace-pre-wrap">${esc(m.texto)}</p>
        <p class="mt-1 text-[10px] ${m.es_rrhh ? "text-slate-400" : "text-slate-400"}">
          ${fechaHora(m.created_at)}</p>
      </div>
    </div>`).join("");
  caja.scrollTop = caja.scrollHeight;
}

async function enviar(e) {
  e.preventDefault();
  const texto = $("chat-texto").value.trim();
  if (!texto) return;

  $("chat-texto").value = "";
  $("chat-texto").style.height = "auto";
  try {
    const r = await api.enviarMensaje({
      texto,
      conversacion_id: estado.conversacion,
      // Solo cuenta al abrir el hilo; con uno en marcha el servidor la ignora.
      region: estado.conversacion ? undefined : estado.sede,
    });
    estado.conversacion = r.conversacion_id;
    const hilo = await api.leerConversacion(estado.conversacion);
    pintarSedes();
    pintar(hilo.mensajes);
  } catch (err) {
    $("chat-mensajes").insertAdjacentHTML("beforeend",
      `<p class="py-2 text-center text-xs text-rose-600">${esc(err.message)}</p>`);
  }
}

async function revisarSinLeer() {
  if (estado.abierto) return;
  try {
    const hilos = await api.misConversaciones();
    const pendientes = hilos.reduce((n, h) => n + (h.sin_leer || 0), 0);
    $("chat-punto").classList.toggle("hidden", pendientes === 0);
  } catch { /* si falla, la burbuja simplemente no avisa */ }
}

function abrirMeet(modo) {
  /* La empresa ya tiene Google Workspace: una sala de Meet es inmediata y
     no obliga a nadie a dar su número personal. Se avisa por el chat para
     que Talento Humano sepa que hay alguien esperando. */
  const sala = `https://meet.google.com/new`;
  api.enviarMensaje({
    texto: `Solicito una ${modo === "video" ? "videollamada" : "llamada"} por Meet. ` +
           `Abro la sala y comparto el enlace aquí.`,
    conversacion_id: estado.conversacion,
  }).then((r) => { estado.conversacion = r.conversacion_id; cargar(); })
    .catch(() => { /* el aviso es complementario: la sala se abre igual */ });
  window.open(sala, "_blank", "noopener");
}

/* ------------------------------------------------- burbuja de Talento Humano */

function montarAtajoBandeja() {
  if (PAGINA === "mensajes.html") return;   // ya está dentro de la bandeja

  const enlace = document.createElement("a");
  enlace.href = "mensajes.html";
  enlace.id = "chat-burbuja";
  enlace.setAttribute("aria-label", "Mensajes de los colaboradores");
  enlace.className =
    "fixed bottom-5 right-5 z-40 grid h-14 w-14 place-items-center rounded-full " +
    "bg-slate-900 text-white shadow-lg transition hover:bg-slate-800";
  enlace.innerHTML = `
    <svg class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
      <path stroke-linecap="round" stroke-linejoin="round"
            d="M8 10.5h8M8 14h5m7-1.5a8.5 8.5 0 0 1-12.2 7.7L4 21l.9-3.6A8.5 8.5 0 1 1 20 12.5Z"/>
    </svg>
    <span id="chat-punto" class="absolute -right-1 -top-1 hidden min-w-[1.25rem] rounded-full
          bg-rose-500 px-1 text-center text-[11px] font-bold leading-5 text-white
          ring-2 ring-white"></span>`;
  document.body.appendChild(enlace);

  const contar = async () => {
    try {
      const hilos = await api.bandejaChat("abierta");
      const sinLeer = hilos.reduce((n, h) => n + (h.sin_leer || 0), 0);
      const punto = $("chat-punto");
      punto.textContent = sinLeer > 99 ? "99+" : sinLeer;
      punto.classList.toggle("hidden", sinLeer === 0);
      enlace.setAttribute("aria-label", sinLeer
        ? `Mensajes de los colaboradores: ${sinLeer} sin leer`
        : "Mensajes de los colaboradores");
    } catch { /* sin conexión la burbuja simplemente no avisa */ }
  };
  contar();
  estado.sondeo = setInterval(contar, 60000);
}
