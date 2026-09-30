/* Barra de navegación por rol, compartida por todas las pantallas.

   Cada rol ve solo sus módulos. La barra es oscura y el contenido claro:
   así la navegación no compite con los datos, que es lo que se lee. */
import { sesion, esc } from "./api.js";

const MODULOS = [
  { id: "panel",    texto: "Mi panel",     href: "dashboard.html",   roles: "*" },
  {
    id: "jefe", texto: "Jefe", roles: ["jefe", "rrhh", "admin"],
    opciones: [
      { texto: "Pendientes de autorización", href: "dashboard.html#aprobaciones", contador: "pendientes" },
      { texto: "Períodos de mis colaboradores", href: "colaboradores.html" },
      { texto: "Calendario del equipo", href: "equipo.html" },
    ],
  },
  {
    id: "rrhh", texto: "Talento Humano", roles: ["rrhh", "admin"],
    opciones: [
      { texto: "Pendientes de autorización", href: "dashboard.html#aprobaciones", contador: "pendientes" },
      { texto: "Pendientes de anulación", href: "dashboard.html#anulaciones", contador: "anulaciones" },
      { texto: "Colaboradores", href: "colaboradores.html" },
      // La bandeja del chat: el backend la servía desde el principio y
      // ninguna pantalla la consumía, así que las consultas llegaban y
      // nadie podía leerlas.
      { texto: "Mensajes de colaboradores", href: "mensajes.html" },
      { texto: "Cambios de ficha", href: "administracion.html#cambios-ficha" },
      { texto: "Días no laborables", href: "administracion.html#feriados" },
      { texto: "Antigüedades y días", href: "administracion.html#antiguedades" },
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
      { texto: "Resumen por departamento", href: "informes.html#departamentos" },
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
export function montarNavegacion(contenedor, { activo = "panel", contadores = {} } = {}) {
  const perfil = sesion.perfil;
  if (!perfil) return;

  const cfg = window.RRHH_CONFIG || {};
  const modulos = MODULOS.filter((m) => visible(m, perfil.rol));

  const insignia = (clave) => {
    const n = contadores[clave];
    return n ? `<span class="ml-1.5 rounded-full bg-cyan-400 px-1.5 text-[11px] font-bold text-slate-900">${n}</span>` : "";
  };

  contenedor.innerHTML = `
    <div class="bg-slate-900 text-slate-100">
      <div class="mx-auto flex max-w-6xl items-center gap-2 px-3 py-2">
        <a href="dashboard.html" class="flex shrink-0 items-center gap-2 rounded-lg px-1 py-1">
          <img src="${esc(cfg.LOGO_OSCURO || cfg.LOGO || "img/logo-oscuro.png")}"
               alt="${esc(cfg.EMPRESA || "")}" class="h-7 w-auto">
        </a>

        <nav class="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto" aria-label="Módulos">
          ${modulos.map((m) => m.opciones ? `
            <div class="relative shrink-0" data-menu="${m.id}">
              <button type="button" data-abrir="${m.id}"
                      class="flex items-center gap-1 whitespace-nowrap rounded-lg px-3 py-2 text-sm
                             ${activo === m.id ? "bg-slate-800 font-medium" : "text-slate-300 hover:bg-slate-800"}">
                ${esc(m.texto)}
                ${insignia(m.opciones.find((o) => o.contador && contadores[o.contador])?.contador)}
                <span class="text-[10px] opacity-60">▼</span>
              </button>
              <div data-panel="${m.id}" role="menu"
                   class="fixed z-50 hidden min-w-[16rem] overflow-y-auto overscroll-contain rounded-xl
                          border border-slate-200 bg-white py-1.5 text-slate-800 shadow-xl">
                ${m.opciones.map((o) => `
                  <a href="${o.href}"
                     class="flex items-center justify-between gap-3 px-4 py-2.5 text-sm hover:bg-slate-50">
                    <span>${esc(o.texto)}</span>
                    ${o.contador && contadores[o.contador]
                      ? `<span class="rounded-full bg-rose-100 px-1.5 text-xs font-semibold text-rose-700">${contadores[o.contador]}</span>`
                      : ""}
                  </a>`).join("")}
              </div>
            </div>` : `
            <a href="${m.href}"
               class="shrink-0 whitespace-nowrap rounded-lg px-3 py-2 text-sm
                      ${activo === m.id ? "bg-slate-800 font-medium" : "text-slate-300 hover:bg-slate-800"}">
              ${esc(m.texto)}
            </a>`).join("")}
        </nav>

        <button id="nav-campana" class="relative shrink-0 rounded-lg p-2 text-slate-300 hover:bg-slate-800"
                aria-label="Notificaciones">
          <svg class="h-5 w-5" fill="none" stroke="currentColor" stroke-width="1.7" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round"
                  d="M14.9 17.1a3 3 0 1 1-5.8 0m8.6-4.6V10a5.7 5.7 0 1 0-11.4 0v2.5c0 .6-.2 1.1-.6 1.5l-.8.9c-.5.5-.1 1.3.6 1.3h13c.7 0 1.1-.8.6-1.3l-.8-.9a2.1 2.1 0 0 1-.6-1.5Z"/>
          </svg>
          <span id="nav-punto" class="absolute right-1.5 top-1.5 hidden h-2.5 w-2.5 rounded-full
                bg-cyan-400 ring-2 ring-slate-900"></span>
        </button>

        <div class="relative shrink-0">
          <button type="button" data-abrir="perfil"
                  class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-800">
            <span class="grid h-7 w-7 place-items-center rounded-full bg-slate-700 text-xs font-semibold">
              ${esc((perfil.nombre || "?").split(" ").map((p) => p[0]).slice(0, 2).join(""))}
            </span>
            <span class="hidden max-w-[10rem] truncate sm:block">${esc(perfil.nombre)}</span>
          </button>
          <div data-panel="perfil" data-alinear="derecha" role="menu"
               class="fixed z-50 hidden min-w-[14rem] overflow-y-auto overscroll-contain rounded-xl
                      border border-slate-200 bg-white py-1.5 text-slate-800 shadow-xl">
            <p class="px-4 py-2 text-xs text-slate-500">
              ${esc(perfil.cargo || "")}<br>${esc(ROL_TEXTO[perfil.rol] || perfil.rol)}
            </p>
            <hr class="my-1 border-slate-100">
            <a href="dashboard.html" class="block px-4 py-2.5 text-sm hover:bg-slate-50">Mi panel</a>
            <a href="mi-ficha.html" class="block px-4 py-2.5 text-sm hover:bg-slate-50">Mi ficha personal</a>
            <button id="nav-salir" class="block w-full px-4 py-2.5 text-left text-sm hover:bg-slate-50">
              Cerrar sesión
            </button>
          </div>
        </div>
      </div>
    </div>`;

  /* Menús desplegables.

     Los paneles se posicionan con `fixed` y coordenadas calculadas, no con
     `absolute` dentro del botón. Motivo: la barra de módulos necesita
     `overflow-x-auto` para desplazarse en pantallas angostas, y un ancestro
     con overflow recorta a sus descendientes posicionados —aunque sobre
     espacio en la pantalla—. Con `absolute`, el panel simplemente no se veía.
     Con `fixed` sale del recorte, y al calcular la posición se lo mantiene
     dentro de la ventana en móvil. */
  const botones = [...contenedor.querySelectorAll("[data-abrir]")];
  const paneles = [...contenedor.querySelectorAll("[data-panel]")];
  const MARGEN = 8;

  function cerrarTodos() {
    paneles.forEach((p) => p.classList.add("hidden"));
    botones.forEach((b) => b.setAttribute("aria-expanded", "false"));
  }

  function colocar(panel, boton) {
    const caja = boton.getBoundingClientRect();
    panel.classList.remove("hidden");
    const ancho = panel.offsetWidth;
    const derecha = panel.dataset.alinear === "derecha";
    let izquierda = derecha ? caja.right - ancho : caja.left;
    // Nunca fuera de la ventana: en un teléfono el último módulo queda al borde
    izquierda = Math.min(Math.max(MARGEN, izquierda),
                         Math.max(MARGEN, window.innerWidth - ancho - MARGEN));
    panel.style.left = `${izquierda}px`;
    panel.style.top = `${caja.bottom + 4}px`;
    panel.style.maxHeight = `${Math.max(120, window.innerHeight - caja.bottom - 16)}px`;
  }

  let abierto = null;

  botones.forEach((boton) => {
    boton.setAttribute("aria-haspopup", "true");
    boton.setAttribute("aria-expanded", "false");
    boton.addEventListener("click", (e) => {
      e.stopPropagation();
      const panel = contenedor.querySelector(`[data-panel="${boton.dataset.abrir}"]`);
      const yaEstaba = abierto === panel;
      cerrarTodos();
      if (yaEstaba) { abierto = null; return; }
      colocar(panel, boton);
      boton.setAttribute("aria-expanded", "true");
      abierto = panel;
    });
  });

  // Un panel `fixed` no acompaña al documento: si este se mueve, se cierra.
  const cerrar = () => { cerrarTodos(); abierto = null; };
  document.addEventListener("click", cerrar);
  document.addEventListener("keydown", (e) => e.key === "Escape" && cerrar());
  window.addEventListener("resize", cerrar);
  window.addEventListener("scroll", cerrar, { passive: true, capture: true });
  paneles.forEach((p) => p.addEventListener("click", (e) => e.stopPropagation()));

  montarNotificaciones(contenedor);
  // El chat se monta desde aquí y no desde cada pantalla: antes solo lo
  // llamaba el panel, de modo que en el calendario, los informes o
  // administración la burbuja desaparecía sin explicación.
  import("./chat.js").then((m) => m.montarChat()).catch(() => {
    /* si el módulo falla, la pantalla sigue siendo usable */
  });

  contenedor.querySelector("#nav-salir").addEventListener("click", async () => {
    const { api } = await import("./api.js");
    try { await api.cerrarSesion(); } catch { /* el token se descarta igual */ }
    sesion.borrar();
    location.href = "index.html";
  });
}

/* --------------------------------------------------------- notificaciones
   Había dos campanas: esta, presente en todas las pantallas pero sin
   manejador, y otra en la cabecera del panel que sí funcionaba pero solo
   existía ahí. El resultado era que en el calendario, los informes o
   administración no había forma de ver un aviso, y en el panel había dos
   campanas de las que una no respondía.

   Queda una sola, la de la barra, que acompaña a todas las pantallas. */
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
  const boton = contenedor.querySelector("#nav-campana");
  const punto = contenedor.querySelector("#nav-punto");
  if (!boton) return;

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
    punto.classList.toggle("hidden", sinLeer === 0);
    boton.setAttribute("aria-label",
      sinLeer ? `Notificaciones: ${sinLeer} sin leer` : "Notificaciones");
    dialogo.querySelector("#nav-marcar-leidas").classList.toggle("hidden", sinLeer === 0);
    pintar(dialogo.querySelector("#nav-buscar-notif").value);
  };

  boton.addEventListener("click", async (e) => {
    e.stopPropagation();
    await refrescar();
    dialogo.showModal();
  });

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
