#!/usr/bin/env bash
# Diagnóstico del servidor antes de instalar el sistema de Talento Humano.
#
#     bash despliegue/diagnostico.sh
#
# SOLO LEE. No instala, no reinicia ni cambia nada. Tampoco muestra claves:
# es seguro copiar su salida para revisarla.
#
# Pide la clave de sudo una vez, para leer la configuración de MySQL y qué
# programa ocupa cada puerto.

set -u
t() { printf '\n==== %s ====\n' "$1"; }

t "Sistema"
. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME"
uname -m
timedatectl 2>/dev/null | grep -i "time zone" || date +"zona: %Z %z"

t "Recursos"
df -h / /var 2>/dev/null | sort -u
free -h | head -2

t "Permisos"
id
sudo -v && echo "sudo: disponible" || echo "sudo: NO disponible"

t "Python"
for p in python3 python3.11 python3.12 python3.13; do
  command -v "$p" >/dev/null && echo "$p -> $($p --version 2>&1)"
done
python3 -c "import venv, ensurepip" 2>/dev/null && echo "venv: disponible" || echo "venv: falta (paquete python3-venv)"
git --version 2>/dev/null || echo "git: no instalado"

t "MySQL"
mysql --version 2>/dev/null || echo "cliente mysql: no instalado"
for s in mysql mysqld mariadb; do
  systemctl is-active --quiet "$s" 2>/dev/null && echo "servicio $s: activo"
done
sudo mysql -N -e "
  SELECT CONCAT('version: ', VERSION());
  SELECT CONCAT('sql_mode: ', @@GLOBAL.sql_mode);
  SELECT CONCAT('charset: ', @@character_set_server, ' / ', @@collation_server);
  SELECT CONCAT('bind_address: ', @@bind_address, '  puerto: ', @@port);
  SELECT CONCAT('log_bin: ', @@log_bin, '  trust_function_creators: ', @@log_bin_trust_function_creators);
  SELECT CONCAT('time_zone: ', @@GLOBAL.time_zone);
  SELECT CONCAT('bases existentes: ', COUNT(*)) FROM information_schema.schemata
   WHERE schema_name NOT IN ('mysql','sys','information_schema','performance_schema');
  SELECT CONCAT('ya existe una base rrhh*: ', schema_name) FROM information_schema.schemata
   WHERE schema_name LIKE 'rrhh%';
" 2>&1 | sed 's/^/  /'

t "Apache"
(apache2 -v 2>/dev/null || httpd -v 2>/dev/null) | head -1 || echo "apache: no instalado"
for s in apache2 httpd; do
  systemctl is-active --quiet "$s" 2>/dev/null && echo "servicio $s: activo"
done
(sudo apachectl -M 2>/dev/null || sudo httpd -M 2>/dev/null) | grep -E "proxy_module|proxy_http|ssl_module|headers_module|rewrite_module" | sed 's/^/  /'
ls /etc/apache2/sites-enabled/ 2>/dev/null | sed 's/^/  sitio habilitado: /'
ls /etc/httpd/conf.d/ 2>/dev/null | sed 's/^/  conf.d: /'

t "Puertos en uso (TCP)"
sudo ss -ltnp 2>/dev/null | awk 'NR>1 {print "  " $4 "  " $6}' | sort -u

t "Salida a internet"
for u in https://github.com https://pypi.org https://supabase.com; do
  printf '  %-24s ' "$u"
  curl -sS -o /dev/null -m 8 -w '%{http_code}\n' "$u" 2>&1 | tail -1
done

t "Fin"
echo "Copie todo lo de arriba y compártalo. No contiene claves."
