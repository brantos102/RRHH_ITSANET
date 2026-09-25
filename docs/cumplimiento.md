# Cumplimiento normativo

Este sistema opera en Quito, Ecuador. Lo que sigue documenta qué exige cada norma y **dónde** está implementada en el código, para que una auditoría pueda verificarlo sin leer todo el esquema.

## Código del Trabajo

| Artículo | Exigencia | Implementación |
|---|---|---|
| Art. 69 | 15 días de vacaciones por año cumplido; +1 día por año desde el 6to | `dias_por_antiguedad()`, `vacation_periods.dias_asignados` |
| Art. 71 | Vacaciones incluyen días no laborables | `calcular_dias()` cuenta días calendario para `vacacion` |
| Art. 73 | El período vacacional debe constar y ser visible | `requests` + vista `v_trazabilidad_solicitudes` |
| Art. 74 | El empleador puede postergar y acumular | `vacation_periods` mantiene cada año por separado |
| Art. 75 | Acumulación máxima de 3 años; lo excedente se pierde | `caducar_periodos_vencidos()`, alerta `vacaciones_por_caducar` |
| Art. 42 núm. 9 | Respeto a certificados médicos del IESS | `permission_types` `cita_medica` y `enfermedad` con adjunto obligatorio |
| Art. 42 núm. 29 | Facilidades para instrucción y capacitación | `permission_types.estudios` |
| Art. 42 núm. 30 | Calamidad doméstica y 3 días por fallecimiento hasta 2do grado | `calamidad_domestica`, `fallecimiento_familiar`, `family_members.grado_consanguinidad` |
| Art. 152 | 12 semanas de maternidad / 10-15 días de paternidad | `permission_types` con `max_dias` 84 y 15 |
| Art. 155 | Jornada de lactancia de 6 horas durante 12 meses | `permission_types.lactancia` con `max_horas` 2 |

## Otras normas

| Norma | Exigencia | Implementación |
|---|---|---|
| Ley Orgánica de Discapacidades Art. 49 | 2 horas diarias por cuidado de persona con discapacidad severa | `cuidado_discapacidad`, `family_members.tiene_discapacidad` |
| Código de la Democracia | Permiso para sufragar sin descuento | `permission_types.sufragio` |
| COGEP Art. 53 | Deber de comparecer a citación judicial | `permission_types.citacion_judicial` |
| Ley Orgánica de Salud Art. 79 | Permiso para donación de sangre | `permission_types.donacion_sangre` |

## LOPDP — Ley Orgánica de Protección de Datos Personales

| Artículo | Exigencia | Implementación |
|---|---|---|
| Art. 4 | Los datos de salud y discapacidad son **sensibles** | `users.tiene_discapacidad` y `family_members` fuera del alcance del jefe: solo el titular y Talento Humano (RLS) |
| Art. 7 | Consentimiento libre, específico e informado | `data_consents` con versión de política, finalidad, fecha e IP |
| Art. 10 | Minimización, conservación limitada | No se almacena salario ni datos no usados; `aplicar_retencion()` purga bitácoras según `app_config` |
| Art. 12-16 | Derechos ARCO, plazo de 15 días | `data_subject_requests` con `vence_en = created_at + 15 días` |
| Art. 37 | Cifrado y medidas técnicas | OTP guardado solo como hash SHA-256; buckets privados; TLS de Supabase; RLS por rol |

## ISO/IEC 27001:2022

| Control | Implementación |
|---|---|
| A.5.15 Control de acceso | RLS por rol en todas las tablas; mínimo privilegio; `anon` sin acceso a `users` |
| A.5.34 Privacidad | Ver sección LOPDP |
| A.8.12 Prevención de fuga de datos | Buckets privados con política por carpeta; vistas de garita sin columnas sensibles |
| A.8.15 Registro de eventos | `audit_logs` y `access_logs` **inmutables** por trigger; `UPDATE`/`DELETE` revocados |
| A.8.16 Actividades de seguimiento | Alertas automáticas y vistas de resumen para Talento Humano |

## ISO 9001:2015

| Cláusula | Implementación |
|---|---|
| 8.5.2 Identificación y trazabilidad | Cada solicitud tiene UUID, historial de estados en `audit_logs`, firmas con hash congelado y bitácora de uso del QR |
| 9.1 Seguimiento y medición | `v_trazabilidad_empleado` y `v_resumen_general` (aprobadas/rechazadas, % de aprobación, días por departamento y mes) |

## Pendiente de decisión de la empresa

- **Registro ante la Superintendencia de Protección de Datos Personales**: obligación del responsable del tratamiento, no del software.
- **Política de tratamiento de datos** publicada y aceptada por cada empleado: el sistema ya registra la aceptación (`data_consents`), falta el texto oficial aprobado por la empresa.
- **Delegado de protección de datos**: la LOPDP lo exige para ciertos responsables; verificar si aplica a ITSANET.
