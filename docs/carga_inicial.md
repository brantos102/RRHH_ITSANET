# Subir la planilla al sistema

La planilla de Talento Humano (`BD_inicial_RRHH.xlsx`) se convierte en SQL
con un script, y ese SQL se pega en Supabase. El script **no escribe en la
base**: genera el archivo para que usted lo revise antes de aplicarlo.

---

## 1. Genere el SQL

```powershell
cd C:\ruta\al\proyecto\RRHH_ITSANET_git
pip install openpyxl
python scripts\importar_planilla.py C:\ruta\a\BD_inicial_RRHH.xlsx
```

Produce `supabase/carga_inicial.sql` y, en pantalla, el resumen de lo que
encontró: cuántas personas, cuántas con saldo, cuántas sin correo y qué
conviene revisar.

## 2. Aplique primero las migraciones

En el SQL Editor de Supabase, en orden, todos los archivos de
`supabase/migrations/`. Compruebe con:

```bash
python scripts\verificar.py
```

Debe listar las migraciones **0001 a 0011** en verde.

## 3. Pegue la carga en Supabase

El archivo `supabase/carga_inicial.sql` queda en la carpeta del proyecto,
**en su computadora**. No se sube a GitHub a propósito: lleva cédulas,
nombres, correos y teléfonos de 351 personas, que son datos personales bajo
la LOPDP. Cada quien lo genera en su máquina.

Para llevarlo a Supabase:

1. Ábralo con el Bloc de notas o VS Code:

   ```powershell
   notepad supabase\carga_inicial.sql
   ```

2. Seleccione todo (`Ctrl+E` o `Ctrl+A`) y copie (`Ctrl+C`).

3. En Supabase: **SQL Editor** → **New query** → pegue (`Ctrl+V`) → **Run**.

> **Si el editor se queja de que el texto es muy largo**, no lo parta a la
> mitad: la carga es una sola transacción y cortarla la deja incompleta.
> Use en su lugar el cliente de línea de comandos, que no tiene ese límite:
>
> ```powershell
> psql "postgresql://postgres.<ref>:<clave>@aws-0-...pooler.supabase.com:6543/postgres" -f supabase\carga_inicial.sql
> ```
>
> La cadena de conexión es la misma de `DATABASE_URL` en su `backend\.env`.

Al final devuelve dos tablas:

- **Saldos que no se cargaron**, con el motivo. Esas personas entran con el
  saldo que calcula el sistema; revise el caso y corríjalo a mano.
- **El resumen**: personas activas, sin correo, con jefe, jefaturas
  detectadas y saldo promedio.

Es idempotente: volver a ejecutarlo actualiza los datos de quien ya existe.
**Pero no lo repita una vez que el sistema empiece a descontar vacaciones**,
porque recarga el saldo desde la planilla y pisaría los movimientos hechos
en el sistema.

---

## Lo que hace con cada hoja

| Hoja | Qué se toma |
|---|---|
| **ACTIVOS 2026** | Cédula, nombre, cargo, área, bodega, centro de costo, cliente, ciudad, jefe inmediato, fechas de ingreso, fin de contrato y nacimiento, género, correo y teléfono |
| **REGISTRO DE VACACIONES** | El saldo real. La hoja lleva un saldo corriente —cada fila descuenta lo gozado de la anterior—, así que se toma la **última fila de cada persona** |

El saldo que se carga es **el que su planilla ya tiene conciliado**, no uno
recalculado. El sistema solo verifica que no supere lo devengado.

---

## Tres cosas que debe resolver Talento Humano

### Las personas sin correo no pueden entrar

El acceso es por código al correo. **230 de 351 personas no tienen correo
en la planilla.** Se cargan igual, con una dirección marcadora, y quedan
señaladas. Para verlas:

```sql
select * from public.v_sin_correo;
```

No se les puede avisar en la pantalla de acceso sin revelar qué cédulas
existen en el sistema, así que completar esos correos es una tarea de
Talento Humano, no del colaborador.

### Los jefes que no están en la planilla

Cinco nombres aparecen como jefe inmediato pero no figuran como empleados
activos: Stefanya Vera, Javier Coronel, Jorge Samore, Lilibeth Riascos y
Ricardo Barcelo. Su gente queda sin jefe asignado y **sus solicitudes no
tendrán a quién ir**. Agréguelos en Administración → Usuarios y vuelva a
ejecutar la carga, o asígneles jefe a mano.

### Los datos que no cuadran entre hojas

El script coteja la fecha de ingreso en las dos hojas y avisa cuando
difieren. Hoy hay dos casos; uno de ellos hace que su saldo no se pueda
cargar porque sería más de lo devengado. Corrija la planilla y vuelva a
generar.

---

## Qué pasa con los roles

- Todos entran como **empleado**.
- Quien tiene gente a cargo pasa automáticamente a **jefe**.
- Los perfiles de **Talento Humano** y **administrador** se asignan a mano
  en Administración → Usuarios. La carga nunca degrada un rol ya asignado.

---

## Cargar el historial de vacaciones

Talento Humano lleva desde hace años una hoja con cada vacación tomada. Sin
ella, un colaborador entra, ve su saldo y no puede responder la pregunta más
simple que se le ocurre a cualquiera: **«¿cuándo tomé vacaciones la última
vez?»**.

```powershell
cd backend
..\.venv\Scripts\python ..\scripts\cargar_historial.py "C:\ruta\REGISTRO DE VACACIONES.xlsx"
```

Sin `--aplicar` no escribe nada: dice qué haría y se detiene. Léalo antes de
seguir.

### Lo delicado: el emparejamiento

La hoja identifica a la gente por **nombre** y el sistema por **cédula**.
Equivocarse ahí significa cargarle a una persona las vacaciones de otra, y eso
no se nota nunca. La regla es estricta a propósito:

> Solo se carga cuando el nombre completo coincide **exactamente** —ignorando
> tildes, mayúsculas y espacios de más— con **una y solo una** persona activa.

Nada de parecidos. Lo que no empareja se lista con su motivo y **no se carga**.
Es preferible que falten datos a que estén mal atribuidos: lo primero se nota,
lo segundo no.

En la carga de septiembre de 2026, de 3.339 vacaciones anotadas:

| | |
|---|---|
| Cargadas | **3.303**, de 223 personas |
| Sin emparejar | 36, de 10 nombres — 34 de personal **PASIVO** que ya no está en la nómina |
| Filas repetidas en la hoja | 5 (se carga una sola vez; el guion las lista con su número de fila) |

### Qué NO hace

**No toca el saldo.** El saldo ya viene de esta misma hoja y es correcto; lo que
faltaba era el detalle de cómo se llegó a él. Sumarlo otra vez sería descontar
dos veces los mismos días. El guion compara el saldo total antes y después y
**falla si cambió**.

**No inventa solicitudes.** Estos registros no pasaron por un jefe, no tienen
folio ni código QR. Van a `vacaciones_historicas`, no a `requests`, y en la
pantalla salen marcados como «Registro de Talento Humano».

### Comprobar lo cargado

```powershell
..\.venv\Scripts\python ..\scripts\cargar_historial.py ARCHIVO.xlsx --informe cotejo.csv
```

Deja un CSV con fila de la hoja, cédula, nombre y fechas de cada registro
emparejado, para cotejarlo contra el original. Al terminar, el guion suma los
días por persona y los compara con la hoja; si alguno no cuadra, lo dice y
termina con error.

Desde la base:

```sql
select * from public.v_historico_resumen order by dias_gozados_historicos desc;
```

El archivo lleva datos personales de 350 personas. Bórrelo cuando termine
(LOPDP, Art. 10).
