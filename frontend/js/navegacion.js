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
      { texto: "Calendario del equipo", href: "dashboard.html#calendario" },
    ],
  },
  {
    id: "rrhh", texto: "Talento Humano", roles: ["rrhh", "admin"],
    opciones: [
      { texto: "Pendientes de autorización", href: "dashboard.html#aprobaciones", contador: "pendientes" },
      { texto: "Pendientes de anulación", href: "dashboard.html#anulaciones", contador: "anulaciones" },
      { texto: "Colaboradores", href: "colaboradores.html" },
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
          <img src="${esc(cfg.LOGO || "img/logo.svg")}" alt="${esc(cfg.EMPRESA || "")}" class="h-7 w-auto">
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

  contenedor.querySelector("#nav-salir").addEventListener("click", async () => {
    const { api } = await import("./api.js");
    try { await api.cerrarSesion(); } catch { /* el token se descarta igual */ }
    sesion.borrar();
    location.href = "index.html";
  });
}

export const ROL_TEXTO = {
  admin: "Administrador", rrhh: "Talento Humano", jefe: "Jefe inmediato",
  empleado: "Empleado", guardia: "Guardia de seguridad",
};
