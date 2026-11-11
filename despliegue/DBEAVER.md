# Revisar la base desde DBeaver

Cómo ver la base `rrhh` del servidor desde DBeaver en Windows, sin abrir MySQL a
la red y sin tocar nada de otros sistemas.

## Cómo está armado el acceso

| Qué | Dónde escucha | Quién entra |
|---|---|---|
| Web del sistema (Apache, HTTPS) | `192.168.4.94:8444` | la red interna de la empresa |
| API del sistema (uvicorn) | `127.0.0.1:8010` | solo Apache, dentro del servidor |
| MySQL 8.0 | `127.0.0.1:3306` | solo programas del propio servidor |
| SSH | `192.168.4.94:22` | usuarios del servidor (`enicolalde`) |

MySQL **no** está abierto a la red, y así debe quedarse: los datos de los
colaboradores no deben viajar sin cifrar por la red de la oficina. DBeaver entra
por un **túnel SSH**: se conecta al servidor por el puerto 22 (cifrado) y desde
allí habla con MySQL en `127.0.0.1:3306`, como si estuviera dentro del servidor.

Puertos que no se tocan: 3000, 3002, 8000, 8080, 8443 (otros sistemas) y la
base `iv_itsanet` (IV ITSANET).

## Paso 1: ver qué hay abierto (en el servidor)

En la terminal de VS Code conectada al servidor (`enicolalde@apps`):

```bash
cd ~/bryan/RRHH_ITSANET
git pull
bash despliegue/accesos.sh
```

Solo mira, no cambia nada. Muestra los puertos que escuchan, los servicios, cómo
está configurado MySQL (`bind_address`), qué usuarios tienen permiso sobre `rrhh`
y si alguna cuenta de MySQL puede entrar desde fuera. Lo correcto:

- `3306` en `127.0.0.1` (no `0.0.0.0`).
- `8010` en `127.0.0.1`.
- «Cuentas que pueden entrar desde fuera del servidor: ninguna».

## Paso 2: crear el usuario de solo lectura (una sola vez)

Para mirar no se usa `root` ni `rrhh_app` (el usuario de la aplicación, que puede
modificar datos). Se crea uno que **solo puede leer** la base `rrhh`:

```bash
bash despliegue/usuario_lectura.sh
```

Le pide la clave de `sudo` y muestra **una sola vez** la clave de `rrhh_lectura`.
Escríbala directamente en DBeaver (paso 3) y luego limpie la pantalla con `clear`.
No la pegue en chats, correos ni documentos. Si la pierde:
`bash despliegue/usuario_lectura.sh --nueva-clave`.

Qué puede `rrhh_lectura`: `SELECT` y `SHOW VIEW` sobre `rrhh`. No escribe, no
borra, no ve `iv_itsanet` ni ninguna otra base, y solo se conecta desde el propio
servidor.

## Paso 3: la conexión en DBeaver (en Windows)

1. **Base de datos → Nueva conexión → MySQL → Siguiente.**
2. Pestaña **Principal**:
   - Servidor: `127.0.0.1` (sí, local: es el extremo del túnel en el servidor).
   - Puerto: `3306`.
   - Base de datos: `rrhh`.
   - Usuario: `rrhh_lectura`.
   - Contraseña: la del paso 2. Si marca «Guardar contraseña», ponga antes una
     contraseña maestra en DBeaver (Ventana → Preferencias → Seguridad → «Usar
     contraseña maestra»), para que no quede legible en el equipo.
3. Pestaña **SSH** (o «Túneles SSH»): marque **Usar túnel SSH**.
   - Host: `192.168.4.94`, puerto `22`.
   - Usuario: `enicolalde`.
   - Autenticación: la misma con que entra VS Code (contraseña o llave).
4. **Propiedades del controlador** (pestaña «Driver properties»), si al probar
   sale «Public Key Retrieval is not allowed»: ponga `allowPublicKeyRetrieval`
   en `true`. Es seguro aquí porque todo va dentro del túnel SSH.
5. **Configuración general de la conexión**:
   - Nombre: `RRHH ITSANET (solo lectura)`.
   - Tipo de conexión: **Producción** (DBeaver la marca en rojo y pide
     confirmación antes de ejecutar).
   - Marque **Solo lectura** («Read-only connection»).
6. **Probar conexión → Finalizar.**

Si DBeaver pide descargar el controlador de MySQL, acepte (se descarga en su
Windows, no en el servidor).

## Paso 4: qué mirar

Consultas listas en `mysql/depuracion/01_revisar.sql` (ábralo en DBeaver con
Archivo → Abrir). Algunas útiles:

```sql
-- Tablas y cuántas filas tiene cada una (aproximado).
SELECT table_name, table_rows FROM information_schema.tables
 WHERE table_schema = 'rrhh' ORDER BY table_name;

-- Las relaciones (claves foráneas) entre tablas.
SELECT table_name, column_name, referenced_table_name, referenced_column_name
  FROM information_schema.key_column_usage
 WHERE table_schema = 'rrhh' AND referenced_table_name IS NOT NULL
 ORDER BY table_name;

-- Migraciones aplicadas.
SELECT * FROM rrhh.schema_migraciones ORDER BY 1;

-- Colaboradores activos por sede.
SELECT region, ciudad, COUNT(*) FROM rrhh.users WHERE activo GROUP BY region, ciudad;
```

Para el diagrama de relaciones: en el panel de la izquierda, clic derecho sobre
`rrhh` → **Ver diagrama** (pestaña «ER Diagram»).

## Corregir datos

`rrhh_lectura` no puede. Las correcciones se hacen, en este orden de preferencia:

1. Desde el propio sistema (pantallas de Talento Humano y Administración), que
   valida y deja constancia en la bitácora.
2. Con los scripts del repositorio (`mysql/saldos.py`, `mysql/cargar_personas.py`,
   ver `despliegue/COMANDOS.md`), que primero muestran y solo con `--aplicar`
   cambian.
3. A mano en SQL, solo si no hay otra vía, siguiendo `mysql/depuracion/00_LEER_PRIMERO.sql`
   (siempre dentro de una transacción) y con respaldo previo
   (`despliegue/COMANDOS.md`, sección de respaldo).

## Protección de datos (LOPDP)

- Esta conexión ve cédulas, correos, fechas de nacimiento y saldos de todos los
  colaboradores. Es del responsable técnico: no se comparte la clave ni la
  conexión.
- No exporte tablas a Excel o CSV salvo que haga falta, y si hace falta,
  guárdelos solo en la carpeta de trabajo de Windows o en `~/bryan/rrhh_datos/`,
  nunca en el repositorio, el correo personal ni nubes personales.
- Cuando ya no la necesite: `bash despliegue/usuario_lectura.sh --quitar`.
