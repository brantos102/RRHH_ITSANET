# Informe para Infraestructura

**Sistema Integrado de Permisos, Vacaciones y Control de Garita**
ITSANET · 13 de octubre de 2026

Objeto: informar el funcionamiento y las conexiones del sistema para que
Infraestructura valide el tratamiento y la protección de los datos.

Las cifras de este informe están medidas sobre la base real, no estimadas.

---

## 1. Qué es y a quién afecta

Sistema interno que gestiona permisos, vacaciones y el control de salidas en
garita. **Alcance actual: 351 colaboradores activos**, toda la nómina.

Sustituye hojas de cálculo que llevaba Talento Humano. No es un piloto: ya
contiene el expediente de vacaciones de toda la plantilla (3.298 registros
históricos cargados) y es la fuente con la que se autorizan ausencias.

---

## 2. Arquitectura y conexiones

Cuatro componentes:

| Componente | Tecnología | Dónde corre hoy |
|---|---|---|
| Interfaz | HTML + JavaScript (sin framework) | Navegador del colaborador |
| Backend | Python 3.11 / FastAPI | Estación de trabajo del responsable |
| Base de datos | **PostgreSQL 16 en Supabase** | Nube, fuera del Ecuador |
| Almacenamiento de adjuntos | Supabase Storage (buckets privados) | Nube, fuera del Ecuador |

### Conexiones salientes y entrantes

| Origen | Destino | Protocolo / puerto | Qué viaja | Credencial |
|---|---|---|---|---|
| Navegador | Backend | HTTP **sin TLS**, 8000 | Sesión, datos de ficha, solicitudes | JWT en cabecera |
| Backend | Supabase (PostgreSQL) | TLS, 6543 (pooler) | Todas las consultas | Usuario y contraseña (`DATABASE_URL`) |
| Backend | Supabase Storage | HTTPS, 443 | Adjuntos (certificados, respaldos) | Clave de servicio |
| Backend | SMTP corporativo | STARTTLS, 587 | Códigos de acceso y avisos | Usuario y contraseña |
| Garita | Backend | HTTP sin TLS, LAN | Lectura de códigos QR | JWT de perfil guardia |

**No hay puertos publicados a Internet.** El acceso es por red interna.

El origen permitido está restringido por CORS a direcciones declaradas; los
métodos habilitados son GET, POST, PATCH, DELETE y OPTIONS.

---

## 3. Qué datos se tratan

38 tablas. Las categorías, según la Ley Orgánica de Protección de Datos
Personales (LOPDP):

**Datos identificativos y de contacto**
Cédula, nombre, fecha de nacimiento, género, estado civil, dirección,
teléfonos, correo, fotografía.

**Datos laborales**
Cargo, departamento, bodega, centro de costo, cliente, fecha de ingreso y de
salida, motivo de salida según el Código del Trabajo, jefe inmediato, saldo
de vacaciones, historial de ausencias.

**Datos sensibles (LOPDP, Art. 4)** — requieren el tratamiento más estricto
- Campos de **salud y discapacidad**: tipo de sangre, condición de
  discapacidad, porcentaje, carné del CONADIS.
  *Hoy sin usar: 0 registros en ambos campos.* Existen en el modelo porque la
  ley de inclusión los exige para el cálculo de la cuota.
- **Adjuntos de solicitudes**: certificados médicos y documentos de respaldo.
  Es la vía por la que entra información de salud al sistema.

**Datos de registro**
Bitácora de auditoría (quién hizo qué y cuándo), bitácora de accesos de
garita, direcciones IP, registro de errores.

---

## 4. Controles de protección vigentes

Lo que ya está implementado y es verificable en la base:

| Control | Estado medido |
|---|---|
| Seguridad por fila (RLS) | **Activa en las 38 tablas, 55 políticas** |
| Bitácora de auditoría | 15 tipos de acción registrados; retención 84 meses (7 años) |
| Bitácora de accesos de garita | Retención 24 meses |
| Autenticación | **Sin contraseñas.** Cédula + código de un solo uso de 6 dígitos al correo institucional |
| Vigencia del código | 10 minutos · máx. 5 intentos · máx. 5 envíos por hora |
| Sesión | JWT firmado HS256, caduca a las 8 horas |
| Perfiles | admin, rrhh, jefe, empleado, guardia |
| Segregación territorial | Talento Humano ve solo su región (Sierra / Costa) |
| Adjuntos | Buckets privados, no públicos |
| Minimización | El tablero de indicadores entrega solo agregados: ningún nombre ni cédula |
| Jefe inmediato | No accede al historial completo del colaborador, solo a lo que debe autorizar |

**Sin contraseñas es una decisión de diseño**, no una carencia: no hay
credenciales que robar, reutilizar ni que el colaborador apunte en un papel.
La identidad se acredita contra el buzón institucional, que ya administra
Infraestructura.

---

## 5. Brechas conocidas

Se declaran abiertamente porque son justamente lo que Infraestructura debe
resolver o aceptar:

| # | Brecha | Riesgo | Prioridad |
|---|---|---|---|
| 1 | **Tráfico sin TLS.** Se accede por `http://` a una IP de la red | Los códigos de acceso y las sesiones viajan en claro por la LAN | Alta |
| 2 | **El sistema corre en una estación de trabajo personal** | Si se apaga ese equipo, el servicio cae para 351 personas | Alta |
| 3 | **Sin respaldos automáticos ni verificados** del lado de la empresa | Dependencia total del respaldo del proveedor | Alta |
| 4 | **Datos personales alojados fuera del Ecuador**, sin el documento de garantías de transferencia internacional (LOPDP, Arts. 56 a 62) | Incumplimiento documental | Alta |
| 5 | **Sin registro de actividades de tratamiento** (LOPDP, Art. 40) | Es un documento, no software; hoy no existe | Media |
| 6 | **Un solo administrador** con conocimiento del sistema | Continuidad operativa | Media |
| 7 | **225 de 351 colaboradores sin correo** que reciba avisos | No pueden recibir el código y dependen de Talento Humano para entrar | Media |

---

## 6. Base de datos: estado actual y plan

### Cómo se construyó

**La base de datos completa se creó sobre Supabase** (PostgreSQL 16
administrado): tablas, vistas, funciones, disparadores y políticas de
seguridad. El esquema está versionado en el repositorio en **46 migraciones
SQL** que se aplican en orden, y está comprobado que reconstruyen la base
desde cero de forma idéntica, objeto por objeto.

Tamaño actual: **15 MB** con toda la nómina y el histórico cargados.
Proyección: no supera los 150 MB en diez años. El crecimiento real está en
los adjuntos, estimado en **1,6 GB anuales**.

### Plan en curso

**Actualmente se trabaja en la migración del motor a MySQL.** El objetivo es
alinear el sistema al estándar de la empresa y dejar de depender de un
proveedor en la nube.

### Implicaciones técnicas que Infraestructura debe conocer

Se exponen para que la validación de protección de datos se haga con la
información completa:

1. **MySQL no dispone de seguridad por fila.** Las 55 políticas que hoy
   impiden, en el propio motor, que un colaborador consulte el expediente de
   otro tendrían que reimplementarse en el código de la aplicación. El
   control pasa de la base a la aplicación: sigue siendo posible, pero deja
   de existir la última barrera si una consulta se escribe sin el filtro.
2. **Volumen de reescritura**: 172 funciones, 39 vistas, 14 tipos
   enumerados, 26 disparadores, 24 índices parciales y 11.665 líneas de SQL.
   Los datos se migran sin dificultad; la lógica se reescribe.
3. **Alternativa a considerar**: si el motivo principal es dejar de depender
   del proveedor en la nube, trasladar el mismo PostgreSQL a un servidor
   propio lo consigue sin reescribir lógica ni perder controles.

La decisión corresponde a la dirección del proyecto. Lo que se solicita de
Infraestructura es que la tome **conociendo el efecto sobre los controles de
protección de datos**, y que si se confirma MySQL se planifique la
reimplementación de los 55 controles de acceso como parte del alcance.

---

## 7. Qué se solicita a Infraestructura

1. **Un servidor para alojar el sistema**, fuera de la estación de trabajo
   personal. Es lo más urgente.
2. **Certificado TLS y nombre interno** para publicar por HTTPS.
3. **Política de respaldo**: diario, cifrado, fuera del equipo, con prueba de
   restauración trimestral.
4. **Validación del tratamiento de datos personales** y, si el alojamiento
   sigue en el exterior, el documento de garantías de transferencia
   internacional.
5. **Cuentas de correo institucional** para los 225 colaboradores que no las
   tienen, o la validación del mecanismo alternativo de acceso.
6. **Un segundo responsable técnico** designado, por continuidad.
7. **Pronunciamiento sobre el motor de base de datos**, conforme a la
   sección 6.

---

## 8. Resumen para la decisión

El sistema está **funcionando y en uso con la nómina completa**. Sus
controles de acceso, auditoría y minimización están implementados y son
verificables.

Lo que falta no es funcionalidad: es **infraestructura y formalización**. Las
tres brechas de prioridad alta —tráfico sin cifrar, alojamiento en una
estación personal y ausencia de respaldo propio— se resuelven con un
servidor, un certificado y una política de respaldo.

---

*Elaborado por la dirección técnica del proyecto. Las cifras son verificables
en la base de datos y en el repositorio del sistema.*
