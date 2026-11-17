# El recordatorio al jefe sale por correo y se ve si salió (17/11/2026)

No trae migraciones.

## Qué fallaba

Al pulsar **«Recordar»** (en «Todas las solicitudes» o desde el asistente):

1. Se mandaba **el mismo correo del aviso original**, con el mismo asunto
   («Fulano solicita vacaciones»). Gmail y Outlook lo juntaban en la
   conversación anterior: el jefe no veía un correo nuevo.
2. Se mandaba **en segundo plano**: si el servidor de correo fallaba, la
   pantalla decía igual «Se le recordó a…» y el error solo quedaba en el
   registro.
3. El enlace del correo vence a los **15 días de creada** la solicitud. En
   una solicitud más vieja, el recordatorio llevaba un enlace que ya no
   servía.

## Qué cambia

- El recordatorio es **un correo propio**: asunto «Recordatorio: Fulano
  espera su decisión (solicitud Nº N)», con quién de Talento Humano lo
  recuerda, los datos de la solicitud y el botón **«Revisar y decidir»**.
- Si el enlace ya venció, el botón es **«Entrar al sistema»** (lleva a «Por
  autorizar»).
- Se envía **en el momento** y la pantalla dice el resultado:
  - «Se le recordó a Jefe X por correo (je***@empresa.com) y en el sistema.»
  - Si el jefe **no tiene correo**: lo dice; solo verá el aviso en el sistema.
  - Si el correo **no sale**: aviso en rojo, «el correo NO salió…». El aviso
    en el sistema sí queda, y en la bitácora queda `recordatorio_correo_fallido`.
- Cuando sale, se anota en el aviso (`email_enviado_en`).

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

1. Talento Humano › Por autorizar › «Todas las solicitudes» › en una que
   espere al jefe, **«Recordar»**. Debe decir «…por correo (xx***@…) y en el
   sistema».
2. El jefe debe recibir un correo **nuevo** cuyo asunto empieza por
   «Recordatorio:». Revise también la carpeta de spam.
3. Si la pantalla dice que el jefe **no tiene correo**, regístreselo en
   Administración › Usuarios.

Se puede recordar la misma solicitud **una vez por hora**.

## Si el correo no sale

La pantalla lo dice en rojo. Para ver por qué:

```bash
sudo journalctl -u rrhh-itsanet-api -n 80 --no-pager | grep -A6 "recordatorio"
```

Las líneas siguientes dicen qué corregir (servidor, puerto, clave). Para
probar el correo del servidor por separado:

```bash
.venv/bin/python despliegue/probar_correo.py su.correo@itsanet.com
```
