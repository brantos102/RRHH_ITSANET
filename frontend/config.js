/* Configuración del frontend.

   API vacío significa «dedúcelo del navegador»: mismo host que esta página,
   puerto PUERTO_API. Así no hay que editar este archivo para trabajar en
   local —que es como terminó publicado apuntando a un puerto de pruebas— y
   desaparece el desajuste entre abrir localhost y abrir 127.0.0.1.

   Al publicar, escriba aquí la URL real del backend:
       API: "https://api.permisos.itsanet.com.ec",
*/
window.RRHH_CONFIG = {
  API: "",
  PUERTO_API: 8000,
  EMPRESA: "ITSANET",
  SISTEMA: "Permisos y Vacaciones",
  // El logo tiene dos versiones porque «net» va en negro: sobre la barra
  // oscura no se vería. LOGO se usa en fondo claro, LOGO_OSCURO en la barra.
  LOGO: "img/logo.png",
  LOGO_OSCURO: "img/logo-oscuro.png",
  COLOR_MARCA: "#1c58d7",
};
