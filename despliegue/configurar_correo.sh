#!/usr/bin/env bash
# Configura el envío de correo del sistema en servidor/.env.
#
#     bash despliegue/configurar_correo.sh
#
# Pide el servidor SMTP, el puerto, el usuario, el remitente y la clave. La
# clave se escribe (o se pega) sin que se vea y no queda en el historial de
# la terminal. Todo va a servidor/.env, con permisos 600: solo su dueño lo
# lee, y el archivo no se sube al repositorio (.gitignore).
#
# Si servidor/.env no tiene todavía JWT_SECRET (el secreto con que se firman
# las sesiones), lo genera al azar.
#
# Se puede volver a ejecutar para cambiar cualquier dato: reemplaza las
# líneas del correo y deja las demás (MYSQL_URL, etc.) como estaban.

set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
ENV="$RAIZ/servidor/.env"

limpiar() {
  # Lo que una terminal agrega al pegar (marcas de «pegado entre corchetes»
  # y el retorno de carro de Windows) no es parte del dato.
  local v="$1"
  v="${v//$'\e[200~'/}"
  v="${v//$'\e[201~'/}"
  v="${v//$'\r'/}"
  v="${v#"${v%%[![:space:]]*}"}"
  v="${v%"${v##*[![:space:]]}"}"
  printf '%s' "$v"
}

preguntar() {
  local texto="$1" omision="${2:-}" v
  if [ -n "$omision" ]; then
    read -r -p "$texto [$omision]: " v
  else
    read -r -p "$texto: " v
  fi
  v="$(limpiar "$v")"
  printf '%s' "${v:-$omision}"
}

echo "Configuración del correo del sistema (se guarda en servidor/.env)"
echo
HOST="$(preguntar "Servidor SMTP" "pro.eu.turbo-smtp.com")"
PUERTO="$(preguntar "Puerto" "587")"
USUARIO="$(preguntar "Usuario SMTP")"
REMITENTE="$(preguntar "Remitente (nombre y correo)" "Talento Humano ITSANET <notificaciones@entregar.net.ar>")"
read -rs -p "Clave SMTP (no se verá al escribirla ni al pegarla): " CLAVE; echo
CLAVE="$(limpiar "$CLAVE")"

case "$PUERTO" in
  ''|*[!0-9]*) echo "El puerto tiene que ser un número." >&2; exit 1 ;;
esac
if [ -z "$USUARIO" ] || [ -z "$CLAVE" ]; then
  echo "Faltan el usuario o la clave. No se cambió nada." >&2
  exit 1
fi
case "$CLAVE" in
  *$'\n'*|*'"'*) echo "La clave tiene un carácter que no se puede guardar así; avise." >&2; exit 1 ;;
esac

umask 077
touch "$ENV"
chmod 600 "$ENV"
grep -v -E '^(SMTP_HOST|SMTP_PORT|SMTP_USER|SMTP_PASSWORD|SMTP_REMITENTE|SMTP_STARTTLS|EMAIL_BACKEND)=' \
  "$ENV" > "$ENV.tmp" || true
{
  printf 'SMTP_HOST=%s\n' "$HOST"
  printf 'SMTP_PORT=%s\n' "$PUERTO"
  printf 'SMTP_USER=%s\n' "$USUARIO"
  printf 'SMTP_PASSWORD="%s"\n' "$CLAVE"
  printf 'SMTP_REMITENTE="%s"\n' "$REMITENTE"
  # 465 cifra desde el inicio; los demás (587) suben a TLS con STARTTLS.
  if [ "$PUERTO" = "465" ]; then echo "SMTP_STARTTLS=false"; else echo "SMTP_STARTTLS=true"; fi
  echo "EMAIL_BACKEND=smtp"
} >> "$ENV.tmp"
if ! grep -q '^JWT_SECRET=' "$ENV.tmp"; then
  printf 'JWT_SECRET=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')" >> "$ENV.tmp"
  echo "Se generó JWT_SECRET (el secreto de las sesiones)."
fi
mv "$ENV.tmp" "$ENV"
chmod 600 "$ENV"
unset CLAVE

echo
echo "Guardado en servidor/.env (solo legible por $(id -un)). Así quedó, sin la clave:"
sed -E 's/^(SMTP_PASSWORD=).*/\1********/; s/^(JWT_SECRET=).*/\1********/; s/(rrhh_app:)[^@]*@/\1********@/' "$ENV" | sed 's/^/  /'
echo
echo "Para probar el envío:"
echo "  .venv/bin/python despliegue/probar_correo.py su.correo@empresa.com"
