# Registros: cómo rastrear un error

Cuando alguien reporta «me salió un error», lo único que hace falta es el
**código de referencia** que aparece en su pantalla.

## En pantalla

Un fallo del servidor ya no dice solo «ocurrió un error inesperado». Dice:

> Ocurrió un error inesperado. El incidente quedó registrado con la
> referencia **a1b2c3d4**; indíquela al reportarlo.

Ese código de ocho caracteres es el de la petición. Viaja también en la
cabecera `X-Peticion-Id` de toda respuesta, así que se puede leer desde las
herramientas del navegador incluso cuando no hubo error.

## En el servidor

Los registros se escriben en `backend/logs/`:

| Archivo | Qué contiene |
|---|---|
| `sistema.log` | Toda la actividad: cada petición con su código, su duración y quién la hizo |
| `errores.log` | Solo advertencias y errores, con la traza completa |

Cada archivo rota al llegar a 5 MB y se conservan diez, es decir varias
semanas de historia. Van a archivo *además* de a la consola a propósito: una
terminal cerrada se lleva consigo la única evidencia de lo que pasó anoche, y
los incidentes casi nunca se reportan mientras ocurren.

Formato de cada línea:

```
2026-09-27 07:40:40 INFO  [ad4ca7d2] 1724356348 rrhh :: GET /catalogos/permisos → 200 en 8 ms
                          └ petición  └ cédula
```

La cédula aparece en cuanto la petición trae sesión válida; en el inicio de
sesión y en las rutas inexistentes sale `—`, porque todavía no hay usuario.

## Buscar

En Windows no hay `grep` ni `tail`, así que hay un lector:

```powershell
python scripts\ver_logs.py                        # últimas 40 líneas
python scripts\ver_logs.py --errores              # solo advertencias y errores
python scripts\ver_logs.py --referencia a1b2c3d4  # el rastro de un caso
python scripts\ver_logs.py --buscar 1724356348    # todo lo de una persona
python scripts\ver_logs.py --buscar /calendario   # todo lo de una pantalla
python scripts\ver_logs.py --seguir               # en vivo, mientras se prueba
python scripts\ver_logs.py --errores --ultimas 0  # el historial entero
```

Con `--referencia` se muestran todas las líneas de esa petición **y la traza
que las sigue**, que es donde está la causa. El tipo y el mensaje de la
excepción van además en la propia línea de cabecera:

```
ERROR [d453ab54] 1724356348 rrhh :: Error no controlado en GET /calendario → KeyError: 'jefe_id'
```

Eso permite que `--errores` diga qué pasó sin tener que desplegar las cuarenta
líneas de entrañas de Starlette que trae la traza.

## Ajustes

En `backend/.env`:

```ini
NIVEL_LOG=INFO      # DEBUG para ver también el detalle interno
LOG_A_ARCHIVO=true  # false deja solo la consola
```

Se registra toda petición, no solo las que fallan: la pregunta que más veces
hubo que responder durante el desarrollo fue «¿la petición llegó al
servidor?» —el preflight rechazado, el puerto equivocado, la sesión
caducada—, y para eso el silencio no sirve de nada. Los `OPTIONS` sí se
omiten: son dos por cada petición real y no dicen nada que ella no diga.

## Qué no se registra

No se escriben contraseñas, códigos de un solo uso ni el contenido de los
cuerpos de las peticiones. La traza de una excepción puede incluir valores
que venían en la consulta, así que **los registros se tratan como datos
personales** (LOPDP): quedan en el servidor, no se publican y `*.log` está
en `.gitignore` para que no lleguen nunca al repositorio.

La bitácora de auditoría es otra cosa y vive en la base de datos, en la tabla
`audit_log`: ahí queda quién aprobó qué y cuándo, que es información del
negocio y debe conservarse. Estos registros son para diagnosticar fallos.
