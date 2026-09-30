/* Barra de navegación por rol, compartida por todas las pantallas.

   Cada rol ve solo sus módulos. La barra es oscura y el contenido claro:
   así la navegación no compite con los datos, que es lo que se lee. */
import { sesion, esc } from "./api.js";

const MODULOS = [
  { id: "panel",    texto: "Mi panel",     href: "dashboard.html",   roles: "*" },
  {
    id: "jefe", texto: "Jefe", roles: ["jefe", "rrhh", "admin"],
    opciones: [
      { texto: "Por autorizar", href: "dashboard.html#aprobaciones", contador: "pendientes" },
      { texto: "Períodos del equipo", href: "colaboradores.html" },
      { texto: "Calendario", href: "equipo.html" },
    ],
  },
  {
    id: "rrhh", texto: "Talento Humano", roles: ["rrhh", "admin"],
    opciones: [
      { texto: "Por autorizar", href: "dashboard.html#aprobaciones", contador: "pendientes" },
      { texto: "Anulaciones por resolver", href: "dashboard.html#anulaciones", contador: "anulaciones" },
      { texto: "Colaboradores", href: "colaboradores.html" },
      // La bandeja del chat: el backend la servía desde el principio y
      // ninguna pantalla la consumía, así que las consultas llegaban y
      // nadie podía leerlas.
      { texto: "Mensajes", href: "mensajes.html" },
      { texto: "Cambios de ficha", href: "administracion.html#cambios-ficha" },
      { texto: "Días no laborables", href: "administracion.html#feriados" },
      { texto: "Antigüedades", href: "administracion.html#antiguedades" },
      // La bitácora es herramienta de Talento Humano, no solo del administrador:
      // la trazabilidad de quién pidió, quién aprobó y cuándo es responsabilidad
      // suya ante la LOPDP. El backend ya se la permitía; faltaba en el menú.
      { texto: "Bitácora", href: "administracion.html#bitacora" },
    ],
  },
  {
    id: "informes", texto: "Informes", roles: ["jefe", "rrhh", "admin"],
    opciones: [
      { texto: "Solicitudes", href: "informes.html" },
      { texto: "Por departamento", href: "informes.html#departamentos" },
    ],
  },
  {
    id: "admin", texto: "Administrador", roles: ["admin"],
    opciones: [
      { texto: "Configuración", href: "administracion.html#configuracion" },
      { texto: "Usuarios", href: "administracion.html#usuarios" },
      { texto: "Tipos de solicitud", href: "administracion.html#tipos" },
      { texto: "Bitácora", href: "administracion.html#bitacora" },
    ],
  },
  { id: "garita", texto: "Garita", href: "garita.html", roles: ["guardia", "rrhh", "admin"] },
];

function visible(modulo, rol) {
  return modulo.roles === "*" || modulo.roles.includes(rol);
}

/** Dibuja la barra dentro del elemento indicado. */
/* Iconos en línea, uno por módulo.

   Un menú vertical sin iconos es una lista de palabras: el operativo que
   entra a pedir un permiso recorre todo el texto cada vez. Con icono, la
   segunda vez ya no lee, reconoce. Van en línea y no como archivo: son seis
   trazos y una petición más por pantalla no se justifica. */
const ICONOS = {
  panel: 'M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1V9.5Z',
  jefe: 'M17 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9.5 6.5a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0ZM22 20v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8',
  rrhh: 'M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2m1 0a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2H9V4Zm-1 9h8m-8 4h5',
  informes: 'M3 3v18h18M7 15l3.5-4.5 3 3L20 7',
  admin: 'M10.3 3.3a1 1 0 0 1 1-.8h1.4a1 1 0 0 1 1 .8l.3 1.6a7 7 0 0 1 1.4.8l1.5-.6a1 1 0 0 1 1.2.4l.7 1.2a1 1 0 0 1-.2 1.3l-1.2 1a7 7 0 0 1 0 1.6l1.2 1a1 1 0 0 1 .2 1.3l-.7 1.2a1 1 0 0 1-1.2.4l-1.5-.6a7 7 0 0 1-1.4.8l-.3 1.6a1 1 0 0 1-1 .8h-1.4a1 1 0 0 1-1-.8l-.3-1.6a7 7 0 0 1-1.4-.8l-1.5.6a1 1 0 0 1-1.2-.4l-.7-1.2a1 1 0 0 1 .2-1.3l1.2-1a7 7 0 0 1 0-1.6l-1.2-1a1 1 0 0 1-.2-1.3l.7-1.2a1 1 0 0 1 1.2-.4l1.5.6a7 7 0 0 1 1.4-.8l.3-1.6ZM14.5 12a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z',
  garita: 'M12 2 4 6v6c0 4.4 3.4 8.5 8 10 4.6-1.5 8-5.6 8-10V6l-8-4Zm0 7v4m0 3h.01',
};

const icono = (id) => `
  <svg class="h-5 w-5 shrink-0" fill="none" stroke="currentColor" stroke-width="1.7"
       viewBox="0 0 24 24" aria-hidden="true">
    <path stroke-linecap="round" stroke-linejoin="round" d="${ICONOS[id] || ICONOS.panel}"/>
  </svg>`;

/** Dibuja la navegación: barra lateral en pantalla grande, cajón en teléfono.
 *
 * Era horizontal, y en horizontal los módulos de Talento Humano y
 * administración solo cabían escondidos detrás de desplegables: había que
 * saber que estaban ahí para encontrarlos. En vertical caben abiertos, con
 * sus opciones a la vista, y se entiende de un vistazo qué puede hacer cada
 * quien. También deja de haber una barra que se desplaza de lado en el
 * teléfono, que era la parte que nadie lograba usar.
 *
 * La barra es `fixed` y el desplazamiento del contenido se aplica al `body`
 * desde aquí, no en cada pantalla: así ninguna página tuvo que tocarse.
 */
export function montarNavegacion(contenedor, { activo = "panel", contadores = {} } = {}) {
  const perfil = sesion.perfil;
  if (!perfil) return;

  const cfg = window.RRHH_CONFIG || {};
  const modulos = MODULOS.filter((m) => visible(m, perfil.rol));
  const iniciales = (perfil.nombre || "?").split(" ").map((p) => p[0]).slice(0, 2).join("");

  const insignia = (clave) => {
    const n = contadores[clave];
    return n
      ? `<span class="ml-auto rounded-full bg-cyan-400 px-1.5 text-[11px] font-bold text-slate-900">${n}</span>`
      : "";
  };

  const seccion = (m) => m.opciones ? `
    <div class="mt-3">
      <p class="flex items-center gap-2 px-3 pb-1 text-[11px] font-semibold uppercase
                tracking-wider text-slate-500">
        ${icono(m.id)} <span>${esc(m.texto)}</span>
      </p>
      ${m.opciones.map((o) => `
        <a href="${o.href}" class="flex items-center gap-2 rounded-lg py-1.5 pl-9 pr-3 text-sm
                                   text-slate-300 hover:bg-slate-800 hover:text-white">
          <span class="min-w-0 truncate">${esc(o.texto)}</span>
          ${o.contador && contadores[o.contador]
            ? `<span class="ml-auto rounded-full bg-rose-500 px-1.5 text-[11px] font-bold text-white">${contadores[o.contador]}</span>`
            : ""}
        </a>`).join("")}
    </div>` : `
    <a href="${m.href}" class="mt-1 flex items-center gap-2 rounded-lg px-3 py-2 text-sm
              ${activo === m.id ? "bg-slate-800 font-medium text-white" : "text-slate-300 hover:bg-slate-800 hover:text-white"}">
      ${icono(m.id)} <span>${esc(m.texto)}</span>${insignia(m.id)}
    </a>`;

  const campana = (sufijo) => `
    <button id="nav-campana${sufijo}" data-campana
            class="relative shrink-0 rounded-lg p-2 text-slate-300 hover:bg-slate-800 hover:text-white"
            aria-label="Notificaciones">
      <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.7" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round"
              d="M14.9 17.1a3 3 0 1 1-5.8 0m8.6-4.6V10a5.7 5.7 0 1 0-11.4 0v2.5c0 .6-.2 1.1-.6 1.5l-.8.9c-.5.5-.1 1.3.6 1.3h13c.7 0 1.1-.8.6-1.3l-.8-.9a2.1 2.1 0 0 1-.6-1.5Z"/>
      </svg>
      <span data-punto class="absolute right-1.5 top-1.5 hidden h-2.5 w-2.5 rounded-full
            bg-cyan-400 ring-2 ring-slate-900"></span>
    </button>`;

  const pie = `
    <div class="mt-auto border-t border-slate-800 pt-3">
      <div class="flex items-center gap-2 px-3 py-2">
        <span class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-slate-700 text-xs font-semibold">
          ${esc(iniciales)}
        </span>
        <div class="min-w-0 flex-1">
          <p class="truncate text-sm font-medium text-white">${esc(perfil.nombre)}</p>
          <p class="truncate text-xs text-slate-400">${esc(ROL_TEXTO[perfil.rol] || perfil.rol)}</p>
        </div>
      </div>
      <a href="mi-ficha.html" class="flex items-center gap-2 rounded-lg px-3 py-2 text-sm
                text-slate-300 hover:bg-slate-800 hover:text-white">Mi ficha personal</a>
      <button data-salir class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm
              text-slate-300 hover:bg-slate-800 hover:text-white">Cerrar sesión</button>
    </div>`;

  const cuerpo = (sufijo) => `
    <a href="dashboard.html" class="mb-2 flex shrink-0 items-center gap-2 px-2 py-1">
      <img src="${esc(cfg.LOGO_OSCURO || cfg.LOGO || "img/logo-oscuro.png")}"
           alt="${esc(cfg.EMPRESA || "")}" class="h-8 w-auto">
    </a>
    <nav class="flex-1 overflow-y-auto" aria-label="Módulos">
      ${modulos.map(seccion).join("")}
    </nav>
    ${pie}`;

  contenedor.innerHTML = `
    <!-- Barra superior: solo en pantalla chica, con el botón del cajón -->
    <header class="sticky top-0 z-30 flex items-center gap-2 bg-slate-900 px-3 py-2 text-slate-100 lg:hidden">
      <button id="nav-abrir" class="rounded-lg p-2 hover:bg-slate-800" aria-label="Abrir menú">
        <svg class="h-6 w-6" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24">
          <path stroke-linecap="round" d="M4 7h16M4 12h16M4 17h16"/>
        </svg>
      </button>
      <a href="dashboard.html" class="flex min-w-0 flex-1 items-center">
        <img src="${esc(cfg.LOGO_OSCURO || cfg.LOGO || "img/logo-oscuro.png")}"
             alt="${esc(cfg.EMPRESA || "")}" class="h-7 w-auto">
      </a>
      ${campana("-movil")}
      <span class="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-slate-700 text-xs font-semibold">
        ${esc(iniciales)}
      </span>
    </header>

    <!-- Barra lateral fija, desde lg -->
    <aside class="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col bg-slate-900 px-3 py-4
                  text-slate-100 lg:flex">
      ${cuerpo("")}
      <div class="mt-2 flex justify-center border-t border-slate-800 pt-2">${campana("")}</div>
    </aside>

    <!-- Cajón en teléfono -->
    <div id="nav-cajon" class="fixed inset-0 z-40 hidden lg:hidden">
      <div id="nav-fondo" class="absolute inset-0 bg-slate-900/60"></div>
      <aside class="absolute inset-y-0 left-0 flex w-64 flex-col bg-slate-900 px-3 py-4 text-slate-100 shadow-2xl">
        ${cuerpo("-cajon")}
      </aside>
    </div>`;

  // El contenido se corre para dejarle sitio a la barra. Se hace aquí y no en
  // cada pantalla: así ninguna página tuvo que tocarse para el cambio.
  document.body.classList.add("lg:pl-64");

  const cajon = contenedor.querySelector("#nav-cajon");
  const abrir = () => cajon.classList.remove("hidden");
  const cerrar = () => cajon.classList.add("hidden");
  contenedor.querySelector("#nav-abrir")?.addEventListener("click", abrir);
  contenedor.querySelector("#nav-fondo")?.addEventListener("click", cerrar);
  document.addEventListener("keydown", (e) => e.key === "Escape" && cerrar());

  // Hay dos copias del menú —la fija y la del cajón— y las dos tienen los
  // mismos botones. Se enganchan por atributo y no por identificador, que
  // solo puede haber uno.
  contenedor.querySelectorAll("[data-salir]").forEach((b) =>
    b.addEventListener("click", async () => {
      const { api } = await import("./api.js");
      try { await api.cerrarSesion(); } catch { /* el token se descarta igual */ }
      sesion.borrar();
      location.href = "index.html";
    }));

  montarNotificaciones(contenedor);
  // El chat se monta desde aquí y no desde cada pantalla: antes solo lo
  // llamaba el panel, de modo que en el calendario, los informes o
  // administración la burbuja desaparecía sin explicación.
  import("./chat.js").then((m) => m.montarChat()).catch(() => {
    /* si el módulo falla, la pantalla sigue siendo usable */
  });
}

/* --------------------------------------------------------- notificaciones
   Hubo un momento con dos campanas: una presente en todas las pantallas pero
   sin manejador, y otra en la cabecera del panel que sí funcionaba pero solo
   existía ahí. En el calendario o en los informes no había forma de ver un
   aviso, y en el panel había dos de las que una no respondía.

   Ahora la campana vive en la navegación, que acompaña a todas las
   pantallas. Se dibuja más de una vez —barra lateral, cabecera del teléfono,
   cajón— porque la navegación tiene esas tres formas, pero todas abren el
   mismo diálogo y encienden el mismo punto: es una sola campana con varias
   apariciones, no varias campanas. */
const TONO_PUNTO = {
  critica: "bg-rose-500", advertencia: "bg-amber-500", info: "bg-sky-500",
};

function fechaHora(valor) {
  if (!valor) return "";
  return new Date(valor).toLocaleString("es-EC", {
    day: "numeric", month: "short", hour: "2-digit", minute: "2-digit",
  });
}

function montarNotificaciones(contenedor) {
  // Ahora hay hasta tres copias de la campana —la de la barra lateral, la de
  // la cabecera del teléfono y la del cajón— y las tres tienen que abrir el
  // mismo diálogo y encender el mismo punto. Se buscan por atributo: un
  // identificador solo puede haber uno.
  const botones = [...contenedor.querySelectorAll("[data-campana]")];
  const puntos = [...contenedor.querySelectorAll("[data-punto]")];
  if (!botones.length) return;

  // El diálogo se inyecta aquí y no en cada HTML: una sola copia, y las
  // pantallas que no lo tenían pasan a tenerlo sin tocarlas.
  const dialogo = document.createElement("dialog");
  dialogo.id = "modal-notificaciones";
  dialogo.className = "w-[min(100vw-1.5rem,34rem)] rounded-2xl p-0 text-slate-900";
  dialogo.innerHTML = `
    <div class="max-h-[85dvh] overflow-y-auto">
      <header class="sticky top-0 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4">
        <h2 class="font-semibold">Notificaciones</h2>
        <div class="flex items-center gap-2">
          <button type="button" id="nav-marcar-leidas"
                  class="hidden rounded-lg px-2.5 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100">
            Marcar todas como leídas
          </button>
          <button type="button" id="nav-cerrar-notif"
                  class="rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-100" aria-label="Cerrar">✕</button>
        </div>
      </header>
      <div id="nav-buscar-notif-caja" class="border-b border-slate-100 px-5 py-2.5">
        <input type="search" id="nav-buscar-notif" placeholder="Buscar en sus notificaciones"
               class="w-full rounded-lg border-slate-300 text-sm focus:border-slate-900 focus:ring-slate-900">
      </div>
      <div id="nav-lista-notif" class="divide-y divide-slate-100"></div>
    </div>`;
  document.body.appendChild(dialogo);

  let notificaciones = [];

  const pintar = (filtro = "") => {
    const aguja = filtro.trim().toLowerCase();
    const visibles = aguja
      ? notificaciones.filter((n) =>
          `${n.titulo} ${n.mensaje} ${n.norma || ""} ${n.articulo || ""}`
            .toLowerCase().includes(aguja))
      : notificaciones;

    dialogo.querySelector("#nav-lista-notif").innerHTML = visibles.length
      ? visibles.map((n) => `
        <article class="px-5 py-4 ${n.leida_en ? "opacity-60" : ""}">
          <div class="flex items-start gap-3">
            <span class="mt-1.5 h-2 w-2 shrink-0 rounded-full ${
              TONO_PUNTO[n.severidad] || TONO_PUNTO.info}"></span>
            <div class="min-w-0">
              <p class="font-medium">${esc(n.titulo)}</p>
              <p class="mt-1 text-sm leading-relaxed text-slate-600">${esc(n.mensaje)}</p>
              ${n.articulo_texto ? `<details class="mt-2">
                   <summary class="cursor-pointer text-xs font-medium text-slate-500">
                     ${esc(n.norma)} · ${esc(n.articulo)}</summary>
                   <p class="mt-1.5 rounded-lg bg-slate-50 p-3 text-xs leading-relaxed text-slate-600">
                     ${esc(n.articulo_texto)}</p>
                 </details>` : ""}
              <p class="mt-1.5 text-xs text-slate-400">${fechaHora(n.created_at)}</p>
            </div>
          </div>
        </article>`).join("")
      : `<p class="px-5 py-8 text-center text-sm text-slate-500">${
           aguja ? "Nada coincide con esa búsqueda." : "No tiene notificaciones."}</p>`;
  };

  const refrescar = async () => {
    const { api } = await import("./api.js");
    try {
      notificaciones = await api.notificaciones();
    } catch {
      return;   // Sin conexión no se molesta al usuario: el punto se queda como esté.
    }
    const sinLeer = notificaciones.filter((n) => !n.leida_en).length;
    puntos.forEach((p) => p.classList.toggle("hidden", sinLeer === 0));
    botones.forEach((b) => b.setAttribute("aria-label",
      sinLeer ? `Notificaciones: ${sinLeer} sin leer` : "Notificaciones"));
    dialogo.querySelector("#nav-marcar-leidas").classList.toggle("hidden", sinLeer === 0);
    pintar(dialogo.querySelector("#nav-buscar-notif").value);
  };

  botones.forEach((boton) => boton.addEventListener("click", async (e) => {
    e.stopPropagation();
    await refrescar();
    dialogo.showModal();
  }));

  dialogo.querySelector("#nav-cerrar-notif").addEventListener("click", () => dialogo.close());
  dialogo.querySelector("#nav-buscar-notif").addEventListener("input", (e) => pintar(e.target.value));
  dialogo.querySelector("#nav-marcar-leidas").addEventListener("click", async () => {
    const { api } = await import("./api.js");
    try {
      await api.marcarNotificacionesLeidas();
      await refrescar();
    } catch { /* si falla, quedan sin leer: no se finge lo contrario */ }
  });

  // Al abrir la pantalla se consulta una vez, para que el punto sea fiable
  // desde el primer momento y no solo después de pulsar la campana.
  refrescar();
}

export const ROL_TEXTO = {
  admin: "Administrador", rrhh: "Talento Humano", jefe: "Jefe inmediato",
  empleado: "Empleado", guardia: "Guardia de seguridad",
};
