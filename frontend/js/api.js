/* Cliente de la API y utilidades compartidas. */
const API = (window.RRHH_CONFIG && window.RRHH_CONFIG.API) || "http://localhost:8000";
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
  constructor(mensaje, estado, detalle) {
    super(mensaje);
    this.estado = estado;
    this.detalle = detalle;
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
    throw new ErrorApi(mensaje, respuesta.status, typeof d === "object" ? d : null);
  }
  return cuerpo;
}

export const api = {
  solicitarToken: (cedula) =>
    peticion("/auth/solicitar-token", { method: "POST", body: JSON.stringify({ cedula }) }),
  validarToken: (cedula, codigo) =>
    peticion("/auth/validar-token", { method: "POST", body: JSON.stringify({ cedula, codigo }) }),
  perfil: () => peticion("/auth/me"),
  saldo: () => peticion("/auth/mi-saldo"),
  notificaciones: () => peticion("/auth/mis-notificaciones"),
  cerrarSesion: () => peticion("/auth/cerrar-sesion", { method: "POST" }),

  tiposPermiso: () => peticion("/catalogos/tipos-permiso"),
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
  decidir: (id, accion, motivo) =>
    peticion(`/aprobaciones/${id}/decidir`, { method: "POST", body: JSON.stringify({ accion, motivo }) }),
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
  informeCsvUrl: (parametros) => `${API}/informes/solicitudes.csv?${parametros}`,
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
  colaboradores: () => peticion("/rrhh/colaboradores"),

  miFirma: () => peticion("/firmas/mia"),
  guardarFirma: (contenido) =>
    peticion("/firmas/dibujada", { method: "POST", body: JSON.stringify({ contenido }) }),
  subirFirma: (archivo) => {
    const fd = new FormData();
    fd.append("archivo", archivo);
    return peticion("/firmas/archivo", { method: "POST", body: fd });
  },
};

/* ------------------------------------------------------------- utilidades */
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
