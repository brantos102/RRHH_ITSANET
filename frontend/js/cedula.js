/* Leer una cédula ecuatoriana a partir de lo que entrega el escáner.

   Tres fuentes, de la más confiable a la menos:

   1. La zona de lectura mecánica (MRZ) del reverso: tres líneas de 30
      caracteres con el formato TD1 de la OACI (Doc 9303, parte 5). Trae
      dígitos verificadores, así que una lectura mala se detecta en lugar de
      colarse en el registro.
   2. El código QR del reverso. Lleva a la página del Registro Civil
      (qr.registrocivil.gob.ec): el sistema NO la consulta ni copia nada de
      ella; solo ofrece abrirla para que la persona compare a simple vista.
      Si el QR trae un número de cédula válido, se usa.
   3. El anverso leído con OCR: el número (NUI) y, si se distinguen, los
      rótulos APELLIDOS y NOMBRES. Es lo menos seguro: el resultado se
      muestra para que quien registra lo revise antes de guardarlo.

   Este archivo no toca la cámara ni la red: recibe texto y devuelve datos.
   Así se prueba sin navegador (frontend/tests/cedula.test.mjs). */

/* ------------------------------------------------------- módulo 10

   La misma regla que `validarCedula` de api.js. Se repite aquí para que este
   módulo no dependa de la sesión ni del navegador. */
export function cedulaValida(cedula) {
  if (!/^\d{10}$/.test(cedula)) return false;
  const provincia = +cedula.slice(0, 2);
  if (!((provincia >= 1 && provincia <= 24) || provincia === 30)) return false;
  if (+cedula[2] > 5) return false;
  let suma = 0;
  for (let i = 0; i < 9; i++) {
    let d = +cedula[i];
    if (i % 2 === 0) { d *= 2; if (d > 9) d -= 9; }
    suma += d;
  }
  return (10 - (suma % 10)) % 10 === +cedula[9];
}

/* ------------------------------------------------- dígito verificador */

const VALOR = (c) => (c === "<" ? 0 : /\d/.test(c) ? +c : c.charCodeAt(0) - 55);

export function digitoMRZ(texto) {
  const pesos = [7, 3, 1];
  let suma = 0;
  for (let i = 0; i < texto.length; i++) suma += VALOR(texto[i]) * pesos[i % 3];
  return String(suma % 10);
}

/* El OCR confunde letras y números parecidos. En un campo que solo puede
   llevar números se corrige hacia el número, y al revés en los nombres. */
const A_NUMERO = { O: "0", Q: "0", D: "0", U: "0", I: "1", L: "1", T: "1", Z: "2",
                   S: "5", G: "6", B: "8" };
const A_LETRA = { 0: "O", 1: "I", 2: "Z", 5: "S", 6: "G", 8: "B" };

const comoNumero = (t) => [...t].map((c) => A_NUMERO[c] ?? c).join("");
const comoLetra = (t) => [...t].map((c) => A_LETRA[c] ?? c).join("");

/* ------------------------------------------------------ líneas MRZ */

/* Deja una línea del OCR con solo los caracteres que existen en una MRZ.
   El relleno «<» suele leerse como ««», «‹», «(» o «K» entre rellenos. */
function limpiarLinea(linea) {
  return linea.toUpperCase()
    .replace(/[«‹(\[{]/g, "<")
    .replace(/\s+/g, "")
    .replace(/[^A-Z0-9<]/g, "");
}

/* Busca tres líneas seguidas que parezcan una MRZ TD1. Devuelve null si no
   las encuentra. */
export function encontrarMRZ(texto) {
  const lineas = String(texto || "").split(/\r?\n/).map(limpiarLinea)
    .filter((l) => l.length >= 24 && (l.match(/</g) || []).length >= 1);
  for (let i = lineas.length - 3; i >= 0; i--) {
    const [a, b, c] = lineas.slice(i, i + 3);
    // La primera empieza por el tipo de documento (I, A o C) y el país; la
    // segunda tiene la fecha de nacimiento al inicio.
    if (/^[IAC][A-Z<]/.test(a) && /^[0-9OQDILSZBG]{6}/.test(b) && c.includes("<")) {
      return [a, b, c].map((l) => (l + "<".repeat(30)).slice(0, 30));
    }
  }
  return null;
}

function fechaMRZ(aammdd, futura = false) {
  if (!/^\d{6}$/.test(aammdd)) return null;
  const aa = +aammdd.slice(0, 2), mm = +aammdd.slice(2, 4), dd = +aammdd.slice(4, 6);
  if (mm < 1 || mm > 12 || dd < 1 || dd > 31) return null;
  const actual = new Date().getFullYear() % 100;
  // Nacimiento: un año de dos cifras mayor que el actual es del siglo pasado.
  // Vencimiento: siempre de este siglo.
  const siglo = futura ? 2000 : (aa > actual ? 1900 : 2000);
  return `${siglo + aa}-${String(mm).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
}

/* Las 10 cifras seguidas que pasan el módulo 10, dentro de un campo. */
function cedulaEn(campo) {
  const cifras = comoNumero(campo).replace(/</g, " ");
  for (const m of cifras.matchAll(/\d{10,}/g)) {
    for (let i = 0; i + 10 <= m[0].length; i++) {
      const c = m[0].slice(i, i + 10);
      if (cedulaValida(c)) return c;
    }
  }
  return null;
}

/* Un número de documento de más de 9 caracteres: el dígito de la posición 15
   es «<» y el número sigue en el campo opcional, cerrado por su verificador. */
function numeroLargo(l1) {
  if (l1[14] !== "<") return l1.slice(5, 14);
  const resto = l1.slice(15).split("<")[0];
  return l1.slice(5, 14) + resto.slice(0, -1);
}

/* Interpreta una MRZ TD1. `verificada` es verdadero solo si TODOS los
   dígitos verificadores cuadran: entonces la lectura es la del documento,
   letra por letra. */
export function leerMRZ(lineas) {
  const [l1, l2, l3] = lineas;

  const numeroDoc = comoNumero(l1.slice(5, 14)).replace(/<+$/, "");
  const nacimiento = comoNumero(l2.slice(0, 6));
  const vencimiento = comoNumero(l2.slice(8, 14));
  const control = {
    documento: digitoMRZ(l1.slice(5, 14)) === comoNumero(l1[14]) || l1[14] === "<",
    nacimiento: digitoMRZ(nacimiento) === comoNumero(l2[6]),
    vencimiento: digitoMRZ(vencimiento) === comoNumero(l2[14]),
  };
  const compuesto = l1.slice(5, 30) + nacimiento + comoNumero(l2[6])
    + vencimiento + comoNumero(l2[14]) + l2.slice(18, 29);
  control.general = digitoMRZ(compuesto) === comoNumero(l2[29]);

  // El número de cédula: Ecuador lo pone en un campo opcional. Se busca en
  // todos los campos donde puede estar y solo se acepta si pasa el módulo 10.
  // Nunca se busca a caballo entre dos campos: juntar el final de uno con el
  // inicio del otro puede formar por azar diez cifras que pasen el módulo 10.
  const cedula = cedulaEn(l1.slice(15, 30)) || cedulaEn(l2.slice(18, 29))
    || cedulaEn(numeroLargo(l1));

  // Apellidos<<Nombres, con «<» como espacio.
  const nombre = comoLetra(l3).replace(/[^A-Z<]/g, "<");
  const [apellidos = "", nombres = ""] = nombre.split(/<<+/).filter(Boolean)
    .map((p) => p.replace(/<+/g, " ").trim());

  return {
    fuente: "mrz",
    cedula,
    apellidos: apellidos || null,
    nombres: nombres || null,
    nacionalidad: comoLetra(l2.slice(15, 18)).replace(/</g, "") || null,
    pais_emisor: comoLetra(l1.slice(2, 5)).replace(/</g, "") || null,
    sexo: { M: "M", F: "F" }[l2[7]] || null,
    fecha_nacimiento: fechaMRZ(nacimiento),
    vencimiento: fechaMRZ(vencimiento, true),
    numero_documento: numeroDoc || null,
    verificada: Object.values(control).every(Boolean) && !!cedula,
    control,
  };
}

/* ---------------------------------------------------------- anverso */

const ROTULOS = /^(APELLIDOS?|NOMBRES?|NACIONALIDAD|SEXO|FECHA|LUGAR|NUI|CONDICI|ESTADO|FIRMA|REP[UÚ]BLICA|C[EÉ]DULA|DOCUMENTO|IDENTIDAD|REGISTRO)/;

/* Lo que se pueda sacar del anverso: el número siempre se valida con el
   módulo 10; los nombres solo si aparecen debajo de su rótulo. */
export function leerAnverso(texto) {
  const lineas = String(texto || "").toUpperCase().split(/\r?\n/)
    .map((l) => l.replace(/[^A-ZÁÉÍÓÚÑÜ0-9 \-.]/g, " ").replace(/\s+/g, " ").trim())
    .filter(Boolean);

  // El NUI aparece como 1234567890 o 123456789-0.
  let cedula = null;
  for (const l of lineas) {
    const cifras = comoNumero(l.replace(/[^0-9OQDILSZBG\- ]/g, " "))
      .replace(/(\d{9})\s*-\s*(\d)/g, "$1$2");
    cedula = cedulaEn(cifras.replace(/[^\d]/g, " "));
    if (cedula) break;
  }

  const debajo = (rotulo) => {
    const i = lineas.findIndex((l) => rotulo.test(l));
    if (i < 0) return null;
    // A veces el valor queda en la misma línea, después del rótulo.
    const resto = lineas[i].replace(rotulo, "").trim();
    const candidato = resto.length >= 3 ? resto : lineas[i + 1];
    if (!candidato || ROTULOS.test(candidato) || /\d/.test(candidato)) return null;
    return candidato.replace(/[^A-ZÁÉÍÓÚÑÜ ]/g, "").trim() || null;
  };

  return {
    fuente: "anverso",
    cedula,
    apellidos: debajo(/^APELLIDOS?\b/),
    nombres: debajo(/^NOMBRES?\b/),
    nacionalidad: /ECUATORIAN/.test(lineas.join(" ")) ? "ECU" : null,
    verificada: false,
  };
}

/* ------------------------------------------------------------- QR */

/* Lo que trae el QR. Si es un enlace, solo se acepta el dominio del Registro
   Civil: un QR pegado encima de la cédula podría llevar a cualquier sitio. */
export function leerQR(texto) {
  const valor = String(texto || "").trim();
  let enlace = null;
  try {
    const url = new URL(valor);
    if (url.protocol === "https:" &&
        (url.hostname === "registrocivil.gob.ec" || url.hostname.endsWith(".registrocivil.gob.ec"))) {
      enlace = url.href;
    }
  } catch { /* no es un enlace */ }
  return {
    fuente: "qr",
    cedula: cedulaEn(valor.replace(/\D/g, (c) => (c === "-" ? "" : " "))),
    enlace_registro_civil: enlace,
    enlace_desconocido: !enlace && /^https?:/i.test(valor),
    verificada: false,
  };
}

/* ------------------------------------------------------------ junto */

/* Une lo leído del texto del OCR: la MRZ manda; el anverso completa lo que
   falte. */
export function interpretarTexto(texto) {
  const mrz = encontrarMRZ(texto);
  const desdeMRZ = mrz ? leerMRZ(mrz) : null;
  const desdeAnverso = leerAnverso(texto);
  if (!desdeMRZ) return desdeAnverso.cedula || desdeAnverso.apellidos ? desdeAnverso : null;
  for (const campo of ["cedula", "apellidos", "nombres", "nacionalidad"]) {
    if (!desdeMRZ[campo] && desdeAnverso[campo]) desdeMRZ[campo] = desdeAnverso[campo];
  }
  return desdeMRZ;
}

/* «APELLIDOS NOMBRES», como se escribe en el registro de la empresa. */
export function nombreCompleto(datos) {
  const titulo = (t) => t.toLowerCase().replace(/(^|\s)\S/g, (c) => c.toUpperCase());
  return [datos?.apellidos, datos?.nombres].filter(Boolean).map(titulo).join(" ");
}
