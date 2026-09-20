# Sistema Integrado de Permisos, Vacaciones y Control de Garita

Stack: **Supabase (PostgreSQL + Auth + Realtime + Storage)** · **Python / FastAPI** · **HTML + JS + TailwindCSS**

| Sprint | Entregable | Estado |
|---|---|---|
| Tarea 1 | Esquema de base de datos y reglas de negocio Ecuador | ✅ |
| Tarea 2 | API Backend — Autenticación OTP por cédula (FastAPI) | ⏳ |
| Tarea 3 | Interfaz del empleado (login + dashboard + firma) | ⏳ |
| Tarea 4 | Flujo de aprobaciones + generación de QR | ⏳ |
| Tarea 5 | Dashboard de garita (Realtime + escáner QR + visitas) | ⏳ |

## Base de datos

```
supabase/
├── migrations/
│   ├── 20260919000001_init_schema.sql      # tablas, RLS, triggers, Realtime
│   ├── 20260919000002_reglas_ecuador.sql   # vacaciones, permisos, firmas, adjuntos
│   └── 20260919000003_storage.sql          # buckets privados de Storage
├── seed.sql                                # feriados + usuarios de prueba
└── tests/smoke_test.sql                    # 71 casos de reglas de negocio
```

### Cómo aplicarlo

**SQL Editor de Supabase:** ejecuta las tres migraciones **en orden**, luego `seed.sql`.

**CLI:**
```bash
supabase link --project-ref <TU_PROJECT_REF>
supabase db push
psql "$SUPABASE_DB_URL" -f supabase/seed.sql
```

Las migraciones son **idempotentes**: se pueden volver a ejecutar sin errores.

## Reglas de negocio implementadas en la base

### Vacaciones por antigüedad (Art. 69 Código del Trabajo)

15 días por año cumplido; desde el 6to año se suma 1 día por cada año de servicio, con tope configurable (por defecto 15 adicionales = 30 días máximo).

| Año de servicio | 1–5 | 6 | 7 | 10 | 20+ |
|---|---|---|---|---|---|
| Días | 15 | 16 | 17 | 20 | 30 |

El saldo **no es un número suelto**: se deriva de `vacation_periods`, un registro por año de servicio con sus días asignados, consumidos y su fecha de caducidad (3 años, Art. 75). El consumo es **FIFO** (se gastan primero los períodos más antiguos, los que están por caducar). `users.dias_vacaciones` es solo una caché que los triggers mantienen sincronizada.

### Dos fines de semana obligatorios por período

De los 15 días, 4 deben ser 2 fines de semana completos. La base bloquea una solicitud de vacaciones que **termine en viernes** o **empiece en lunes** sin incluir el sábado y domingo adyacentes, mientras al empleado le falten fines de semana por consumir. El error incluye el rango corregido, y `previsualizar_solicitud()` lo devuelve al frontend para ofrecer la corrección con un clic.

Una vez consumidos los 2 fines de semana del período, la restricción se levanta sola. RRHH puede saltarla caso por caso con `omitir_regla_fds`.

### Cálculo de días

- **Vacaciones**: días calendario (hábiles + fines de semana), descontando feriados nacionales.
- **Permisos**: días hábiles, descontando feriados.

### Permisos categorizados

`permission_types` es un catálogo configurable por RRHH (16 tipos precargados según normativa ecuatoriana: cita médica, enfermedad, calamidad doméstica, fallecimiento de familiar, maternidad, paternidad, lactancia, matrimonio, estudios, trámite gubernamental, citación judicial, sufragio, donación de sangre, cuidado de persona con discapacidad, caso fortuito, asunto personal).

Cada tipo define por sí mismo: si exige **adjunto de respaldo**, si exige **justificación**, si exige **firma**, si es **remunerado**, si **descuenta de vacaciones**, y sus topes de días y horas. Agregar o ajustar un tipo es un `UPDATE`, no una migración.

### Adjuntos y firma electrónica

- `request_attachments` + bucket privado `solicitudes/<user_id>/<request_id>/`. Solo JPEG, PNG, WebP, HEIC o PDF, máximo 10 MB.
- `signatures`: firma registrada del usuario — **dibujada con el mouse**, imagen subida o certificado oficial. Una sola activa por usuario.
- `request_signatures`: **instantánea** de la firma al momento de firmar. Si el usuario cambia su firma después, las solicitudes ya firmadas conservan la original.
- La exigencia de adjunto y firma se valida con un **trigger diferido**: el backend inserta solicitud + archivos + firma en una sola transacción y la base rechaza el conjunto incompleto al confirmar.

### Flujo y trazabilidad

- Máquina de estados `pendiente_jefe → pendiente_rrhh → aprobado`: cualquier salto se rechaza en la base, no solo en el backend.
- Al aprobar RRHH se emite el `qr_hash` con expiración y se descuenta el saldo por períodos.
- Cancelar una solicitud aprobada devuelve días y fines de semana.
- `audit_logs` (usuario, IP, acción, timestamp, detalle JSON) + `access_logs` (garita) + `vacation_movements` (ledger del saldo).

### Migrar los 250 empleados

`cargar_saldo_inicial(user_id, saldo_real, fines_semana_ya_consumidos)` genera los períodos históricos del empleado y ajusta el consumo para que el saldo cuadre con el que RRHH ya tiene en planilla. Es la función a usar en la carga masiva inicial.

## Seguridad

- **RLS por rol**: empleado ve lo suyo, jefe ve su equipo, RRHH/admin ven todo, guardia solo lo necesario para la garita.
- `auth_otp` **sin políticas RLS y con privilegios revocados** a `anon`/`authenticated`: solo el backend (service_role). Del OTP se guarda únicamente el hash SHA-256.
- `anon` no tiene `SELECT` sobre `users`: el login por cédula pasa siempre por el backend.
- Buckets **privados** con políticas por carpeta: cada quien sube a `<su user_id>/` y solo su jefe y RRHH pueden leerlo.
- Las vistas de garita filtran por `is_guardia()` internamente, sin exponer columnas sensibles.

## Verificación

```
supabase/tests/
├── _helpers.sql                # ejecutar PRIMERO (crea utilidades temporales)
├── smoke_test.sql              # 71 casos: vacaciones, permisos, QR, garita
└── smoke_test_normativa.sql    # 39 casos: normativa, alertas, datos, seguridad
```

En el SQL Editor de Supabase, **en la misma pestaña**: primero `_helpers.sql`, luego el archivo de pruebas. Las utilidades son temporales y viven solo mientras dure la sesión de esa pestaña.

Ambos archivos son **SQL puro** y están escritos como sentencias cortas e independientes (la mayor no llega a 1,5 KB). Si el editor corta el pegado, el error señala en qué sección ocurrió y se puede reanudar desde ahí, en lugar de fallar entero.

Cada archivo crea sus propios datos (`@smoke.test` / `@norm.test`) y **los borra en su sección final**. Devuelven una tabla con ✅/❌ por caso.

Ejecútalos preferentemente en staging: escriben y borran filas reales.
