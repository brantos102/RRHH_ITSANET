# Migración a MySQL 8.0 en el servidor corporativo

Decisión de RI y TI: **MySQL 8.0 en un servidor Linux, publicado con
Apache.** El backend Python se conserva detrás de Apache como proxy inverso.
Se trasladan los datos actuales y todo lo tramitado: solicitudes,
aprobaciones y bitácora de auditoría.

Este documento dice cómo se hace, qué cambia y cómo se comprueba que nada se
rompió. Está escrito para quien ejecuta la migración y para TI.

---

## 1. El principio que guía todo

**Las pruebas automáticas son el contrato.** El sistema actual tiene 723
pruebas que describen cada regla: cuántos días le tocan a quien lleva siete
años, que una solicitud aprobada no cambie de fechas, que la constancia de
goce se emita una sola vez, que el jefe no vea el historial completo de su
equipo. La versión MySQL está terminada cuando pasa esas mismas pruebas.
No antes.

Y donde una regla se reescribe, se compara contra la original: el mismo
cálculo se ejecuta en PostgreSQL y en la versión nueva, con los mismos
datos, y tiene que dar lo mismo.

---

## 2. Cómo se organiza el código durante la migración

```
backend/      PostgreSQL. NO SE TOCA. Sigue funcionando hasta el día del corte.
supabase/     Las 46 migraciones de PostgreSQL. Referencia, no se modifican.
servidor/     NUEVO. El backend para MySQL. Es lo que se instala en el servidor.
mysql/        NUEVO. El esquema de MySQL y el traslado de datos.
despliegue/   NUEVO. Apache, el servicio del sistema y la guía para TI.
frontend/     Sin cambios. Habla con la API, no con la base.
```

Durante la migración conviven dos backends. Es deliberado: el sistema actual
tiene que poder seguir usándose y actualizándose (`git pull`) sin romperse
mientras TI prepara el servidor. El día del corte, `backend/` y `supabase/`
se archivan en un solo cambio.

**La interfaz no cambia.** Las pantallas hablan con la API, y la API
conserva exactamente las mismas rutas y respuestas.

---

## 3. Dónde vive cada regla

En PostgreSQL buena parte de la lógica vive en la base: 89 funciones y 17
disparadores. MySQL tiene disparadores y procedimientos, pero su lenguaje es
más limitado y no admite lo que el sistema usa (funciones que devuelven
tablas, disparadores diferidos hasta el final de la transacción). La
división queda así:

| Qué | Dónde queda | Por qué |
|---|---|---|
| Estructura: claves, únicos, foráneas, `CHECK`, no nulos | **MySQL** | Son invariantes: tienen que valer escriba quien escriba |
| Bitácoras inmutables (auditoría y garita) | **MySQL**, disparador | Que nadie pueda editar el registro, ni desde la aplicación ni desde fuera |
| Fecha de última modificación | **MySQL**, `ON UPDATE CURRENT_TIMESTAMP` | Nativo, sin disparador |
| Reglas de solicitudes: días, saldo, ruta, estados | **Python**, en la misma transacción | Lógica extensa y entrelazada; en Python se lee, se prueba y se depura |
| Cálculos que devuelven estructuras (saldo explicado, tablero, papeles) | **Python** | MySQL no devuelve tablas desde una función |
| Requisitos al confirmar (adjuntos) | **Python**, antes del `commit` | MySQL no tiene disparadores diferidos |

Las reglas en Python **no** se pueden saltar desde la aplicación, pero sí
desde fuera escribiendo directamente en la base. Por eso la base tiene que
quedar cerrada a la red y el usuario del backend con los permisos justos
(sección 8).

---

## 4. Traducción de tipos

| PostgreSQL | MySQL 8.0 | Nota |
|---|---|---|
| `uuid` | `CHAR(36)` | Legible en phpMyAdmin o Workbench. El volumen no justifica optimizar. |
| `citext` (correos) | `VARCHAR` con colación `utf8mb4_0900_ai_ci` | Ignora mayúsculas **y tildes** al comparar |
| Enumerados (14 tipos) | `VARCHAR` + `CHECK (... IN (...))` | Añadir un valor es una línea, no recrear el tipo |
| `jsonb` | `JSON` | |
| Arreglos (`roles[]`) | `JSON` | |
| `timestamptz` | `DATETIME(6)` en hora de Ecuador | Ver sección 5 |
| `numeric` | `DECIMAL` | Mismos decimales |
| Columna generada `dias_saldo` | Columna generada `STORED` | Nativo |
| Índices parciales de rendimiento (21) | Índices normales | Con 351 personas la diferencia no existe |
| Índices **únicos** parciales (3) | Columna generada + índice único | Son reglas de negocio: se conservan exactas |

Los tres índices únicos parciales que son reglas y no rendimiento:

- un solo contacto de emergencia **principal** por persona,
- una sola firma **activa** por persona,
- una sola **constancia de goce** sin autorización por persona.

---

## 5. Hallazgo: la fecha de «hoy» del sistema actual

**El sistema actual tiene un defecto que la migración corrige.** El backend
no fija zona horaria y Supabase trabaja en UTC. Para la base, el día
empieza a las **19:00 de Ecuador**. Entre las 7 de la noche y la medianoche:

- el panel de garita muestra los permisos de **mañana**,
- los plazos de anticipación se cuentan con un día de diferencia,
- el indicador «fuera hoy» cuenta a quienes salen mañana.

En MySQL cada conexión fija la hora de Ecuador (`-05:00`; Ecuador no tiene
horario de verano), y las fechas se guardan en hora local, que es como las
lee cualquiera que abra la base.

---

## 6. Hallazgo: el juego de caracteres

Probado en este servidor de pruebas: si el cliente que se conecta a MySQL no
declara `utf8mb4`, **los nombres con tilde se corrompen al guardarse, sin
ningún error**. «Suárez» queda guardado mal y después no aparece al buscar
«suarez». El backend fija `utf8mb4` en cada conexión, y hay una prueba que
lo comprueba con nombres reales con tildes y eñes.

Lo mismo vale para cualquier herramienta que TI use contra esta base
(phpMyAdmin, Workbench, importaciones manuales): tiene que estar en
`utf8mb4`.

---

## 7. Fases

| # | Fase | Se da por terminada cuando |
|---|---|---|
| 1 | Esquema MySQL | Las 38 tablas se crean y cada restricción rechaza lo que debe rechazar |
| 2 | Capa de datos | Booleanos, fechas, tildes y errores salen igual que en PostgreSQL |
| 3 | Lógica de negocio a Python | Cada cálculo da lo mismo que su original en PostgreSQL |
| 4 | Vistas y consultas | Cada ruta responde lo mismo |
| 5 | Pruebas | **Las 723 pruebas pasan contra MySQL** |
| 6 | Traslado de datos | Conteos y sumas de saldo idénticos entre origen y destino |
| 7 | Despliegue | El sistema responde por HTTPS detrás de Apache en el servidor de TI |
| 8 | Corte | Ver sección 9 |

---

## 8. Lo que TI tiene que preparar

- **Servidor Linux** con Apache 2.4 y MySQL 8.0.
- **Python 3.11** o superior.
- **Una base** `rrhh` en `utf8mb4` / `utf8mb4_0900_ai_ci`.
- **Un usuario MySQL para el backend** con permisos solo sobre esa base, y
  solo `SELECT, INSERT, UPDATE, DELETE, EXECUTE`. Sin `DROP`, `ALTER`,
  `GRANT` ni acceso a otras bases.
- **Un usuario MySQL aparte para instalar y migrar el esquema**, que se
  usa solo durante la instalación.
- **MySQL escuchando solo en `127.0.0.1`.** La base no debe ser alcanzable
  desde la red: así nadie puede saltarse los controles de la aplicación.
- **Certificado TLS** y un nombre interno (por ejemplo
  `rrhh.itsanet.local`).
- **Una carpeta para los adjuntos**, fuera de la carpeta pública de Apache.
- **Respaldo diario** de la base y de la carpeta de adjuntos.

La guía paso a paso está en `despliegue/`.

---

## 9. El día del corte

1. Aviso a los usuarios: el sistema se detiene durante el traslado.
2. Respaldo final de Supabase.
3. Traslado de datos a MySQL, con el informe de conteos y sumas.
4. Carga de los datos actuales de vacaciones que entregue Talento Humano.
5. Verificación: el informe de traslado sin diferencias y las pruebas de
   humo en el servidor.
6. Apache empieza a atender. Supabase queda en solo lectura como respaldo
   durante el período que RI determine, y después se da de baja.

**Si algo falla en el paso 5, no se abre el servicio.** Se vuelve al sistema
anterior, que sigue intacto, y se corrige con calma.
