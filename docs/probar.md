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

```bash
cp backend/.env.example backend/.env
```

Solo **tres valores** son imprescindibles para la primera prueba:

| Valor | Dónde sacarlo |
|---|---|
| `DATABASE_URL` | Supabase → Project Settings → **Database** → Connection string (URI). Use el pooler, puerto **6543** |
| `SUPABASE_JWT_SECRET` | Supabase → Project Settings → **API** → JWT Settings → JWT Secret |
| `EMAIL_BACKEND=console` | Así el código de acceso se **imprime en la terminal** en lugar de enviarse por correo |

> `EMAIL_BACKEND=console` le permite probar **sin configurar nada de correo**. Cuando quiera probar el envío real, pase a `smtp` y complete `SMTP_USER` y `SMTP_PASSWORD` (con Google Workspace: una contraseña de aplicación, no la normal).

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

```bash
./scripts/iniciar.sh
```

Crea el entorno de Python la primera vez, ajusta `frontend/config.js` y levanta:

- **Backend** en `http://localhost:8000` (documentación interactiva en `/docs`)
- **Frontend** en `http://localhost:5500`

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
| | Nueva solicitud | Elija lunes a viernes: debe avisar del fin de semana obligatorio y ofrecer corregir |
| | | Elija una semana con feriado: el desglose lo nombra |
| | Firma | Dibújela con el mouse o el dedo |
| **Jefe** | Pestaña *Por aprobar* | El Nº, el reemplazo y las banderas de lo que falta |
| | Correo | El aviso trae un enlace que decide **sin iniciar sesión** |
| **Talento Humano** | Pestaña *Anulaciones* | Pida anular una aprobada desde el panel del empleado y resuélvala aquí |
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
| «No se pudo conectar con el servidor» | El backend no está arriba, o `frontend/config.js` apunta a otro puerto |
| El código nunca llega | Con `EMAIL_BACKEND=console` está **en la terminal**, no en el correo |
| «Su sesión expiró» al entrar | `SUPABASE_JWT_SECRET` no coincide con el de su proyecto |
| La página se ve sin estilos | El CDN de Tailwind está bloqueado por la red. Pruebe desde otra conexión |
| «Demasiados intentos» | Son 5 códigos por cédula y hora. Espere, o `delete from public.auth_otp where cedula = '…'` |
| `pool initialization incomplete` | `DATABASE_URL` incorrecta, o falta la contraseña en la URI |

---

## Después: ponerlo en línea

El frontend son archivos estáticos: sirve cualquier hosting (Cloudflare Pages, Vercel, Netlify). El backend necesita Python; `backend/Dockerfile` está listo para Fly.io, Render o Railway.

Recuerde antes de publicar:

1. `ENTORNO=produccion` — desactiva la documentación interactiva y activa HSTS
2. `CORS_ORIGINS` con el dominio real, sin `localhost`
3. `APP_URL` con el dominio real: es lo que se pone en los enlaces de los correos
4. `EMAIL_BACKEND=smtp` con la cuenta corporativa

La cámara de garita **no funciona sin HTTPS**: es un requisito del navegador, no del sistema.
