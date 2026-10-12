-- ---------------------------------------------------------------------------
-- 0000 · Que la base se pueda levantar fuera de Supabase.
--
-- Todo el esquema se apoya en dos cosas que Supabase trae puestas y que un
-- PostgreSQL recién instalado no tiene:
--
--     auth.users    la tabla a la que apunta users.auth_user_id
--     auth.uid()    la función que usan las 55 políticas de seguridad por
--                   fila para saber quién está preguntando
--
-- Mientras el sistema vivió solo en Supabase eso no se notó. Se notó al
-- intentar levantar la base desde cero en un PostgreSQL propio —que es
-- exactamente el plan de infraestructura— y encontrarse con:
--
--     ERROR: schema "auth" does not exist
--
-- Es decir: el repositorio no contenía todo lo necesario para reconstruir su
-- propia base de datos. Un repositorio que no puede reconstruir lo que
-- describe no es una copia de seguridad de nada.
--
-- ESTA MIGRACIÓN NO TOCA SUPABASE. Todo va con `if not exists`: en Supabase
-- el esquema, la tabla y la función ya están, así que no se crea nada y no se
-- reemplaza nada. En un PostgreSQL propio, los crea.
--
-- POR QUÉ LA FUNCIÓN SE DEFINE ASÍ. `auth.uid()` lee el identificador del
-- usuario de una variable de la sesión, que es como PostgREST y el conector
-- de Supabase entregan las credenciales del JWT. El backend de este sistema
-- no usa esa vía —se conecta con un solo usuario y comprueba los permisos en
-- Python—, pero las políticas de seguridad por fila la necesitan igual para
-- poder existir, y hay que dejarlas tal como están: el día que se exponga la
-- base directamente, son la última defensa.
--
-- Va numerada 0000 a propósito: tiene que ejecutarse ANTES que la 0001.
-- Idempotente.
-- ---------------------------------------------------------------------------

create schema if not exists auth;

-- La tabla a la que apunta `users.auth_user_id`. Solo las dos columnas que
-- este sistema usa: aquí no se replica Supabase, se replica lo que hace falta
-- para que la clave foránea exista.
create table if not exists auth.users (
  id    uuid primary key default gen_random_uuid(),
  email text
);

comment on table auth.users is
  'Compatibilidad. En Supabase la trae el proveedor; en un PostgreSQL propio la crea la migración 0000.';

-- Solo se crea si no existe: en Supabase la función es del proveedor y
-- reemplazarla sería romper la autenticación de toda la instalación.
do $$
begin
  if not exists (
    select 1 from pg_proc p
      join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'auth' and p.proname = 'uid'
  ) then
    execute $f$
      create function auth.uid() returns uuid
      language sql stable
      as $cuerpo$
        select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
      $cuerpo$
    $f$;
  end if;
end $$;

grant usage on schema auth to public;
