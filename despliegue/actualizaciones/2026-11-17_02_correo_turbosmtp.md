# Nuevo correo de envío: notificaciones@flexnetecuador.com (17/11/2026)

Cambia la cuenta desde la que salen los correos del sistema (códigos de
ingreso, avisos a jefes y a Talento Humano). No trae migraciones.

| | Antes | Ahora |
|---|---|---|
| Servidor SMTP | `pro.eu.turbo-smtp.com` | `pro.turbo-smtp.com` |
| Puerto | 587 | 587, y si no conecta, **2525** |
| Cifrado | STARTTLS obligatorio | STARTTLS **si el proveedor lo ofrece** (`auto`) |
| Remitente | dominio anterior | `Talento Humano ITSANET <notificaciones@flexnetecuador.com>` |

El usuario y la clave del proveedor **no están en el repositorio**: se
escriben a mano en el servidor, una sola vez, con `configurar_correo.sh`, y
quedan solo en `servidor/.env`.

## Qué cambia en el código

- `SMTP_PORT_ALTERNO`: si el puerto principal no conecta (tiempo agotado o
  conexión rechazada), el envío pasa de inmediato al alterno. El registro
  (`journalctl`) dice por qué puerto salió o falló.
- `SMTP_STARTTLS=auto`: usa cifrado si el servidor lo ofrece (los puertos
  587 y 2525 «sin SSL» de turboSMTP lo ofrecen). `true` lo exige y `false`
  lo apaga (solo para 465).
- `configurar_correo.sh` propone los datos nuevos, comprueba si los puertos
  587 y 2525 están abiertos desde el servidor y, si solo uno lo está, lo usa
  como principal.
- El mensaje de «no se pudo enviar» lista la prueba de cada puerto.

## Comandos, uno por uno

En la terminal de VS Code conectada al servidor (`enicolalde@apps`).

**1. Traer el código** (respalda, trae, migra y reinstala):

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```

**2. Ver si el servidor llega al proveedor** (no cambia nada):

```bash
getent hosts pro.turbo-smtp.com
```
```bash
timeout 5 bash -c '</dev/tcp/pro.turbo-smtp.com/587' && echo ABIERTO || echo CERRADO
```
```bash
timeout 5 bash -c '</dev/tcp/pro.turbo-smtp.com/2525' && echo ABIERTO || echo CERRADO
```

Basta con que **uno** diga ABIERTO. Si los dos dicen CERRADO, siga igual con
el paso 3 (queda guardado) y pida a TI lo del final.

**3. Guardar la cuenta nueva:**

```bash
bash despliegue/configurar_correo.sh
```

Pulse **Enter** para aceptar cada valor propuesto (servidor, puerto 587,
alterno 2525, remitente). Escriba a mano el **usuario** que le dio el
proveedor y la **clave** (no se ve mientras la escribe; es normal).

**4. Reiniciar el sistema para que tome la cuenta nueva:**

```bash
sudo systemctl restart rrhh-itsanet-api
```

**5. Probar un envío real** (a su propio correo):

```bash
.venv/bin/python despliegue/probar_correo.py su.correo@itsanet.com
```

Debe decir que el correo salió y llegarle en un minuto. Revise también la
carpeta de spam.

## Qué probar en el sistema

1. Cerrar sesión y entrar con el código por correo: debe llegar desde
   `notificaciones@flexnetecuador.com`.
2. Crear una solicitud de prueba: el jefe debe recibir el aviso.
3. Si algo falla, la pantalla muestra una **referencia**; búsquela en:
   `sudo journalctl -u rrhh-itsanet-api -n 80 --no-pager | grep <referencia>`

## Lo que debe revisar TI (fuera del sistema)

- **Salida a internet:** permitir desde `192.168.4.94` la salida hacia
  `pro.turbo-smtp.com` (IP `199.244.74.83`, la del paso 2) por los puertos
  **587 y 2525**. Con el anterior servidor el puerto 587 no conectaba.
- **Remitente verificado** en turboSMTP: `notificaciones@flexnetecuador.com`.
- **DNS de flexnetecuador.com:** el registro SPF debe incluir a turboSMTP
  y conviene activar DKIM; sin eso los correos pueden caer en spam.
- Si «IP origen 199.244.74.83» era la IP **pública de salida** autorizada en
  el proveedor, compruebe con `curl -s ifconfig.me` que el servidor sale por
  esa IP.

## Si algo sale mal

- Los correos que no salen no detienen el sistema: las solicitudes se
  guardan igual y el aviso se puede reenviar con «Recordar».
- Volver a la cuenta anterior: ejecutar de nuevo `configurar_correo.sh` con
  los datos viejos y reiniciar (paso 4).
- Ver el registro: `sudo journalctl -u rrhh-itsanet-api -n 50 --no-pager`
