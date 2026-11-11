#!/usr/bin/env bash
# Crea (o quita) el usuario de MySQL de SOLO LECTURA para revisar la base
# desde DBeaver: rrhh_lectura. Guía completa en despliegue/DBEAVER.md.
#
#     bash despliegue/usuario_lectura.sh                # lo crea si no existe
#     bash despliegue/usuario_lectura.sh --nueva-clave  # le cambia la clave
#     bash despliegue/usuario_lectura.sh --quitar       # lo elimina
#
# Qué puede: SELECT y SHOW VIEW sobre la base `rrhh`. Nada más: no escribe,
# no borra, no ve otras bases del servidor (IV_ITSANET incluida) y solo se
# conecta desde el propio servidor —desde fuera se entra por túnel SSH—.
#
# La clave se genera al azar y se muestra UNA SOLA VEZ en esta terminal, para
# escribirla en DBeaver. No se guarda en ningún archivo. Nunca se pega en un
# chat, un correo ni un documento: si se pierde, se genera otra con
# --nueva-clave.
#
# Protección de datos (LOPDP): esta cuenta ve datos personales de todos los
# colaboradores. Es para el responsable técnico; no se comparte.
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then MYSQL=(mysql); else MYSQL=(sudo mysql); fi
HOSTS=("localhost" "127.0.0.1")
ACCION="crear"
case "${1:-}" in
  "") ;;
  --nueva-clave) ACCION="clave" ;;
  --quitar) ACCION="quitar" ;;
  *) echo "Uso: bash despliegue/usuario_lectura.sh [--nueva-clave|--quitar]" >&2; exit 2 ;;
esac

existe() {
  "${MYSQL[@]}" -N -e "SELECT COUNT(*) FROM mysql.user WHERE user='rrhh_lectura' AND host='$1';"
}

if [ "$ACCION" = "quitar" ]; then
  for h in "${HOSTS[@]}"; do "${MYSQL[@]}" -e "DROP USER IF EXISTS 'rrhh_lectura'@'$h';"; done
  echo "Usuario rrhh_lectura eliminado. Borre también la conexión en DBeaver."
  exit 0
fi

ya=0
for h in "${HOSTS[@]}"; do [ "$(existe "$h")" != "0" ] && ya=1; done
if [ "$ya" = "1" ] && [ "$ACCION" = "crear" ]; then
  echo "El usuario rrhh_lectura ya existe: no se le cambió la clave."
  echo "Si no la recuerda:  bash despliegue/usuario_lectura.sh --nueva-clave"
else
  # Mayúsculas, minúsculas, números y un signo: pasa cualquier política de
  # claves de MySQL. Va por la entrada estándar: no queda en la lista de
  # procesos ni en el historial.
  CLAVE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(18) + "-Lc7")')"
  for h in "${HOSTS[@]}"; do
    if [ "$(existe "$h")" = "0" ]; then ORDEN="CREATE USER"; else ORDEN="ALTER USER"; fi
    printf "%s 'rrhh_lectura'@'%s' IDENTIFIED BY '%s';\n" "$ORDEN" "$h" "$CLAVE" | "${MYSQL[@]}"
  done
  echo
  echo "  Clave de rrhh_lectura (se muestra esta única vez):"
  echo
  echo "      $CLAVE"
  echo
  echo "  Escríbala en DBeaver y luego limpie la pantalla con:  clear"
  echo "  No la pegue en chats, correos ni documentos."
  unset CLAVE
fi

for h in "${HOSTS[@]}"; do
  "${MYSQL[@]}" -e "REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'rrhh_lectura'@'$h';" 2>/dev/null || true
  "${MYSQL[@]}" -e "GRANT SELECT, SHOW VIEW ON \`rrhh\`.* TO 'rrhh_lectura'@'$h';"
done
echo
echo "Permisos de rrhh_lectura:"
for h in "${HOSTS[@]}"; do
  "${MYSQL[@]}" -N -e "SHOW GRANTS FOR 'rrhh_lectura'@'$h';" | sed 's/^/  /'
done
