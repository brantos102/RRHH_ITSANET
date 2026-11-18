#!/usr/bin/env bash
# Actualiza el sistema en este servidor EN UN SOLO PASO, con respaldo previo.
#
#     bash despliegue/actualizar.sh          # muestra qué trae la actualización y pregunta
#     bash despliegue/actualizar.sh --si     # sin preguntar
#
# En orden, y se detiene en el primer error:
#   1. Comprueba que no haya cambios hechos a mano en el código del servidor.
#   2. Trae del repositorio lo nuevo y muestra qué trae (y qué nota de
#      despliegue/actualizaciones/ hay que leer).
#   3. Respalda la base (rrhh) y la carpeta de adjuntos en rrhh_datos/respaldos/.
#   4. git pull (solo avance rápido: nunca mezcla cambios locales).
#   5. Aplica las migraciones que falten (como root, por el socket de MySQL).
#   6. Reinstala el servicio, la web y el sitio de Apache (instalar.sh --si).
#   7. Comprueba que el sistema responda.
#
# No toca IV ITSANET ni los demás sitios del servidor: lo que hace cada paso
# es lo mismo que la guía de comandos, solo que encadenado.

set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
DATOS="$(dirname "$RAIZ")/rrhh_datos"
RESPALDOS="$DATOS/respaldos"
MYSQL_ROOT="mysql://root@localhost/rrhh?unix_socket=/var/run/mysqld/mysqld.sock"
SIN_PREGUNTAR=0
[ "${1:-}" = "--si" ] && SIN_PREGUNTAR=1

VERDE=$'\e[32m'; ROJO=$'\e[31m'; AMARILLO=$'\e[33m'; GRIS=$'\e[90m'; FIN=$'\e[0m'
paso()  { printf '\n%s== %s ==%s\n' "$VERDE" "$1" "$FIN"; }
aviso() { printf '%s%s%s\n' "$AMARILLO" "$1" "$FIN"; }
error() { printf '%s%s%s\n' "$ROJO" "$1" "$FIN" >&2; exit 1; }
seguir() {
  [ "$SIN_PREGUNTAR" = 1 ] && return 0
  read -r -p "$1 [s/N]: " r
  case "$r" in s|S|si|SI|Si|sí|Sí) return 0 ;; *) return 1 ;; esac
}

[ "$(id -u)" = 0 ] && error "Ejecútelo con su usuario, no con sudo: el script pide sudo donde hace falta."
cd "$RAIZ"

# ------------------------------------------------------------ 1. comprobar
paso "1. Comprobaciones"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  git status --short --untracked-files=no
  error "Hay cambios hechos a mano en el código del servidor. El código se cambia en el
repositorio y llega con git pull; revise esos archivos con TI antes de actualizar."
fi
RAMA="$(git rev-parse --abbrev-ref HEAD)"
echo "  Rama: $RAMA · versión instalada: $(git rev-parse --short HEAD)"

# ------------------------------------------------------- 2. qué trae
paso "2. Qué trae la actualización"
git fetch --quiet origin "$RAMA"
NUEVOS="$(git log --oneline HEAD..FETCH_HEAD || true)"
if [ -z "$NUEVOS" ]; then
  echo "  El código ya está al día. Se revisan igual las migraciones y el servicio."
else
  echo "$NUEVOS" | sed 's/^/  · /'
  NOTAS="$(git diff --name-only HEAD FETCH_HEAD -- despliegue/actualizaciones/ | grep -v LEEME || true)"
  if [ -n "$NOTAS" ]; then
    echo
    aviso "  Notas de esta actualización (léalas: dicen qué probar):"
    echo "$NOTAS" | sed 's/^/    /'
  fi
fi
seguir "¿Actualizar ahora (con respaldo previo)?" || { echo "No se cambió nada."; exit 0; }

# ------------------------------------------------------------ 3. respaldo
paso "3. Respaldo de la base y de los adjuntos"
install -d -m 700 "$RESPALDOS"
SELLO="$(date +%F_%H%M)"
sudo mysqldump --single-transaction --routines --triggers rrhh > "$RESPALDOS/rrhh_antes_de_actualizar_$SELLO.sql"
[ -s "$RESPALDOS/rrhh_antes_de_actualizar_$SELLO.sql" ] || error "El respaldo de la base salió vacío. No se actualizó nada."
echo "  Base: $RESPALDOS/rrhh_antes_de_actualizar_$SELLO.sql ($(du -h "$RESPALDOS/rrhh_antes_de_actualizar_$SELLO.sql" | cut -f1))"
if [ -d "$DATOS/adjuntos" ]; then
  tar -czf "$RESPALDOS/adjuntos_$SELLO.tar.gz" -C "$DATOS" adjuntos
  echo "  Adjuntos, fotos y escaneos: $RESPALDOS/adjuntos_$SELLO.tar.gz"
fi

# ------------------------------------------------------------- 4. código
paso "4. Código nuevo"
git pull --ff-only --quiet origin "$RAMA"
echo "  Ahora en $(git rev-parse --short HEAD)"

# ------------------------------------------------------- 5. migraciones
paso "5. Base de datos"
sudo env MYSQL_URL="$MYSQL_ROOT" "$RAIZ/.venv/bin/python" mysql/migrar.py --aplicar

# ------------------------------------------------- 6. servicio y web
paso "6. Servicio, web y Apache"
bash despliegue/instalar.sh --si

# --------------------------------------------------------- 7. verificar
paso "7. Verificación"
if curl -fsS "http://127.0.0.1:8010/salud" >/dev/null; then
  echo "  ${VERDE}El sistema responde.${FIN}"
else
  error "El backend no responde. Mire: journalctl -u rrhh-itsanet-api -n 50
Para volver atrás: restaure $RESPALDOS/rrhh_antes_de_actualizar_$SELLO.sql (COMANDOS.md, sección 5)."
fi
cat <<EOF

  Listo. En el navegador, Ctrl+F5 una vez.
  Las notas de cada actualización están en despliegue/actualizaciones/ y en
  el sistema: Administración › Actualizaciones.
EOF
