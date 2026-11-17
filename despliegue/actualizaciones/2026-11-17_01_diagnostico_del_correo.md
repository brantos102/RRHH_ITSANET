# Diagnóstico del correo: «No pudimos enviar el correo» (17/11/2026)

No trae migraciones. Solo mejora los mensajes que el sistema escribe en su
registro cuando un correo no sale: ahora hablan de `servidor/.env` y de
comandos del servidor Linux, y reconocen el **límite de envíos del proveedor**
(cuota o créditos agotados).

## Cuando alguien ve «No pudimos enviar el correo… (referencia XXXXXXXX)»

El sistema no pudo entregar el código al servidor de correo (SMTP). La causa
exacta está en el registro, bajo esa misma referencia. En la terminal del
servidor (`enicolalde@apps`), uno por uno:

**1. Ver la causa** (cambie la referencia por la de la pantalla):

```bash
sudo journalctl -u rrhh-itsanet-api --since "2 days ago" --no-pager | grep -A14 "a10a9ddd"
```

Las líneas en castellano debajo del error dicen qué pasó y qué hacer.

**2. Probar el envío a mano**, con la misma configuración del sistema:

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
.venv/bin/python despliegue/probar_correo.py su.correo@itsanet.com
```

**3. Ver la configuración** (sin la clave):

```bash
grep -E '^(SMTP_HOST|SMTP_PORT|SMTP_USER|SMTP_REMITENTE|SMTP_STARTTLS|EMAIL_BACKEND)=' servidor/.env
```

**4. Comprobar que el puerto sale del servidor** (ponga el host y el puerto
del paso 3):

```bash
timeout 5 bash -c '</dev/tcp/pro.eu.turbo-smtp.com/587' && echo ABIERTO || echo CERRADO
```

## Qué hacer según la causa

| Lo que dice el registro | Causa | Qué hacer |
|---|---|---|
| «rechazó el usuario o la contraseña» (535) | Clave cambiada, vencida o mal copiada | `bash despliegue/configurar_correo.sh` con la clave vigente y reiniciar (lo hace el script) |
| «se alcanzó el límite de su plan» | Cuota o créditos del proveedor agotados | Panel del proveedor: ampliar el plan o esperar la renovación |
| «no respondió a tiempo» / CERRADO en el paso 4 | Cortafuegos o red bloquean la salida | Pedir a TI abrir la salida al puerto, o configurar otro puerto (465, 2525) |
| «El cifrado no cuadra con el puerto» | Puerto y STARTTLS mezclados | 587 con STARTTLS, o 465 sin él |
| «no quiso enviar el mensaje» (550/553) | El remitente no coincide con la cuenta | Remitente = la cuenta autenticada o un alias autorizado |

Después de corregir, repita el paso 2. Si el correo llega, los códigos de
acceso también.

> Nunca pegue la clave SMTP en el chat ni en un documento: solo en
> `configurar_correo.sh`, que no la muestra.

## Cómo aplicarla

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
bash despliegue/actualizar.sh
```
