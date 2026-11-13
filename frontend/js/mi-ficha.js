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
import { montarContactos } from "./contactos.js";

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
  // El contrato se muestra, no se edita: lo registra Talento Humano.
  ["tipo_contrato", "Tipo de contrato", (v) => CONTRATO[v] || v],
  ["contrato_fin", "Fin del contrato", (v) => fecha(v)],
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

const CONTRATO = {
  indefinido: "Indefinido", eventual: "Eventual", ocasional: "Ocasional", temporada: "De temporada",
  obra_cierta: "Por obra cierta", prueba: "A prueba", aprendizaje: "De aprendizaje", pasantia: "Pasantía",
};

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

const SI_NO = new Set(["tiene_discapacidad", "sustituto_discapacidad"]);
const TIPO_DISC = { fisica: "Física", intelectual: "Intelectual", auditiva: "Auditiva", visual: "Visual",
                    psicosocial: "Psicosocial", multiple: "Múltiple" };
function legible(campo, valor) {
  if (valor == null || valor === "") return valor;
  if (SI_NO.has(campo)) return valor === "1" ? "Sí" : valor === "0" ? "No" : valor;
  if (campo === "tipo_discapacidad") return TIPO_DISC[valor] || valor;
  if (campo === "porcentaje_discapacidad") return `${valor} %`;
  return valor;
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
          ${esc(legible(c.campo, c.valor_anterior) || "sin dato")} → <strong>${esc(legible(c.campo, c.valor_nuevo))}</strong>
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

  // Solo se pregunta a quien no ha confirmado su jefe. El cargo y el área
  // los administra Talento Humano: no se confirman ni se piden aquí.
  const falta = !p.jefe_confirmado_en;
  $("caja-confirmar").classList.toggle("hidden", !falta);
  if (!falta) return;

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
  DOMICILIO.forEach(([id, campo]) => { $(id).value = p[campo] || ""; });
  pintarTelefonos(estado.ficha.telefonos || []);
  $("mf-sangre").value = p.tipo_sangre || "";

  $("mf-correo-actual").textContent = p.email;
  const pendiente = p.correo_por_confirmar;
  $("mf-correo-pendiente").classList.toggle("hidden", !pendiente);
  if (pendiente) {
    $("mf-correo-pendiente").textContent =
      `Falta confirmar ${pendiente}. Abra el enlace que le enviamos ahí; ` +
      "mientras tanto sigue vigente el correo de arriba.";
  }

  pintarDiscapacidad();
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

/* ---------------------------------------------- domicilio y teléfonos */
const DOMICILIO = [
  ["mf-dom-provincia", "domicilio_provincia"], ["mf-dom-canton", "domicilio_canton"],
  ["mf-dom-parroquia", "domicilio_parroquia"], ["mf-dom-calle", "domicilio_calle"],
  ["mf-dom-numero", "domicilio_numero"], ["mf-dom-interseccion", "domicilio_interseccion"],
  ["mf-dom-referencia", "domicilio_referencia"],
];
const TIPO_TEL = { celular: "Celular", fijo: "Fijo", trabajo: "Trabajo", otro: "Otro" };

function pintarTelefonos(lista) {
  $("mf-telefonos").innerHTML = lista.length ? lista.map((t) => `
    <li class="flex items-center gap-3 px-3 py-2 text-sm">
      <span class="font-mono">${esc(t.numero)}</span>
      <span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs">${esc(TIPO_TEL[t.tipo] || t.tipo)}</span>
      <span class="min-w-0 flex-1 truncate text-slate-500">${esc(t.etiqueta || "")}</span>
      <button type="button" data-quitar-tel="${t.id}" class="rounded-lg px-2 py-1 text-xs text-rose-700 hover:bg-rose-50">Quitar</button>
    </li>`).join("") : '<li class="px-3 py-2.5 text-sm text-slate-500">Sin teléfonos adicionales.</li>';
  $("form-telefono").classList.toggle("hidden", lista.length >= 5);
}

$("mf-tel-numero").addEventListener("input", (e) => { e.target.value = e.target.value.replace(/\D/g, "").slice(0, 13); });
$("form-telefono").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    avisar((await api.agregarMiTelefono({ numero: $("mf-tel-numero").value,
      tipo: $("mf-tel-tipo").value, etiqueta: $("mf-tel-etiqueta").value.trim() || null })).mensaje);
    $("form-telefono").reset();
    pintarTelefonos(await api.misTelefonos());
  } catch (err) { avisar(err.message, true); }
});
$("mf-telefonos").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-quitar-tel]");
  if (!b || !confirm("¿Quitar este teléfono?")) return;
  try {
    avisar((await api.quitarMiTelefono(b.dataset.quitarTel)).mensaje);
    pintarTelefonos(await api.misTelefonos());
  } catch (err) { avisar(err.message, true); }
});

/* ------------------------------------------------------- discapacidad */
function pintarDiscapacidad() {
  // Lo enviado y aún sin verificar se muestra en el formulario: si no,
  // parecería que no se registró nada.
  const enviado = Object.fromEntries((estado.ficha.cambios || [])
    .filter((c) => c.estado === "pendiente").map((c) => [c.campo, c.valor_nuevo]));
  const p = { ...estado.ficha.persona };
  for (const campo of ["porcentaje_discapacidad", "tipo_discapacidad", "carnet_conadis"]) {
    if (campo in enviado) p[campo] = enviado[campo];
  }
  for (const campo of ["tiene_discapacidad", "sustituto_discapacidad"]) {
    if (campo in enviado) p[campo] = enviado[campo] === "1";
  }
  $("mf-disc-tiene").checked = !!p.tiene_discapacidad;
  $("mf-disc-porcentaje").value = p.porcentaje_discapacidad || "";
  $("mf-disc-tipo").value = p.tipo_discapacidad || "";
  $("mf-disc-carnet").value = p.carnet_conadis || "";
  $("mf-disc-sustituto").checked = !!p.sustituto_discapacidad;
  mostrarCamposDiscapacidad();
  const espera = (estado.ficha.cambios || []).some((c) => c.estado === "pendiente"
    && /discapacidad|conadis/.test(c.campo));
  $("mf-disc-estado").textContent = espera
    ? "Tiene datos enviados que Talento Humano todavía no verifica."
    : p.tiene_discapacidad ? "Verificado por Talento Humano." : "";
}

function mostrarCamposDiscapacidad() {
  document.querySelectorAll("[data-disc]").forEach((el) =>
    el.classList.toggle("hidden", !$("mf-disc-tiene").checked));
}
$("mf-disc-tiene").addEventListener("change", mostrarCamposDiscapacidad);

$("form-discapacidad").addEventListener("submit", async (e) => {
  e.preventDefault();
  const tiene = $("mf-disc-tiene").checked;
  try {
    const r = await api.declararDiscapacidad({
      tiene,
      porcentaje: tiene ? Number($("mf-disc-porcentaje").value) || null : null,
      tipo: tiene ? $("mf-disc-tipo").value || null : null,
      carnet: tiene ? $("mf-disc-carnet").value.trim() || null : null,
      sustituto: $("mf-disc-sustituto").checked,
    });
    avisar(r.mensaje);
    await cargar();
  } catch (err) {
    avisar(err.message, true);
  }
});

/* --------------------------------------------------------------- foto */
async function pintarFoto() {
  const caja = $("mf-foto");
  const url = sesion.perfil?.tiene_foto ? await api.foto() : null;
  if (url) {
    caja.innerHTML = `<img src="${url}" alt="Su foto" class="h-full w-full object-cover">`;
  } else {
    caja.textContent = (sesion.perfil?.nombre || "?").split(" ").map((x) => x[0]).slice(0, 2).join("");
  }
  $("mf-foto-quitar").classList.toggle("hidden", !url);
}

$("mf-foto-archivo").addEventListener("change", async (e) => {
  const archivo = e.target.files[0];
  e.target.value = "";
  if (!archivo) return;
  if (archivo.size > 8 * 1024 * 1024) return avisar("La foto debe pesar menos de 8 MB.", true);
  try {
    avisar((await api.subirFoto(archivo)).mensaje);
    sesion.actualizarPerfil({ tiene_foto: true });
    await pintarFoto();
    document.dispatchEvent(new CustomEvent("rrhh:foto"));
  } catch (err) {
    avisar(err.message, true);
  }
});

$("mf-foto-quitar").addEventListener("click", async () => {
  if (!confirm("¿Quitar su foto de perfil?")) return;
  try {
    avisar((await api.quitarFoto()).mensaje);
    sesion.actualizarPerfil({ tiene_foto: false });
    await pintarFoto();
    document.dispatchEvent(new CustomEvent("rrhh:foto"));
  } catch (err) {
    avisar(err.message, true);
  }
});

/* --------------------------------------------------- cargo y jefe */

const elegido = (grupo) =>
  document.querySelector(`input[name="${grupo}"]:checked`)?.value || "si";

function marcarIncorrecto(grupo) {
  const opcion = document.querySelector(`input[name="${grupo}"][value="no"]`);
  if (opcion) { opcion.checked = true; opcion.dispatchEvent(new Event("change", { bubbles: true })); }
}

[["mf-jefe-ok", "mf-jefe-nuevo"]].forEach(([grupo, campo]) =>
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
  const jefeOk = elegido("mf-jefe-ok") === "si";
  if (!jefeOk && !$("mf-jefe-nuevo").value) {
    return avisar("Elija quién es su jefe inmediato.", true);
  }
  try {
    const r = await api.confirmarCargoYJefe({
      cargo_correcto: true,
      jefe_correcto: jefeOk,
      cargo_propuesto: null,
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
      ...Object.fromEntries(DOMICILIO.map(([id, campo]) => [campo, $(id).value.trim() || null])),
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

/* ---------------------------------------------------------- dispositivos */
const CIERRE = {
  salida: "cerró sesión", otro_dispositivo: "se cerró al entrar desde otro dispositivo",
  mismo_dispositivo: "renovada", cerrada_por_usuario: "la cerró usted",
  talento_humano: "la cerró Talento Humano",
};

async function cargarDispositivos() {
  try {
    const lista = await api.misSesiones();
    $("mf-dispositivos").innerHTML = lista.length ? lista.map((s) => `
      <li class="flex flex-wrap items-center gap-2 px-3 py-2.5 text-sm">
        <span class="min-w-0 flex-1">
          <b>${esc(s.dispositivo || "Dispositivo")}</b>
          ${s.actual ? '<span class="ml-1 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">este</span>' : ""}
          <span class="block text-xs text-slate-500">
            ${s.abierta ? "Abierta" : esc(CIERRE[s.motivo_cierre] || "cerrada")} ·
            entró ${fechaHora(s.creada_en)} · último uso ${fechaHora(s.ultimo_uso)}${s.ip ? ` · IP ${esc(s.ip)}` : ""}
          </span>
        </span>
        ${s.abierta && !s.actual ? `<button type="button" data-cerrar-sesion="${esc(s.id)}"
            class="rounded-lg px-2.5 py-1 text-xs font-medium text-rose-700 hover:bg-rose-50">Cerrar</button>` : ""}
      </li>`).join("")
      : '<li class="px-3 py-3 text-sm text-slate-500">Sin registros.</li>';
    $("mf-dispositivos").querySelectorAll("[data-cerrar-sesion]").forEach((b) =>
      b.addEventListener("click", async () => {
        try { avisar((await api.cerrarMiSesion(b.dataset.cerrarSesion)).mensaje); cargarDispositivos(); }
        catch (err) { avisar(err.message, true); }
      }));
  } catch { /* la ficha sigue sirviendo sin esta lista */ }
}

cargar();
pintarFoto();
cargarDispositivos();
montarContactos($("mf-contactos"), {
  listar: () => api.misContactos(),
  guardar: (id, d) => api.guardarMiContacto(id, d),
  quitar: (id) => api.quitarMiContacto(id),
}, avisar).cargar();
