/* Escanear una cédula con la cámara del equipo de la garita o de Talento
   Humano, para no escribir a mano número y nombres.

   Protección de datos (LOPDP):
   - La imagen se procesa en ESTE navegador. No se envía al servidor ni a
     nadie: el OCR (tesseract.js) está copiado en vendor/tesseract y funciona
     sin internet.
   - No se guarda: el fotograma vive en un lienzo que se borra al terminar, y
     el archivo elegido se suelta en cuanto se lee.
   - Del documento solo se toman cédula y nombres —y la nacionalidad para que
     quien registra la vea—. Fecha de nacimiento, sexo y vencimiento se leen
     porque vienen en la misma línea, pero no salen de este archivo.
   - El enlace del QR (página del Registro Civil) no se consulta: solo se
     ofrece abrirlo para comparar a simple vista.

   Uso:  const datos = await escanearCedula();   // null si se cancela
         datos → { cedula, nombre, nacionalidad, fuente, verificada } */
import { interpretarTexto, leerQR, nombreCompleto } from "./cedula.js";

const BASE = "vendor/tesseract";
let ocr = null;          // el «worker» de tesseract, mientras el diálogo está abierto

/* --------------------------------------------------------- el diálogo */

function crearDialogo() {
  const d = document.createElement("dialog");
  d.id = "modal-escaner";
  d.className = "w-[min(100vw-1.5rem,34rem)] rounded-2xl p-0";
  d.innerHTML = `
    <div class="flex items-center justify-between border-b border-slate-200 px-5 py-4">
      <div>
        <h2 class="font-semibold">Escanear cédula</h2>
        <p class="mt-0.5 text-xs text-slate-500">
          La imagen se lee en este equipo y no se guarda ni se envía.
        </p>
      </div>
      <button type="button" data-esc-cerrar
              class="rounded-lg px-2 py-1 text-slate-400 hover:bg-slate-100" aria-label="Cerrar">✕</button>
    </div>
    <div class="space-y-3 px-5 py-4">
      <p class="text-sm text-slate-600">
        Enfoque el <strong>reverso</strong> de la cédula, con las tres líneas de letras y
        «&lt;&lt;&lt;» de abajo bien nítidas y sin reflejos. Si no tiene esas líneas,
        sirve el anverso.
      </p>
      <div data-esc-camara class="relative hidden overflow-hidden rounded-xl bg-black">
        <video data-esc-video playsinline muted class="aspect-[4/3] w-full object-cover"></video>
        <div class="pointer-events-none absolute inset-x-4 bottom-4 h-1/3 rounded-lg border-2
                    border-dashed border-white/70"></div>
      </div>
      <div class="flex flex-wrap gap-2">
        <button type="button" data-esc-leer
                class="hidden flex-1 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white
                       hover:bg-slate-800">Leer ahora</button>
        <label class="flex-1 cursor-pointer rounded-xl bg-slate-100 px-4 py-2.5 text-center text-sm
                      font-medium hover:bg-slate-200">
          Tomar o elegir foto
          <input type="file" accept="image/*" capture="environment" data-esc-archivo class="hidden">
        </label>
      </div>
      <p data-esc-estado class="hidden rounded-xl bg-slate-50 p-3 text-sm text-slate-700"></p>
      <div data-esc-qr class="hidden rounded-xl bg-sky-50 p-3 text-sm text-sky-900 ring-1 ring-sky-200"></div>
      <div data-esc-resultado class="hidden rounded-xl p-3 text-sm ring-1"></div>
    </div>
    <div class="flex gap-3 border-t border-slate-200 px-5 py-4">
      <button type="button" data-esc-cerrar
              class="flex-1 rounded-xl bg-slate-100 px-4 py-3 font-medium hover:bg-slate-200">Cancelar</button>
      <button type="button" data-esc-usar disabled
              class="flex-1 rounded-xl bg-emerald-600 px-4 py-3 font-medium text-white
                     hover:bg-emerald-700 disabled:opacity-40">Usar estos datos</button>
    </div>`;
  document.body.appendChild(d);
  return d;
}

const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

/* ------------------------------------------------------------ el OCR */

function cargarScript(src) {
  return new Promise((ok, mal) => {
    if (window.Tesseract) return ok();
    const s = document.createElement("script");
    s.src = src;
    s.onload = ok;
    s.onerror = () => mal(new Error("No se pudo cargar el lector de texto."));
    document.head.appendChild(s);
  });
}

async function prepararOCR() {
  if (ocr) return ocr;
  await cargarScript(`${BASE}/tesseract.min.js`);
  // Todo desde el propio servidor: sin CDN, sin internet.
  ocr = await window.Tesseract.createWorker("eng", 1, {
    workerPath: `${BASE}/worker.min.js`,
    corePath: `${BASE}/tesseract-core-lstm.wasm.js`,
    langPath: BASE,
    workerBlobURL: false,
    gzip: true,
  });
  return ocr;
}

async function cerrarOCR() {
  const w = ocr;
  ocr = null;
  try { await w?.terminate(); } catch { /* ya estaba cerrado */ }
}

/* Escala de grises y más contraste: la MRZ es tinta negra sobre un fondo con
   guilloches de colores, y el color solo confunde al OCR. */
function prepararImagen(origen, ancho, alto) {
  const escala = Math.min(1, 1800 / Math.max(ancho, alto));
  const lienzo = document.createElement("canvas");
  lienzo.width = Math.round(ancho * escala);
  lienzo.height = Math.round(alto * escala);
  const ctx = lienzo.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(origen, 0, 0, lienzo.width, lienzo.height);
  const img = ctx.getImageData(0, 0, lienzo.width, lienzo.height);
  const p = img.data;
  for (let i = 0; i < p.length; i += 4) {
    const gris = 0.299 * p[i] + 0.587 * p[i + 1] + 0.114 * p[i + 2];
    const v = Math.max(0, Math.min(255, (gris - 128) * 1.6 + 128));
    p[i] = p[i + 1] = p[i + 2] = v;
  }
  ctx.putImageData(img, 0, 0);
  return lienzo;
}

function borrar(lienzo) {
  if (!lienzo) return;
  lienzo.getContext("2d")?.clearRect(0, 0, lienzo.width, lienzo.height);
  lienzo.width = lienzo.height = 0;
}

const MRZ_LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<";

async function reconocer(lienzo) {
  const w = await prepararOCR();
  await w.setParameters({ tessedit_char_whitelist: "" });
  const general = (await w.recognize(lienzo)).data.text;
  let datos = interpretarTexto(general);
  if (datos?.verificada) return datos;

  // Segunda pasada, solo el tercio de abajo y solo los caracteres de una MRZ:
  // ahí el OCR se equivoca mucho menos.
  await w.setParameters({ tessedit_char_whitelist: MRZ_LETRAS });
  const alto = Math.round(lienzo.height * 0.45);
  const abajo = (await w.recognize(lienzo, {
    rectangle: { left: 0, top: lienzo.height - alto, width: lienzo.width, height: alto },
  })).data.text;
  await w.setParameters({ tessedit_char_whitelist: "" });
  const desdeMRZ = interpretarTexto(abajo);
  if (desdeMRZ && (desdeMRZ.verificada || !datos || desdeMRZ.cedula && !datos.cedula)) {
    // Lo del anverso que la MRZ no trajo se conserva.
    for (const c of ["cedula", "apellidos", "nombres"]) {
      if (!desdeMRZ[c] && datos?.[c]) desdeMRZ[c] = datos[c];
    }
    datos = desdeMRZ;
  }
  return datos;
}

/* ------------------------------------------------------- QR del reverso */

const detectorQR = () =>
  ("BarcodeDetector" in window) ? new window.BarcodeDetector({ formats: ["qr_code"] }) : null;

/* ---------------------------------------------------------- principal */

export function escanearCedula() {
  const d = document.getElementById("modal-escaner") || crearDialogo();
  const q = (sel) => d.querySelector(sel);
  const video = q("[data-esc-video]");
  const estado = { flujo: null, sondeo: null, datos: null, qr: null, ocupado: false };

  const mostrarEstado = (texto, tono = "bg-slate-50 text-slate-700") => {
    const el = q("[data-esc-estado]");
    el.className = `rounded-xl p-3 text-sm ${tono}`;
    el.textContent = texto;
    el.classList.toggle("hidden", !texto);
  };

  const pintarQR = () => {
    const caja = q("[data-esc-qr]");
    const r = estado.qr;
    if (!r) return caja.classList.add("hidden");
    caja.classList.remove("hidden");
    caja.innerHTML = r.enlace_registro_civil
      ? `Código QR del Registro Civil leído.
         <a href="${esc(r.enlace_registro_civil)}" target="_blank" rel="noopener noreferrer"
            class="font-medium underline">Abrir la verificación oficial ↗</a>
         <span class="block text-xs text-sky-800">Necesita internet. Compare los datos que muestre
         con la persona y con su cédula; el sistema no copia nada de esa página.</span>`
      : r.enlace_desconocido
        ? `<span class="text-rose-800">El QR lleva a un sitio que no es del Registro Civil:
           no lo abra. La cédula puede estar alterada.</span>`
        : r.cedula ? `El QR trae la cédula ${esc(r.cedula)}.` : "QR leído, sin datos útiles.";
  };

  const pintarResultado = () => {
    const caja = q("[data-esc-resultado]");
    const r = estado.datos;
    q("[data-esc-usar]").disabled = !r?.cedula;
    if (!r) return caja.classList.add("hidden");
    const nombre = nombreCompleto(r);
    const fila = (k, v) => `<div class="flex justify-between gap-3 py-0.5">
      <span class="text-slate-500">${k}</span><span class="text-right font-medium">${esc(v || "—")}</span></div>`;
    caja.className = `rounded-xl p-3 text-sm ring-1 ${r.verificada
      ? "bg-emerald-50 ring-emerald-200" : "bg-amber-50 ring-amber-200"}`;
    caja.innerHTML = `
      <p class="mb-2 font-medium ${r.verificada ? "text-emerald-800" : "text-amber-900"}">
        ${r.verificada
          ? "Lectura verificada con los dígitos de control del documento."
          : "Lectura sin verificar: revise cada dato con la cédula en la mano."}
      </p>
      ${fila("Cédula", r.cedula || "no se leyó")}
      ${fila("Apellidos y nombres", nombre)}
      ${fila("Nacionalidad", r.nacionalidad)}
      ${r.fuente === "anverso" ? `<p class="mt-2 text-xs text-amber-900">
        Leído del anverso. Si puede, lea el reverso: es más fiable.</p>` : ""}`;
    caja.classList.remove("hidden");
  };

  const detenerCamara = () => {
    clearInterval(estado.sondeo);
    estado.flujo?.getTracks().forEach((t) => t.stop());
    estado.flujo = null;
    video.srcObject = null;
  };

  async function leer(origen, ancho, alto) {
    if (estado.ocupado) return;
    estado.ocupado = true;
    q("[data-esc-leer]").disabled = true;
    let lienzo;
    try {
      mostrarEstado("Leyendo… la primera vez tarda unos segundos.");
      lienzo = prepararImagen(origen, ancho, alto);
      const detector = detectorQR();
      if (detector && !estado.qr) {
        const codigos = await detector.detect(lienzo).catch(() => []);
        if (codigos.length) { estado.qr = leerQR(codigos[0].rawValue); pintarQR(); }
      }
      const datos = await reconocer(lienzo);
      if (datos && !datos.cedula && estado.qr?.cedula) datos.cedula = estado.qr.cedula;
      if (!datos?.cedula && estado.qr?.cedula) {
        estado.datos = { fuente: "qr", cedula: estado.qr.cedula, verificada: false };
      } else {
        estado.datos = datos;
      }
      pintarResultado();
      mostrarEstado(estado.datos?.cedula ? ""
        : "No se pudo leer. Acerque la cédula, evite reflejos y vuelva a intentar.",
        "bg-rose-50 text-rose-800");
      if (estado.datos?.verificada) detenerCamara();
    } catch (err) {
      mostrarEstado(err.message || "No se pudo leer la imagen.", "bg-rose-50 text-rose-800");
    } finally {
      borrar(lienzo);
      estado.ocupado = false;
      q("[data-esc-leer]").disabled = false;
    }
  }

  async function abrirCamara() {
    // La cámara solo existe con HTTPS (o en el propio equipo). Sin ella queda
    // el botón de foto, que en el celular abre la cámara igual.
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) return;
    try {
      estado.flujo = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } },
      });
      video.srcObject = estado.flujo;
      await video.play();
      q("[data-esc-camara]").classList.remove("hidden");
      q("[data-esc-leer]").classList.remove("hidden");
      const detector = detectorQR();
      if (detector) {
        estado.sondeo = setInterval(async () => {
          if (estado.qr || estado.ocupado) return;
          const codigos = await detector.detect(video).catch(() => []);
          if (codigos.length) { estado.qr = leerQR(codigos[0].rawValue); pintarQR(); }
        }, 500);
      }
    } catch {
      mostrarEstado("No se pudo abrir la cámara. Use «Tomar o elegir foto».");
    }
  }

  return new Promise((resolver) => {
    let terminado = false;
    const terminar = (valor) => {
      if (terminado) return;
      terminado = true;
      detenerCamara();
      cerrarOCR();
      q("[data-esc-archivo]").value = "";
      estado.datos = estado.qr = null;
      d.close();
      d.remove();       // nada del documento queda en la página
      resolver(valor);
    };

    d.querySelectorAll("[data-esc-cerrar]").forEach((b) =>
      b.addEventListener("click", () => terminar(null)));
    d.addEventListener("cancel", (e) => { e.preventDefault(); terminar(null); });

    q("[data-esc-leer]").addEventListener("click", () =>
      leer(video, video.videoWidth, video.videoHeight));

    q("[data-esc-archivo]").addEventListener("change", async (e) => {
      const archivo = e.target.files?.[0];
      e.target.value = "";
      if (!archivo) return;
      let mapa;
      try {
        mapa = await createImageBitmap(archivo);
        await leer(mapa, mapa.width, mapa.height);
      } catch {
        mostrarEstado("No se pudo abrir esa imagen.", "bg-rose-50 text-rose-800");
      } finally {
        mapa?.close();
      }
    });

    q("[data-esc-usar]").addEventListener("click", () => {
      const r = estado.datos;
      if (!r?.cedula) return;
      terminar({
        cedula: r.cedula,
        nombre: nombreCompleto(r),
        nacionalidad: r.nacionalidad || null,
        fuente: r.fuente,
        verificada: !!r.verificada,
      });
    });

    d.showModal();
    abrirCamara();
    // El OCR se prepara mientras la persona acomoda la cédula.
    prepararOCR().catch((err) => mostrarEstado(err.message, "bg-rose-50 text-rose-800"));
  });
}
