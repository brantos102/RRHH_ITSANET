# Registrar personas nuevas por Excel y manuales (13/11/2026)

Trae la migración **0017**. Si las notas `_01` y `_02` todavía no se
aplicaron, este mismo paso aplica todas las migraciones que falten, en orden.

## Qué cambia

- **Registrar personas nuevas** (Administración › Actualización masiva ›
  «Registrar personas nuevas»): para completar el sistema con quienes faltan.
  Se puede subir la **nómina completa**: quien ya está registrado se reconoce
  por la cédula y no se toca. La revisión muestra quién se registraría (con
  el saldo que le quedaría), cuántos ya estaban, los errores por fila y quién
  está en el sistema pero no en el archivo. Nada cambia hasta «Registrar
  personas» con un motivo; queda con folio `CM-AAAA-NNNN`.
- El historial de cargas distingue «Altas» de «Actualización».
- El asistente explica que el cargo y el área los administra Talento Humano.
- **Manuales** en `manuales/`: el de usuario (para publicar en GitHub Pages) y
  el técnico para TI. No requieren nada en el servidor.

## Cómo aplicarla

En la terminal de VS Code conectada al servidor (`enicolalde@apps`):

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

Después, en el navegador: **Ctrl+F5** una vez.

### Forma larga (uno por uno)

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
sudo mysqldump --single-transaction --routines --triggers rrhh > ~/bryan/rrhh_datos/respaldos/rrhh_$(date +%F_%H%M).sql
```
```bash
git pull
```
```bash
sudo env MYSQL_URL="mysql://root@localhost/rrhh?unix_socket=/var/run/mysqld/mysqld.sock" .venv/bin/python mysql/migrar.py --aplicar
```
```bash
bash despliegue/instalar.sh --si
```

## Completar la base con quienes faltan (guía para Talento Humano)

1. **Respaldo.** `bash despliegue/actualizar.sh` ya deja uno. Si pasa tiempo
   entre la actualización y la carga, haga otro (COMANDOS.md, sección 5).
2. **Prepare la nómina vigente en Excel** (en Windows, en
   `C:\Users\IMORETA\Documents\AP\MOD_RRHH`; nunca en el repositorio). Por
   persona activa hoy:
   - obligatorio: **cédula**, **apellidos y nombres**, **fecha de ingreso**;
   - muy recomendado: **días de vacaciones disponibles** (el saldo conciliado
     a hoy) y **correo personal**;
   - opcional: celular, cargo, área, cédula del jefe, ciudad de trabajo,
     bodega, centro de costo, cliente, tipo y fin de contrato, fecha de
     nacimiento.
3. En el sistema: **Administración › Actualización masiva › Registrar personas
   nuevas › Descargar plantilla de personas nuevas**. Pegue la nómina en la
   hoja «Personas nuevas» respetando las columnas (la hoja «Cómo usarla»
   explica cada una). No hace falta llevar el archivo al servidor: se sube
   desde el navegador.
4. **Súbala** con «Subir archivo» y revise:
   - **errores** (en rojo): cédula inválida, fecha de ingreso futura, correo
     repetido o ya usado, saldo mayor que lo devengado, jefe que no existe.
     Esas filas no se registran;
   - **avisos** (en ámbar): sin correo, sin ciudad (queda en la sede de
     Quito), cargo o área nuevos, **saldo calculado** porque no puso días
     disponibles;
   - **«…están en el sistema y no en su archivo»**: si subió la nómina
     completa, son personas que quizá ya salieron.
5. Corrija en el Excel lo que haga falta y vuelva a subirlo. Descarte la
   revisión anterior («Descartar») para que el historial quede limpio.
6. Cuando la revisión esté bien, escriba el motivo (por ejemplo, «Completar
   la nómina vigente de noviembre») y pulse **«Registrar personas»**. Entran
   todas las de la carga, o ninguna.
7. **Después:**
   - registre el correo de quien no lo tenga (Administración › Usuarios):
     sin correo no puede entrar;
   - asigne las jefaturas (Administración › Jefaturas);
   - revise «Depuración › No pueden entrar»;
   - dé de baja, con su causa, a quien figure en el sistema y ya no trabaje
     (Administración › Usuarios).

> **Importante:** sin «días disponibles», el saldo se calcula desde la fecha
> de ingreso como si la persona no hubiera gozado nada. Para alguien con años
> en la empresa casi nunca es lo correcto.

## Qué probar

1. Descargar la plantilla de personas nuevas y subirla con 2 o 3 filas
   (una de alguien que ya está, para ver que se reconoce).
2. Comprobar el saldo que muestra la revisión contra el de Talento Humano.
3. Registrar y buscar a la persona en Colaboradores: saldo, jefe, sede.
4. Ver la carga en «Cargas realizadas» con la etiqueta «Altas».

## Si algo sale mal

- Ver el registro: `sudo journalctl -u rrhh-itsanet-api -n 50 --no-pager`
- Volver a la base anterior: `despliegue/COMANDOS.md`, sección 5, con el
  respaldo `rrhh_antes_de_actualizar_…sql` que dejó el script.
