/** Escanea el frontend para incluir solo las clases que realmente se usan.
    Las clases generadas en JS con plantillas también se detectan porque se
    buscan como texto en los .js. */
module.exports = {
  content: ["../frontend/**/*.html", "../frontend/**/*.js"],
  theme: { extend: {} },
  plugins: [],
};
