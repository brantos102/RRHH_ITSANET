-- ===========================================================================
-- 02 · CORREGIR DATOS
--
-- Recetas listas para usar. TODAS traen el SELECT de antes y el de después:
-- no es adorno, es la diferencia entre corregir una fila y corregir mil.
--
-- Cambie lo que está entre <<< >>> y nada más.
--
-- CON EL AUTO-COMMIT APAGADO en DBeaver. Si no, el `rollback` no le va a
-- servir de nada cuando lo necesite.
-- ===========================================================================


-- ===========================================================================
-- A. UNA PERSONA
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- A.1 Corregir un nombre mal escrito
--
-- Los dos que reportó la carga del historial:
--   ANDI BOHOROQUEZ              →  debería ser BOHORQUEZ
--   CHILAN CHOEZ ANTHONY FRANSISCO → debería ser FRANCISCO
--
-- Corregir el nombre en el sistema NO vuelve a cargar su historial: la carga
-- empareja por nombre exacto, así que después hay que volver a correr el
-- guion de carga para que esas vacaciones entren.
-- ---------------------------------------------------------------------------
begin;

select id, cedula, nombre from public.users
 where cedula = '<<<0000000000>>>';

update public.users
   set nombre = '<<<NOMBRE CORREGIDO>>>'
 where cedula = '<<<0000000000>>>';

select id, cedula, nombre from public.users
 where cedula = '<<<0000000000>>>';

-- commit;   -- o   rollback;
rollback;


-- ---------------------------------------------------------------------------
-- A.2 Corregir una cédula
--
-- Es la llave con la que la persona entra al sistema. Compruebe primero que
-- la nueva sea válida y que no la tenga ya otro.
-- ---------------------------------------------------------------------------
begin;

select public.es_cedula_valida('<<<NUEVA_CEDULA>>>')          as la_nueva_es_valida,
       exists(select 1 from public.users
               where cedula = '<<<NUEVA_CEDULA>>>')           as ya_la_tiene_alguien;

update public.users
   set cedula = '<<<NUEVA_CEDULA>>>'
 where cedula = '<<<CEDULA_ACTUAL>>>';

-- Los códigos de acceso viejos quedan colgados de la cédula anterior y ya no
-- sirven: se limpian para que no confundan.
delete from public.auth_otp where cedula = '<<<CEDULA_ACTUAL>>>';

select cedula, nombre from public.users where cedula = '<<<NUEVA_CEDULA>>>';

rollback;


-- ---------------------------------------------------------------------------
-- A.3 Corregir la FECHA DE INGRESO
--
-- Es el cambio que más cosas mueve: de ella salen los años de servicio, los
-- días de cada año y el saldo. HAY QUE REGENERAR LOS PERÍODOS DESPUÉS, o el
-- saldo queda calculado sobre una antigüedad que ya no es.
-- ---------------------------------------------------------------------------
begin;

select cedula, nombre, fecha_ingreso, dias_vacaciones,
       public.anios_cumplidos(fecha_ingreso) as anios
  from public.users where cedula = '<<<0000000000>>>';

update public.users
   set fecha_ingreso = '<<<2020-01-15>>>'::date
 where cedula = '<<<0000000000>>>';

-- Sin esto, lo de arriba queda a medias.
select public.generar_periodos_vacaciones(id) as periodos_generados
  from public.users where cedula = '<<<0000000000>>>';

select periodo, fecha_desde, fecha_hasta, dias_asignados, dias_consumidos, dias_saldo
  from public.vacation_periods
 where user_id = (select id from public.users where cedula = '<<<0000000000>>>')
 order by periodo;

rollback;


-- ---------------------------------------------------------------------------
-- A.4 Registrar o borrar un correo
--
-- Sin correo no llega el código de acceso: la persona entra por «primer
-- ingreso» y declara el suyo. Poner uno a mano le ahorra ese paso.
--
-- Deje `correo_pendiente` en false solo si el correo es real y suyo. Si lo
-- pone en true, el sistema le pedirá confirmarlo al entrar.
-- ---------------------------------------------------------------------------
begin;

update public.users
   set email = '<<<persona@ejemplo.com>>>',   -- o NULL para borrarlo
       correo_pendiente = false
 where cedula = '<<<0000000000>>>';

select cedula, nombre, email, correo_pendiente, ficha_completa
  from public.users where cedula = '<<<0000000000>>>';

rollback;


-- ---------------------------------------------------------------------------
-- A.5 Asignar jefe
--
-- Sin jefe, las solicitudes de esa persona no le llegan a nadie y se quedan
-- en trámite para siempre.
-- ---------------------------------------------------------------------------
begin;

update public.users
   set jefe_id = (select id from public.users where cedula = '<<<CEDULA_DEL_JEFE>>>')
 where cedula = '<<<CEDULA_DE_LA_PERSONA>>>';

select u.cedula, u.nombre, j.nombre as jefe, j.activo as jefe_activo
  from public.users u left join public.users j on j.id = u.jefe_id
 where u.cedula = '<<<CEDULA_DE_LA_PERSONA>>>';

rollback;


-- ---------------------------------------------------------------------------
-- A.6 Dar de baja a alguien  (NUNCA con DELETE)
--
-- Borrar la fila arrastra diecisiete tablas —diecinueve contando lo que a su
-- vez arrastran las solicitudes— y se lleva el expediente entero,
-- incluidos los consentimientos de protección de datos que la ley obliga a
-- conservar. Se desactiva.
-- ---------------------------------------------------------------------------
begin;

update public.users
   set activo = false,
       fecha_salida = '<<<2026-09-30>>>'::date
 where cedula = '<<<0000000000>>>';

-- Quien quede reportando a esta persona se queda sin jefe: reasígnelos.
select cedula, nombre from public.users
 where activo
   and jefe_id = (select id from public.users where cedula = '<<<0000000000>>>');

rollback;


-- ---------------------------------------------------------------------------
-- A.7 Corregir el SALDO de vacaciones
--
-- NO se hace con `update users set dias_vacaciones`. Ese número lo recalcula
-- un disparador desde `vacation_periods` y su cambio se pierde en el
-- siguiente movimiento, sin avisar.
--
-- `cargar_saldo_inicial` fija el saldo real y reparte lo ya gozado entre los
-- períodos más antiguos, que es como corresponde.
-- ---------------------------------------------------------------------------
begin;

select * from public.explicar_saldo(
  (select id from public.users where cedula = '<<<0000000000>>>'));

select public.cargar_saldo_inicial(
  (select id from public.users where cedula = '<<<0000000000>>>'),
  <<<8.75>>>,      -- el saldo que debe quedar
  <<<0>>>          -- fines de semana obligatorios ya gozados
);

select periodo, dias_asignados, dias_consumidos, dias_saldo,
       fines_semana_obligatorios, fines_semana_consumidos
  from public.vacation_periods
 where user_id = (select id from public.users where cedula = '<<<0000000000>>>')
 order by periodo;

rollback;


-- ---------------------------------------------------------------------------
-- A.8 Dar por cumplidos los fines de semana obligatorios
--
-- Para quien los tomó antes de que existiera el sistema y no consta.
-- Los períodos gozados por completo ya se dan por cumplidos solos.
-- ---------------------------------------------------------------------------
begin;

select periodo, dias_asignados, dias_consumidos,
       fines_semana_obligatorios, fines_semana_consumidos, situacion
  from public.v_fines_semana
 where cedula = '<<<0000000000>>>' order by periodo;

update public.vacation_periods
   set fines_semana_consumidos = fines_semana_obligatorios
 where user_id = (select id from public.users where cedula = '<<<0000000000>>>')
   and periodo = <<<3>>>;

rollback;


-- ===========================================================================
-- B. EN BLOQUE
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- B.1 Limpiar espacios y unificar mayúsculas en los nombres
--
-- Corre sobre toda la planilla. Mire primero cuántas filas cambia.
-- ---------------------------------------------------------------------------
begin;

select count(*) as filas_que_cambiarian
  from public.users
 where nombre <> regexp_replace(btrim(nombre), '\s+', ' ', 'g');

update public.users
   set nombre = regexp_replace(btrim(nombre), '\s+', ' ', 'g')
 where nombre <> regexp_replace(btrim(nombre), '\s+', ' ', 'g');

rollback;


-- ---------------------------------------------------------------------------
-- B.2 Cambiar el departamento de un grupo
--
-- El caso típico: un área se renombró.
-- ---------------------------------------------------------------------------
begin;

select departamento, count(*) from public.users
 where activo group by 1 order by 2 desc;

update public.users
   set departamento = '<<<NOMBRE NUEVO>>>'
 where departamento = '<<<NOMBRE VIEJO>>>';

rollback;


-- ---------------------------------------------------------------------------
-- B.3 Dar de baja a varias personas de una lista
--
-- La lista de cédulas entre paréntesis, separadas por comas.
-- ---------------------------------------------------------------------------
begin;

select cedula, nombre, departamento from public.users
 where cedula in ('<<<0000000000>>>', '<<<1111111111>>>');

update public.users
   set activo = false, fecha_salida = current_date
 where cedula in ('<<<0000000000>>>', '<<<1111111111>>>');

-- Quién se queda sin jefe por esto:
select u.cedula, u.nombre, j.nombre as jefe_dado_de_baja
  from public.users u join public.users j on j.id = u.jefe_id
 where u.activo and not j.activo;

rollback;


-- ---------------------------------------------------------------------------
-- B.4 Asignar jefe a todo un departamento
-- ---------------------------------------------------------------------------
begin;

update public.users
   set jefe_id = (select id from public.users where cedula = '<<<CEDULA_DEL_JEFE>>>')
 where activo
   and departamento = '<<<DEPARTAMENTO>>>'
   and cedula <> '<<<CEDULA_DEL_JEFE>>>';   -- que no sea su propio jefe

select count(*) as personas_con_jefe_nuevo from public.users
 where activo and departamento = '<<<DEPARTAMENTO>>>'
   and jefe_id = (select id from public.users where cedula = '<<<CEDULA_DEL_JEFE>>>');

rollback;


-- ---------------------------------------------------------------------------
-- B.5 Recalcular todos los saldos
--
-- Después de cualquier corrección de períodos o de fechas de ingreso.
-- No cambia días de nadie: vuelve a sumar lo que ya hay.
-- ---------------------------------------------------------------------------
begin;

select round(sum(dias_vacaciones), 2) as saldo_total_antes
  from public.users where activo;

select public.recalcular_saldos() as personas_recalculadas;

select round(sum(dias_vacaciones), 2) as saldo_total_despues
  from public.users where activo;

-- Si los dos totales no coinciden, algo estaba descuadrado. Mire 1.5 de
-- 01_revisar.sql antes de confirmar.
rollback;
