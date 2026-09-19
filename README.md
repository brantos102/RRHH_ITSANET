# Sistema Integrado de Permisos, Vacaciones y Control de Garita

Stack: **Supabase (PostgreSQL + Auth + Realtime)** · **Python / FastAPI** · **HTML + JS + TailwindCSS**

| Sprint | Entregable | Estado |
|---|---|---|
| Tarea 1 | Esquema de base de datos y setup de Supabase | ✅ |
| Tarea 2 | API Backend — Autenticación OTP por cédula (FastAPI) | ⏳ |
| Tarea 3 | Interfaz del empleado (login + dashboard) | ⏳ |
| Tarea 4 | Flujo de aprobaciones + generación de QR | ⏳ |
| Tarea 5 | Dashboard de garita (Realtime + escáner QR + visitas) | ⏳ |

## Tarea 1 — Base de datos

```
supabase/
├── migrations/20260919000001_init_schema.sql   # esquema completo
├── seed.sql                                    # feriados Ecuador + usuarios de prueba
└── tests/smoke_test.sql                        # pruebas de reglas de negocio
```

### Cómo aplicarlo

**Opción A — SQL Editor de Supabase:** pega y ejecuta primero `migrations/20260919000001_init_schema.sql` y luego `seed.sql`.

**Opción B — CLI:**
```bash
supabase link --project-ref <TU_PROJECT_REF>
supabase db push
psql "$SUPABASE_DB_URL" -f supabase/seed.sql
```

La migración es **idempotente**: se puede volver a ejecutar sin errores.

### Qué incluye

- **8 tablas**: `users`, `requests`, `access_logs`, `visitors`, `audit_logs`, `vacation_movements`, `feriados`, `auth_otp`.
- **Validación de cédula ecuatoriana** (módulo 10) como función SQL y como `CHECK` en `users` y `visitors`.
- **Regla Ecuador de días**: `permiso` → días hábiles; `vacacion` → días calendario (hábiles + fines de semana), descontando feriados nacionales.
- **Justificación obligatoria** por `CHECK` cuando los días solicitados superan el saldo (marca `es_adelanto = true`).
- **Máquina de estados** del flujo secuencial: `pendiente_jefe → pendiente_rrhh → aprobado`; cualquier salto se rechaza a nivel de base de datos.
- **Emisión automática del QR** (`qr_hash`, `qr_emitido_en`, `qr_expira_en`) y **débito del saldo** al aprobar RRHH; la cancelación devuelve los días.
- **Trazabilidad**: `audit_logs` (usuario, IP, acción, timestamp, detalle JSON) y `access_logs` (garita).
- **RLS por rol**: empleado ve lo suyo, jefe ve su equipo, RRHH/admin ven todo, guardia solo lo necesario para la garita.
- **Realtime** habilitado en `requests`, `access_logs` y `visitors` (`replica identity full`).
- **Vistas de garita**: `v_garita_actividad` y `v_visitantes_dentro`.

### Notas de seguridad

- `auth_otp` **no tiene políticas RLS y revoca privilegios a `anon`/`authenticated`**: solo el backend FastAPI (service_role) la toca. Del OTP se guarda únicamente el hash.
- El rol `anon` no tiene `SELECT` sobre `users`: el login por cédula pasa siempre por el backend.
- Las vistas de garita filtran por `public.is_guardia()` internamente, por lo que no exponen columnas sensibles de `users`.

### Verificación

`supabase/tests/smoke_test.sql` es **SQL puro**: se pega y ejecuta tal cual en el SQL Editor de Supabase. Corre 30 casos (validación de cédula, cálculo de días, justificación obligatoria, transiciones de estado, emisión de QR, débito y reversa de saldo, auditoría y registro de garita), crea sus propios datos de prueba con correos `@smoke.test` y **los borra al terminar**. Devuelve una tabla con ✅/❌ por caso.

Aun así, ejecútalo preferentemente en una base de staging: escribe y borra filas reales.
