-- =====================================================================
--  Utilidades para los smoke tests. EJECUTAR PRIMERO, en la misma pestaña.
--  Crea tablas y funciones temporales que viven solo en esta sesión.
-- =====================================================================
drop table if exists _res;
create temp table _res (
  n serial primary key, caso text, esperado text, obtenido text, ok boolean
);

drop table if exists _ctx;
create temp table _ctx (clave text primary key, valor text);

-- Registra el resultado de un caso
create or replace function pg_temp.chk(p_caso text, p_esperado text, p_obtenido text)
returns void language sql as $f$
  insert into _res (caso, esperado, obtenido, ok)
  values (p_caso, p_esperado, p_obtenido, p_esperado is not distinct from p_obtenido);
$f$;

-- Guarda y recupera valores entre bloques (ids, fechas)
create or replace function pg_temp.pon(p_clave text, p_valor text)
returns void language sql as $f$
  insert into _ctx values (p_clave, p_valor)
  on conflict (clave) do update set valor = excluded.valor;
$f$;

create or replace function pg_temp.dame(p_clave text)
returns text language sql stable as $f$
  select valor from _ctx where clave = p_clave;
$f$;

create or replace function pg_temp.uid(p_clave text)
returns uuid language sql stable as $f$
  select valor::uuid from _ctx where clave = p_clave;
$f$;

create or replace function pg_temp.fecha(p_clave text)
returns date language sql stable as $f$
  select valor::date from _ctx where clave = p_clave;
$f$;

select 'Utilidades listas. Ahora ejecute el archivo de pruebas.' as estado;
