# Permisos: sin «días a descontar», justificación opcional y respaldo a pedido (17/11/2026)

Trae la migración **0020**. `bash despliegue/actualizar.sh` la aplica (y las
que falten, en orden).

## Qué cambia

**Para el colaborador**

- Al pedir un permiso, el resumen ya no dice «1 día a descontar · le
  quedarían 11». Dice **«Permiso de 1 día · no se descuenta de sus
  vacaciones»**. Solo los permisos **con cargo a vacaciones** (por ejemplo,
  «Asunto personal») muestran cuántos días le quedarían.
- La **justificación** del permiso es **opcional**. La descripción (motivo,
  lugar, hora) sigue siendo obligatoria.
- El **respaldo** ya no «se exige»: el formulario dice que puede adjuntarlo
  ahora o después.
- En «Mis solicitudes», cada permiso vigente tiene **«Adjuntar respaldo»**,
  para entregarlo después (el certificado de una cita se emite después de la
  cita).

**Para Talento Humano**

- **Pedir respaldo** (en «Todas las solicitudes» y en las tarjetas por
  aprobar): se escribe qué documento hace falta. A la persona le llega un
  correo y un aviso, y su solicitud muestra un recuadro con el pedido y el
  botón para adjuntarlo. **La solicitud no cambia de estado**: se puede pedir
  mientras espera o después de aprobada.
- Cuando la persona lo adjunta, le llega un aviso a quien lo pidió y la fila
  pasa de «Respaldo pedido» a **«Respaldo entregado»**.
- **Ver respaldo (📎)**: antes los adjuntos solo se contaban, no se podían
  abrir desde la web. Ahora los abren la persona, su jefe en esa solicitud y
  Talento Humano. **Cada apertura queda en la bitácora** (`adjunto_visto`),
  porque son documentos sensibles (LOPDP).

**En la base (0020)**

- Se quita la restricción que exigía 10 caracteres de justificación en todo
  permiso.
- `requests` gana `respaldo_pedido_en`, `respaldo_pedido_por`,
  `respaldo_pedido_mensaje` y `respaldo_entregado_en`.
- El lineamiento «adjúntelo al pedirlo» se reescribe, solo si Talento
  Humano no lo había cambiado.

## Comandos, uno por uno

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

## Qué probar

1. **Colaborador:** «Solicitar permiso» › «Estudios o capacitación» › un día.
   El resumen dice «Permiso de 1 día · no se descuenta de sus vacaciones» y
   la justificación dice «(opcional)». Enviarlo sin justificación.
2. **Talento Humano:** Por autorizar › «Todas las solicitudes» › en ese
   permiso, **«Pedir respaldo»** › «Enviar pedido».
3. **Colaborador:** le llega el correo; en «Mis solicitudes» aparece el
   recuadro ámbar. «Adjuntar respaldo» › elegir una foto o PDF.
4. **Talento Humano:** la fila dice «Respaldo entregado»; el botón 📎 lo abre.
5. Un permiso «Asunto personal (con cargo a vacaciones)» sí muestra cuántos
   días le quedarían.

## Si algo sale mal

- Ver el registro: `sudo journalctl -u rrhh-itsanet-api -n 50 --no-pager`
- Volver a la base anterior: `despliegue/COMANDOS.md`, sección 5, con el
  respaldo `rrhh_antes_de_actualizar_…sql` que dejó el script.
