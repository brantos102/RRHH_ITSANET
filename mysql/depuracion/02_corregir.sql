-- ===========================================================================
-- 02 · CORREGIR DATOS (MySQL)
--
-- Recetas listas para usar. TODAS traen el SELECT de antes y el de después:
-- no es adorno, es la diferencia entre corregir una fila y corregir mil.
--
-- Cambie lo que está entre <<< >>> y nada más.
--
-- CON EL AUTO-COMMIT APAGADO en DBeaver. Si no, el `rollback` no le va a
-- servir de nada cuando lo necesite. Cada receta termina en `rollback`: cuando
-- esté conforme con lo que ve, cámbielo por `commit`.
-- ===========================================================================


-- ===========================================================================
-- A. UNA PERSONA
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- A.1 Corregir un nombre mal escrito
--
-- Corregir el nombre en el sistema NO vuelve a cargar su historial: la carga
-- empareja por nombre exacto, así que después hay que volver a correr el
-- guion de carga para que esas vacaciones entren.
-- ---------------------------------------------------------------------------
start transaction;

select id, cedula, nombre from users
 where cedula = '<<<0000000000>>>';

update users
   set nombre = '<<<NOMBRE CORREGIDO>>>'
 where cedula = '<<<0000000000>>>';

select id, cedula, nombre from users
 where cedula = '<<<0000000000>>>';

-- commit;   -- o   rollback;
rollback;


-- ---------------------------------------------------------------------------
-- A.2 Corregir una cédula
--
-- Es la llave con la que la persona entra al sistema. Compruebe primero que
-- la nueva sea válida y que no la tenga ya otro.
-- ---------------------------------------------------------------------------
start transaction;

select es_cedula_valida('<<<NUEVA_CEDULA>>>')                as la_nueva_es_valida,
       exists(select 1 from users
               where cedula = '<<<NUEVA_CEDULA>>>')           as ya_la_tiene_alguien;

update users
   set cedula = '<<<NUEVA_CEDULA>>>'
 where cedula = '<<<CEDULA_ACTUAL>>>';

-- Los códigos de acceso viejos quedan colgados de la cédula anterior y ya no
-- sirven: se limpian para que no confundan.
delete from auth_otp where cedula = '<<<CEDULA_ACTUAL>>>';

select cedula, nombre from users where cedula = '<<<NUEVA_CEDULA>>>';

rollback;


-- ---------------------------------------------------------------------------
-- A.3 Corregir la FECHA DE INGRESO
--
-- Es el cambio que más cosas mueve: de ella salen los años de servicio, los
-- días de cada año y el saldo. HAY QUE REGENERAR LOS PERÍODOS DESPUÉS, o el
-- saldo queda calculado sobre una antigüedad que ya no es.
-- ---------------------------------------------------------------------------
start transaction;

select cedula, nombre, fecha_ingreso, dias_vacaciones,
       anios_cumplidos(fecha_ingreso) as anios
  from users where cedula = '<<<0000000000>>>';

update users
   set fecha_ingreso = '<<<2020-01-15>>>'
 where cedula = '<<<0000000000>>>';

rollback;

-- EN MYSQL la regeneración no se hace desde aquí. Después del commit, en la
-- terminal del servidor, primero mire y después aplique:
--
--   .venv/bin/python mysql/saldos.py regenerar --cedula <<<0000000000>>>
--   .venv/bin/python mysql/saldos.py regenerar --cedula <<<0000000000>>> --aplicar


-- ---------------------------------------------------------------------------
-- A.4 Registrar o borrar un correo
--
-- Sin correo no llega el código de acceso: la persona entra por «primer
-- ingreso» y declara el suyo. Poner uno a mano le ahorra ese paso.
--
-- Deje `correo_pendiente` en false solo si el correo es real y suyo. Si lo
-- pone en true, el sistema le pedirá confirmarlo al entrar.
-- ---------------------------------------------------------------------------
start transaction;

update users
   set email = '<<<persona@ejemplo.com>>>',   -- o NULL para borrarlo
       correo_pendiente = false
 where cedula = '<<<0000000000>>>';

select cedula, nombre, email, correo_pendiente, ficha_completa
  from users where cedula = '<<<0000000000>>>';

rollback;


-- ---------------------------------------------------------------------------
-- A.5 Asignar jefe
--
-- Sin jefe, las solicitudes de esa persona no le llegan a nadie y se quedan
-- en trámite para siempre.
--
-- EN MYSQL no se puede leer y modificar `users` en la misma sentencia
-- (error 1093), así que el jefe se busca primero y se guarda en @jefe.
-- ---------------------------------------------------------------------------
start transaction;

select id into @jefe from users where cedula = '<<<CEDULA_DEL_JEFE>>>';

update users
   set jefe_id = @jefe
 where cedula = '<<<CEDULA_DE_LA_PERSONA>>>';

select u.cedula, u.nombre, j.nombre as jefe, j.activo as jefe_activo
  from users u left join users j on j.id = u.jefe_id
 where u.cedula = '<<<CEDULA_DE_LA_PERSONA>>>';

rollback;


-- ---------------------------------------------------------------------------
-- A.6 Dar de baja a alguien  (NUNCA con DELETE)
--
-- Lo correcto es la pantalla de Administración, que registra la causa de
-- salida y lo que queda por liquidar. Si no hay otra forma:
-- ---------------------------------------------------------------------------
start transaction;

update users
   set activo = false,
       fecha_salida = '<<<2026-09-30>>>',
       motivo_salida = '<<<renuncia>>>'
 where cedula = '<<<0000000000>>>';

-- Quien quede reportando a esta persona se queda sin jefe: reasígnelos.
select u.cedula, u.nombre
  from users u
  join users j on j.id = u.jefe_id
 where u.activo and j.cedula = '<<<0000000000>>>';

rollback;


-- ---------------------------------------------------------------------------
-- A.7 Corregir el SALDO de vacaciones
--
-- NO se hace con `update users set dias_vacaciones`. Ese número lo recalcula
-- un disparador desde `vacation_periods` y su cambio se pierde en el
-- siguiente movimiento, sin avisar.
--
-- EN MYSQL se hace desde la terminal del servidor. `cargar` fija el saldo
-- real y reparte lo ya gozado entre los períodos más antiguos, que es como
-- corresponde. Sin --aplicar solo muestra cómo quedaría:
--
--   .venv/bin/python mysql/saldos.py explicar --cedula <<<0000000000>>>
--   .venv/bin/python mysql/saldos.py cargar   --cedula <<<0000000000>>> --saldo <<<8.75>>> --fds <<<0>>>
--   .venv/bin/python mysql/saldos.py cargar   --cedula <<<0000000000>>> --saldo <<<8.75>>> --fds <<<0>>> --aplicar
--
-- Para mirar los períodos desde DBeaver:
-- ---------------------------------------------------------------------------
select p.periodo, p.dias_asignados, p.dias_consumidos, p.dias_saldo,
       p.fines_semana_obligatorios, p.fines_semana_consumidos
  from vacation_periods p
  join users u on u.id = p.user_id
 where u.cedula = '<<<0000000000>>>'
 order by p.periodo;


-- ---------------------------------------------------------------------------
-- A.8 Dar por cumplidos los fines de semana obligatorios
--
-- Para quien los tomó antes de que existiera el sistema y no consta.
-- Los períodos gozados por completo ya se dan por cumplidos solos.
-- ---------------------------------------------------------------------------
start transaction;

select periodo, dias_asignados, dias_consumidos,
       fines_semana_obligatorios, fines_semana_consumidos, situacion
  from v_fines_semana
 where cedula = '<<<0000000000>>>' order by periodo;

update vacation_periods p
  join users u on u.id = p.user_id
   set p.fines_semana_consumidos = p.fines_semana_obligatorios
 where u.cedula = '<<<0000000000>>>'
   and p.periodo = <<<3>>>;

rollback;


-- ===========================================================================
-- B. EN BLOQUE
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- B.1 Limpiar espacios en los nombres
--
-- Corre sobre toda la planilla. Mire primero cuántas filas cambia.
-- ---------------------------------------------------------------------------
start transaction;

select count(*) as filas_que_cambiarian
  from users
 where nombre <> regexp_replace(trim(nombre), '[[:space:]]+', ' ');

update users
   set nombre = regexp_replace(trim(nombre), '[[:space:]]+', ' ')
 where nombre <> regexp_replace(trim(nombre), '[[:space:]]+', ' ');

rollback;


-- ---------------------------------------------------------------------------
-- B.2 Cambiar el departamento de un grupo
--
-- El caso típico: un área se renombró.
-- ---------------------------------------------------------------------------
start transaction;

select departamento, count(*) from users
 where activo group by 1 order by 2 desc;

update users
   set departamento = '<<<NOMBRE NUEVO>>>'
 where departamento = '<<<NOMBRE VIEJO>>>';

rollback;


-- ---------------------------------------------------------------------------
-- B.3 Dar de baja a varias personas de una lista
--
-- La lista de cédulas entre paréntesis, separadas por comas.
-- ---------------------------------------------------------------------------
start transaction;

select cedula, nombre, departamento from users
 where cedula in ('<<<0000000000>>>', '<<<1111111111>>>');

update users
   set activo = false, fecha_salida = current_date(), motivo_salida = '<<<renuncia>>>'
 where cedula in ('<<<0000000000>>>', '<<<1111111111>>>');

-- Quién se queda sin jefe por esto:
select u.cedula, u.nombre, j.nombre as jefe_dado_de_baja
  from users u join users j on j.id = u.jefe_id
 where u.activo and not j.activo;

rollback;


-- ---------------------------------------------------------------------------
-- B.4 Asignar jefe a todo un departamento
-- ---------------------------------------------------------------------------
start transaction;

select id into @jefe from users where cedula = '<<<CEDULA_DEL_JEFE>>>';

update users
   set jefe_id = @jefe
 where activo
   and departamento = '<<<DEPARTAMENTO>>>'
   and cedula <> '<<<CEDULA_DEL_JEFE>>>';   -- que no sea su propio jefe

select count(*) as personas_con_jefe_nuevo from users
 where activo and departamento = '<<<DEPARTAMENTO>>>' and jefe_id = @jefe;

rollback;


-- ---------------------------------------------------------------------------
-- B.5 Recalcular todos los saldos
--
-- Después de cualquier corrección de períodos o de fechas de ingreso.
-- No cambia días de nadie: vuelve a sumar lo que ya hay. EN MYSQL, desde la
-- terminal del servidor:
--
--   .venv/bin/python mysql/saldos.py recalcular
--
-- Muestra el total de la planilla antes y después. Si no coinciden, algo
-- estaba descuadrado: mire 1.5 de 01_revisar.sql.
-- ---------------------------------------------------------------------------
select round(sum(dias_vacaciones), 2) as saldo_total
  from users where activo;
