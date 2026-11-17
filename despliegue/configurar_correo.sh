#!/usr/bin/env bash
# Configura el envío de correo del sistema en servidor/.env.
#
#     bash despliegue/configurar_correo.sh
#
# Pide el servidor SMTP, el puerto (y uno alterno), el usuario, el remitente
# y la clave. Antes de guardar, comprueba qué puertos salen del servidor. La
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
HOST="$(preguntar "Servidor SMTP" "pro.turbo-smtp.com")"
PUERTO="$(preguntar "Puerto" "587")"
ALTERNO="$(preguntar "Puerto alterno (Enter para 2525, «no» para ninguno)" "2525")"
USUARIO="$(preguntar "Usuario SMTP")"
REMITENTE="$(preguntar "Remitente (nombre y correo)" "Talento Humano ITSANET <notificaciones@flexnetecuador.com>")"
read -rs -p "Clave SMTP (no se verá al escribirla ni al pegarla): " CLAVE; echo
CLAVE="$(limpiar "$CLAVE")"

case "$PUERTO" in
  ''|*[!0-9]*) echo "El puerto tiene que ser un número." >&2; exit 1 ;;
esac
case "$ALTERNO" in
  no|NO|No|ninguno) ALTERNO="" ;;
  ''|*[!0-9]*) ALTERNO="" ;;
esac
[ "$ALTERNO" = "$PUERTO" ] && ALTERNO=""

# ¿Salen esos puertos del servidor? Un puerto bloqueado por el cortafuegos
# deja el envío colgado hasta que vence el plazo; mejor saberlo ahora.
abierto() { timeout 6 bash -c "</dev/tcp/$HOST/$1" >/dev/null 2>&1; }
echo
echo "Comprobando la salida hacia $HOST…"
for p in $PUERTO $ALTERNO; do
  if abierto "$p"; then echo "  puerto $p: ABIERTO"; else echo "  puerto $p: CERRADO o sin respuesta"; fi
done
if ! abierto "$PUERTO" && [ -n "$ALTERNO" ] && abierto "$ALTERNO"; then
  echo "  El $PUERTO no sale y el $ALTERNO sí: se usará el $ALTERNO como principal."
  t="$PUERTO"; PUERTO="$ALTERNO"; ALTERNO="$t"
elif ! abierto "$PUERTO" && { [ -z "$ALTERNO" ] || ! abierto "$ALTERNO"; }; then
  echo "  ATENCIÓN: ningún puerto sale. Se guarda igual, pero el correo no saldrá hasta que TI"
  echo "  abra la salida hacia $HOST ($(getent hosts "$HOST" | awk '{print $1}' | head -1)) en esos puertos."
fi
echo
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
grep -v -E '^(SMTP_HOST|SMTP_PORT|SMTP_PORT_ALTERNO|SMTP_USER|SMTP_PASSWORD|SMTP_REMITENTE|SMTP_STARTTLS|EMAIL_BACKEND)=' \
  "$ENV" > "$ENV.tmp" || true
{
  printf 'SMTP_HOST=%s\n' "$HOST"
  printf 'SMTP_PORT=%s\n' "$PUERTO"
  [ -n "$ALTERNO" ] && printf 'SMTP_PORT_ALTERNO=%s\n' "$ALTERNO"
  printf 'SMTP_USER=%s\n' "$USUARIO"
  printf 'SMTP_PASSWORD="%s"\n' "$CLAVE"
  printf 'SMTP_REMITENTE="%s"\n' "$REMITENTE"
  # 465 cifra desde el inicio; en los demás (587, 2525) se cifra con
  # STARTTLS si el servidor lo ofrece («auto»): los proveedores que publican
  # esos puertos «sin SSL» lo aceptan igual, y si no, se envía sin él.
  if [ "$PUERTO" = "465" ]; then echo "SMTP_STARTTLS=false"; else echo "SMTP_STARTTLS=auto"; fi
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
sed -E 's/^(SMTP_USER=.{4}).*/\1…/; s/^(SMTP_PASSWORD=).*/\1********/; s/^(JWT_SECRET=).*/\1********/; s/(rrhh_app:)[^@]*@/\1********@/' "$ENV" | sed 's/^/  /'
echo
echo "Para que el sistema use la configuración nueva, reinicie el backend:"
echo "  sudo systemctl restart rrhh-itsanet-api"
echo
echo "Y pruebe el envío:"
echo "  .venv/bin/python despliegue/probar_correo.py su.correo@empresa.com"
