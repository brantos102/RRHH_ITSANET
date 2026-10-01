/* Cliente de la API y utilidades compartidas. */
/* Si config.js no fija una URL, se deduce del navegador: el mismo host desde
   el que se sirve esta página y el puerto del backend. Evita dos problemas
   que ya costaron tiempo: un puerto de pruebas quedando fijo en el archivo
   del repositorio, y la diferencia entre abrir localhost y abrir 127.0.0.1,
   que para el navegador son hosts distintos. */
const CFG = window.RRHH_CONFIG || {};
const API = (CFG.API || `${location.protocol}//${location.hostname}:${CFG.PUERTO_API || 8000}`)
  .replace(/\/+$/, "");
const CLAVE_SESION = "rrhh_sesion";

/* ------------------------------------------------------------------ sesión */
export const sesion = {
  guardar(datos) {
    localStorage.setItem(CLAVE_SESION, JSON.stringify(datos));
  },
  leer() {
    try {
      return JSON.parse(localStorage.getItem(CLAVE_SESION) || "null");
    } catch {
      return null;
    }
  },
  borrar() {
    localStorage.removeItem(CLAVE_SESION);
  },
  get token() {
    return this.leer()?.access_token || null;
  },
  get perfil() {
    return this.leer()?.perfil || null;
  },
  get vigente() {
    const s = this.leer();
    return !!s && new Date(s.expira_en) > new Date();
  },
};

/* --------------------------------------------------------------- peticiones */
export class ErrorApi extends Error {
  constructor(mensaje, estado, detalle, referencia) {
    // La referencia se incorpora al mensaje aquí y no en cada pantalla: son
    // unas cuarenta las que muestran `err.message`, y basta una que se olvide
    // para que el usuario reporte un error sin el código que lo ubica. El
    // servidor ya la incluye en el texto de los 500; esto cubre el caso en que
    // la respuesta no traiga cuerpo (un 502 del proxy, la conexión cortada).
    //
    // Solo para lo inesperado. Todas las respuestas llevan el código en la
    // cabecera, así que sin este filtro «el código es incorrecto» o «debe
    // justificar el bloque menor» terminarían con un «(referencia a1b2c3d4)»
    // que no aporta nada: esos mensajes el usuario los resuelve leyéndolos.
    if (referencia && estado >= 500 && !String(mensaje).includes(referencia)) {
      mensaje = `${mensaje} (referencia ${referencia})`;
    }
    super(mensaje);
    this.estado = estado;
    this.detalle = detalle;
    // Código con el que el servidor marcó esta petición. Va en pantalla para
    // que quien reporta el problema lo dicte y se pueda buscar el rastro
    // exacto en los registros.
    this.referencia = referencia || null;
  }
}

async function peticion(ruta, opciones = {}) {
  const cabeceras = { ...(opciones.headers || {}) };
  if (!(opciones.body instanceof FormData)) cabeceras["Content-Type"] = "application/json";
  if (sesion.token) cabeceras["Authorization"] = `Bearer ${sesion.token}`;

  let respuesta;
  try {
    respuesta = await fetch(`${API}${ruta}`, { ...opciones, headers: cabeceras });
  } catch {
    throw new ErrorApi("No se pudo conectar con el servidor. Revise su conexión.", 0);
  }

  if (respuesta.status === 401 && sesion.leer()) {
    sesion.borrar();
    location.href = "index.html?expirada=1";
    return;
  }

  if (respuesta.status === 204) return null;

  const cuerpo = await respuesta.json().catch(() => ({}));

  if (!respuesta.ok) {
    const d = cuerpo.detail;
    let mensaje = "Ocurrió un error.";
    if (typeof d === "string") mensaje = d;
    else if (d && typeof d === "object" && d.mensaje) mensaje = d.mensaje;
    else if (Array.isArray(d) && d[0]?.msg) mensaje = d[0].msg.replace(/^Value error, /, "");
    const referencia = cuerpo.referencia || respuesta.headers.get("X-Peticion-Id");
    throw new ErrorApi(mensaje, respuesta.status, typeof d === "object" ? d : null, referencia);
  }
  return cuerpo;
}

export const api = {
  // La dirección base, para las descargas: van con `fetch` y su cabecera de
  // sesión, no con un enlace normal, que iría sin token.
  base: API,
  solicitarToken: (cedula) =>
    peticion("/auth/solicitar-token", { method: "POST", body: JSON.stringify({ cedula }) }),
  validarToken: (cedula, codigo) =>
    peticion("/auth/validar-token", { method: "POST", body: JSON.stringify({ cedula, codigo }) }),
  perfil: () => peticion("/auth/me"),
  saldo: () => peticion("/auth/mi-saldo"),
  notificaciones: () => peticion("/auth/mis-notificaciones"),
  marcarNotificacionesLeidas: () =>
    peticion("/auth/mis-notificaciones/leidas", { method: "POST" }),
  cerrarSesion: () => peticion("/auth/cerrar-sesion", { method: "POST" }),
  necesitaFicha: (cedula) =>
    peticion("/auth/necesita-ficha", { method: "POST", body: JSON.stringify({ cedula }) }),
  probarIdentidad: (cedula, fecha_nacimiento, fecha_ingreso) =>
    peticion("/auth/probar-identidad", {
      method: "POST",
      body: JSON.stringify({ cedula, fecha_nacimiento, fecha_ingreso }),
    }),
  completarFicha: (datos) =>
    peticion("/auth/completar-ficha", { method: "POST", body: JSON.stringify(datos) }),
  jefaturasDelAlta: (token) => peticion(`/auth/alta/jefaturas?token=${token}`),
  confirmarCorreo: (token) =>
    peticion("/auth/confirmar-correo", { method: "POST", body: JSON.stringify({ token }) }),
  cambiarCorreo: (email) =>
    peticion("/mi-ficha/correo", { method: "POST", body: JSON.stringify({ email }) }),
  confirmarCargoYJefe: (datos) =>
    peticion("/mi-ficha/confirmar", { method: "POST", body: JSON.stringify(datos) }),
  jefaturas: () => peticion("/catalogos/jefaturas"),
  // --- personal temporal ---
  temporales: (buscar = "") =>
    peticion(`/temporal${buscar ? `?buscar=${encodeURIComponent(buscar)}` : ""}`),
  crearTemporal: (datos) =>
    peticion("/temporal", { method: "POST", body: JSON.stringify(datos) }),
  editarTemporal: (id, datos) =>
    peticion(`/temporal/${id}`, { method: "PATCH", body: JSON.stringify(datos) }),
  temporalEntrada: (temporal_id) =>
    peticion("/temporal/entrada", { method: "POST", body: JSON.stringify({ temporal_id }) }),
  temporalSalida: (temporal_id) =>
    peticion("/temporal/salida", { method: "POST", body: JSON.stringify({ temporal_id }) }),
  temporalesDentro: () => peticion("/temporal/dentro"),
  temporalesSinCerrar: () => peticion("/temporal/sin-cerrar"),
  cerrarJornadaTemporal: (id, datos) =>
    peticion(`/temporal/jornadas/${id}/cerrar`, { method: "POST", body: JSON.stringify(datos) }),
  temporalSemana: (params = "") => peticion(`/temporal/semana${params}`),

  tiposPermiso: () => peticion("/catalogos/tipos-permiso"),
  catalogoPermisos: () => peticion("/catalogos/permisos"),
  tablaAntiguedad: () => peticion("/catalogos/antiguedad"),
  candidatosReemplazo: (id) => peticion(`/aprobaciones/${id}/candidatos`),
  ajustarAusencia: (id, datos) =>
    peticion(`/aprobaciones/${id}/ajustar`, { method: "POST", body: JSON.stringify(datos) }),
  ajustesDe: (id) => peticion(`/solicitudes/${id}/ajustes`),
  calendarioEquipo: (params = "") => peticion(`/jefe/calendario-equipo${params}`),
  // --- ficha personal ---
  miFicha: () => peticion("/mi-ficha"),
  miHistorial: () => peticion("/mi-historial"),
  corregirFicha: (datos) => peticion("/mi-ficha", { method: "PATCH", body: JSON.stringify(datos) }),
  pedirCambioFicha: (datos) =>
    peticion("/mi-ficha/cambios", { method: "POST", body: JSON.stringify(datos) }),
  cambiosFichaPendientes: () => peticion("/rrhh/cambios-ficha"),
  resolverCambioFicha: (id, accion, motivo = null) =>
    peticion(`/rrhh/cambios-ficha/${id}`, {
      method: "POST", body: JSON.stringify({ accion, motivo }),
    }),
  // --- chat con Talento Humano ---
  chatContactos: (region) =>
    peticion("/chat/contactos" + (region ? `?region=${region}` : "")),
  misConversaciones: () => peticion("/chat/mis-conversaciones"),
  bandejaChat: (estado = "abierta") => peticion(`/chat/bandeja?estado=${estado}`),
  leerConversacion: (id) => peticion(`/chat/conversaciones/${id}`),
  enviarMensaje: (datos) =>
    peticion("/chat/mensajes", { method: "POST", body: JSON.stringify(datos) }),
  cerrarConversacion: (id) =>
    peticion(`/chat/conversaciones/${id}/cerrar`, { method: "POST" }),
  feriados: () => peticion("/catalogos/feriados"),
  companeros: () => peticion("/catalogos/companeros"),
  calendario: (desde, hasta) =>
    peticion("/calendario" + (desde ? `?desde=${desde}&hasta=${hasta}` : "")),

  previsualizar: (datos) =>
    peticion("/solicitudes/previsualizar", { method: "POST", body: JSON.stringify(datos) }),
  crearSolicitud: (datos) =>
    peticion("/solicitudes", { method: "POST", body: JSON.stringify(datos) }),
  misSolicitudes: () => peticion("/solicitudes/mias"),
  cancelar: (id, motivo) =>
    peticion(`/solicitudes/${id}/cancelar`, { method: "POST", body: JSON.stringify({ motivo }) }),
  subirAdjunto: (solicitudId, archivo) => {
    const fd = new FormData();
    fd.append("archivo", archivo);
    return peticion(`/solicitudes/adjuntos?solicitud_id=${solicitudId}`, { method: "POST", body: fd });
  },

  // Aprobaciones
  pendientes: () => peticion("/aprobaciones/pendientes"),
  decidir: (id, accion, motivo, reemplazoId = null) =>
    peticion(`/aprobaciones/${id}/decidir`, {
      method: "POST",
      body: JSON.stringify({ accion, motivo, reemplazo_id: reemplazoId }),
    }),
  // Enlace del correo: no requiere sesión
  verEnlace: (token, rol) => peticion(`/aprobaciones/enlace/${token}?rol=${rol}`),
  decidirEnlace: (token, rol, accion, motivo) =>
    peticion(`/aprobaciones/enlace/${token}/decidir?rol=${rol}`,
             { method: "POST", body: JSON.stringify({ accion, motivo }) }),
  qrUrl: (id) => `${API}/solicitudes/${id}/qr.png`,

  // Garita
  validarQR: (codigo) =>
    peticion("/garita/validar-qr", { method: "POST", body: JSON.stringify({ codigo }) }),
  garitaHoy: () => peticion("/garita/hoy"),
  garitaAccesos: (limite = 25) => peticion(`/garita/accesos?limite=${limite}`),
  visitantesDentro: () => peticion("/garita/visitantes/dentro"),
  registrarVisita: (datos) =>
    peticion("/garita/visitantes", { method: "POST", body: JSON.stringify(datos) }),
  salidaVisita: (id) => peticion(`/garita/visitantes/${id}/salida`, { method: "POST" }),
  buscarAnfitrion: (q) => peticion(`/garita/buscar-anfitrion?q=${encodeURIComponent(q)}`),

  // Anulaciones
  anulacionesPendientes: () => peticion("/aprobaciones/anulaciones"),
  resolverAnulacion: (id, accion, motivo) =>
    peticion(`/aprobaciones/${id}/anulacion`, { method: "POST", body: JSON.stringify({ accion, motivo }) }),

  // Informes
  dimensiones: () => peticion("/informes/dimensiones"),
  informe: (parametros) => peticion(`/informes/solicitudes?${parametros}`),
  resumenDepartamentos: (anio) =>
    peticion("/informes/resumen-departamentos" + (anio ? `?anio=${anio}` : "")),

  // Administración
  adminUsuarios: (q = "", inactivos = false) =>
    peticion(`/admin/usuarios?q=${encodeURIComponent(q)}&incluir_inactivos=${inactivos}`),
  crearUsuario: (datos) => peticion("/admin/usuarios", { method: "POST", body: JSON.stringify(datos) }),
  editarUsuario: (id, cambios) =>
    peticion(`/admin/usuarios/${id}`, { method: "PATCH", body: JSON.stringify(cambios) }),
  ajustarSaldo: (id, saldo) =>
    peticion(`/admin/usuarios/${id}/saldo?saldo=${saldo}`, { method: "POST" }),
  antiguedades: () => peticion("/admin/antiguedades"),
  adminJefaturas: () => peticion("/admin/jefaturas"),
  talentoHumano: () => peticion("/admin/talento-humano"),
  integrarTalentoHumano: (persona_id, region) =>
    peticion("/admin/talento-humano",
             { method: "POST", body: JSON.stringify({ persona_id, region }) }),
  retirarTalentoHumano: (id, rol_destino) =>
    peticion(`/admin/talento-humano/${id}/retirar`,
             { method: "POST", body: JSON.stringify({ rol_destino }) }),
  correosTalentoHumano: (correos) =>
    peticion("/admin/talento-humano/correos",
             { method: "PATCH", body: JSON.stringify(correos) }),
  crearJefatura: (persona_id) =>
    peticion("/admin/jefaturas", { method: "POST", body: JSON.stringify({ persona_id }) }),
  quitarJefatura: (id, datos) =>
    peticion(`/admin/jefaturas/${id}/quitar`,
             { method: "POST", body: JSON.stringify(datos) }),
  periodosDe: (id) => peticion(`/admin/usuarios/${id}/periodos`),
  corregirFinesSemana: (id, datos) =>
    peticion(`/admin/usuarios/${id}/fines-semana`,
             { method: "POST", body: JSON.stringify(datos) }),
  adminTipos: () => peticion("/admin/tipos-permiso"),
  editarTipo: (id, cambios) =>
    peticion(`/admin/tipos-permiso/${id}`, { method: "PATCH", body: JSON.stringify(cambios) }),
  adminFeriados: (anio) => peticion("/admin/feriados" + (anio ? `?anio=${anio}` : "")),
  crearFeriado: (datos) => peticion("/admin/feriados", { method: "POST", body: JSON.stringify(datos) }),
  quitarFeriado: (fecha) => peticion(`/admin/feriados/${fecha}`, { method: "DELETE" }),
  adminConfiguracion: () => peticion("/admin/configuracion"),
  cambiarParametro: (clave, valor) =>
    peticion(`/admin/configuracion/${clave}`, { method: "PATCH", body: JSON.stringify({ valor }) }),
  bitacora: (limite = 100) => peticion(`/admin/bitacora?limite=${limite}`),

  // Los lineamientos que se leen antes de enviar una solicitud. Los escribe
  // Talento Humano: cambian por circular, no por versión del sistema.
  depuracion: () => peticion("/admin/depuracion"),
  lineamientos: () => peticion("/rrhh/lineamientos"),
  crearLineamiento: (datos) =>
    peticion("/rrhh/lineamientos", { method: "POST", body: JSON.stringify(datos) }),
  cambiarLineamiento: (id, cambios) =>
    peticion(`/rrhh/lineamientos/${id}`,
             { method: "PATCH", body: JSON.stringify(cambios) }),

  // Personal temporal: el informe que se presenta a Finanzas.
  opcionesInformeTemporal: () => peticion("/temporal/opciones-informe"),
  informeTemporal: (filtro) =>
    peticion("/temporal/informe", { method: "POST", body: JSON.stringify(filtro) }),
  /* La descarga lleva el token, así que se pide con fetch y se guarda como
     blob: un enlace normal iría sin cabecera de sesión y el servidor lo
     rechazaría. El nombre lo pone el servidor, que sabe la fecha. */
  bajarInformeTemporal: async (formato, filtro) => {
    const respuesta = await fetch(`${API}/temporal/informe.${formato}`, {
      method: "POST",
      headers: { "Content-Type": "application/json",
                 Authorization: `Bearer ${sesion.token}` },
      body: JSON.stringify(filtro),
    });
    if (!respuesta.ok) throw new ErrorApi("No se pudo generar el archivo.", respuesta.status);
    const cabecera = respuesta.headers.get("content-disposition") || "";
    const nombre = /filename="([^"]+)"/.exec(cabecera)?.[1]
      || `personal-temporal-${new Date().toISOString().slice(0, 10)}.${formato}`;
    const url = URL.createObjectURL(await respuesta.blob());
    Object.assign(document.createElement("a"), { href: url, download: nombre }).click();
    URL.revokeObjectURL(url);
    return nombre;
  },

  // El expediente de una persona, para jefaturas y Talento Humano.
  buscarPersona: (q) => peticion(`/personas/buscar?q=${encodeURIComponent(q)}`),
  expediente: (id) => peticion(`/personas/${id}`),

  // La pantalla principal: qué bloques se ven, en qué orden y para qué roles.
  misBloques: () => peticion("/panel/bloques"),
  panelConfiguracion: () => peticion("/panel/configuracion"),
  panelCambiar: (clave, cambios) =>
    peticion(`/panel/configuracion/${clave}`,
             { method: "PATCH", body: JSON.stringify(cambios) }),
  panelReordenar: (claves) =>
    peticion("/panel/configuracion/orden",
             { method: "POST", body: JSON.stringify({ claves }) }),
  colaboradores: () => peticion("/rrhh/colaboradores"),
};

/* ------------------------------------------------------------- utilidades */

/* Un identificador único, también fuera de un «contexto seguro».

   `crypto.randomUUID()` SOLO existe en HTTPS y en localhost. Sirviendo el
   sistema en la red de la oficina —http://192.168.x.x:5500, que es como lo
   prueban los colaboradores— no existe, y la pantalla moría con

       TypeError: crypto.randomUUID is not a function

   justo al pulsar «Enviar solicitud»: en el equipo de quien instala todo
   funcionaba, y en el de los demás no se podía enviar nada.

   `crypto.getRandomValues` sí está disponible en contexto inseguro, así que
   el UUID v4 se arma con él: mismos bits de azar, misma forma. */
export function uuid() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();

  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  b[6] = (b[6] & 0x0f) | 0x40;   // versión 4
  b[8] = (b[8] & 0x3f) | 0x80;   // variante RFC 4122
  const h = [...b].map((n) => n.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

export function validarCedula(cedula) {
  if (!/^\d{10}$/.test(cedula)) return false;
  const provincia = +cedula.slice(0, 2);
  if (!((provincia >= 1 && provincia <= 24) || provincia === 30)) return false;
  if (+cedula[2] > 5) return false;

  let suma = 0;
  for (let i = 0; i < 9; i++) {
    let d = +cedula[i];
    if (i % 2 === 0) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    suma += d;
  }
  return (10 - (suma % 10)) % 10 === +cedula[9];
}

const MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

export function fecha(valor, conAnio = true) {
  if (!valor) return "—";
  const d = new Date(`${String(valor).slice(0, 10)}T12:00:00`);
  return `${d.getDate()} ${MESES[d.getMonth()]}${conAnio ? " " + d.getFullYear() : ""}`;
}

export function fechaHora(valor) {
  if (!valor) return "—";
  const d = new Date(valor);
  return `${fecha(valor)}, ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** Escapa texto antes de insertarlo en HTML. */
export function esc(texto) {
  const div = document.createElement("div");
  div.textContent = texto ?? "";
  return div.innerHTML;
}

export const ESTADOS = {
  pendiente_jefe: { etiqueta: "Espera a su jefe", clase: "bg-amber-100 text-amber-800 ring-amber-200" },
  pendiente_rrhh: { etiqueta: "Espera a Talento Humano", clase: "bg-sky-100 text-sky-800 ring-sky-200" },
  pendiente_anulacion: { etiqueta: "Anulación en trámite", clase: "bg-orange-100 text-orange-800 ring-orange-200" },
  aprobado: { etiqueta: "Aprobada", clase: "bg-emerald-100 text-emerald-800 ring-emerald-200" },
  rechazado: { etiqueta: "Rechazada", clase: "bg-rose-100 text-rose-800 ring-rose-200" },
  cancelado: { etiqueta: "Cancelada", clase: "bg-slate-100 text-slate-600 ring-slate-200" },
};
