/* Garita: validación de códigos y registro de visitas.

   El guardia está de pie, con poca luz y con gente esperando. Por eso:
   el foco vuelve solo al campo del escáner, el veredicto ocupa la pantalla
   entera con un color inequívoco, y Enter cierra y deja listo el siguiente. */
import { api, sesion, esc, fechaHora, validarCedula } from "./api.js";
import { montarNavegacion } from "./navegacion.js";

const $ = (id) => document.getElementById(id);
if (!sesion.vigente) location.replace("index.html");

let temporizadorAviso;
const avisar = (texto, error = false) => {
  const el = $("aviso");
  el.textContent = texto;
  el.className = `max-w-sm rounded-xl px-4 py-3 text-center text-sm shadow-lg ${
    error ? "bg-rose-600 text-white" : "bg-slate-900 text-white"}`;
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => el.classList.add("hidden"), 4000);
};

montarNavegacion($("barra"), { activo: "garita" });

/* --------------------------------------------------------------- el reloj */
function reloj() {
  const d = new Date();
  $("reloj").textContent =
    `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}
reloj();
setInterval(reloj, 1000);

/* ------------------------------------------------------------- veredicto */
function mostrarVeredicto(r) {
  const ok = r.autorizado;
  $("veredicto-fondo").className =
    `flex h-full w-full flex-col items-center justify-center px-6 text-center text-white ${
      ok ? "bg-emerald-600" : "bg-rose-700"}`;
  $("veredicto-icono").textContent = ok ? "✅" : "⛔";
  $("veredicto-titulo").textContent = ok ? "SALIDA AUTORIZADA" : "NO AUTORIZADO";
  $("veredicto-motivo").textContent = r.motivo || "";

  const filas = [];
  if (r.nombre) filas.push(["Empleado", r.nombre]);
  if (r.cedula) filas.push(["Cédula", r.cedula]);
  if (r.cargo) filas.push(["Cargo", [r.cargo, r.departamento].filter(Boolean).join(" · ")]);
  if (r.folio) filas.push(["Solicitud", `Nº ${r.folio}`]);
  if (r.tipo) filas.push(["Tipo", r.tipo]);
  if (r.hora_inicio) filas.push(["Horario", `${r.hora_inicio} a ${r.hora_fin}`]);
  if (ok) {
    // Las firmas que respaldan la salida: es lo que el guardia debe poder mostrar
    filas.push(["Autorizó el jefe", r.autorizo_jefe || "—"]);
    filas.push(["Autorizó Talento Humano", r.autorizo_rrhh || "—"]);
    if (r.firmas) filas.push(["Firmas registradas", String(r.firmas)]);
    if (r.ya_usado_antes) filas.push(["Atención", "Este código ya se usó antes"]);
  }

  $("veredicto-datos").innerHTML = filas.length
    ? filas.map(([k, v]) =>
        `<div class="flex justify-between gap-4">
           <dt class="text-sm opacity-80">${esc(k)}</dt>
           <dd class="text-right text-sm font-medium">${esc(v)}</dd>
         </div>`).join("")
    : "";
  $("veredicto-datos").classList.toggle("hidden", filas.length === 0);

  $("veredicto").showModal();
  $("veredicto-cerrar").focus();
}

function cerrarVeredicto() {
  $("veredicto").close();
  $("entrada-qr").value = "";
  $("entrada-qr").focus();
  cargarTodo();
}
$("veredicto-cerrar").addEventListener("click", cerrarVeredicto);
$("veredicto").addEventListener("close", () => $("entrada-qr").focus());

/* ------------------------------------------------------------- escaneo */
$("form-qr").addEventListener("submit", async (e) => {
  e.preventDefault();
  const codigo = $("entrada-qr").value.trim();
  if (!codigo) return;
  try {
    mostrarVeredicto(await api.validarQR(codigo));
  } catch (err) {
    mostrarVeredicto({ autorizado: false, motivo: err.message });
  }
});

/* Un lector de código de barras «teclea» muy rápido y termina con Enter:
   si llega un UUID completo de golpe, se valida sin esperar al botón. */
let ultimaTecla = 0;
$("entrada-qr").addEventListener("input", (e) => {
  const ahora = Date.now();
  const rafaga = ahora - ultimaTecla < 40;
  ultimaTecla = ahora;
  const valor = e.target.value.trim();
  if (rafaga && /^[0-9a-f-]{36}$/i.test(valor)) $("form-qr").requestSubmit();
});

// El foco siempre vuelve al escáner: el guardia no debe tener que buscarlo
document.addEventListener("click", (e) => {
  if (!e.target.closest("input, select, textarea, button, a, dialog")) $("entrada-qr").focus();
});

/* --------------------------------------------------------------- cámara */
let lector = null;
$("btn-camara").addEventListener("click", async () => {
  const caja = $("caja-camara");
  if (!caja.classList.contains("hidden")) {
    detenerCamara();
    return;
  }
  if (!("BarcodeDetector" in window)) {
    avisar("Este navegador no lee códigos con la cámara. Use el escáner de mano.", true);
    return;
  }
  try {
    const flujo = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "environment" },
    });
    $("video").srcObject = flujo;
    await $("video").play();
    caja.classList.remove("hidden");
    const detector = new BarcodeDetector({ formats: ["qr_code"] });
    lector = setInterval(async () => {
      try {
        const codigos = await detector.detect($("video"));
        if (codigos.length) {
          const valor = codigos[0].rawValue;
          detenerCamara();
          mostrarVeredicto(await api.validarQR(valor).catch((err) =>
            ({ autorizado: false, motivo: err.message })));
        }
      } catch { /* un fotograma ilegible no interrumpe la lectura */ }
    }, 400);
  } catch {
    avisar("No se pudo abrir la cámara. Revise los permisos del navegador.", true);
  }
});

function detenerCamara() {
  clearInterval(lector);
  lector = null;
  const flujo = $("video").srcObject;
  flujo?.getTracks().forEach((t) => t.stop());
  $("video").srcObject = null;
  $("caja-camara").classList.add("hidden");
}

/* ------------------------------------------------------- panel del día */
function tarjetaPersona(p, autorizada) {
  const horas = p.hora_inicio ? `${p.hora_inicio} a ${p.hora_fin}` : "todo el día";
  return `
    <div class="flex items-center gap-3 rounded-xl px-3 py-2.5 ${
      autorizada ? "bg-emerald-50 ring-1 ring-emerald-100" : "bg-amber-50 ring-1 ring-amber-100"}">
      <span class="grid h-9 w-9 shrink-0 place-items-center rounded-full ${
        autorizada ? "bg-emerald-600" : "bg-amber-500"} text-xs font-bold text-white">
        ${esc((p.nombre || "?").split(" ").map((x) => x[0]).slice(0, 2).join(""))}
      </span>
      <div class="min-w-0 flex-1">
        <p class="truncate text-sm font-medium">${esc(p.nombre)}</p>
        <p class="truncate text-xs text-slate-600">
          ${esc(p.cedula)} · ${esc(p.departamento || "—")} · ${esc(horas)}
        </p>
      </div>
      <span class="shrink-0 text-xs font-medium ${autorizada ? "text-emerald-700" : "text-amber-700"}">
        ${autorizada ? (p.qr_usado_en ? "ya salió" : "puede salir") : "en trámite"}
      </span>
    </div>`;
}

async function cargarHoy() {
  const datos = await api.garitaHoy();
  $("cuenta-hoy").textContent = `${datos.aprobadas.length} autorizada(s)`;
  $("lista-hoy").innerHTML = datos.aprobadas.length
    ? datos.aprobadas.map((p) => tarjetaPersona(p, true)).join("")
    : `<p class="rounded-xl bg-slate-50 p-4 text-center text-sm text-slate-500">
         Nadie tiene autorización vigente hoy.</p>`;

  $("caja-tramite").classList.toggle("hidden", datos.en_tramite.length === 0);
  $("cuenta-tramite").textContent = datos.en_tramite.length;
  $("lista-tramite").innerHTML = datos.en_tramite.map((p) => tarjetaPersona(p, false)).join("");
}

async function cargarVisitas() {
  const visitas = await api.visitantesDentro();
  $("lista-visitas").innerHTML = visitas.length
    ? visitas.map((v) => `
        <div class="rounded-xl bg-slate-50 px-3 py-2.5">
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="truncate text-sm font-medium">${esc(v.nombre)}</p>
              <p class="truncate text-xs text-slate-600">
                ${esc(v.cedula)}${v.empresa ? " · " + esc(v.empresa) : ""}
              </p>
              <p class="mt-0.5 truncate text-xs text-slate-500">
                ${esc(v.motivo_visita)}${v.visita_a ? " · visita a " + esc(v.visita_a) : ""}
              </p>
            </div>
            <button data-salida="${v.id}"
                    class="shrink-0 rounded-lg bg-white px-2.5 py-1.5 text-xs font-medium
                           text-slate-700 ring-1 ring-slate-200 hover:bg-slate-100">
              Salida
            </button>
          </div>
          <p class="mt-1 text-xs text-slate-400">Desde ${fechaHora(v.ingreso_en)}</p>
        </div>`).join("")
    : `<p class="rounded-xl bg-slate-50 p-4 text-center text-sm text-slate-500">
         No hay visitas dentro.</p>`;
}

async function cargarBitacora() {
  const accesos = await api.garitaAccesos(25);
  $("bitacora").innerHTML = accesos.length
    ? `<table class="w-full text-left text-sm">
         <thead class="text-xs uppercase tracking-wide text-slate-400">
           <tr><th class="pb-2 pr-3">Hora</th><th class="pb-2 pr-3">Persona</th>
               <th class="pb-2 pr-3">Movimiento</th><th class="pb-2">Resultado</th></tr>
         </thead>
         <tbody class="divide-y divide-slate-100">
           ${accesos.map((a) => `
             <tr>
               <td class="py-2 pr-3 whitespace-nowrap text-slate-500">${fechaHora(a.created_at)}</td>
               <td class="py-2 pr-3">${esc(a.persona || a.cedula || "—")}</td>
               <td class="py-2 pr-3 text-slate-600">${esc(MOVIMIENTOS[a.tipo_acceso] || a.tipo_acceso)}</td>
               <td class="py-2">
                 <span class="rounded-full px-2 py-0.5 text-xs font-medium ${
                   a.autorizado ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"}">
                   ${a.autorizado ? "autorizado" : esc(a.observacion || "denegado")}
                 </span>
               </td>
             </tr>`).join("")}
         </tbody>
       </table>`
    : `<p class="text-sm text-slate-500">Sin movimientos registrados.</p>`;
}

const MOVIMIENTOS = {
  salida_empleado: "Salida de empleado", retorno_empleado: "Retorno de empleado",
  ingreso_visita: "Ingreso de visita", salida_visita: "Salida de visita",
  acceso_denegado: "Intento denegado",
};

/* ------------------------------------------------------------- visitas */
$("btn-nueva-visita").addEventListener("click", () => {
  $("form-visita").reset();
  $("v-error").classList.add("hidden");
  $("v-error-cedula").classList.add("hidden");
  $("modal-visita").showModal();
  $("v-cedula").focus();
});

document.addEventListener("click", async (e) => {
  if (e.target.closest("[data-cerrar]")) {
    e.target.closest("dialog")?.close();
    $("entrada-qr").focus();
    return;
  }
  const salida = e.target.closest("[data-salida]");
  if (salida) {
    salida.disabled = true;
    try {
      avisar((await api.salidaVisita(salida.dataset.salida)).mensaje);
      await cargarTodo();
    } catch (err) {
      avisar(err.message, true);
      salida.disabled = false;
    }
  }
});

$("v-cedula").addEventListener("input", (e) => {
  e.target.value = e.target.value.replace(/\D/g, "").slice(0, 10);
  const error = $("v-error-cedula");
  if (e.target.value.length === 10 && !validarCedula(e.target.value)) {
    error.textContent = "Esta cédula no es válida. Verifique los dígitos.";
    error.classList.remove("hidden");
  } else {
    error.classList.add("hidden");
  }
});

let buscando;
$("v-anfitrion").addEventListener("input", (e) => {
  clearTimeout(buscando);
  const q = e.target.value.trim();
  if (q.length < 2) return;
  buscando = setTimeout(async () => {
    try {
      const gente = await api.buscarAnfitrion(q);
      $("anfitriones").innerHTML = gente
        .map((p) => `<option value="${esc(p.nombre)}">${esc(p.cargo || "")}</option>`).join("");
    } catch { /* la sugerencia es una ayuda, no un requisito */ }
  }, 250);
});

$("form-visita").addEventListener("submit", async (e) => {
  e.preventDefault();
  const cedula = $("v-cedula").value.trim();
  if (!validarCedula(cedula)) {
    $("v-error-cedula").textContent = "Esta cédula no es válida. Verifique los dígitos.";
    $("v-error-cedula").classList.remove("hidden");
    return $("v-cedula").focus();
  }
  try {
    const r = await api.registrarVisita({
      cedula,
      nombre: $("v-nombre").value.trim(),
      empresa: $("v-empresa").value.trim() || null,
      telefono: $("v-telefono").value.trim() || null,
      motivo_visita: $("v-motivo").value.trim(),
      a_quien_visita_texto: $("v-anfitrion").value.trim() || null,
    });
    $("modal-visita").close();
    avisar(r.mensaje);
    await cargarTodo();
    $("entrada-qr").focus();
  } catch (err) {
    $("v-error").textContent = err.message;
    $("v-error").classList.remove("hidden");
  }
});

/* --------------------------------------------------------------- carga */
async function cargarTodo() {
  await Promise.all([
    cargarHoy().catch(() => {}),
    cargarVisitas().catch(() => {}),
    cargarBitacora().catch(() => {}),
  ]);
}

cargarTodo();
// Se refresca solo: el guardia no debería tener que recargar la página
setInterval(cargarTodo, 30000);
$("entrada-qr").focus();
