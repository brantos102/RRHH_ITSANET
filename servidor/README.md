# API — Autenticación por cédula + OTP

FastAPI sobre PostgreSQL (Supabase). Sin contraseñas: el empleado ingresa su cédula y recibe un código de un solo uso en su correo institucional.

## Arrancar en local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env     # completar con los datos del proyecto
cd backend && uvicorn app.main:app --reload
```

Documentación interactiva en `http://localhost:8000/docs` (se desactiva sola cuando `ENTORNO=produccion`).

## Endpoints

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/auth/solicitar-token` | Valida la cédula (módulo 10) y envía el código al correo |
| POST | `/auth/validar-token` | Verifica el código y devuelve la sesión |
| GET | `/auth/me` | Perfil del empleado |
| GET | `/auth/mi-saldo` | Desglose del saldo con la explicación y los artículos que lo sustentan |
| GET | `/auth/mis-notificaciones` | Alertas del empleado, con su base legal |
| POST | `/auth/cerrar-sesion` | Registra el cierre en la bitácora |
| GET | `/glosario` | Normativa vigente que sustenta las reglas |
| GET | `/salud` | Estado del servicio y de la base |

## Cómo encaja con Supabase

El backend firma el JWT con el **JWT Secret del proyecto**, así que el mismo token sirve para `supabase-js` en el navegador y **las políticas RLS aplican al usuario que inició sesión**. El claim `sub` es el id de `auth.users`, que es lo que lee `auth.uid()`.

En consecuencia: el frontend lee datos directamente de Supabase con RLS, y solo pasa por esta API lo que requiere privilegios de servicio (enviar el código, aprobar, emitir el QR).

## Decisiones de seguridad

- **No se revela si una cédula existe.** La respuesta de `/auth/solicitar-token` es idéntica esté o no registrada. Una cédula es un dato personal (LOPDP): permitir enumerarlas convertiría el login en un directorio de empleados.
- **El código se guarda solo como hash SHA-256 ligado a la cédula**, nunca en claro. Un volcado de la tabla no sirve para iniciar sesión.
- **Correo enmascarado con longitud fija** (`j***z@…`): si la máscara tuviera un asterisco por letra, revelaría el largo del correo.
- **Comparación en tiempo constante** (`hmac.compare_digest`).
- **El intento se cuenta antes de comparar**: un fallo del servidor no regala intentos.
- **Un solo código vigente**: pedir uno nuevo anula el anterior.
- **Límites**: 5 envíos por cédula/hora, 20 por IP/hora, 5 intentos por código, vigencia de 10 minutos.
- **Todo queda en `audit_logs`** con IP, agente y marca de tiempo.
- Las trazas de error nunca llegan al cliente; van al log del servidor.
- Cabeceras `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` y HSTS en producción.

## Pruebas

```bash
.venv/bin/python -m pytest backend/tests -q
```

35 pruebas **contra una base PostgreSQL real**, no simulada: cédula módulo 10, límite de envíos, hash del código, un solo uso, expiración, intentos agotados, token manipulado, auditoría y explicación del saldo con su base legal.
