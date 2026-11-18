#!/usr/bin/env bash
# Usuarios de MySQL para revisar o corregir la base `rrhh` desde DBeaver.
# Guía completa: despliegue/DBEAVER.md
#
#     bash despliegue/usuario_bd.sh lectura                 # crea rrhh_lectura
#     bash despliegue/usuario_bd.sh edicion                 # crea rrhh_edicion
#     bash despliegue/usuario_bd.sh edicion --nueva-clave   # le cambia la clave
#     bash despliegue/usuario_bd.sh edicion --quitar        # lo elimina
#
#   rrhh_lectura   SELECT y SHOW VIEW. Mira, no cambia nada. Para el día a día.
#   rrhh_edicion   además INSERT, UPDATE, DELETE y EXECUTE: corrige datos.
#                  NO puede crear, alterar ni borrar tablas, ni dar permisos,
#                  ni tocar otras bases (iv_itsanet incluida). Las bitácoras
#                  siguen protegidas: un disparador impide modificarlas.
#
# Los dos solo se conectan desde el propio servidor: desde Windows se entra
# por túnel SSH. La clave se genera al azar y se muestra UNA SOLA VEZ en esta
# terminal; no se guarda en ningún archivo. Nunca se pega en chats ni correos.
#
# Protección de datos (LOPDP): ven los datos de todo el personal. Son para el
# responsable técnico. rrhh_edicion conviene quitarlo cuando no se use.
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then MYSQL=(mysql); else MYSQL=(sudo mysql); fi
HOSTS=("localhost" "127.0.0.1")

PERFIL="${1:-}"
case "$PERFIL" in
  lectura) USUARIO="rrhh_lectura"; PERMISOS="SELECT, SHOW VIEW" ;;
  edicion) USUARIO="rrhh_edicion"; PERMISOS="SELECT, SHOW VIEW, INSERT, UPDATE, DELETE, EXECUTE" ;;
  *) echo "Uso: bash despliegue/usuario_bd.sh lectura|edicion [--nueva-clave|--quitar]" >&2; exit 2 ;;
esac
ACCION="crear"
case "${2:-}" in
  "") ;;
  --nueva-clave) ACCION="clave" ;;
  --quitar) ACCION="quitar" ;;
  *) echo "Uso: bash despliegue/usuario_bd.sh lectura|edicion [--nueva-clave|--quitar]" >&2; exit 2 ;;
esac

existe() {
  "${MYSQL[@]}" -N -e "SELECT COUNT(*) FROM mysql.user WHERE user='$USUARIO' AND host='$1';"
}

if [ "$ACCION" = "quitar" ]; then
  for h in "${HOSTS[@]}"; do "${MYSQL[@]}" -e "DROP USER IF EXISTS '$USUARIO'@'$h';"; done
  echo "Usuario $USUARIO eliminado. Borre también la conexión en DBeaver."
  exit 0
fi

ya=0
for h in "${HOSTS[@]}"; do [ "$(existe "$h")" != "0" ] && ya=1; done
if [ "$ya" = "1" ] && [ "$ACCION" = "crear" ]; then
  echo "El usuario $USUARIO ya existe: no se le cambió la clave."
  echo "Si no la recuerda:  bash despliegue/usuario_bd.sh $PERFIL --nueva-clave"
else
  # Mayúsculas, minúsculas, números y un signo: pasa cualquier política de
  # claves de MySQL. Va por la entrada estándar: no queda en la lista de
  # procesos ni en el historial.
  CLAVE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18) + "-Lc7")')"
  for h in "${HOSTS[@]}"; do
    if [ "$(existe "$h")" = "0" ]; then ORDEN="CREATE USER"; else ORDEN="ALTER USER"; fi
    printf "%s '%s'@'%s' IDENTIFIED BY '%s';\n" "$ORDEN" "$USUARIO" "$h" "$CLAVE" | "${MYSQL[@]}"
  done
  echo
  echo "  Clave de $USUARIO (se muestra esta única vez):"
  echo
  echo "      $CLAVE"
  echo
  echo "  Escríbala en DBeaver y luego limpie la pantalla con:  clear"
  echo "  No la pegue en chats, correos ni documentos."
  unset CLAVE
fi

for h in "${HOSTS[@]}"; do
  "${MYSQL[@]}" -e "REVOKE ALL PRIVILEGES, GRANT OPTION FROM '$USUARIO'@'$h';" 2>/dev/null || true
  "${MYSQL[@]}" -e "GRANT $PERMISOS ON \`rrhh\`.* TO '$USUARIO'@'$h';"
done
echo
echo "Permisos de $USUARIO:"
for h in "${HOSTS[@]}"; do
  "${MYSQL[@]}" -N -e "SHOW GRANTS FOR '$USUARIO'@'$h';" | sed 's/^/  /'
done
