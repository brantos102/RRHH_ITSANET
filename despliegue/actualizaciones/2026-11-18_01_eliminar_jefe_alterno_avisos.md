# Eliminar solicitudes, quitar adjuntos, jefe alterno y avisos en vivo (18/11/2026)

Trae la migración **0021**. `bash despliegue/actualizar.sh` la aplica (y las
que falten, en orden). No agrega librerías nuevas ni servicios externos.

## Qué cambia

### 1. Eliminar una solicitud con justificación

- **El colaborador** elimina las suyas que **no están aprobadas**
  (pendientes, rechazadas o canceladas). Una aprobada sigue con «Pedir
  anulación», porque devuelve días y la revisa Talento Humano.
- **Talento Humano y administración** eliminan **cualquiera** (por ejemplo,
  duplicadas o con datos equivocados): en la tarjeta por aprobar y en
  «Todas las solicitudes». Si estaba aprobada, **se devuelven los días** y
  el código de salida deja de servir. La persona recibe un aviso y un correo
  con el motivo.
- Siempre con **motivo** (mínimo 10 caracteres). **No se borra de la base**:
  se marca como eliminada (quién, cuándo, por qué), deja de verse en las
  listas y queda en la bitácora (`solicitud_eliminada`).

### 2. Quitar un adjunto equivocado

- En «📎 adjunto(s)» aparece **«Quitar»** para la persona dueña de la
  solicitud y para Talento Humano o administración (no para el jefe).
- Pide un motivo. **El archivo se borra del disco** (si era el documento de
  otra persona, no debe quedar guardado). La bitácora (`adjunto_quitado`)
  conserva quién, cuándo, por qué, el nombre y la huella SHA-256.
- Si era el respaldo que Talento Humano había pedido, el pedido vuelve a
  quedar abierto.

### 3. Jefe alterno (momentáneo)

- Si al enviar una solicitud el jefe directo **no tiene correo**, **está de
  vacaciones o con permiso de día completo hoy**, está inactivo o **no hay
  jefe registrado**, el sistema lo dice y abre **«Enviar a un jefe
  alterno»**. La tarjeta en «Mis solicitudes» también ofrece «Elegir jefe
  alterno» mientras espere al jefe.
- La lista muestra primero al jefe del jefe y a las jefaturas del mismo
  departamento. Solo jefaturas, Talento Humano o administración activos,
  con correo y presentes hoy.
- **Solo para esa solicitud**: el jefe de la ficha **no cambia**. El alterno
  recibe el aviso y el correo con su enlace; el jefe directo recibe una
  constancia. La tarjeta dice «La decide X como jefe alterno».
- Si el jefe directo sí está disponible, el colaborador no puede cambiarlo:
  lo hace Talento Humano con «Reasignar», que ahora también recuerda quién
  era el jefe original.

### 4. Avisos: campana en vivo, navegador y resumen diario

- La **campana se actualiza sola cada minuto** y la pestaña muestra los sin
  leer: «(3) Mi panel».
- **Avisos del navegador**: en la campana, «🔔 Activar avisos» › «Permitir».
  Con el sistema abierto (aunque esté en otra pestaña o programa), el
  navegador muestra el aviso; al pulsarlo lleva a lo que hay que atender.
- **Resumen diario por correo** (lunes a viernes, con la tarea de las
  06:50): a cada jefe, lo que espera su decisión desde hace más de un día; a
  Talento Humano, lo de su sede que espera a Talento Humano y lo atascado
  con el jefe (más de 2 días, sin correo, ausente o sin jefe). Uno al día
  por persona, como máximo.

## Firebase: evaluación

**No se usa Firebase, y no hace falta.**

- Los avisos del navegador salen del propio navegador, con la información
  que ya está en el servidor de la empresa. Firebase (Google) exigiría una
  cuenta y un proyecto de Google, sus librerías en las pantallas, y enviar
  el contenido de los avisos (nombres, solicitudes) a servidores fuera del
  país: es una transferencia internacional de datos personales que la LOPDP
  obliga a justificar y documentar.
- Para recibir avisos **con el navegador cerrado** existe el estándar *Web
  Push* (la misma tecnología que usa Firebase por debajo, sin cuenta de
  Google y con el contenido cifrado de punta a punta). Requiere dos cosas
  que hoy no están y dependen de TI:
  1. Un **certificado HTTPS válido** para un nombre (por ejemplo
     `rrhh.itsanet.local` con la CA interna instalada en los equipos, o un
     dominio público). Con la IP y el certificado actual, el navegador no
     permite el *service worker* que necesita Web Push.
  2. **Salida a internet** desde el servidor hacia los servicios de push de
     los navegadores (Google, Mozilla, Apple) por el puerto 443.
  Cuando TI tenga eso, se puede agregar sin cambiar lo demás.
- Mientras tanto: campana en vivo, aviso del navegador con el sistema
  abierto, correo inmediato y resumen diario.

## Comandos, uno por uno

En la terminal de VS Code conectada al servidor (`enicolalde@apps`):

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

Después, en el navegador: **Ctrl+F5** una vez.

Para probar el resumen diario sin esperar a mañana (envía los correos de
hoy, una vez):

```bash
.venv/bin/python mysql/tareas.py diaria
```

## Qué probar

1. **Eliminar (colaborador):** en una solicitud pendiente propia, «Eliminar»
   › motivo › «Eliminar». Desaparece de la lista.
2. **Eliminar (Talento Humano):** en «Todas las solicitudes», «Eliminar» en
   una de prueba. Si estaba aprobada, el mensaje dice cuántos días se
   devolvieron.
3. **Quitar adjunto:** «📎» › «Quitar» › motivo.
4. **Jefe alterno:** con una persona cuyo jefe no tenga correo, enviar un
   permiso: se abre «Enviar a un jefe alterno». Elegir a alguien: le llega
   el aviso, y en la ficha de la persona el jefe sigue siendo el mismo.
5. **Avisos:** abrir la campana › «🔔 Activar avisos» › Permitir. Desde
   otra cuenta, pedir el respaldo o recordar una solicitud: en menos de un
   minuto aparece el aviso del navegador.

## Si algo sale mal

- Ver el registro: `sudo journalctl -u rrhh-itsanet-api -n 50 --no-pager`
- Volver a la base anterior: `despliegue/COMANDOS.md`, sección 5, con el
  respaldo `rrhh_antes_de_actualizar_…sql` que dejó el script.
