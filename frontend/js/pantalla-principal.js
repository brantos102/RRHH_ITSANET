/* Qué se ve en la pantalla principal, decidido desde una pantalla.

   El panel del colaborador se fue llenando de bloques y todos se mostraban
   siempre a todo el mundo. No todas las empresas quieren lo mismo en la
   primera pantalla: hay quien no usa firma electrónica, quien prefiere que el
   calendario del equipo lo vea solo jefatura, y quien necesita poner un aviso
   arriba durante una semana.

   Cada cambio se guarda solo, en cuanto se toca. No hay botón de «guardar»
   para los interruptores a propósito: un formulario con diez interruptores y
   un botón al fondo se queda a medias con toda naturalidad, y quien lo dejó a
   medias cree que ya está hecho. El aviso sí lleva botón, porque se escribe. */
import { api, sesion, esc } from "./api.js";
import { montarNavegacion } from "./navegacion.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");
if (sesion.perfil?.rol !== "admin") location.replace("dashboard.html");

montarNavegacion($("barra"), { activo: "admin" });

let temporizador;
const avisar = (texto, error = false) => {
  const el = $("aviso");
  el.innerHTML = `<div class="max-w-sm rounded-xl px-4 py-3 text-center text-sm shadow-lg ${
    error ? "bg-rose-600 text-white" : "bg-slate-900 text-white"}">${esc(texto)}</div>`;
  clearTimeout(temporizador);
  temporizador = setTimeout(() => { el.innerHTML = ""; }, 5000);
};

const estado = { bloques: [] };

const ROLES = [
  ["empleado", "Colaboradores"],
  ["jefe", "Jefaturas"],
  ["rrhh", "Talento Humano"],
  ["admin", "Administradores"],
  ["guardia", "Garita"],
];

/* ------------------------------------------------------------- la lista */

function fila(b, indice, total) {
  // Los roles se dicen en palabras y no como etiquetas sueltas: «Lo ven
  // Jefaturas y Talento Humano» se entiende sin aprenderse nada.
  const quienes = b.para_todos
    ? "Lo ve todo el personal"
    : "Lo ven " + b.roles.map((r) => ROLES.find(([c]) => c === r)?.[1] || r).join(", ");

  return `
  <article data-clave="${esc(b.clave)}"
           class="rounded-xl p-4 ring-1 ${
             b.visible ? "bg-white ring-slate-200" : "bg-slate-50 ring-slate-200"}">
    <div class="flex flex-wrap items-start gap-3">
      <div class="flex shrink-0 flex-col gap-1">
        <button data-subir class="rounded-lg px-2 py-0.5 text-slate-400 hover:bg-slate-100
                hover:text-slate-900 disabled:opacity-25" ${indice === 0 ? "disabled" : ""}
                aria-label="Subir ${esc(b.titulo)}">▲</button>
        <button data-bajar class="rounded-lg px-2 py-0.5 text-slate-400 hover:bg-slate-100
                hover:text-slate-900 disabled:opacity-25" ${indice === total - 1 ? "disabled" : ""}
                aria-label="Bajar ${esc(b.titulo)}">▼</button>
      </div>

      <div class="min-w-0 flex-1">
        <p class="font-medium ${b.visible ? "" : "text-slate-500"}">
          ${esc(b.titulo)}
          ${b.esencial
            ? `<span class="ml-1.5 rounded-full bg-slate-900 px-2 py-0.5 text-[11px]
                 font-medium text-white">imprescindible</span>` : ""}
        </p>
        <p class="mt-1 text-sm leading-relaxed text-slate-600">${esc(b.descripcion)}</p>

        <div class="mt-2 flex flex-wrap items-center gap-2">
          <span class="text-xs text-slate-500">${esc(quienes)}</span>
          <button data-roles class="rounded-lg bg-slate-100 px-2 py-1 text-xs font-medium
                  hover:bg-slate-200">Cambiar quién lo ve</button>
        </div>

        <div data-caja-roles class="mt-2 hidden flex-wrap gap-3 rounded-xl bg-slate-50 p-3">
          <label class="flex items-center gap-2 text-xs">
            <input type="checkbox" data-todos ${b.para_todos ? "checked" : ""}
                   class="h-4 w-4 rounded border-slate-300">
            Todo el personal
          </label>
          ${ROLES.map(([clave, texto]) => `
            <label class="flex items-center gap-2 text-xs">
              <input type="checkbox" data-rol="${clave}"
                     ${b.roles.includes(clave) ? "checked" : ""}
                     ${b.para_todos ? "disabled" : ""}
                     class="h-4 w-4 rounded border-slate-300">
              ${texto}
            </label>`).join("")}
        </div>

        ${b.actualizado_por_nombre
          ? `<p class="mt-2 text-xs text-slate-400">Último cambio: ${
               esc(b.actualizado_por_nombre)}</p>` : ""}
      </div>

      <label data-interruptor class="flex shrink-0 cursor-pointer items-center gap-2 ${
        b.esencial ? "cursor-not-allowed opacity-40" : ""}">
        <input type="checkbox" data-visible ${b.visible ? "checked" : ""}
               ${b.esencial ? "disabled" : ""} class="peer sr-only">
        <span class="relative h-6 w-11 rounded-full bg-slate-300 transition
                     peer-checked:bg-emerald-600
                     after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5
                     after:rounded-full after:bg-white after:transition
                     peer-checked:after:translate-x-5"></span>
        <span class="w-14 text-xs text-slate-600">${b.visible ? "Se ve" : "Oculto"}</span>
      </label>
    </div>
  </article>`;
}

function pintar() {
  const total = estado.bloques.length;
  $("lista").innerHTML = estado.bloques.map((b, i) => fila(b, i, total)).join("");

  const anuncio = estado.bloques.find((b) => b.clave === "anuncio");
  $("anuncio").value = anuncio?.cuerpo || "";
  $("anuncio-estado").textContent = anuncio?.cuerpo
    ? "Se está mostrando en el panel de todo el personal."
    : "Ahora mismo no se muestra ningún aviso.";
}

/* -------------------------------------------------------------- cambios */

async function cambiar(clave, cambios) {
  try {
    await api.panelCambiar(clave, cambios);
    await recargar();
    avisar("Guardado.");
  } catch (e) {
    // Se recarga también al fallar: si la base rechazó el cambio —apagar un
    // bloque imprescindible, por ejemplo—, la pantalla no puede quedarse
    // mostrando el interruptor como si hubiera funcionado.
    await recargar();
    avisar(e.message || "No se pudo guardar.", true);
  }
}

$("lista").addEventListener("click", async (ev) => {
  const tarjeta = ev.target.closest("[data-clave]");
  if (!tarjeta) return;
  const clave = tarjeta.dataset.clave;

  if (ev.target.closest("[data-roles]")) {
    tarjeta.querySelector("[data-caja-roles]").classList.toggle("hidden");
    tarjeta.querySelector("[data-caja-roles]").classList.toggle("flex");
    return;
  }

  const delta = ev.target.closest("[data-subir]") ? -1
              : ev.target.closest("[data-bajar]") ? 1 : 0;
  if (!delta) return;

  const i = estado.bloques.findIndex((b) => b.clave === clave);
  if (i + delta < 0 || i + delta >= estado.bloques.length) return;
  const orden = estado.bloques.map((b) => b.clave);
  [orden[i], orden[i + delta]] = [orden[i + delta], orden[i]];
  try {
    const r = await api.panelReordenar(orden);
    estado.bloques = r.bloques;
    pintar();
  } catch (e) {
    avisar(e.message || "No se pudo reordenar.", true);
  }
});

$("lista").addEventListener("change", async (ev) => {
  const tarjeta = ev.target.closest("[data-clave]");
  if (!tarjeta) return;
  const clave = tarjeta.dataset.clave;

  if (ev.target.matches("[data-visible]")) {
    await cambiar(clave, { visible: ev.target.checked });
    return;
  }

  if (ev.target.matches("[data-todos]") || ev.target.matches("[data-rol]")) {
    const todos = tarjeta.querySelector("[data-todos]").checked;
    // «Todo el personal» es la lista vacía, no los cinco roles marcados.
    // Guardar los cinco funcionaría hoy y dejaría de funcionar el día que
    // se añada un rol nuevo, que no estaría en ninguna lista.
    const roles = todos ? [] : [...tarjeta.querySelectorAll("[data-rol]:checked")]
                                 .map((c) => c.dataset.rol);
    if (!todos && !roles.length) {
      avisar("Elija al menos un rol, o marque «Todo el personal».", true);
      await recargar();
      return;
    }
    await cambiar(clave, { roles });
  }
});

$("btn-anuncio").addEventListener("click", async () => {
  $("btn-anuncio").disabled = true;
  await cambiar("anuncio", { cuerpo: $("anuncio").value });
  $("btn-anuncio").disabled = false;
});

/* --------------------------------------------------------------- inicio */

async function recargar() {
  const r = await api.panelConfiguracion();
  estado.bloques = r.bloques;
  pintar();
}

recargar().catch((e) => {
  $("lista").innerHTML =
    `<p class="rounded-xl bg-rose-50 p-4 text-sm text-rose-800">${
       esc(e.message || "No se pudo cargar la configuración.")}</p>`;
});
