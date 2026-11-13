#!/usr/bin/env bash
# Muestra quién puede entrar al sistema y por dónde: puertos abiertos,
# servicios, usuarios de MySQL y sus permisos. SOLO MIRA: no cambia nada.
#
#     bash despliegue/accesos.sh
#
# Úselo antes de configurar DBeaver (guía en despliegue/DBEAVER.md) y cada vez
# que TI quiera comprobar que la base no quedó expuesta a la red.
set -uo pipefail

if [ "$(id -u)" -eq 0 ]; then SUDO=(); else SUDO=(sudo); fi
t() { printf '\n== %s ==\n' "$1"; }

if ! command -v ss >/dev/null; then
  echo "Falta la orden «ss» (paquete iproute2): no se pueden listar los puertos."
fi

t "Puertos que escuchan en este servidor"
echo "  (0.0.0.0 o * = abierto a la red; 127.0.0.1 = solo dentro del servidor)"
"${SUDO[@]}" ss -ltnp 2>/dev/null | awk 'NR==1 || /:(22|3306|33060|8010|8444|3000|3002|8000|8080|8443)[[:space:]]/' \
  | sed 's/^/  /'

t "Los de este sistema"
for p in 8010 8444 3306; do
  linea=$("${SUDO[@]}" ss -ltn 2>/dev/null | awk -v p=":$p" '$4 ~ p"$" {print $4}' | paste -sd' ')
  case "$p" in
    8010) que="API (debe ser 127.0.0.1)";;
    8444) que="web HTTPS por Apache (abierto a la red interna)";;
    3306) que="MySQL (debe ser 127.0.0.1: se entra por túnel SSH)";;
  esac
  printf '  %-5s %-48s %s\n' "$p" "$que" "${linea:-no escucha}"
done
if "${SUDO[@]}" ss -ltn 2>/dev/null | awk '$4 ~ /:3306$/ {print $4}' | grep -vqE '^(127\.0\.0\.1|\[::1\]):'; then
  echo "  AVISO: MySQL escucha hacia la red. Debería ser solo 127.0.0.1."
fi

t "Servicios"
for s in rrhh-itsanet-api apache2 mysql ssh; do
  printf '  %-18s %s\n' "$s" "$(systemctl is-active "$s" 2>/dev/null || echo desconocido)"
done

t "MySQL: configuración de red"
"${SUDO[@]}" mysql -N -e "
  SELECT CONCAT('  bind_address: ', @@bind_address, '   puerto: ', @@port);
  SELECT CONCAT('  require_secure_transport: ', @@require_secure_transport);" 2>&1

t "MySQL: usuarios con acceso a la base rrhh"
"${SUDO[@]}" mysql -N -e "
  SELECT DISTINCT CONCAT('  ', grantee, '  ', privilege_type)
    FROM information_schema.schema_privileges
   WHERE table_schema = 'rrhh'
   ORDER BY 1;" 2>&1
echo "  (root y los administradores de MySQL también pueden, aunque no salgan aquí)"

t "MySQL: cuentas que pueden entrar desde fuera del servidor"
"${SUDO[@]}" mysql -N -e "
  SELECT CONCAT('  ', user, '@', host)
    FROM mysql.user
   WHERE host NOT IN ('localhost', '127.0.0.1', '::1')
     AND user NOT LIKE 'mysql.%';" 2>&1 | grep . || echo "  ninguna (correcto)"

t "Permisos exactos de las cuentas del sistema"
for cuenta in "'rrhh_app'@'localhost'" "'rrhh_lectura'@'localhost'" "'rrhh_lectura'@'127.0.0.1'" "'rrhh_edicion'@'localhost'" "'rrhh_edicion'@'127.0.0.1'"; do
  if "${SUDO[@]}" mysql -N -e "SHOW GRANTS FOR $cuenta" >/dev/null 2>&1; then
    echo "  $cuenta"
    "${SUDO[@]}" mysql -N -e "SHOW GRANTS FOR $cuenta" | sed 's/^/    /'
  fi
done

t "Últimos ingresos SSH a este servidor"
last -n 8 -w 2>/dev/null | head -8 | sed 's/^/  /'
echo
