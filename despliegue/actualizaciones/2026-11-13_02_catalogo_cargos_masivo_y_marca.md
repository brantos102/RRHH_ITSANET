# Cargos y áreas, actualización masiva, contactos y marca oficial (13/11/2026)

Trae la migración **0016**. Si la nota `2026-11-13_01` todavía no se aplicó,
no importa: `migrar.py` aplica todas las que falten, en orden.

## Qué cambia

- **Catálogo oficial de áreas y cargos** (Administración › Cargos y áreas).
  Se arma solo con los cargos y áreas que ya están en las fichas. Desde ahí
  Talento Humano agrega, renombra, **unifica** (por ejemplo «BODEGA» y
  «Bodega Norte» → «Bodega») y desactiva. Renombrar o unificar cambia también
  las fichas de las personas, no solo la lista.
- **Primer ingreso:** si la persona no tiene cargo o área registrados, los
  elige de la lista del catálogo (o escribe «No está en la lista…»). Talento
  Humano lo confirma. Si ya constan, no se le preguntan.
- **Desde entonces, el cargo y el área solo los cambia Talento Humano.** En
  «Mi ficha» se ven, pero no se editan ni se piden.
- **Actualización masiva por Excel** (Administración › Actualización masiva):
  se descarga la plantilla con los datos actuales (todos, un área o una sede),
  se corrige en Excel, se sube y el sistema muestra persona por persona qué
  cambiaría y qué errores hay. **Nada cambia hasta «Aplicar cambios» con un
  motivo.** Queda con folio `CM-AAAA-NNNN` y en la bitácora. Una celda vacía
  no borra nada. Campos: cargo, área, jefe, ciudad, bodega, centro de costo,
  cliente, tipo y fin de contrato.
- **Mi ficha (lo corrige el colaborador):** domicilio por partes (provincia,
  cantón, parroquia, calle, número, intersección, referencia), **hasta 5
  teléfonos adicionales** opcionales y los contactos de emergencia (ya se
  podían agregar varios).
- **Marca oficial:** azul #1C58D7, azul oscuro #06122B, celeste #D2DEF7 y
  grises del manual; tipografía **Schibsted Grotesk** servida desde el propio
  servidor (no depende de Internet; licencia OFL incluida). Correos con los
  mismos colores.

## Cómo aplicarla

En la terminal de VS Code conectada al servidor (`enicolalde@apps`):

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

(Si el script no existiera todavía en el servidor, antes ejecute `git pull`.)

### Forma larga (uno por uno)

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
sudo mysqldump --single-transaction --routines --triggers rrhh > ~/bryan/rrhh_datos/respaldos/rrhh_$(date +%F_%H%M).sql
```
```bash
tar -czf ~/bryan/rrhh_datos/respaldos/adjuntos_$(date +%F_%H%M).tar.gz -C ~/bryan/rrhh_datos adjuntos
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

Después, en el navegador: **Ctrl+F5** una vez (cambian los estilos y la letra).

## Qué probar (Talento Humano)

1. **Cargos y áreas:** revisar la lista. Si arriba aparece «En fichas pero no
   en el catálogo», pulsar «Agregarlos al catálogo». Unificar dos áreas
   escritas distinto y comprobar en Colaboradores que las personas pasaron.
2. **Actualización masiva:** descargar la plantilla de un área, cambiar el
   cargo o el centro de costo de dos personas, subirla. Revisar la vista
   previa, escribir el motivo y aplicar. Ver el folio en «Cargas realizadas».
   Probar también «Descartar».
3. **Primer ingreso** con una persona sin cargo: debe pedirle área y cargo de
   la lista; la propuesta llega a Pendientes › Cambios de ficha.
4. **Mi ficha** (como colaborador): cargo y área sin poder editarse; guardar
   el domicilio por partes; agregar y quitar un teléfono adicional.
5. Ver la ficha de esa persona como Talento Humano: domicilio y teléfonos.

## Si algo sale mal

- Ver el registro: `sudo journalctl -u rrhh-itsanet-api -n 50 --no-pager`
- Volver a la base anterior: `despliegue/COMANDOS.md`, sección 5, con el
  respaldo `rrhh_antes_de_actualizar_…sql` que dejó el script.
