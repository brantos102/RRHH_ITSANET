# Infraestructura: qué hace falta de verdad

Documento de ingeniería para decidir servidores, alojamiento y plataforma.
Las cifras están medidas sobre la copia real de la planilla (351 personas,
3.298 vacaciones históricas), no estimadas. Los precios son órdenes de
magnitud para pedir cotizaciones, no cotizaciones.

Fecha: 12 de octubre de 2026.

---

## 1. La respuesta corta

**Sí, hace falta un servidor. Uno.** No un clúster, no tres máquinas, no
Kubernetes. Este sistema es pequeño en cómputo y delicado en datos: lo caro
aquí no es la capacidad, es la custodia.

Y hace falta decidir **dónde viven los datos de 350 personas reales**, que es
la decisión que de verdad cuesta deshacer.

---

## 2. Qué hay hoy, y qué se rompe

Hoy el sistema corre así:

| Pieza | Dónde está hoy | Qué pasa si falla |
|---|---|---|
| Base de datos | Supabase (nube, fuera del Ecuador) | Nadie entra, ni la garita |
| Archivos adjuntos | Supabase Storage | No se suben respaldos |
| Backend (FastAPI) | Su computador de trabajo | El sistema no existe |
| Interfaz (HTML/JS) | Su computador de trabajo | Nadie entra |
| Correo de códigos | SMTP corporativo | Nadie puede iniciar sesión |

Tres problemas, en orden de gravedad:

1. **El sistema vive en un computador personal.** Si usted apaga esa máquina,
   se va de vacaciones o le cambian el equipo, se cae para 351 personas. No
   es una hipótesis: ya pasó durante las pruebas.
2. **Los datos personales de 350 ecuatorianos están en una nube extranjera.**
   La LOPDP permite la transferencia internacional, pero con condiciones
   (Arts. 56 a 62: país con nivel adecuado, o garantías contractuales
   documentadas). Hoy no hay ese documento. Es exactamente lo que usted viene
   repitiendo que hay que proteger.
3. **La garita depende de internet.** Si se cae el enlace, el guardia no
   puede validar un código QR. El puesto de garita es lo único del sistema
   que opera siete días a la semana y lo único que no puede esperar.

---

## 3. Cuánto pesa esto de verdad

Medido, no estimado:

```
Base de datos completa, con todo cargado ......... 15 MB
  users (351 personas) .......................... 1,9 MB
  vacaciones_historicas (3.298 registros) ....... 0,9 MB
  vacation_periods .............................. 0,7 MB
  todo lo demás ................................. 11 MB
```

Proyección de crecimiento, con supuestos declarados:

| Qué crece | Supuesto | Al año |
|---|---|---|
| Solicitudes | 351 personas × 6 trámites | ~2 MB |
| Bitácora de auditoría | retención 7 años, todo auditado | ~6 MB |
| Bitácora de garita | retención 2 años, solo permisos | ~1 MB |
| Períodos de vacaciones | 351 nuevos al año | < 1 MB |

**La base de datos no llega a 150 MB en diez años.** Cabe diez veces en una
memoria USB de regalo. Cualquier conversación sobre «capacidad de base de
datos» en este proyecto es una conversación equivocada.

Lo único que crece de verdad son **los archivos adjuntos**: certificados
médicos, partidas, respaldos. Con 351 personas y tres adjuntos al año de
1,5 MB cada uno son **~1,6 GB al año**; con la retención de siete años de la
bitácora, unos **12 GB**. Un disco de 500 GB sobra con holgura para una
década.

**Concurrencia real.** 351 colaboradores no son 351 usuarios simultáneos.
Alguien pide vacaciones dos o tres veces al año; un jefe aprueba cuando le
llega el aviso. El pico realista son 20 a 30 sesiones a la vez, más la garita
con una o dos terminales. Eso lo atiende de sobra un servidor modesto.

---

## 4. ¿Necesita servidores? Sí: uno. Las tres formas de tenerlo

### Opción A — Un servidor propio en ITSANET (recomendada)

Una máquina en la oficina, en la red de la empresa.

**A favor**
- Los datos no salen de la empresa ni del país. Desaparece el problema de
  transferencia internacional de la LOPDP: no hay transferencia.
- **La garita sigue funcionando con el internet caído.** Está en la misma
  red; el QR se valida contra un servidor que está a veinte metros.
- Sin cuota mensual. Se paga una vez.
- El control físico del expediente laboral es de la empresa, que es de quien
  legalmente tiene que ser.

**En contra**
- ITSANET se hace cargo: respaldos, corriente (UPS), actualizaciones del
  sistema operativo, seguridad física del cuarto.
- Quien esté fuera de la oficina necesita VPN o publicar el servicio con
  cuidado. No es difícil; es trabajo que alguien tiene que hacer.
- Si se quema el equipo, el reemplazo lo consigue usted.

**Qué comprar** (suficiente, sin exagerar):

| | Mínimo | Holgado (recomendado) |
|---|---|---|
| CPU | 4 núcleos | 8 núcleos |
| RAM | 8 GB | 16 GB |
| Disco | 250 GB SSD | 2 × 500 GB SSD en espejo |
| Red | 1 Gb | 1 Gb |
| Energía | UPS 1 kVA | UPS 1,5 kVA |

Un servidor de torre de entrada o incluso un mini-PC de nivel empresarial
cubre esto. Orden de magnitud: **USD 900 a 2.000** el equipo, más la UPS.
Pida al menos tres cotizaciones; no compre el de 6 núcleos y 64 GB que le van
a ofrecer, porque este sistema no lo va a usar.

### Opción B — Una máquina virtual en la nube

Un VPS pequeño (2 vCPU, 4 GB RAM, 80 GB SSD).

**A favor**: sin hardware que mantener, energía y red de centro de datos,
acceso desde cualquier parte, instantáneas para respaldo.

**En contra**: cuota mensual (orden de **USD 10 a 30 al mes** según
proveedor); **los datos salen del país**, con lo que el requisito de la LOPDP
sigue vigente y hay que documentarlo; y **la garita deja de operar si se cae
el enlace**, que es el peor momento posible.

### Opción C — Propio + respaldo en la nube (lo que yo haría)

El servidor en ITSANET atiende todo. Los respaldos cifrados se copian cada
noche fuera de la oficina. Es la Opción A sin su único riesgo serio, que es
perder el equipo y los datos a la vez.

Costo adicional: el almacenamiento de respaldos, unos pocos dólares al mes.

---

## 5. La decisión que está detrás: salir de Supabase

Esta es la misma pregunta que la del motor de base de datos, y conviene verla
junta.

Hoy Supabase da tres cosas: PostgreSQL, el almacenamiento de adjuntos y el
secreto con el que se firman las sesiones. Las tres se pueden tener en el
servidor propio:

| Hoy | En el servidor propio |
|---|---|
| PostgreSQL de Supabase | PostgreSQL 16, el mismo motor |
| Supabase Storage | Carpeta en disco, o MinIO si quiere la misma API |
| Secreto JWT de Supabase | Un secreto generado por usted |

La migración de los datos es `pg_dump` y `psql`: **una tarde**, porque es el
mismo motor y no se traduce nada.

### Sobre migrar a MySQL

Usted preguntó si hay que reimplementar la base o si se puede migrar. La
respuesta medida, hoy, sobre el sistema real:

```
funciones en la base ......................... 172
vistas ....................................... 39
políticas de seguridad por fila (RLS) ........ 55
tipos enumerados ............................. 14
disparadores ................................. 26
índices parciales ............................ 24
migraciones .................................. 45
líneas de SQL ............................ 11.665
```

**Mover los datos a MySQL es fácil. Mover las reglas, no: hay que
reescribirlas.** Y el punto que decide:

> **MySQL no tiene seguridad por fila.** Las 55 políticas que hoy impiden que
> un colaborador lea el expediente de otro desaparecerían del motor y habría
> que reescribirlas dentro del programa. Eso es precisamente donde se escapan
> los datos: basta una consulta sin el filtro para que alguien vea lo que no
> debe, y no hay nada debajo que lo detenga.

También faltarían en MySQL: los índices parciales, los arreglos, los
disparadores diferidos, las funciones que devuelven tablas y la forma en que
se usa `jsonb`. No son detalles de estilo: son el andamiaje sobre el que está
construido el cálculo de derechos de 351 personas.

**Mi recomendación como responsable del proyecto: no migre a MySQL.** Si el
motivo era dejar de depender de Supabase, eso se resuelve con PostgreSQL
propio, en una tarde, sin tocar una línea de lógica. Si el motivo es que el
estándar de la empresa es MySQL, dígamelo y presupuestamos la reescritura
honestamente: son semanas de trabajo y una pérdida neta de seguridad, y hay
que decidirlo sabiendo eso.

---

## 6. Si es la plataforma de varios proyectos de RI

Esto cambia el dimensionamiento, no la arquitectura. Un servidor como el de
la Opción A aloja cómodamente varias aplicaciones internas de este tamaño.
Lo que hay que montar una sola vez:

1. **Un contenedor por aplicación** (Docker Compose). Cada proyecto con sus
   dependencias, sin que la versión de Python de uno rompa la del otro. Este
   proyecto todavía no tiene `Dockerfile`; es trabajo de medio día y lo deja
   listo para esto.
2. **Un PostgreSQL, una base de datos por aplicación.** No un motor por
   proyecto: uno solo, con usuarios y bases separadas.
3. **Un proxy inverso con HTTPS** (Caddy saca los certificados solo, nginx si
   prefiere lo conocido). Además de ordenar, resuelve un problema real que ya
   nos mordió: sobre `http://` a una IP de la red, el navegador **desactiva**
   `crypto.randomUUID`, la cámara y el portapapeles. Con HTTPS todo eso
   vuelve a funcionar.
4. **Respaldos automáticos y verificados.** Un respaldo que nunca se restauró
   no es un respaldo. Una restauración de prueba al trimestre.
5. **Un registro central de lo que pasa** (sin inventar nada: `journald` y
   rotación bastan al principio).

Con eso, el servidor pasa de ser «la máquina de RRHH» a ser la plataforma
interna, y el sexto proyecto se despliega igual que el primero.

Si van a convivir cinco o seis aplicaciones, vaya al **16 GB de RAM y los dos
discos en espejo**. La diferencia de precio es menor que una tarde de
reinstalar todo.

---

## 7. Lo que hace falta sí o sí, con cualquier opción

Esto no es opcional ni negociable, y es más importante que la marca del
servidor:

- **HTTPS.** Hoy se entra por `http://` a una IP. Las contraseñas de un solo
  uso y las sesiones viajan en claro por la red de la empresa.
- **Respaldo diario, cifrado y fuera del equipo.** Con una prueba de
  restauración cada tres meses.
- **UPS.** Un corte de luz a mitad de una escritura corrompe la base.
- **Actualizaciones de seguridad del sistema operativo**, con alguien
  responsable y una fecha.
- **Un segundo administrador.** Hoy el conocimiento del sistema está en una
  sola cabeza, y eso es un riesgo de continuidad tan real como el hardware.
- **El registro de actividades de tratamiento de la LOPDP** (Art. 40), que es
  un documento, no un programa, y hoy no existe.

---

## 8. Plan por fases

| Fase | Qué | Esfuerzo | Cuándo |
|---|---|---|---|
| 1 | Sacar el sistema del computador personal a un servidor, aunque sea prestado | 1 día | ya |
| 2 | HTTPS con certificado y nombre interno | medio día | con la fase 1 |
| 3 | PostgreSQL propio; dejar de depender de Supabase | 1 día | semana siguiente |
| 4 | Respaldos automáticos + primera restauración de prueba | 1 día | con la fase 3 |
| 5 | `Dockerfile` y Compose para desplegar igual siempre | medio día | después |
| 6 | Servidor definitivo comprado y migración | según compra | cuando llegue |

Las fases 1 a 4 se pueden hacer sobre cualquier máquina decente que haya hoy
en la empresa. No espere a la compra para dejar de depender de su
computador: eso es lo urgente.

---

## 9. Lo que yo decidiría

1. Un servidor propio en ITSANET, 8 núcleos / 16 GB / dos discos en espejo,
   con UPS. Opción A.
2. Respaldos cifrados fuera de la oficina. Opción C.
3. PostgreSQL propio. **No** MySQL.
4. HTTPS desde el primer día.
5. Docker Compose para que el sexto proyecto de RI se despliegue como el
   primero.

La inversión está dominada por una compra de orden de **USD 1.500 a 2.500**
una sola vez, más unos dólares al mes de respaldo. Para un sistema que
sostiene el expediente laboral de 351 personas, es barato; lo que sale caro
es la alternativa de dejarlo donde está.
