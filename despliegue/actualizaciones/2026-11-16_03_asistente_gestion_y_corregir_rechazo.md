# Asistente para la gestión y corregir un rechazo (16/11/2026)

Trae la migración **0019**: cambia dos disparadores de la tabla de solicitudes
para permitir la corrección de un rechazo, solo desde la aplicación.

## Qué cambia

- **Corregir un rechazo hecho por error.** En **Por autorizar**, abajo:
  «Rechazadas en los últimos 30 días» › **«Corregir y aprobar»**, con un
  motivo que queda en la bitácora. La solicitud vuelve a la etapa en que se
  rechazó y se aprueba ahí: si la corrige el jefe, pasa a Talento Humano; si
  la corrige Talento Humano, queda aprobada con su código QR (o pasa al jefe,
  en las vacaciones de menos de 7 días). La persona recibe el aviso.
  - La corrige quien la rechazó, el jefe inmediato o Talento Humano.
  - Hasta 30 días después del rechazo.
  - Si la persona pidió otra ausencia en esas fechas, primero hay que
    resolver esa.
  - La base no deja «des-rechazar» con un UPDATE suelto desde DBeaver: solo
    por esta vía.
- **Asistente para jefes, Talento Humano y administración.** Además de lo
  del colaborador, responde lo de su trabajo con los números de hoy y el
  botón a la pantalla exacta: qué tiene pendiente (por sede), dónde se
  aprueba, cómo corregir un rechazo, parámetros vigentes, tipos de permiso,
  registrar personas, actualización masiva, cargos y áreas, bajas, accesos,
  documentos firmados, exportar, tableros, jefaturas, anulaciones y
  vacaciones emergentes. Cada perfil ve solo lo suyo.
- En Talento Humano, la burbuja del chat abre el **asistente** si no hay
  consultas sin leer; si las hay, abre la bandeja.

## Cómo aplicarla

En la terminal de VS Code conectada al servidor (`enicolalde@apps`):

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

Después, en el navegador: **Ctrl+F5** una vez.

## Qué probar

1. Como jefe: rechazar una solicitud de prueba; en Por autorizar › «Rechazadas
   en los últimos 30 días», pulsar «Corregir y aprobar» con un motivo. Debe
   pasar a Talento Humano y el colaborador ver el aviso.
2. Como Talento Humano: rechazar una que ya aprobó el jefe y corregirla. Debe
   quedar aprobada, con QR, y descontar los días.
3. En el chat, como Talento Humano: «¿Qué tengo pendiente?», «Rechacé una
   solicitud por error», «¿Dónde cambio un parámetro?».
4. Como jefe: «¿Qué tengo por aprobar?».
5. Como colaborador: el asistente sigue respondiendo lo suyo y no muestra
   opciones de gestión.

## Si algo sale mal

- Ver el registro: `sudo journalctl -u rrhh-itsanet-api -n 50 --no-pager`
- Volver a la base anterior: `despliegue/COMANDOS.md`, sección 5, con el
  respaldo `rrhh_antes_de_actualizar_…sql` que dejó el script.
