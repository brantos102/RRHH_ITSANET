# Hoja de comandos — RRHH ITSANET

Todos van en la **terminal de VS Code conectada al servidor** (la línea empieza
con `enicolalde@apps`), salvo los marcados como *PowerShell*. Lo que lleva `sudo`
pide la clave de `enicolalde` (no se ve al escribirla).

Escríbalos **de uno en uno**. Los que dicen «revisa» no cambian nada; los que
llevan `--aplicar` sí escriben.

---

## 1. Entrar y actualizar

```bash
cd ~/bryan/RRHH_ITSANET                       # ir al sistema
git pull                                      # traer la última versión del repositorio
bash despliegue/instalar.sh --si              # aplicarla: reinicia el backend y copia la web
```

Después de `git pull`, si el mensaje menciona archivos de `mysql/migraciones/`,
aplique también la estructura nueva de la base:

```bash
sudo env MYSQL_URL="mysql://root@localhost/rrhh?unix_socket=/var/run/mysqld/mysqld.sock" .venv/bin/python mysql/migrar.py            # revisa
sudo env MYSQL_URL="mysql://root@localhost/rrhh?unix_socket=/var/run/mysqld/mysqld.sock" .venv/bin/python mysql/migrar.py --aplicar  # aplica
```

Dirección del sistema: **https://192.168.4.94:8444**

## 2. ¿Está funcionando?

```bash
systemctl is-active rrhh-itsanet-api                  # debe decir: active
curl -k https://127.0.0.1:8444/api/salud              # debe decir: "estado":"ok","base_datos":"conectada"
systemctl list-timers 'rrhh-itsanet-*'                # próximas tareas programadas
```

## 3. Ver qué pasó (registro) — solo lee, no cambia nada

```bash
sudo journalctl -u rrhh-itsanet-api --since "10 min ago" --no-pager | tail -40   # últimos 10 minutos
sudo journalctl -u rrhh-itsanet-api -f                                            # en vivo (salir: Ctrl + C)
sudo tail -40 /var/log/apache2/rrhh-itsanet-error.log                              # errores de Apache de este sitio
```

## 4. Reiniciar o detener el backend

```bash
sudo systemctl restart rrhh-itsanet-api       # reiniciar
sudo systemctl status rrhh-itsanet-api        # estado detallado (salir: q)
sudo systemctl stop rrhh-itsanet-api          # detener (la web queda sin datos)
sudo systemctl start rrhh-itsanet-api         # volver a arrancar
```

## 5. Respaldo de la base — antes de cualquier carga o cambio grande

```bash
mkdir -p ~/bryan/rrhh_datos/respaldos
sudo mysqldump --single-transaction --routines --triggers rrhh > ~/bryan/rrhh_datos/respaldos/rrhh_$(date +%F_%H%M).sql
ls -lh ~/bryan/rrhh_datos/respaldos/          # comprobar que pesa más de 0
```

**Restaurar un respaldo** (reemplaza TODO lo actual por lo del respaldo; solo
con autorización):

```bash
sudo systemctl stop rrhh-itsanet-api
sudo mysql rrhh < ~/bryan/rrhh_datos/respaldos/ARCHIVO.sql
sudo systemctl start rrhh-itsanet-api
```

## 6. Llevar un archivo de Windows al servidor

Arrastrarlo desde `C:\Users\IMORETA\Documents\AP\MOD_RRHH` y soltarlo sobre
`rrhh_datos` en el Explorer de VS Code. Comprobar:

```bash
ls -l ~/bryan/rrhh_datos/
```

*PowerShell* (solo si arrastrar no funciona; la de 64 bits, no la «(x86)»):

```powershell
scp "C:\Users\IMORETA\Documents\AP\MOD_RRHH\ARCHIVO.xlsx" enicolalde@192.168.4.94:bryan/rrhh_datos/
```

## 7. Cargar el registro de vacaciones (Google Sheets → Excel)

Solo **antes de la publicación**. Después, la hoja queda de solo lectura y no se
vuelve a cargar (borraría los ajustes hechos en el aplicativo).

```bash
cd ~/bryan/RRHH_ITSANET
X=~/bryan/rrhh_datos/NOMBRE_DEL_EXCEL.xlsx
.venv/bin/python mysql/cargar_registro.py "$X"                 # revisa
.venv/bin/python mysql/cargar_registro.py "$X" --aplicar       # personas activas y saldos
.venv/bin/python scripts/cargar_historial.py "$X" --aplicar    # historial de vacaciones
```

Deshacer todo lo cargado de ese Excel:

```bash
.venv/bin/python mysql/cargar_registro.py "$X" --quitar --aplicar
```

## 8. Dar acceso: correo, rol y jefe

Completar el CSV (en Excel: «CSV UTF-8», separado por `;` o `,`) con las
columnas `cedula;nombre;email;rol;fecha_ingreso;jefe_cedula;saldo;cargo;departamento;ciudad`.
Rol: `empleado`, `jefe`, `rrhh`, `guardia` o `admin`. Con `saldo` vacío se
conserva el saldo cargado; las filas con el correo vacío se omiten.

```bash
.venv/bin/python mysql/cargar_personas.py ~/bryan/rrhh_datos/ARCHIVO.csv            # revisa
.venv/bin/python mysql/cargar_personas.py ~/bryan/rrhh_datos/ARCHIVO.csv --aplicar  # carga
.venv/bin/python mysql/cargar_personas.py ~/bryan/rrhh_datos/ARCHIVO.csv --quitar --aplicar   # borra a esas personas (solo pruebas)
```

## 9. Saldos de una persona

```bash
.venv/bin/python mysql/saldos.py explicar   --cedula 0000000000          # cómo se llega a su saldo
.venv/bin/python mysql/saldos.py recalcular                               # volver a sumar toda la planilla
.venv/bin/python mysql/saldos.py regenerar  --cedula 0000000000          # tras cambiar su fecha de ingreso (revisa)
.venv/bin/python mysql/saldos.py regenerar  --cedula 0000000000 --aplicar
.venv/bin/python mysql/saldos.py cargar     --cedula 0000000000 --saldo 8.75           # fijar saldo (revisa)
.venv/bin/python mysql/saldos.py cargar     --cedula 0000000000 --saldo 8.75 --aplicar
```

## 10. Tareas programadas a mano

```bash
sudo systemctl start rrhh-itsanet-tareas.service      # avisos diarios ahora (normalmente 06:50)
.venv/bin/python mysql/tareas.py diaria               # lo mismo, viendo el resultado
```

## 11. Correo

```bash
.venv/bin/python despliegue/probar_correo.py su.correo@itsanet.com    # envía un correo de prueba con un QR
bash despliegue/configurar_correo.sh                                  # cambiar servidor, usuario o clave SMTP
```

## 12. Consultas rápidas a la base (solo lectura)

```bash
sudo mysql rrhh -e "SELECT rol, COUNT(*) FROM users WHERE activo GROUP BY rol"
sudo mysql rrhh -e "SELECT COUNT(*) AS sin_correo FROM users WHERE activo AND email IS NULL"
sudo mysql rrhh -e "SELECT estado, COUNT(*) FROM requests GROUP BY estado"
```

Para depurar datos con DBeaver: `mysql/depuracion/00_LEER_PRIMERO.sql`.

## 13. Retirar el sistema (deja el servidor como estaba)

```bash
sudo systemctl disable --now rrhh-itsanet-api rrhh-itsanet-tareas.timer rrhh-itsanet-retencion.timer
sudo a2dissite rrhh-itsanet && sudo systemctl reload apache2
```

La base `rrhh` y `~/bryan/rrhh_datos` no se borran: son datos.
