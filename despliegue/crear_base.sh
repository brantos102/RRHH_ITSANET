#!/usr/bin/env bash
# Crea la base del sistema de Talento Humano y el usuario con que se conecta
# la aplicación. NO toca ninguna otra base ni la configuración de MySQL.
#
#     bash despliegue/crear_base.sh               # la base del sistema: rrhh
#     bash despliegue/crear_base.sh --nueva-clave # cambia la clave de rrhh_app
#     bash despliegue/crear_base.sh rrhh_ensayo   # una base para ensayar el traslado
#
# Qué crea:
#   - la base, en utf8mb4 (sin eso «Suárez» se guarda corrompido sin avisar);
#   - para `rrhh`, el usuario rrhh_app@localhost con lo justo para operar:
#     leer, escribir y ejecutar las funciones de ESA base. Sin DROP, sin
#     ALTER, sin GRANT, sin acceso a ninguna otra base del servidor.
#
# LA CLAVE NO LA ESCRIBE NADIE. Se genera aquí, al azar, y se guarda
# directamente en servidor/.env (permisos 600: solo su dueño la lee), que es
# de donde la toma el backend. No se muestra en pantalla, no pasa por la
# línea de comandos ni por el portapapeles, y servidor/.env no se sube al
# repositorio (.gitignore).
#
# Se puede ejecutar dos veces: lo que ya existe se deja como está.

set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
ENV="$RAIZ/servidor/.env"
SOCKET="/var/run/mysqld/mysqld.sock"

BASE="rrhh"
NUEVA_CLAVE=0
for arg in "$@"; do
  case "$arg" in
    --nueva-clave) NUEVA_CLAVE=1 ;;
    rrhh|rrhh_ensayo) BASE="$arg" ;;
    *) echo "Uso: bash despliegue/crear_base.sh [rrhh|rrhh_ensayo] [--nueva-clave]" >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" -eq 0 ]; then MYSQL=(mysql); else MYSQL=(sudo mysql); fi

echo "Base: $BASE"
"${MYSQL[@]}" -e "CREATE DATABASE IF NOT EXISTS \`$BASE\`
                  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"

guardar_url() {
  # Reemplaza (o agrega) la línea MYSQL_URL de servidor/.env sin tocar las demás.
  local url="mysql://rrhh_app:$1@localhost/rrhh?unix_socket=$SOCKET"
  umask 077
  touch "$ENV"
  chmod 600 "$ENV"
  grep -v '^MYSQL_URL=' "$ENV" > "$ENV.tmp" || true
  printf 'MYSQL_URL=%s\n' "$url" >> "$ENV.tmp"
  mv "$ENV.tmp" "$ENV"
  chmod 600 "$ENV"
}

if [ "$BASE" = "rrhh" ]; then
  existe=$("${MYSQL[@]}" -N -e "SELECT COUNT(*) FROM mysql.user WHERE user = 'rrhh_app' AND host = 'localhost';")
  if [ "$existe" = "0" ] || [ "$NUEVA_CLAVE" = "1" ]; then
    # 32 caracteres de [A-Za-z0-9_-]: seguros dentro de una URL y de SQL.
    CLAVE="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
    if [ "$existe" = "0" ]; then ORDEN="CREATE USER"; else ORDEN="ALTER USER"; fi
    # Por la entrada estándar de mysql: no aparece en la lista de procesos.
    printf "%s 'rrhh_app'@'localhost' IDENTIFIED BY '%s';\n" "$ORDEN" "$CLAVE" | "${MYSQL[@]}"
    guardar_url "$CLAVE"
    unset CLAVE
    if [ "$existe" = "0" ]; then echo "Usuario rrhh_app creado."; else echo "Clave de rrhh_app cambiada."; fi
    echo "Su clave quedó guardada en servidor/.env (solo legible por $(id -un))."
  else
    echo "El usuario rrhh_app ya existía: no se le cambió la clave."
    grep -q '^MYSQL_URL=' "$ENV" 2>/dev/null \
      || echo "AVISO: servidor/.env no tiene MYSQL_URL. Para generar una clave nueva y guardarla:
    bash despliegue/crear_base.sh --nueva-clave"
  fi
  "${MYSQL[@]}" -e "GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON \`rrhh\`.* TO 'rrhh_app'@'localhost';"

  echo
  echo "Permisos de rrhh_app:"
  "${MYSQL[@]}" -N -e "SHOW GRANTS FOR 'rrhh_app'@'localhost';" | sed 's/^/  /'

  # Prueba de verdad: conectarse como la aplicación, con la clave guardada.
  echo
  if "$RAIZ/.venv/bin/python" - "$ENV" <<'PY' 2>/dev/null; then
import sys
from urllib.parse import urlparse, parse_qs, unquote
import pymysql
url = next(l.split("=", 1)[1].strip() for l in open(sys.argv[1]) if l.startswith("MYSQL_URL="))
u = urlparse(url)
c = pymysql.connect(user=u.username, password=unquote(u.password), database="rrhh",
                    unix_socket=parse_qs(u.query)["unix_socket"][0], charset="utf8mb4")
c.cursor().execute("SELECT 1")
PY
    echo "Conexión de la aplicación: correcta."
  else
    echo "Conexión de la aplicación: NO se pudo comprobar (¿falta el paso de instalar .venv?)."
  fi
fi

echo
"${MYSQL[@]}" -N -e "SELECT CONCAT('  ', schema_name, ' · ', default_character_set_name, ' · ',
                       default_collation_name) FROM information_schema.schemata
                      WHERE schema_name = '$BASE';"
echo "Listo."
