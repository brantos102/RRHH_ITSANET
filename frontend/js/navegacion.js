/* Barra de navegación por rol, compartida por todas las pantallas.

   Cada rol ve solo sus módulos. La barra es oscura y el contenido claro:
   así la navegación no compite con los datos, que es lo que se lee. */
import { sesion, esc } from "./api.js";

const MODULOS = [
  { id: "panel",    texto: "Mi panel",     href: "dashboard.html",   roles: "*" },
  // Lo operativo va arriba: son un enlace cada uno, se usan a diario y al
  // final de la lista quedaban por debajo del corte de la barra.
  { id: "garita", texto: "Garita", href: "garita.html", roles: ["guardia", "rrhh", "admin"] },
  // El personal temporal es otro sistema: viene por jornadas y se le paga por
  // semana. Lo usa la garita para registrar y Talento Humano para liquidar.
  { id: "temporal", texto: "Personal temporal", href: "temporal.html",
    roles: ["guardia", "rrhh", "admin"] },
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
      // Lo que el colaborador lee antes de enviar una solicitud. Estaba
      // escrito en el HTML y lo decide Talento Humano, no el programa.
      { texto: "Lineamientos", href: "administracion.html#lineamientos" },
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
      // Lo primero del menú del administrador es lo que ven las 350
      // personas al entrar. Antes eso solo se cambiaba editando el HTML.
      { texto: "Pantalla principal", href: "pantalla-principal.html" },
      { texto: "Configuración", href: "administracion.html#configuracion" },
      { texto: "Usuarios", href: "administracion.html#usuarios" },
      { texto: "Tipos de solicitud", href: "administracion.html#tipos" },
      { texto: "Bitácora", href: "administracion.html#bitacora" },
    ],
  },
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
  temporal: 'M12 8v4l2.5 2.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
};

/* Y un icono por opción dentro de cada grupo. Un desplegable abierto con
   nueve renglones de texto seguido se lee como un párrafo; con una marca a
   la izquierda de cada uno, se recorre. */
const ICONOS_OPCION = {
  "Por autorizar":            'M9 12.5l2 2 4-4.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  "Anulaciones por resolver": 'M12 9v4m0 3h.01M10.3 3.9 2.6 17a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z',
  "Períodos del equipo":      'M8 2v4M16 2v4M3.5 9.5h17M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z',
  "Calendario":               'M8 2v4M16 2v4M3.5 9.5h17M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z',
  "Colaboradores":            'M17 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9.5 6.5a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0ZM22 20v-2a4 4 0 0 0-3-3.9',
  "Mensajes":                 'M8 10.5h8M8 14h5m7-1.5a8.5 8.5 0 0 1-12.2 7.7L4 21l.9-3.6A8.5 8.5 0 1 1 20 12.5Z',
  "Cambios de ficha":         'M11 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5m-2.5-9.5a2.1 2.1 0 0 1 3 3L12 16l-4 1 1-4 8.5-8.5Z',
  "Días no laborables":       'M8 2v4M16 2v4M3.5 9.5h17M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Zm4 10 6 4m0-4-6 4',
  "Antigüedades":             'M12 8v4l2.5 2.5M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z',
  "Bitácora":                 'M4 5a2 2 0 0 1 2-2h11a1 1 0 0 1 1 1v15H6a2 2 0 0 0-2 2V5Zm4 3h7M8 12h7',
  "Solicitudes":              'M9 3h6a1 1 0 0 1 1 1v1h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2V4a1 1 0 0 1 1-1Zm-1 9h8m-8 4h5',
  "Por departamento":         'M3 3v18h18M7 17v-5m5 5V8m5 9v-7',
  "Pantalla principal":       'M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1V9.5Z',
  "Lineamientos":             'M9 3h6a1 1 0 0 1 1 1v1h2a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h2V4a1 1 0 0 1 1-1Zm-1 8h8m-8 4h5',
  "Configuración":            'M10.3 3.3a1 1 0 0 1 1-.8h1.4a1 1 0 0 1 1 .8l.3 1.6 1.4.8 1.5-.6a1 1 0 0 1 1.2.4l.7 1.2a1 1 0 0 1-.2 1.3l-1.2 1v1.6l1.2 1a1 1 0 0 1 .2 1.3l-.7 1.2a1 1 0 0 1-1.2.4l-1.5-.6-1.4.8-.3 1.6a1 1 0 0 1-1 .8h-1.4a1 1 0 0 1-1-.8M14.5 12a2.5 2.5 0 1 1-5 0 2.5 2.5 0 0 1 5 0Z',
  "Usuarios":                 'M17 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9.5 6.5a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Z',
  "Tipos de solicitud":       'M4 7h16M4 12h10M4 17h7',
};

const iconoOpcion = (texto) => `
  <svg class="h-4 w-4 shrink-0 opacity-70" fill="none" stroke="currentColor" stroke-width="1.7"
       viewBox="0 0 24 24" aria-hidden="true">
    <path stroke-linecap="round" stroke-linejoin="round"
          d="${ICONOS_OPCION[texto] || 'M5 12h14'}"/>
  </svg>`;

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

  /* Cada grupo se pliega y se despliega, y recuerda cómo lo dejó cada quien.

     Antes estaban todos abiertos siempre: veinte renglones que no caben en
     una pantalla de portátil y obligan a desplazar el menú para llegar a lo
     de abajo. Quien usa dos módulos cierra los otros una vez y no vuelve a
     verlos. Se guarda en el navegador de cada persona, que es donde
     corresponde: es una preferencia de uso, no un dato de la empresa.

     El grupo de la pantalla en la que se está aparece siempre abierto, y lo
     que tiene pendientes también: un contador escondido dentro de un grupo
     cerrado no avisa de nada. */
  const LLAVE = "rrhh.menu.cerrados";
  const cerrados = new Set(leerCerrados());

  const pendientesDe = (m) =>
    (m.opciones || []).some((o) => o.contador && contadores[o.contador]);

  const abierto = (m) =>
    activo === m.id || pendientesDe(m) || !cerrados.has(m.id);

  const seccion = (m) => m.opciones ? `
    <div class="mt-2" data-grupo="${m.id}">
      <button type="button" data-plegar="${m.id}" aria-expanded="${abierto(m)}"
              class="flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-[11px]
                     font-semibold uppercase tracking-wider text-slate-400
                     hover:bg-slate-800 hover:text-slate-200">
        ${icono(m.id)}
        <span class="min-w-0 flex-1 truncate text-left">${esc(m.texto)}</span>
        ${pendientesDe(m) && !abierto(m)
          ? `<span class="rounded-full bg-rose-500 px-1.5 text-[11px] font-bold text-white">•</span>`
          : ""}
        <svg data-flecha class="h-3.5 w-3.5 shrink-0 transition-transform duration-150
             ${abierto(m) ? "" : "-rotate-90"}"
             fill="none" stroke="currentColor" stroke-width="2.2" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" d="m6 9 6 6 6-6"/>
        </svg>
      </button>
      <div data-opciones class="${abierto(m) ? "" : "hidden"} mt-0.5">
        ${m.opciones.map((o) => `
          <a href="${o.href}" class="flex items-center gap-2 rounded-lg py-1.5 pl-6 pr-3 text-sm
                                     text-slate-300 hover:bg-slate-800 hover:text-white">
            ${iconoOpcion(o.texto)}
            <span class="min-w-0 truncate">${esc(o.texto)}</span>
            ${o.contador && contadores[o.contador]
              ? `<span class="ml-auto rounded-full bg-rose-500 px-1.5 text-[11px] font-bold text-white">${contadores[o.contador]}</span>`
              : ""}
          </a>`).join("")}
      </div>
    </div>` : `
    <a href="${m.href}" class="mt-1 flex items-center gap-2 rounded-lg px-3 py-2 text-sm
              ${activo === m.id ? "bg-slate-800 font-medium text-white" : "text-slate-300 hover:bg-slate-800 hover:text-white"}">
      ${icono(m.id)} <span>${esc(m.texto)}</span>${insignia(m.id)}
    </a>`;

  /* El buscador de personas, para quien tiene gente a cargo.

     Responde a lo que no se podía hacer: abrir el expediente de alguien por
     su nombre. Antes había que saber en qué pantalla estaba cada cosa —la
     ficha en una, los períodos en otra, las solicitudes en una tercera— y
     cruzarlas a mano. */
  const PUEDE_BUSCAR = ["jefe", "rrhh", "admin"].includes(perfil.rol);
  const buscador = (sufijo) => PUEDE_BUSCAR ? `
    <div class="relative mb-2 px-1">
      <input type="search" data-buscar-persona autocomplete="off"
             placeholder="Buscar una persona…"
             class="w-full rounded-lg border-0 bg-slate-800 px-3 py-2 text-sm text-slate-100
                    placeholder:text-slate-500 focus:bg-slate-700 focus:outline-none
                    focus:ring-2 focus:ring-cyan-400">
      <div data-resultados
           class="absolute inset-x-1 top-full z-50 mt-1 hidden max-h-72 overflow-y-auto
                  rounded-xl bg-white py-1 text-slate-900 shadow-2xl ring-1 ring-slate-300
                  sin-barra"></div>
    </div>` : "";

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
    ${buscador(sufijo)}
    <nav class="sin-barra flex-1 overflow-y-auto overscroll-contain" aria-label="Módulos">
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

  // Plegar y desplegar. Se enganchan por atributo y no por identificador
  // porque hay dos copias del menú —la fija y la del cajón— y las dos tienen
  // los mismos grupos.
  contenedor.querySelectorAll("[data-plegar]").forEach((boton) =>
    boton.addEventListener("click", () => {
      const grupo = boton.dataset.plegar;
      const estaAbierto = boton.getAttribute("aria-expanded") === "true";
      if (estaAbierto) cerrados.add(grupo); else cerrados.delete(grupo);
      guardarCerrados([...cerrados]);
      // Las dos copias a la vez: si no, abrir un grupo en el cajón lo dejaba
      // cerrado en la barra y al girar el teléfono el menú cambiaba solo.
      contenedor.querySelectorAll(`[data-plegar="${grupo}"]`).forEach((b) => {
        b.setAttribute("aria-expanded", String(!estaAbierto));
        b.querySelector("[data-flecha]")?.classList.toggle("-rotate-90", estaAbierto);
        b.parentElement.querySelector("[data-opciones]")
          ?.classList.toggle("hidden", estaAbierto);
      });
    }));

  montarBuscadorDePersonas(contenedor);
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


/* --------------------------------------------------- qué grupos van cerrados

   En el navegador de cada persona y no en la base: es una preferencia de uso
   —cómo le gusta ver su menú— y no un dato de la empresa. Envuelto en
   try/catch porque en una ventana privada o con el almacenamiento bloqueado
   leerlo lanza, y un menú que no se dibuja por esto sería absurdo. */
function leerCerrados() {
  try {
    return JSON.parse(localStorage.getItem("rrhh.menu.cerrados") || "[]");
  } catch { return []; }
}

function guardarCerrados(lista) {
  try {
    localStorage.setItem("rrhh.menu.cerrados", JSON.stringify(lista));
  } catch { /* sin memoria: el menú funciona igual, solo no recuerda */ }
}

/* ------------------------------------------------- buscar a una persona

   Escribir dos letras del nombre y llegar a su expediente. Lo usan las
   jefaturas y Talento Humano, que es a quienes les corresponde; el servidor
   además solo devuelve a quien cada quien puede ver, así que un jefe no
   encuentra gente de otra área ni probando. */
function montarBuscadorDePersonas(contenedor) {
  contenedor.querySelectorAll("[data-buscar-persona]").forEach((entrada) => {
    const caja = entrada.parentElement.querySelector("[data-resultados]");
    let temporizador;
    let ultima = 0;

    const pintar = (gente) => {
      if (!gente.length) {
        caja.innerHTML = `<p class="px-3 py-2 text-sm text-slate-500">
                            Nadie coincide con eso.</p>`;
      } else {
        caja.innerHTML = gente.map((p) => `
          <a href="persona.html?id=${encodeURIComponent(p.id)}"
             class="block px-3 py-2 hover:bg-slate-100">
            <p class="truncate text-sm font-medium">${esc(p.nombre)}</p>
            <p class="truncate text-xs text-slate-500">
              ${esc(p.cedula)}${p.cargo ? ` · ${esc(p.cargo)}` : ""}</p>
          </a>`).join("");
      }
      caja.classList.remove("hidden");
    };

    entrada.addEventListener("input", () => {
      clearTimeout(temporizador);
      const texto = entrada.value.trim();
      if (texto.length < 2) { caja.classList.add("hidden"); return; }
      // Se espera a que deje de teclear: sin esto, «Espinosa» son ocho
      // consultas y la que contesta última no es la última que se pidió.
      temporizador = setTimeout(async () => {
        const mio = ++ultima;
        try {
          const { api } = await import("./api.js");
          const gente = await api.buscarPersona(texto);
          if (mio === ultima) pintar(gente);
        } catch {
          if (mio === ultima) {
            caja.innerHTML = `<p class="px-3 py-2 text-sm text-rose-600">
                                No se pudo buscar.</p>`;
            caja.classList.remove("hidden");
          }
        }
      }, 250);
    });

    entrada.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { entrada.value = ""; caja.classList.add("hidden"); }
      // Enter abre el primero: quien escribe un nombre y pulsa Enter espera
      // llegar, no quedarse mirando una lista de uno.
      if (e.key === "Enter") {
        e.preventDefault();
        caja.querySelector("a")?.click();
      }
    });

    document.addEventListener("click", (e) => {
      if (!entrada.parentElement.contains(e.target)) caja.classList.add("hidden");
    });
  });
}
