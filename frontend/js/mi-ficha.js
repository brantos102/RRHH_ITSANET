/* La ficha personal, vista por su dueño.

   El backend servía /mi-ficha desde hace semanas y ninguna pantalla lo
   consumía: los cuatro niveles de campo, los pedidos de cambio y la bandeja
   de Talento Humano existían solo en la API. En la práctica eso significaba
   que nadie podía corregir su propio teléfono.

   La pantalla ordena los datos por quién decide sobre ellos, que es la
   distinción que importa y la que nadie entiende si no se le dice:

     · Lo que corrige uno mismo, sin esperar a nadie (teléfonos, dirección).
     · El correo, que cambia uno pero confirma la dirección nueva.
     · Lo que se señala y confirma Talento Humano (cargo, jefe).
     · Lo que no se toca desde aquí, y por qué. */
import { api, sesion, esc, fecha, fechaHora } from "./api.js";
import { montarNavegacion } from "./navegacion.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");

montarNavegacion($("barra"), { activo: "panel" });

const estado = { ficha: null, jefaturas: null };

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

/* Cómo se muestra cada dato del expediente. Lo que no está aquí no se
   muestra: la ficha trae más columnas de las que a la persona le sirven. */
const EXPEDIENTE = [
  ["cedula", "Cédula"],
  // Con año: de la fecha de ingreso dependen los días de vacaciones, y «1 feb»
  // sin año no dice nada sobre la antigüedad, que es lo único que interesa.
  ["fecha_ingreso", "Fecha de ingreso", (v) => fecha(v)],
  ["cargo", "Cargo"],
  ["departamento", "Área"],
  ["jefe_nombre", "Jefe inmediato"],
  ["bodega", "Bodega"],
  ["cliente", "Cliente"],
  ["centro_costo", "Centro de costo"],
  ["ciudad", "Ciudad"],
  ["provincia", "Provincia"],
  ["region_nombre", "Talento Humano que lo atiende"],
  ["fecha_nacimiento", "Fecha de nacimiento", (v) => fecha(v)],
  ["estado_civil", "Estado civil"],
];

const NIVEL_TEXTO = {
  libre: "Lo corrige usted",
  confirmado: "Lo cambia usted, se confirma por correo",
  revisado: "Lo confirma Talento Humano",
  bloqueado: "No se modifica desde aquí",
};
const NIVEL_TONO = {
  libre: "bg-emerald-100 text-emerald-800",
  confirmado: "bg-sky-100 text-sky-800",
  revisado: "bg-amber-100 text-amber-800",
  bloqueado: "bg-slate-100 text-slate-600",
};

/* ------------------------------------------------------------- pintar */

function pintarExpediente(filtro = "") {
  const { persona, campos } = estado.ficha;
  const niveles = Object.fromEntries(campos.map((c) => [c.campo, c]));
  const aguja = normalizar(filtro.trim());

  const filas = EXPEDIENTE
    .map(([clave, etiqueta, formato]) => {
      const bruto = persona[clave];
      const valor = bruto == null || bruto === "" ? "—"
        : (formato ? formato(bruto) : String(bruto));
      // El nivel se busca por el campo real de la tabla, no por el alias que
      // usa la consulta: `jefe_nombre` es la lectura de `jefe_id`.
      const campo = clave === "jefe_nombre" ? "jefe_id" : clave;
      // La región no es un campo de la ficha: se deduce de la ciudad. Se
      // muestra sin la ayuda de la ciudad, que si no aparecía dos veces
      // seguidas diciendo lo mismo.
      if (clave === "region_nombre") {
        return { etiqueta, valor, nivel: "bloqueado", ayuda: null };
      }
      return { etiqueta, valor, nivel: niveles[campo]?.nivel || "bloqueado",
               ayuda: niveles[campo]?.ayuda };
    })
    .filter((f) => !aguja || normalizar(`${f.etiqueta} ${f.valor}`).includes(aguja));

  $("mf-expediente").innerHTML = filas.length
    ? filas.map((f) => `
      <div class="flex flex-wrap items-start justify-between gap-2 py-2.5">
        <div class="min-w-0">
          <p class="text-xs text-slate-500">${esc(f.etiqueta)}</p>
          <p class="font-medium">${esc(f.valor)}</p>
          ${f.ayuda ? `<p class="mt-0.5 max-w-md text-xs leading-relaxed text-slate-500">${esc(f.ayuda)}</p>` : ""}
        </div>
        <span class="shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${
          NIVEL_TONO[f.nivel]}">${NIVEL_TEXTO[f.nivel]}</span>
      </div>`).join("")
    : `<p class="py-6 text-center text-sm text-slate-500">Nada coincide con esa búsqueda.</p>`;
}

function pintarCambios() {
  const cambios = estado.ficha.cambios || [];
  $("caja-cambios").classList.toggle("hidden", cambios.length === 0);
  const TONO = {
    pendiente: ["bg-amber-50 ring-amber-200", "Esperando a Talento Humano"],
    aprobado: ["bg-emerald-50 ring-emerald-200", "Aplicado"],
    rechazado: ["bg-rose-50 ring-rose-200", "No procedió"],
  };
  $("mf-cambios").innerHTML = cambios.map((c) => {
    const [tono, texto] = TONO[c.estado] || TONO.pendiente;
    return `
      <article class="rounded-xl p-3 text-sm ring-1 ${tono}">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <p class="font-medium">${esc(c.etiqueta)}</p>
          <span class="text-xs">${texto}</span>
        </div>
        <p class="mt-1 text-slate-700">
          ${esc(c.valor_anterior || "sin dato")} → <strong>${esc(c.valor_nuevo)}</strong>
        </p>
        ${c.motivo_rechazo ? `<p class="mt-1 text-xs text-rose-800">${esc(c.motivo_rechazo)}</p>` : ""}
        <p class="mt-1 text-xs text-slate-500">${fechaHora(c.created_at)}</p>
      </article>`;
  }).join("");
}

function pintarConfirmacion() {
  const p = estado.ficha.persona;
  $("mf-cargo").textContent =
    [p.cargo, p.departamento].filter(Boolean).join(" · ") || "Sin cargo registrado";
  $("mf-jefe").textContent = p.jefe_nombre || "Sin jefe registrado";

  // Solo se pregunta a quien no ha respondido: al resto le sobra el recuadro.
  const falta = !p.cargo_confirmado_en || !p.jefe_confirmado_en;
  $("caja-confirmar").classList.toggle("hidden", !falta);
  if (!falta) return;

  if (!p.cargo) marcarIncorrecto("mf-cargo-ok");
  if (!p.jefe_nombre) marcarIncorrecto("mf-jefe-ok");
  cargarJefaturas();
}

function pintar() {
  const p = estado.ficha.persona;
  $("ficha-nombre").textContent = p.nombre;
  $("ficha-resumen").textContent =
    [p.cargo, p.departamento, p.ciudad].filter(Boolean).join(" · ");

  $("mf-telefono").value = p.telefono || "";
  $("mf-telefono-alt").value = p.telefono_alternativo || "";
  $("mf-direccion").value = p.direccion || "";
  $("mf-sangre").value = p.tipo_sangre || "";

  $("mf-correo-actual").textContent = p.email;
  const pendiente = p.correo_por_confirmar;
  $("mf-correo-pendiente").classList.toggle("hidden", !pendiente);
  if (pendiente) {
    $("mf-correo-pendiente").textContent =
      `Falta confirmar ${pendiente}. Abra el enlace que le enviamos ahí; ` +
      "mientras tanto sigue vigente el correo de arriba.";
  }

  pintarConfirmacion();
  pintarExpediente($("buscar-campo").value);
  pintarCambios();
}

async function cargar() {
  try {
    estado.ficha = await api.miFicha();
    pintar();
  } catch (err) {
    avisar(err.message, true);
  }
}

/* --------------------------------------------------- cargo y jefe */

const elegido = (grupo) =>
  document.querySelector(`input[name="${grupo}"]:checked`)?.value || "si";

function marcarIncorrecto(grupo) {
  const opcion = document.querySelector(`input[name="${grupo}"][value="no"]`);
  if (opcion) { opcion.checked = true; opcion.dispatchEvent(new Event("change", { bubbles: true })); }
}

[["mf-cargo-ok", "mf-cargo-nuevo"], ["mf-jefe-ok", "mf-jefe-nuevo"]].forEach(([grupo, campo]) =>
  document.querySelectorAll(`input[name="${grupo}"]`).forEach((opcion) =>
    opcion.addEventListener("change", () =>
      $(campo).classList.toggle("hidden", elegido(grupo) === "si"))));

async function cargarJefaturas() {
  const lista = $("mf-jefe-nuevo");
  if (estado.jefaturas) return;
  try {
    estado.jefaturas = await api.jefaturas();
    lista.insertAdjacentHTML("beforeend", estado.jefaturas.map((j) =>
      `<option value="${esc(j.id)}">${esc([j.nombre, j.cargo].filter(Boolean).join(" · "))}</option>`
    ).join(""));
  } catch {
    lista.insertAdjacentHTML("beforeend",
      '<option value="" disabled>No se pudo cargar la lista</option>');
  }
}

$("btn-confirmar-datos").addEventListener("click", async () => {
  const cargoOk = elegido("mf-cargo-ok") === "si";
  const jefeOk = elegido("mf-jefe-ok") === "si";
  if (!cargoOk && !$("mf-cargo-nuevo").value.trim()) {
    return avisar("Escriba cuál es su cargo.", true);
  }
  if (!jefeOk && !$("mf-jefe-nuevo").value) {
    return avisar("Elija quién es su jefe inmediato.", true);
  }
  try {
    const r = await api.confirmarCargoYJefe({
      cargo_correcto: cargoOk,
      jefe_correcto: jefeOk,
      cargo_propuesto: cargoOk ? null : $("mf-cargo-nuevo").value.trim(),
      jefe_propuesto_id: jefeOk ? null : $("mf-jefe-nuevo").value,
    });
    avisar(r.mensaje);
    await cargar();
  } catch (err) {
    avisar(err.message, true);
  }
});

/* ------------------------------------------------------- contacto */

["mf-telefono", "mf-telefono-alt"].forEach((id) =>
  $(id).addEventListener("input", (e) => {
    e.target.value = e.target.value.replace(/\D/g, "").slice(0, 13);
  }));

$("form-contacto").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api.corregirFicha({
      telefono: $("mf-telefono").value.trim() || null,
      telefono_alternativo: $("mf-telefono-alt").value.trim() || null,
      direccion: $("mf-direccion").value.trim() || null,
      tipo_sangre: $("mf-sangre").value || null,
    });
    avisar("Sus datos quedaron actualizados.");
    await cargar();
  } catch (err) {
    avisar(err.message, true);
  }
});

$("form-correo").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = $("mf-correo-nuevo").value.trim();
  try {
    const r = await api.cambiarCorreo(email);
    avisar(r.mensaje);
    $("mf-correo-nuevo").value = "";
    await cargar();
  } catch (err) {
    avisar(err.message, true);
  }
});

$("buscar-campo").addEventListener("input", (e) => pintarExpediente(e.target.value));

cargar();
