#!/usr/bin/env bash
# Crea la base del sistema de Talento Humano y el usuario con que se conecta
# la aplicación. NO toca ninguna otra base ni la configuración de MySQL.
#
#     bash despliegue/crear_base.sh             # la base del sistema: rrhh
#     bash despliegue/crear_base.sh rrhh_ensayo # una base para ensayar el traslado
#
# Qué crea:
#   - la base, en utf8mb4 (sin eso «Suárez» se guarda corrompido sin avisar);
#   - para `rrhh`, el usuario rrhh_app@localhost con lo justo para operar:
#     leer, escribir y ejecutar las funciones de ESA base. Sin DROP, sin
#     ALTER, sin GRANT, sin acceso a ninguna otra base del servidor.
#     La base de ensayo no tiene usuario de aplicación: nadie la usa.
#
# La clave se escribe una vez, sin que se vea, y no queda en el historial.
# Si el usuario ya existe, no se le cambia la clave.
#
# Se puede ejecutar dos veces: lo que ya existe se deja como está.

set -euo pipefail

BASE="${1:-rrhh}"
case "$BASE" in
  rrhh|rrhh_ensayo) ;;
  *) echo "Solo se crean las bases rrhh o rrhh_ensayo." >&2; exit 2 ;;
esac

if [ "$(id -u)" -eq 0 ]; then MYSQL=(mysql); else MYSQL=(sudo mysql); fi

echo "Base: $BASE"
"${MYSQL[@]}" -e "CREATE DATABASE IF NOT EXISTS \`$BASE\`
                  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"

if [ "$BASE" = "rrhh" ]; then
  existe=$("${MYSQL[@]}" -N -e "SELECT COUNT(*) FROM mysql.user WHERE user = 'rrhh_app' AND host = 'localhost';")
  if [ "$existe" = "0" ]; then
    echo
    echo "Clave para el usuario rrhh_app. Use una larga y aleatoria; puede generarla con:"
    echo "    python3 -c \"import secrets; print(secrets.token_urlsafe(24))\""
    echo "Guárdela: va en el archivo servidor/.env (MYSQL_URL)."
    read -rs -p "Clave: " CLAVE; echo
    read -rs -p "Repítala: " CLAVE2; echo
    if [ "$CLAVE" != "$CLAVE2" ] || [ ${#CLAVE} -lt 16 ]; then
      echo "No coinciden, o tiene menos de 16 caracteres. No se creó nada más." >&2
      exit 1
    fi
    # La clave va por la entrada estándar de mysql, no en la línea de comandos:
    # así no aparece en la lista de procesos del servidor.
    printf "CREATE USER 'rrhh_app'@'localhost' IDENTIFIED BY '%s';\n" \
      "$(printf '%s' "$CLAVE" | sed "s/'/''/g")" | "${MYSQL[@]}"
    unset CLAVE CLAVE2
    echo "Usuario rrhh_app creado."
  else
    echo "El usuario rrhh_app ya existía: no se le cambió la clave."
  fi
  "${MYSQL[@]}" -e "GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON \`rrhh\`.* TO 'rrhh_app'@'localhost';"
  echo
  echo "Permisos de rrhh_app:"
  "${MYSQL[@]}" -N -e "SHOW GRANTS FOR 'rrhh_app'@'localhost';" | sed 's/^/  /'
fi

echo
"${MYSQL[@]}" -N -e "SELECT CONCAT('  ', schema_name, ' · ', default_character_set_name, ' · ',
                       default_collation_name) FROM information_schema.schemata
                      WHERE schema_name = '$BASE';"
echo "Listo."
