/* La página que abre el enlace del correo de confirmación.

   El cambio se aplica con un POST y no con la simple apertura del enlace, a
   propósito: los antivirus de correo y los previsualizadores de los clientes
   abren los enlaces de los mensajes que analizan. Si bastara con abrirlo, un
   filtro automático aplicaría el cambio sin que la persona hiciera nada, y
   peor: el enlace quedaría consumido antes de que llegara a leerlo. */
import { api, esc, ErrorApi } from "./api.js";

const $ = (id) => document.getElementById(id);
const token = new URLSearchParams(location.search).get("t");

const cfg = window.RRHH_CONFIG || {};
if (cfg.LOGO) $("logo").src = cfg.LOGO;

function mostrar(seccion) {
  ["esperando", "listo", "fallo"].forEach((id) =>
    $(id).classList.toggle("hidden", id !== seccion));
}

if (!token) {
  $("fallo-detalle").textContent =
    "El enlace está incompleto. Ábralo tal como llegó al correo, sin recortarlo.";
  mostrar("fallo");
}

$("btn-confirmar").addEventListener("click", async () => {
  $("btn-confirmar").disabled = true;
  $("btn-confirmar").textContent = "Confirmando…";
  try {
    const r = await api.confirmarCorreo(token);
    $("listo-detalle").innerHTML =
      `${esc(r.nombre)}, desde ahora su código de acceso llega a ` +
      `<strong>${esc(r.email)}</strong>.`;
    mostrar("listo");
  } catch (err) {
    $("fallo-detalle").textContent = err instanceof ErrorApi ? err.message
      : "No se pudo confirmar. Intente de nuevo o escriba a Talento Humano.";
    mostrar("fallo");
  }
});
