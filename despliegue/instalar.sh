#!/usr/bin/env bash
# Publica el sistema en este servidor, sin tocar lo que ya está en producción.
#
#     bash despliegue/instalar.sh              # muestra lo que haría y pregunta
#     bash despliegue/instalar.sh --si         # sin preguntar (para repetirlo tras un git pull)
#
# Qué instala, y nada más:
#
#   · rrhh-itsanet-api.service      el backend (uvicorn) en 127.0.0.1:8010,
#                                   solo accesible desde el propio servidor.
#   · rrhh-itsanet-tareas.timer     la tarea diaria (06:50, hora de Ecuador)
#   · rrhh-itsanet-retencion.timer  la depuración mensual de bitácoras
#   · /var/www/rrhh-itsanet/        una COPIA de frontend/ para que Apache la sirva
#   · /etc/apache2/sites-available/rrhh-itsanet.conf
#                                   un sitio PROPIO en el puerto 8444 (HTTPS),
#                                   con su propio «Listen». /api pasa al backend.
#
# Qué NO toca: los sitios de Apache que ya existen (itsanet-app-8443.conf,
# itsanet-data-sync*.conf…), la configuración general de Apache, la base
# iv_itsanet ni ninguna otra, ni los puertos 3000, 3002, 8000, 8080 y 8443.
#
# Apache solo se RECARGA (graceful: no corta conexiones abiertas) y solo si
# `apache2ctl configtest` da «Syntax OK». Si el sitio nuevo tuviera un error,
# se desactiva y Apache queda exactamente como estaba.
#
# Se puede volver a ejecutar cuantas veces haga falta: cada paso comprueba lo
# que ya está hecho.

set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
ENV="$RAIZ/servidor/.env"
USUARIO="$(stat -c %U "$RAIZ")"
GRUPO="$(id -gn "$USUARIO")"
DATOS="$(dirname "$RAIZ")/rrhh_datos"          # ~/bryan/rrhh_datos
PUERTO_API=8010
PUERTO_WEB=8444
WEB=/var/www/rrhh-itsanet
SITIO=/etc/apache2/sites-available/rrhh-itsanet.conf
SERVICIO=rrhh-itsanet-api
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
puerto_ocupado() { ss -ltnH "( sport = :$1 )" | grep -q .; }

if [ "$(id -u)" = 0 ]; then
  error "Ejecútelo con su usuario ($USUARIO), no con sudo: el script pide sudo solo donde hace falta."
fi

# ---------------------------------------------------------------- 1. comprobar
paso "1. Comprobaciones (no cambia nada)"
[ -x "$RAIZ/.venv/bin/python" ] || error "Falta el entorno de Python. Créelo con:
    python3 -m venv $RAIZ/.venv && $RAIZ/.venv/bin/pip install -r $RAIZ/servidor/requirements.txt"
"$RAIZ/.venv/bin/pip" install -q -r "$RAIZ/servidor/requirements.txt"
echo "  Dependencias de Python al día."

[ -f "$ENV" ] || error "Falta servidor/.env. Ejecute primero: bash despliegue/crear_base.sh"
for clave in MYSQL_URL JWT_SECRET SMTP_HOST SMTP_PASSWORD; do
  grep -q "^$clave=" "$ENV" || error "servidor/.env no tiene $clave. Vea despliegue/crear_base.sh y configurar_correo.sh."
done
echo "  servidor/.env tiene la base, el secreto de sesiones y el correo."

if puerto_ocupado "$PUERTO_API" && ! systemctl is-active --quiet "$SERVICIO"; then
  error "El puerto $PUERTO_API está ocupado por otro programa. No se toca: avise para elegir otro."
fi
if puerto_ocupado "$PUERTO_WEB" && [ ! -f "$SITIO" ]; then
  error "El puerto $PUERTO_WEB está ocupado por otro sitio. No se toca: avise para elegir otro."
fi
echo "  Puertos $PUERTO_API (backend, interno) y $PUERTO_WEB (web) libres o ya nuestros."

IP="$(hostname -I | awk '{print $1}')"
# El certificado: el que se indique (CERT=… LLAVE=… bash instalar.sh) o, si
# no, el mismo que ya usa otro sitio de este Apache. De ese sitio solo se LEE
# la ruta; no se modifica.
CERT="${CERT:-}"; LLAVE="${LLAVE:-}"; CADENA="${CADENA:-}"
[ -n "$CERT" ] && [ -n "$LLAVE" ] && echo "  Certificado indicado: $CERT"
for conf in /etc/apache2/sites-enabled/*.conf; do
  [ -n "$CERT" ] && [ -n "$LLAVE" ] && break
  [ "$conf" = "/etc/apache2/sites-enabled/rrhh-itsanet.conf" ] && continue
  c="$(awk 'tolower($1)=="sslcertificatefile"{print $2; exit}' "$conf" 2>/dev/null || true)"
  k="$(awk 'tolower($1)=="sslcertificatekeyfile"{print $2; exit}' "$conf" 2>/dev/null || true)"
  if [ -n "$c" ] && [ -n "$k" ]; then
    CERT="$c"; LLAVE="$k"
    CADENA="$(awk 'tolower($1)=="sslcertificatechainfile"{print $2; exit}' "$conf" 2>/dev/null || true)"
    echo "  Certificado: el de $(basename "$conf") ($CERT)"
    break
  fi
done
if [ -z "$CERT" ] || [ -z "$LLAVE" ]; then
  error "No se encontró un certificado en los sitios de Apache. Sin HTTPS la cámara de
  garita no funciona (el navegador la bloquea). Pida a TI la ruta del certificado y de
  su llave, y ejecute de nuevo con:
      CERT=/ruta/certificado.pem LLAVE=/ruta/llave.key bash $0"
fi
sudo test -r "$CERT" && sudo test -r "$LLAVE" || error "No se puede leer $CERT o $LLAVE."

MODULOS_FALTAN=()
for m in proxy proxy_http headers ssl; do
  apache2ctl -M 2>/dev/null | grep -q " ${m}_module" || MODULOS_FALTAN+=("$m")
done

URL="https://$IP:$PUERTO_WEB"
cat <<EOF

  Se va a publicar en:   ${VERDE}$URL${FIN}
  Backend interno:       127.0.0.1:$PUERTO_API  (servicio $SERVICIO, usuario $USUARIO)
  Datos y adjuntos:      $DATOS
  Copia de la web:       $WEB
  Sitio de Apache:       $SITIO  (Listen $PUERTO_WEB propio)
EOF
[ ${#MODULOS_FALTAN[@]} -gt 0 ] && aviso "  Módulos de Apache que hay que habilitar: ${MODULOS_FALTAN[*]}
  (se suman a los existentes; no cambian los otros sitios)"
seguir "¿Continuar?" || { echo "No se cambió nada."; exit 0; }

# ------------------------------------------------------------ 2. datos y .env
paso "2. Carpeta de datos y ajustes"
install -d -m 700 "$DATOS" "$DATOS/adjuntos" "$DATOS/respaldos"
echo "  $DATOS (solo $USUARIO puede leerla: ahí van certificados médicos)"

poner() {  # poner CLAVE valor — reemplaza la línea si existe, la agrega si no
  if grep -q "^$1=" "$ENV"; then
    sed -i "s|^$1=.*|$1=$2|" "$ENV"
  else
    printf '%s=%s\n' "$1" "$2" >> "$ENV"
  fi
}
poner ENTORNO produccion
poner APP_URL "$URL"
poner CORS_ORIGINS "$URL"
poner ADJUNTOS_DIR "$DATOS/adjuntos"
chmod 600 "$ENV"
echo "  servidor/.env: ENTORNO=produccion, APP_URL=$URL (los enlaces de los correos apuntan aquí)"

# -------------------------------------------------------------- 3. servicios
paso "3. Servicio del backend y tareas programadas"
sudo tee /etc/systemd/system/$SERVICIO.service >/dev/null <<EOF
[Unit]
Description=RRHH ITSANET — API de permisos y vacaciones
After=network-online.target mysql.service
Wants=network-online.target

[Service]
User=$USUARIO
Group=$GRUPO
WorkingDirectory=$RAIZ/servidor
ExecStart=$RAIZ/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PUERTO_API --workers 2 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
UMask=0077

[Install]
WantedBy=multi-user.target
EOF

tarea() {  # tarea nombre "descripción" "orden" "OnCalendar"
  sudo tee /etc/systemd/system/rrhh-itsanet-$1.service >/dev/null <<EOF
[Unit]
Description=RRHH ITSANET — $2
After=mysql.service

[Service]
Type=oneshot
User=$USUARIO
Group=$GRUPO
WorkingDirectory=$RAIZ
ExecStart=$RAIZ/.venv/bin/python $RAIZ/mysql/tareas.py $3
EOF
  sudo tee /etc/systemd/system/rrhh-itsanet-$1.timer >/dev/null <<EOF
[Unit]
Description=RRHH ITSANET — $2 (programada)

[Timer]
OnCalendar=$4
Persistent=true

[Install]
WantedBy=timers.target
EOF
}
tarea tareas    "avisos diarios de vacaciones"     diaria    "*-*-* 06:50:00 America/Guayaquil"
tarea retencion "depuración mensual de bitácoras"  retencion "*-*-01 05:30:00 America/Guayaquil"

sudo systemctl daemon-reload
sudo systemctl enable --now rrhh-itsanet-tareas.timer rrhh-itsanet-retencion.timer >/dev/null
sudo systemctl enable "$SERVICIO" >/dev/null
sudo systemctl restart "$SERVICIO"
for _ in $(seq 1 20); do
  curl -fsS "http://127.0.0.1:$PUERTO_API/salud" >/dev/null 2>&1 && break
  sleep 1
done
if ! curl -fsS "http://127.0.0.1:$PUERTO_API/salud"; then
  echo
  sudo journalctl -u "$SERVICIO" -n 30 --no-pager
  error "El backend no responde. Arriba está su registro."
fi
echo
echo "  Backend en marcha y conectado a la base."

# ---------------------------------------------------------------- 4. la web
paso "4. Copia de la web para Apache"
sudo install -d -m 755 "$WEB"
if command -v rsync >/dev/null; then
  sudo rsync -a --delete --exclude 'tests/' --exclude '*.ejemplo' --exclude 'README.md' --exclude 'config.local.js' \
    "$RAIZ/frontend/" "${WEB:?}/"
else
  # ${WEB:?} detiene el script si la variable llegara vacía: nunca se borra
  # fuera de la carpeta de la web.
  sudo find "${WEB:?}" -mindepth 1 -delete
  sudo cp -a "$RAIZ/frontend/." "${WEB:?}/"
  sudo rm -rf "${WEB:?}/tests" "${WEB:?}"/*.ejemplo "${WEB:?}/README.md" "${WEB:?}/config.local.js"
fi
# La web habla con el backend por /api, en el mismo sitio: sin CORS y sin
# exponer el puerto interno.
printf 'Object.assign(window.RRHH_CONFIG, { API: "/api" });\n' | sudo tee "$WEB/config.local.js" >/dev/null
sudo chown -R root:root "$WEB"
sudo find "$WEB" -type d -exec chmod 755 {} + ; sudo find "$WEB" -type f -exec chmod 644 {} +
echo "  $WEB actualizado desde frontend/"

# ---------------------------------------------------------------- 5. Apache
paso "5. Sitio propio de Apache en el puerto $PUERTO_WEB"
if [ ${#MODULOS_FALTAN[@]} -gt 0 ]; then
  sudo a2enmod -q "${MODULOS_FALTAN[@]}"
fi
NUEVO="$(mktemp)"
cat > "$NUEVO" <<EOF
# RRHH ITSANET — permisos, vacaciones y garita. Sitio propio: no comparte
# puerto ni configuración con los demás. Lo genera despliegue/instalar.sh.
Listen $PUERTO_WEB

<VirtualHost *:$PUERTO_WEB>
    ServerName $IP
    DocumentRoot $WEB

    SSLEngine on
    SSLCertificateFile $CERT
    SSLCertificateKeyFile $LLAVE
$( [ -n "$CADENA" ] && echo "    SSLCertificateChainFile $CADENA" )

    <Directory $WEB>
        Options -Indexes
        AllowOverride None
        Require all granted
    </Directory>

    # La API, por el mismo sitio. La IP real del colaborador la pone Apache:
    # se descarta la que mande el navegador, que podría inventarla.
    RequestHeader unset X-Forwarded-For early
    ProxyPreserveHost On
    ProxyPass        /api/ http://127.0.0.1:$PUERTO_API/ timeout=60
    ProxyPassReverse /api/ http://127.0.0.1:$PUERTO_API/
    RequestHeader set X-Forwarded-Proto "https"

    # Adjuntos de hasta 10 MB y un poco de margen.
    LimitRequestBody 12582912

    Header always set X-Content-Type-Options "nosniff"
    Header always set Referrer-Policy "same-origin"
    Header always set Strict-Transport-Security "max-age=31536000"

    ErrorLog \${APACHE_LOG_DIR}/rrhh-itsanet-error.log
    CustomLog \${APACHE_LOG_DIR}/rrhh-itsanet-acceso.log combined
</VirtualHost>
EOF
ANTERIOR=""
[ -f "$SITIO" ] && ANTERIOR="$(mktemp)" && sudo cp "$SITIO" "$ANTERIOR"
sudo install -m 644 "$NUEVO" "$SITIO"
rm -f "$NUEVO"
sudo a2ensite -q rrhh-itsanet >/dev/null
PRUEBA="$(sudo apache2ctl configtest 2>&1 || true)"
echo "$PRUEBA" | sed 's/^/  /'
if ! grep -q "Syntax OK" <<<"$PRUEBA"; then
  aviso "La configuración no pasó la prueba. Se deshace y Apache queda como estaba."
  if [ -n "$ANTERIOR" ]; then sudo install -m 644 "$ANTERIOR" "$SITIO"; else sudo a2dissite -q rrhh-itsanet; sudo rm -f "$SITIO"; fi
  error "No se recargó Apache."
fi
sudo systemctl reload apache2
echo "  Apache recargado (sin cortar las conexiones de los otros sitios)."

# ------------------------------------------------------------- 6. cortafuegos
if command -v ufw >/dev/null && sudo ufw status | grep -q "Status: active"; then
  if ! sudo ufw status | grep -qE "^$PUERTO_WEB(/tcp)? +ALLOW"; then
    paso "6. Cortafuegos"
    if seguir "El cortafuegos está activo y no deja pasar el $PUERTO_WEB. ¿Abrirlo (solo ese puerto)?"; then
      sudo ufw allow "$PUERTO_WEB/tcp" comment "RRHH ITSANET" >/dev/null
      echo "  Puerto $PUERTO_WEB abierto."
    else
      aviso "  Sin abrirlo, desde otros equipos no se llega. Comando:  sudo ufw allow $PUERTO_WEB/tcp"
    fi
  fi
fi

# -------------------------------------------------------------- 7. comprobar
paso "7. Comprobación final"
curl -kfsS "https://127.0.0.1:$PUERTO_WEB/api/salud" && echo
curl -kfsS -o /dev/null -w "  Página de inicio: HTTP %{http_code}\n" "https://127.0.0.1:$PUERTO_WEB/"
cat <<EOF

${VERDE}Listo.${FIN} Abra ${VERDE}$URL${FIN} desde un equipo de la red (con la VPN).
El navegador avisará del certificado si es interno: acéptelo una vez.

  Ver el registro del backend:   sudo journalctl -u $SERVICIO -f
  Reiniciarlo tras un git pull:  bash despliegue/instalar.sh --si
  Próximas tareas programadas:   systemctl list-timers 'rrhh-itsanet-*'
EOF
