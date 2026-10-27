# Despliegue en el servidor de la empresa (192.168.4.94)

Sistema de Permisos, Vacaciones y Control de Garita sobre MySQL 8.0, publicado
por Apache en su propio puerto. Todo vive en la carpeta del responsable
(`~/bryan/`) y no toca nada de lo que ya funciona en el servidor.

## Qué ocupa en el servidor

| Pieza | Dónde | Notas |
|---|---|---|
| Código | `~/bryan/RRHH_ITSANET` | clon del repositorio |
| Datos y adjuntos | `~/bryan/rrhh_datos/` | permisos 700: certificados médicos |
| Base de datos | MySQL, base `rrhh`, usuario `rrhh_app` | solo `SELECT, INSERT, UPDATE, DELETE, EXECUTE` sobre `rrhh.*` |
| Backend | `rrhh-itsanet-api.service`, `127.0.0.1:8010` | no accesible desde fuera |
| Tareas | `rrhh-itsanet-tareas.timer` (diaria 06:50), `rrhh-itsanet-retencion.timer` (mensual) | reemplazan a pg_cron |
| Web | `/var/www/rrhh-itsanet/` (copia de `frontend/`) | |
| Apache | `sites-available/rrhh-itsanet.conf`, **puerto 8444 HTTPS** | `Listen` propio; `/api` → 8010 |

**No se toca:** IV ITSANET (base `iv_itsanet`, carpeta `~/bryan/IV_ITSANET`),
los sitios `itsanet-app-8443.conf` e `itsanet-data-sync*.conf`, ni los puertos
3000, 3002, 8000, 8080 y 8443. Apache solo se recarga (sin cortar conexiones) y
solo si `apache2ctl configtest` da «Syntax OK».

## Primera instalación

En la terminal del servidor (VS Code Remote-SSH), con la VPN conectada:

```bash
cd ~/bryan/RRHH_ITSANET
git pull

# 1. Base y usuario de la aplicación (si no se hizo antes). Guarda la clave en servidor/.env
bash despliegue/crear_base.sh

# 2. Estructura de la base: primero mirar, después aplicar (como root, por el socket)
sudo env MYSQL_URL="mysql://root@localhost/rrhh?unix_socket=/var/run/mysqld/mysqld.sock" .venv/bin/python mysql/migrar.py
sudo env MYSQL_URL="mysql://root@localhost/rrhh?unix_socket=/var/run/mysqld/mysqld.sock" .venv/bin/python mysql/migrar.py --aplicar

# 3. Correo (si no se hizo antes) y prueba
bash despliegue/configurar_correo.sh
.venv/bin/python despliegue/probar_correo.py su.correo@itsanet.com

# 4. Publicar: servicio, tareas, web y sitio de Apache
bash despliegue/instalar.sh
```

`instalar.sh` muestra todo lo que va a hacer y pregunta antes. Al final indica
la dirección: **https://192.168.4.94:8444**.

### Certificado

La cámara de garita solo funciona con HTTPS. El instalador reutiliza el
certificado que ya usa otro sitio de este Apache (solo lee la ruta). Si TI
prefiere otro:

```bash
CERT=/ruta/certificado.pem LLAVE=/ruta/llave.key bash despliegue/instalar.sh
```

## Cargar personas para probar

Las personas se cargan desde un CSV que se prepara **en el servidor, fuera del
repositorio** (son datos personales; `*.csv` está excluido de git). Plantilla:
`despliegue/personas_plantilla.csv`.

```bash
cp despliegue/personas_plantilla.csv ~/bryan/rrhh_datos/personas.csv
nano ~/bryan/rrhh_datos/personas.csv          # una fila por persona

.venv/bin/python mysql/cargar_personas.py ~/bryan/rrhh_datos/personas.csv            # revisa, no escribe
.venv/bin/python mysql/cargar_personas.py ~/bryan/rrhh_datos/personas.csv --aplicar  # carga
```

Para la prueba de correos y QR bastan cuatro personas con buzones reales: un
empleado (con `jefe_cedula` = la del jefe), su jefe, alguien de Talento Humano
y un guardia. Volver a cargar el mismo archivo **actualiza** (no duplica).
Para empezar de cero:

```bash
.venv/bin/python mysql/cargar_personas.py ~/bryan/rrhh_datos/personas.csv --quitar --aplicar
```

`--quitar` borra a esas personas con todo su expediente: es para la fase de
pruebas. Con el sistema en uso, a nadie se lo borra; se lo da de baja desde
Administración.

El historial de vacaciones de la hoja de Talento Humano (empareja por nombre
exacto, no toca saldos):

```bash
.venv/bin/python scripts/cargar_historial.py ~/bryan/rrhh_datos/REGISTRO.xlsx            # revisa
.venv/bin/python scripts/cargar_historial.py ~/bryan/rrhh_datos/REGISTRO.xlsx --aplicar  # carga
```

## Después de cada `git pull`

```bash
cd ~/bryan/RRHH_ITSANET && git pull
sudo env MYSQL_URL="mysql://root@localhost/rrhh?unix_socket=/var/run/mysqld/mysqld.sock" .venv/bin/python mysql/migrar.py --aplicar
bash despliegue/instalar.sh --si
```

## Operación diaria

| Para | Comando |
|---|---|
| Ver el registro del backend | `sudo journalctl -u rrhh-itsanet-api -f` |
| Estado del backend | `systemctl status rrhh-itsanet-api` |
| Próximas tareas | `systemctl list-timers 'rrhh-itsanet-*'` |
| Correr la tarea diaria ya | `sudo systemctl start rrhh-itsanet-tareas.service` |
| Saldos: explicar / recalcular | `.venv/bin/python mysql/saldos.py explicar --cedula …` |
| Depurar datos desde DBeaver | `mysql/depuracion/00_LEER_PRIMERO.sql` |
| Respaldo | `sudo mysqldump --single-transaction --routines --triggers rrhh > ~/bryan/rrhh_datos/respaldos/rrhh_$(date +%F_%H%M).sql` |

## Retirar el sistema (si hiciera falta)

```bash
sudo systemctl disable --now rrhh-itsanet-api rrhh-itsanet-tareas.timer rrhh-itsanet-retencion.timer
sudo a2dissite rrhh-itsanet && sudo systemctl reload apache2
```

Eso deja Apache y el resto del servidor exactamente como estaban. La base
`rrhh` y la carpeta `~/bryan/rrhh_datos` no se borran solas: son datos.

## Seguridad pendiente para TI

- **Rotar la clave SMTP**: se compartió por chat durante la configuración.
  Después, `bash despliegue/configurar_correo.sh` con la nueva.
- Si el cortafuegos está activo, abrir solo el 8444 (`instalar.sh` lo ofrece).
