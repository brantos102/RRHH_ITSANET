# Historial por año, cargos nuevos y revisión del correo (18/11/2026)

Trae las migraciones **0022** (revisiones del historial) y **0023**
(constancia de correos). `bash despliegue/actualizar.sh` las aplica. No
agrega librerías nuevas.

## Qué cambia

### 1. Cargos que no están en la lista

- En **Mi ficha › Mi cargo y área** la persona propone su cargo y su área.
  La lista muestra primero los cargos de su área y después **todos** los
  demás de la empresa (antes solo los del área elegida, y un cargo
  aprobado en otra área «no aparecía»). Si no está, lo escribe.
- No rige hasta que Talento Humano lo apruebe (Administración › Cambios de
  ficha). La bandeja marca **«Nuevo: no está en el catálogo»**; al
  aprobarlo entra a la lista oficial, en el área correcta, y lo encuentran
  los compañeros.
- En la bienvenida (primer ingreso) la lista también muestra todos los
  cargos.

### 2. Historial de vacaciones por año («Ver mi historial de vacaciones»)

- Arriba: **días generados, días tomados y saldo actual**.
- Un renglón por año con **asignados**, **tomados** y el balance: «+2 (Días
  sobrantes)» en verde, «−1 (Día adelantado)» en rojo, «0 (Balance
  exacto)» en gris. Al pulsarlo, la tabla con fecha de inicio, fecha de fin,
  días descontados y origen (hoja de Talento Humano o solicitud Nº), y el
  total.
- Asignados = los días de cada año de servicio según la antigüedad, en el
  año calendario en que se cumple (el que está en curso, con lo acumulado
  hasta hoy). Tomados = vacaciones de la hoja de Talento Humano, las
  aprobadas en el sistema y los permisos con cargo a vacaciones.
- Si el saldo oficial no es generados − tomados (ajustes de Talento Humano,
  días caducados o el saldo con que se cargó la ficha), se dice cuánto.

### 3. Refutar un registro, con evidencia obligatoria

- Botón **«Refutar»** en cada registro: motivo y **evidencia obligatoria**
  (correo exportado a PDF o el archivo .eml / .msg, captura o documento;
  hasta 5 de 10 MB).
- Llega **por correo al buzón del departamento de Talento Humano** y a su
  equipo de la sede, **con la evidencia adjunta** y «Responder a» la persona;
  y a **Administración › Pendientes por sede › Revisiones del historial**.
- Talento Humano abre la evidencia, descarga el historial de la persona y
  responde **Aceptar / No aceptar**. La respuesta le llega a la persona por
  correo y aparece junto al registro. Aceptar **no cambia el saldo** por sí
  solo: se corrige en la ficha, con su propia bitácora.

### 4. Descargar el historial en Excel y PDF

- Todos: **⬇ Excel** y **⬇ PDF** en su historial, con el logo, el resumen,
  cada año y su detalle, quién lo generó y la leyenda de datos personales.
- Talento Humano: los mismos botones en el expediente de cada persona.
  Queda en la bitácora.

### 5. Revisión del ingreso y del envío de correos

- **Corregido:** los correos salían **sin las cabeceras `Date` y
  `Message-ID`**. Gmail rechaza o manda a spam lo que llega sin
  `Message-ID`, y otros proveedores lo penalizan. Ahora van, junto con
  `Auto-Submitted` (evita respuestas automáticas en bucle). Puede explicar
  correos que «no llegaban» aunque el sistema los diera por enviados.
- **Constancia de cada envío** (tabla `correos_enviados`): cuándo, a quién
  (enmascarado: `ab***@dominio`), asunto **sin códigos de acceso**, si salió,
  por qué puerto y, si falló, el motivo. Sin contenido. Se borra a los 90
  días.
- **Administración › Correo del sistema** (Talento Humano y administración):
  la configuración (sin la clave), enviados y fallidos de la semana, los
  últimos envíos, **«¿Le llegó a…?»** buscando por el correo exacto, y
  **«Enviarme un correo de prueba»**, que dice en castellano qué revisar si
  falla.

## Comandos, uno por uno

En la terminal de VS Code conectada al servidor (`enicolalde@apps`):

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

Después, en el navegador: **Ctrl+F5** una vez.

## Qué probar

1. **Correo:** Administración › Correo del sistema › «Enviarme un correo
   de prueba». Debe llegar; en la lista aparece «Salió · puerto 2525». En
   Gmail, «Mostrar original» debe mostrar `Message-ID`.
2. **Ingreso:** cerrar sesión y entrar con el código. En «Correo del
   sistema», buscar su correo: aparece «Código de acceso: ••••••» con
   «Salió».
3. **Historial:** «Ver mi historial de vacaciones»: los años, el detalle, y
   ⬇ Excel / ⬇ PDF.
4. **Refutar:** en un registro de prueba, «Refutar» con un PDF. Talento
   Humano recibe el correo con el adjunto y lo ve en Pendientes por sede ›
   Revisiones del historial; responder y comprobar que la persona lo ve.
5. **Cargo:** en Mi ficha › Mi cargo y área, escribir un cargo que no está.
   En Cambios de ficha aparece «Nuevo: no está en el catálogo»; aprobarlo y
   comprobar que ya aparece en la lista de otra persona.

## Si algo sale mal

- Ver el registro: `sudo journalctl -u rrhh-itsanet-api -n 50 --no-pager`
- Volver a la base anterior: `despliegue/COMANDOS.md`, sección 5, con el
  respaldo `rrhh_antes_de_actualizar_…sql` que dejó el script.
