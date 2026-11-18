/* Pruebas del lector de cédula (frontend/js/cedula.js).

   Todo con datos INVENTADOS: ninguna cédula ni nombre de una persona real.
   Se corren con:   node --test frontend/tests/          */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  cedulaValida, digitoMRZ, encontrarMRZ, leerMRZ, leerAnverso, leerQR,
  interpretarTexto, nombreCompleto,
} from "../js/cedula.js";

/* Una cédula inventada que pasa el módulo 10. */
function cedulaInventada(base = "091234567") {
  for (let d = 0; d <= 9; d++) if (cedulaValida(base + d)) return base + d;
  throw new Error("sin dígito");
}
const CEDULA = cedulaInventada();

/* Arma una MRZ TD1 con sus dígitos verificadores correctos. */
function mrz({ doc = "A12345678", cedula = CEDULA, nac = "951016", vence = "330101",
               sexo = "M", apellidos = "PRUEBA<EJEMPLO", nombres = "JUAN<CARLOS" } = {}) {
  const opc1 = (cedula + "<".repeat(15)).slice(0, 15);
  const l1 = `I<ECU${doc}${digitoMRZ(doc)}${opc1}`;
  const opc2 = "<".repeat(11);
  const sinCompuesto = `${nac}${digitoMRZ(nac)}${sexo}${vence}${digitoMRZ(vence)}ECU${opc2}`;
  const compuesto = digitoMRZ(l1.slice(5, 30) + nac + digitoMRZ(nac) + vence
    + digitoMRZ(vence) + opc2);
  const l3 = (`${apellidos}<<${nombres}` + "<".repeat(30)).slice(0, 30);
  return [l1, sinCompuesto + compuesto, l3];
}

test("el dígito verificador sigue la OACI (ejemplo del Doc 9303)", () => {
  // Ejemplo publicado en el Doc 9303: número de documento D23145890 → 7.
  assert.equal(digitoMRZ("D23145890"), "7");
  assert.equal(digitoMRZ("520727"), "3");
});

test("una MRZ bien leída da cédula, nombres y queda verificada", () => {
  const datos = leerMRZ(mrz());
  assert.equal(datos.cedula, CEDULA);
  assert.equal(datos.apellidos, "PRUEBA EJEMPLO");
  assert.equal(datos.nombres, "JUAN CARLOS");
  assert.equal(datos.nacionalidad, "ECU");
  assert.equal(datos.fecha_nacimiento, "1995-10-16");
  assert.equal(datos.vencimiento, "2033-01-01");
  assert.equal(datos.verificada, true);
});

test("se encuentra entre el ruido del OCR, con espacios y «<» mal leídos", () => {
  const [a, b, c] = mrz();
  const texto = `REPUBLICA DEL ECUADOR\nalgo de ruido\n${a.replace(/<</, "« ")}\n` +
                `${b.slice(0, 10)} ${b.slice(10)}\n${c.toLowerCase()}\n`;
  const lineas = encontrarMRZ(texto);
  assert.ok(lineas, "debería encontrar las tres líneas");
  assert.equal(leerMRZ(lineas).cedula, CEDULA);
});

test("una letra confundida con número en un campo numérico se corrige", () => {
  const [a, b, c] = mrz();
  const malo = b.replace(/^(.)5/, "$1S").replace(/^(...)0/, "$1O");   // 951016 → 9S1O16
  const datos = leerMRZ([a, malo, c]);
  assert.equal(datos.fecha_nacimiento, "1995-10-16");
  assert.equal(datos.control.nacimiento, true);
});

test("si un dígito verificador no cuadra, no queda verificada", () => {
  const [a, b, c] = mrz();
  const alterada = b.slice(0, 5) + "9" + b.slice(6);   // otra fecha, mismo dígito
  const datos = leerMRZ([a, alterada, c]);
  assert.equal(datos.control.nacimiento, false);
  assert.equal(datos.verificada, false);
});

test("una cédula que no pasa el módulo 10 no se acepta", () => {
  const otra = CEDULA.slice(0, 9) + ((+CEDULA[9] + 1) % 10);
  const datos = leerMRZ(mrz({ cedula: otra }));
  assert.equal(datos.cedula, null);
  assert.equal(datos.verificada, false);
});

test("el anverso da el NUI con guion y los nombres bajo su rótulo", () => {
  const nui = `${CEDULA.slice(0, 9)}-${CEDULA[9]}`;
  const texto = `REPÚBLICA DEL ECUADOR\nCÉDULA DE IDENTIDAD\nNUI. ${nui}\nAPELLIDOS\n` +
                `PRUEBA EJEMPLO\nNOMBRES\nJUAN CARLOS\nNACIONALIDAD\nECUATORIANA\n`;
  const datos = leerAnverso(texto);
  assert.equal(datos.cedula, CEDULA);
  assert.equal(datos.apellidos, "PRUEBA EJEMPLO");
  assert.equal(datos.nombres, "JUAN CARLOS");
  assert.equal(datos.nacionalidad, "ECU");
  assert.equal(datos.verificada, false, "el anverso nunca queda verificado");
});

test("la MRZ manda y el anverso completa", () => {
  const [a, b, c] = mrz({ cedula: "" });
  const texto = `NUI ${CEDULA}\n${a}\n${b}\n${c}`;
  const datos = interpretarTexto(texto);
  assert.equal(datos.fuente, "mrz");
  assert.equal(datos.cedula, CEDULA);
  assert.equal(datos.apellidos, "PRUEBA EJEMPLO");
});

test("el QR del Registro Civil se ofrece abrir; otro enlace no", () => {
  const bueno = leerQR("https://qr.registrocivil.gob.ec/?t=abc123");
  assert.equal(bueno.enlace_registro_civil, "https://qr.registrocivil.gob.ec/?t=abc123");
  const falso = leerQR("https://registrocivil.gob.ec.sitio-falso.com/x");
  assert.equal(falso.enlace_registro_civil, null);
  assert.equal(falso.enlace_desconocido, true);
  const http = leerQR("http://qr.registrocivil.gob.ec/x");
  assert.equal(http.enlace_registro_civil, null, "solo HTTPS");
});

test("el QR con el número lo entrega si pasa el módulo 10", () => {
  assert.equal(leerQR(`CI:${CEDULA}`).cedula, CEDULA);
  assert.equal(leerQR("1234567890").cedula, null);
});

test("nada legible devuelve null", () => {
  assert.equal(interpretarTexto("foto borrosa\nsin datos"), null);
});

test("el nombre completo queda «Apellidos Nombres» con mayúscula inicial", () => {
  assert.equal(nombreCompleto({ apellidos: "PRUEBA EJEMPLO", nombres: "JUAN CARLOS" }),
               "Prueba Ejemplo Juan Carlos");
});
