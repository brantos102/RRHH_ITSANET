# Conectar DBeaver a la base del sistema

Cómo abrir la base `rrhh` del servidor desde DBeaver en Windows, con dos
conexiones:

| Conexión | Usuario MySQL | Para qué |
|---|---|---|
| **RRHH ITSANET (lectura)** | `rrhh_lectura` | Mirar, consultar, exportar. La de todos los días. |
| **RRHH ITSANET (EDICIÓN)** | `rrhh_edicion` | Corregir datos. Solo cuando haga falta, con respaldo previo. |

Ninguna de las dos puede crear, alterar ni borrar tablas, ni ver otras bases del
servidor (IV ITSANET incluida). Las bitácoras siguen protegidas incluso para la
de edición.

## Cómo está armado el acceso

| Qué | Dónde escucha | Quién entra |
|---|---|---|
| Web del sistema (Apache, HTTPS) | `192.168.4.94:8444` | la red interna |
| API del sistema | `127.0.0.1:8010` | solo Apache, dentro del servidor |
| MySQL 8.0 | `127.0.0.1:3306` | solo programas del propio servidor |
| SSH | `192.168.4.94:22` | usuarios del servidor (`enicolalde`) |

MySQL **no** está abierto a la red, y así debe quedarse: los datos del personal
no deben viajar sin cifrar por la red de la oficina. DBeaver entra por un
**túnel SSH**: se conecta al servidor por el puerto 22 (cifrado) y desde ahí
habla con MySQL como si estuviera dentro del servidor. Por eso, en DBeaver, el
servidor de MySQL es `localhost`.

---

## Paso 1 · Crear los usuarios (en el servidor, una sola vez)

En la terminal de VS Code conectada al servidor (`enicolalde@apps`), uno por uno:

```bash
cd ~/bryan/RRHH_ITSANET
```
```bash
git pull
```
```bash
bash despliegue/usuario_bd.sh lectura
```

Pide la clave de `sudo` y muestra **una sola vez** la clave de `rrhh_lectura`.
Cópiela directamente en DBeaver (paso 3) y después limpie la pantalla:

```bash
clear
```

Para la conexión de edición:

```bash
bash despliegue/usuario_bd.sh edicion
```

(misma mecánica: la clave sale una vez; `clear` después).

Si pierde una clave: `bash despliegue/usuario_bd.sh lectura --nueva-clave`
(o `edicion --nueva-clave`). Para eliminar un usuario:
`bash despliegue/usuario_bd.sh edicion --quitar`.

Para comprobar qué quedó abierto y quién tiene permisos (solo mira):

```bash
bash despliegue/accesos.sh
```

---

## Paso 2 · Respaldo antes de editar

Antes de cualquier corrección con la conexión de edición, haga un respaldo
(hoja `despliegue/COMANDOS.md`, sección 5):

```bash
mkdir -p ~/bryan/rrhh_datos/respaldos
```
```bash
sudo mysqldump --single-transaction --routines --triggers rrhh > ~/bryan/rrhh_datos/respaldos/rrhh_$(date +%F_%H%M).sql
```

---

## Paso 3 · La conexión en DBeaver (Windows)

Hágalo dos veces: una con `rrhh_lectura` y otra con `rrhh_edicion`.

1. **Base de datos → Nueva conexión** (o el enchufe con «+» de la barra) →
   elija **MySQL** → **Siguiente**.

2. Pestaña **General** (la que aparece primero):

   | Campo | Valor |
   |---|---|
   | Connect by | **Host** |
   | Server Host | `localhost` |
   | Port | `3306` |
   | Database | `rrhh` |
   | Show all databases | desmárquelo (solo hay que ver `rrhh`) |
   | Nombre de usuario | `rrhh_lectura` (o `rrhh_edicion`) |
   | Contraseña | la del paso 1 |
   | Save password | ver la nota de seguridad abajo |

3. Botón **«SSH, SSL, …»** (arriba a la derecha) → **SSH**. Aparece la
   pestaña **SSH**:

   | Campo | Valor |
   |---|---|
   | Use SSH tunnel | ✔ |
   | Host/IP | `192.168.4.94` |
   | Port | `22` |
   | User name | `enicolalde` |
   | Authentication method | **Password** (la misma de VS Code), o **Public key** si usa llave |
   | Save credentials | a su criterio (ver nota) |

   Pulse **Test tunnel configuration**: debe decir que conectó.

4. Pestaña **Driver properties** (al abrirla puede pedir descargar el
   controlador de MySQL: acepte). Busque y cambie:

   | Propiedad | Valor |
   |---|---|
   | `allowPublicKeyRetrieval` | `true` |
   | `useSSL` | `false` |

   Es seguro aquí: todo viaja dentro del túnel SSH, que ya va cifrado.

5. Botón **«Connection details (name, type, …)»**:

   - **Connection name:** `RRHH ITSANET (lectura)` o `RRHH ITSANET (EDICIÓN)`.
   - **Connection type:** **Production**. DBeaver la pinta de rojo y pide
     confirmación antes de ejecutar cambios.
   - Para la de lectura marque **Read-only connection**.
   - Para la de edición, **desmarque Auto-commit**: así ningún cambio queda
     guardado hasta que usted pulse **Confirmar** en la barra (o **Revertir**
     para deshacerlo).

6. **Probar conexión …** → debe decir «Connected». Luego **Finalizar**.

**Nota de seguridad (LOPDP).** Si marca «Save password» / «Save credentials»,
active antes una contraseña maestra en DBeaver: **Ventana → Preferencias →
Seguridad → Use secure password storage / master password**. Sin ella, las
claves quedan legibles en el equipo. Estas conexiones ven cédulas, correos,
fechas de nacimiento y saldos de todo el personal: son del responsable técnico
y no se comparten.

### Si algo falla

| Mensaje | Qué revisar |
|---|---|
| `Access denied for user 'rrhh_lectura'@'localhost'` | La clave. Genere otra con `--nueva-clave`. |
| `Public Key Retrieval is not allowed` | Paso 4: `allowPublicKeyRetrieval = true`. |
| `Communications link failure` | El túnel SSH (paso 3) o que Server Host sea `localhost`. |
| Falla el túnel | Que pueda entrar por VS Code con el mismo usuario y clave. |
| No ve tablas | Que en *Database* diga `rrhh`. |

---

## Paso 4 · Qué mirar (conexión de lectura)

Consultas listas en `mysql/depuracion/01_revisar.sql` (en DBeaver: Archivo →
Abrir archivo). Algunas útiles:

```sql
-- Tablas y filas (aproximado).
SELECT table_name, table_rows FROM information_schema.tables
 WHERE table_schema = 'rrhh' ORDER BY table_name;

-- Relaciones entre tablas.
SELECT table_name, column_name, referenced_table_name, referenced_column_name
  FROM information_schema.key_column_usage
 WHERE table_schema = 'rrhh' AND referenced_table_name IS NOT NULL
 ORDER BY table_name;

-- Migraciones aplicadas.
SELECT * FROM schema_migraciones ORDER BY 1;

-- Activos por sede.
SELECT region, ciudad, COUNT(*) FROM users WHERE activo GROUP BY region, ciudad;

-- Quién no tiene jefe asignado.
SELECT cedula, nombre, cargo, departamento FROM users
 WHERE activo AND jefe_id IS NULL ORDER BY departamento, nombre;

-- Sesiones abiertas ahora, con su dispositivo.
SELECT u.nombre, s.dispositivo, s.ip, s.creada_en, s.ultimo_uso
  FROM sesiones s JOIN users u ON u.id = s.user_id
 WHERE s.cerrada_en IS NULL AND s.expira_en > NOW() ORDER BY s.ultimo_uso DESC;
```

Diagrama de relaciones: en el panel izquierdo, clic derecho sobre `rrhh` →
**Ver diagrama** (pestaña «ER Diagram»).

## Paso 5 · Corregir datos (conexión de edición)

En este orden de preferencia:

1. **Desde el sistema** (pantallas de Talento Humano y Administración): valida
   y deja constancia en la bitácora de quién cambió qué. Es lo primero.
2. **Con los scripts del repositorio** (`mysql/saldos.py`,
   `mysql/cargar_personas.py`; ver `despliegue/COMANDOS.md`): muestran antes
   de cambiar y solo aplican con `--aplicar`.
3. **A mano en DBeaver**, solo si no hay otra vía:
   - respaldo previo (paso 2);
   - leer antes `mysql/depuracion/00_LEER_PRIMERO.sql` y usar las consultas de
     `02_corregir.sql` / `03_eliminar.sql`;
   - con Auto-commit apagado: ejecutar, revisar el resultado y recién entonces
     **Confirmar** (o **Revertir**);
   - nunca un `UPDATE` o `DELETE` sin `WHERE`: primero un `SELECT` con el
     mismo `WHERE` para ver cuántas filas toca.

Lo que se cambia a mano **no pasa por las validaciones del sistema ni queda en
su bitácora** con el nombre de quien lo hizo. Por eso es el último recurso.

Al terminar, si no la va a usar pronto:

```bash
bash despliegue/usuario_bd.sh edicion --quitar
```

## Protección de datos (LOPDP)

- No exporte tablas a Excel o CSV salvo que haga falta; si hace falta,
  guárdelas solo en `C:\Users\IMORETA\Documents\AP\MOD_RRHH` o en
  `~/bryan/rrhh_datos/`, nunca en el repositorio, el correo personal ni nubes
  personales.
- Las claves de `rrhh_lectura` y `rrhh_edicion` no se comparten ni se escriben
  en documentos.
