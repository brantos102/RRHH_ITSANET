# Seguimiento de solicitudes y recordatorio al jefe (16/11/2026)

No trae migraciones.

## Qué cambia

- **Seguimiento en el asistente** (Talento Humano, administración y jefes para
  su equipo): «¿En qué va la solicitud Nº 4?» responde:
  - el estado, quién la tiene y desde cuándo;
  - si el jefe abrió el aviso del sistema y si salió el correo;
  - cuándo entró el jefe por última vez;
  - todo lo que pasó: aprobaciones, rechazo y su motivo, correcciones y
    recordatorios.
- **«¿Qué solicitudes esperan al jefe?»**: las más demoradas, con su jefe, si
  el jefe no tiene correo y si el aviso sigue sin abrir. En «¿Qué tengo
  pendiente?» se suma cuántas esperan al jefe y desde cuándo la más antigua.
- **Botón «Recordar al jefe»** en el seguimiento: aviso en el sistema y correo
  con el enlace para decidir. Una vez por hora como máximo; queda en la
  bitácora.
- El sistema anota cuándo salió el correo al jefe, para poder verlo en el
  seguimiento (desde esta versión; las anteriores no lo tienen).

## Cómo aplicarla

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

Después, en el navegador: **Ctrl+F5** una vez.

## Ver ahora mismo una solicitud (solo lectura)

Mientras tanto, o para confirmar, desde la terminal del servidor (cambie el
4 por el número):

```bash
sudo mysql rrhh -e "SELECT r.folio, r.estado, r.ruta_aprobacion, r.bloque_menor_justificado AS emergente, r.created_at AS pedida, j.nombre AS jefe, j.email AS correo_jefe, r.jefe_aprobado_en, r.rrhh_aprobado_en, r.rechazado_en, r.motivo_rechazo, (SELECT MAX(n.leida_en) FROM notifications n WHERE n.entidad_id = r.id AND n.user_id = r.jefe_id) AS jefe_abrio_aviso, (SELECT MAX(s.ultimo_uso) FROM sesiones s WHERE s.user_id = r.jefe_id) AS ultimo_ingreso_jefe FROM requests r LEFT JOIN users j ON j.id = r.jefe_id WHERE r.folio = 4\G"
```

La historia de cambios de estado:

```bash
sudo mysql rrhh -e "SELECT created_at, accion, detalle FROM audit_logs WHERE entidad_id = (SELECT id FROM requests WHERE folio = 4) ORDER BY created_at"
```

## Qué probar

1. En el chat, como Talento Humano: «¿En qué va la solicitud Nº 4?».
2. «Recordar al jefe»: el jefe recibe el aviso y el correo; un segundo
   intento antes de una hora se niega.
3. «¿Qué solicitudes esperan al jefe?».
