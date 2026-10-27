/* Búsqueda en vivo sobre cualquier listado ya pintado.

   Antes cada pantalla resolvía esto por su cuenta, y la mitad no lo resolvía:
   el calendario del equipo, los períodos de los colaboradores, la garita y
   casi todas las pestañas de administración no tenían forma de filtrar. Con
   trescientas cincuenta personas, una tabla sin búsqueda no se puede usar.

   Filtra por el texto visible de cada fila, así que funciona sobre cualquier
   tabla o lista sin que quien la pinta tenga que saber nada de esto. El coste
   es que solo encuentra lo que está en pantalla: para lo que vive en el
   servidor —los informes— la búsqueda va en el filtro, no aquí. */

/** Quita tildes y pasa a minúsculas: «Suárez» debe encontrarse tecleando «suarez». */
export function normalizar(texto) {
  return (texto || "")
    .toString()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase();
}

/**
 * Conecta un campo de búsqueda a un listado.
 *
 * @param {object} opciones
 * @param {string} opciones.campo      id del input
 * @param {string} opciones.contenedor id de la tabla o lista
 * @param {string} [opciones.filas]    selector de cada fila (por omisión, `tbody tr`)
 * @param {string} [opciones.vacio]    id del cartel de «nada coincide»
 * @param {function} [opciones.alFiltrar] recibe cuántas quedaron visibles
 */
export function montarBuscador({ campo, contenedor, filas = "tbody tr", vacio, alFiltrar }) {
  const entrada = document.getElementById(campo);
  const caja = document.getElementById(contenedor);
  if (!entrada || !caja) return;

  const aplicar = () => {
    const aguja = normalizar(entrada.value.trim());
    let visibles = 0;

    caja.querySelectorAll(filas).forEach((fila) => {
      const coincide = !aguja || normalizar(fila.textContent).includes(aguja);
      fila.classList.toggle("hidden", !coincide);
      if (coincide) visibles += 1;
    });

    if (vacio) {
      const cartel = document.getElementById(vacio);
      if (cartel) {
        cartel.classList.toggle("hidden", visibles > 0 || !aguja);
        if (visibles === 0 && aguja) {
          cartel.textContent = `Nada coincide con «${entrada.value.trim()}».`;
        }
      }
    }
    alFiltrar?.(visibles);
  };

  entrada.addEventListener("input", aplicar);
  // Escape limpia: es lo que espera quien busca y no encuentra.
  entrada.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { entrada.value = ""; aplicar(); }
  });

  // Se vuelve a aplicar cuando el listado se repinta: sin esto, al recargar
  // los datos reaparecían las filas que el usuario había filtrado.
  new MutationObserver(() => { if (entrada.value.trim()) aplicar(); })
    .observe(caja, { childList: true, subtree: true });

  return aplicar;
}

/** El campo de búsqueda, con el mismo aspecto en todas las pantallas. */
export function campoBusqueda(id, marcador = "Buscar") {
  return `<input type="search" id="${id}" placeholder="${marcador}"
                 class="w-full rounded-xl border-0 bg-slate-50 px-3 py-2 text-sm ring-1 ring-slate-300
                        focus:bg-white focus:ring-2 focus:ring-slate-900 sm:w-56">`;
}
