# Cómo probar el sistema

Las migraciones ya están aplicadas. Faltan tres cosas: **un usuario con el que entrar**, **la configuración del backend** y **arrancarlo**.

---

## 1. Créese un usuario (2 minutos)

Sin esto no podrá iniciar sesión: el sistema solo deja entrar a quien esté registrado.

Abra `supabase/crear_mi_usuario.sql`, **cambie los cuatro valores del inicio** por su cédula y su correo real, y ejecútelo en el SQL Editor de Supabase.

```sql
v_cedula        text := '1712345675';          -- la suya, válida según módulo 10
v_nombre        text := 'Nombre Apellido';
v_email         text := 'usted@itsanet.com.ec'; -- ahí llegará su código
v_fecha_ingreso date := '2018-03-01';           -- decide cuántos días le tocan
```

Si la cédula no es válida, el script se lo dice **y le sugiere cuál debería ser el último dígito**.

¿Quiere recorrer el flujo completo usted solo (solicitar → aprobar como jefe → aprobar como RRHH → validar el QR como guardia)? Ejecute también `supabase/crear_equipo_de_prueba.sql`. Si su correo admite alias (`usted+jefe@…`), todos los códigos llegan a su misma bandeja.

---

## 2. Configure el backend

Copie el ejemplo a `backend/.env`:

```powershell
# Windows (PowerShell), desde la raíz del proyecto
copy backend\.env.example backend\.env
```

```bash
# Linux / macOS
cp backend/.env.example backend/.env
```

Solo **dos valores** hay que completar a mano; el resto del archivo ya viene listo para probar en su máquina:

| Valor | Dónde sacarlo |
|---|---|
| `DATABASE_URL` | Supabase → Project Settings → **Database** → Connection string (URI). Use el pooler, puerto **6543**, y reemplace `[YOUR-PASSWORD]` por la contraseña real |
| `SUPABASE_JWT_SECRET` | Supabase → Project Settings → **API** → JWT Settings → JWT Secret |

Así debe quedar el final del archivo para la primera prueba (ya viene así en el ejemplo):

```ini
EMAIL_BACKEND=console
APP_URL=http://localhost:5500
CORS_ORIGINS=http://localhost:5500,http://127.0.0.1:5500
ENTORNO=desarrollo
```

Qué hace cada uno:

- **`EMAIL_BACKEND=console`** imprime el código de acceso **en la terminal del backend** en vez de enviarlo. Prueba sin tocar nada de correo. Para el envío real: `smtp` más `SMTP_USER` y `SMTP_PASSWORD` (con Google Workspace, una contraseña de aplicación, no la normal).
- **`CORS_ORIGINS`** son las direcciones desde las que el navegador puede llamar a la API. `http://localhost:5500` y `http://127.0.0.1:5500` son **orígenes distintos** para el navegador: por eso están los dos.
- **`ENTORNO=desarrollo`** deja abierta la documentación en `/docs` y acepta **cualquier puerto local** (Live Server usa 5500 o 5501 según esté libre). Al publicar se pone `produccion` y entonces solo valen los dominios listados.

> Si cambia el `.env`, **reinicie uvicorn**: `--reload` vigila el código, no el `.env`.

---

## 3. Compruebe que todo esté en su sitio

```bash
python scripts/verificar.py
```

Revisa la configuración, la conexión, cada migración y con quién puede entrar. Si algo falta, dice **qué** y **cómo resolverlo**:

```
2. Base de datos
  ✓ Conexión establecida
  ✓ Migración 0001 esquema base
  ✓ Migración 0006 anulación y administración

4. Con quién puede iniciar sesión
    1712345675  Nombre Apellido     admin     usted@itsanet.com.ec

Todo listo. Arranque con:  ./scripts/iniciar.sh
```

---

## 4. Arranque

### Linux / macOS

```bash
./scripts/iniciar.sh
```

Crea el entorno de Python la primera vez, ajusta `frontend/config.js` y levanta backend y frontend juntos.

### Windows (PowerShell)

Hacen falta **dos ventanas**: una para la API y otra para las páginas. El frontend **no se abre con doble clic** sobre el `.html` — así el navegador manda el origen `null` y la API lo rechaza siempre.

Ventana 1 — backend:

```powershell
cd C:\ruta\al\proyecto\RRHH_ITSANET
python scripts\servidor.py
```

> **Use `scripts\servidor.py`, no `uvicorn` directamente.** En Windows, psycopg
> no puede trabajar sobre el bucle de eventos que Python trae por omisión
> (`ProactorEventLoop`), y uvicorn solo lo cambia cuando arranca un
> subproceso, es decir con `--reload`. Sin `--reload` el servidor levanta pero
> no logra conectarse a la base: `Psycopg cannot use the 'ProactorEventLoop'`.
> El lanzador fija el bucle correcto siempre. Para probar cómo se comportará
> publicado, `python scripts\servidor.py --sin-recarga`.

Ventana 2 — frontend:

```powershell
cd C:\ruta\al\proyecto\RRHH_ITSANET\frontend
python -m http.server 5500
```

Y abra **`http://127.0.0.1:5500`** (no `localhost`, para que coincida con el `--host 127.0.0.1` del backend: en Windows `localhost` a veces resuelve a IPv6 y la conexión se rechaza).

Al arrancar, el backend dice en su terminal qué orígenes acepta:

```
INFO rrhh :: Entorno: desarrollo
INFO rrhh :: CORS acepta: http://localhost:5500, http://127.0.0.1:5500 y cualquier http://localhost:PUERTO
```

Resultado en ambos sistemas:

- **Backend** en `http://127.0.0.1:8000` (documentación interactiva en `/docs`)
- **Frontend** en `http://127.0.0.1:5500`

Abra `http://localhost:5500`, escriba su cédula, y **el código aparecerá en esa misma terminal**:

```
=== CORREO (modo consola) ===
Para: usted@itsanet.com.ec
Asunto: Código de acceso: 428917
```

Ctrl+C detiene todo.

---

## 5. Qué probar

| Como | Dónde | Qué mirar |
|---|---|---|
| **Empleado** | Panel | El saldo y su botón *¿Por qué tengo estos días?* con los artículos |
| | Nueva solicitud | Elija lunes a viernes: son 5 días y el mínimo son 7. Debe frenarlo y ofrecer corregir con un clic |
| | Solicitar permiso | Elija un pilar y un subtipo: aparece el ejemplo de cómo redactarlo y qué adjuntar |
| | | Elija una semana con feriado: el desglose lo nombra |
| | Firma | Dibújela con el mouse o el dedo |
| **Jefe** | Pestaña *Por aprobar* | Al aprobar, elige quién cubre el puesto; quien también falta esas fechas sale bloqueado |
| | Menú *Jefe → Calendario del equipo* | Su equipo mes a mes. Pulse un bloque para ver quién cubre |
| | Correo | El aviso trae un enlace que decide **sin iniciar sesión** |
| **Talento Humano** | Pestaña *Anulaciones* | Pida anular una aprobada desde el panel del empleado y resuélvala aquí |
| | *Calendario del equipo* → una ausencia aprobada | Botón **Ajustar**: el permiso de dos horas que deriva en tres días de reposo |
| | Informes | Filtre y descargue el CSV (se abre en Excel con acentos) |
| | Administración | Antigüedades, días no laborables, parámetros y bitácora |
| **Guardia** | `garita.html` | Pegue el código QR: el veredicto ocupa la pantalla |
| | | Pruebe un código inventado: queda registrado en la bitácora |
| | | Registre una visita con cédula inválida: la rechaza en el navegador |

**Para ver el QR**: el empleado lo abre desde *Mis solicitudes* → «Ver código QR». Si quiere pegarlo a mano en garita, el valor está en la base:

```sql
select folio, qr_hash from public.requests where estado = 'aprobado';
```

**Ojo con las fechas**: la garita solo autoriza si la ausencia rige **hoy**. Para probar sin esperar:

```sql
-- Solo mientras la solicitud siga pendiente; una vez aprobada no se mueven
update public.requests set fecha_inicio = current_date, fecha_fin = current_date + 3
 where folio = 1;
```

---

## Si algo falla

| Síntoma | Causa y arreglo |
|---|---|
| «No se pudo conectar con el servidor» **y en la terminal del backend aparece `"OPTIONS /auth/solicitar-token" 400 Bad Request`** | El navegador pidió permiso (preflight) desde un origen no autorizado. El backend escribe en su terminal la línea `CORS: origen rechazado …` con el origen exacto: agréguelo a `CORS_ORIGINS` en `backend/.env` y **reinicie uvicorn**. Si el origen es `null`, está abriendo el HTML con doble clic: sírvalo con `python -m http.server 5500` |
| «No se pudo conectar con el servidor» **sin ninguna línea nueva en la terminal** | La petición no llegó: el backend no está arriba, o `frontend/config.js` apunta a otro puerto, o uvicorn escucha en `127.0.0.1` y usted abrió `localhost` (en Windows resuelve a IPv6). Use `127.0.0.1` en ambos lados, o arranque con `--host 0.0.0.0` |
| El código nunca llega | Con `EMAIL_BACKEND=console` está **en la terminal**, no en el correo |
| «Su sesión expiró» al entrar | `SUPABASE_JWT_SECRET` no coincide con el de su proyecto |
| La página se ve sin estilos | Falta `frontend/vendor/tailwind.css`. Regenérelo con `cd build && npm install && npm run estilos`, o traiga el archivo del repositorio |
| «Demasiados intentos» | Son 5 códigos por cédula y hora. Espere, o `delete from public.auth_otp where cedula = '…'` |
| `pool initialization incomplete` | `DATABASE_URL` incorrecta, o falta la contraseña en la URI |
| `Psycopg cannot use the 'ProactorEventLoop'` (Windows) | Arranque con `python scripts\servidor.py` en vez de llamar a uvicorn directamente |
| `Field required: database_url` | No encuentra `backend/.env`. Compruebe que el archivo exista **dentro de la carpeta `backend`** y que se llame `.env`, no `.env.txt` (el Bloc de notas añade la extensión si no la pone entre comillas al guardar) |

---

## Después: ponerlo en línea

El frontend son archivos estáticos: sirve cualquier hosting (Cloudflare Pages, Vercel, Netlify). El backend necesita Python; `backend/Dockerfile` está listo para Fly.io, Render o Railway.

Recuerde antes de publicar:

1. `ENTORNO=produccion` — desactiva la documentación interactiva y activa HSTS
2. `CORS_ORIGINS` con el dominio real, sin `localhost`
3. `APP_URL` con el dominio real: es lo que se pone en los enlaces de los correos
4. `EMAIL_BACKEND=smtp` con la cuenta corporativa

La cámara de garita **no funciona sin HTTPS**: es un requisito del navegador, no del sistema.
