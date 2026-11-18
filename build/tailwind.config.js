/** Escanea el frontend para incluir solo las clases que realmente se usan.
    Las clases generadas en JS con plantillas también se detectan porque se
    buscan como texto en los .js.

    MARCA ITSANET (manual de marca): azul #1C58D7, azul oscuro #06122B,
    celeste #D2DEF7, negro #0C0C0C y grises #F7F7F7 / #C2C2C2 / #707171 /
    #333434; tipografía Schibsted Grotesk.

    Toda la interfaz está escrita con la escala «slate» de Tailwind; aquí se
    reemplaza esa escala por la de la marca (grises neutros y el azul oscuro
    en 800–900), así cada pantalla toma los colores oficiales sin tocar su
    código. Igual la escala «sky» (los acentos azules: botones «Atender»,
    avisos informativos) pasa al azul de marca #1C58D7 con el celeste
    #D2DEF7 en los tonos claros. «itsa-*» queda disponible para usar los
    colores por su nombre. */
module.exports = {
  content: ["../frontend/**/*.html", "../frontend/**/*.js", "!../frontend/vendor/**"],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Schibsted Grotesk Variable"', '"Schibsted Grotesk"', "ui-sans-serif", "system-ui",
               "-apple-system", '"Segoe UI"', "Roboto", "Arial", "sans-serif"],
      },
      colors: {
        slate: {
          50: "#FAFAFA", 100: "#F7F7F7", 200: "#E6E6E6", 300: "#C2C2C2", 400: "#9A9B9B",
          500: "#707171", 600: "#545555", 700: "#333434", 800: "#13244C", 900: "#06122B",
          950: "#0C0C0C",
        },
        sky: {
          50: "#EEF3FC", 100: "#D2DEF7", 200: "#B3C7F1", 300: "#8AA9EA", 400: "#5A85E1",
          500: "#2F67DB", 600: "#1C58D7", 700: "#1747B0", 800: "#133A8C", 900: "#0F2C68",
          950: "#06122B",
        },
        itsa: {
          azul: "#1C58D7", "azul-hover": "#1747B0", oscuro: "#06122B", celeste: "#D2DEF7",
          negro: "#0C0C0C", gris: "#F7F7F7",
        },
      },
    },
  },
  plugins: [],
};
