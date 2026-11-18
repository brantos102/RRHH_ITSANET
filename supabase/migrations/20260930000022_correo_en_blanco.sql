-- ---------------------------------------------------------------------------
-- 0022 · Quien no tiene correo no tiene correo.
--
-- La columna `email` era `not null` con formato obligatorio, así que la carga
-- de la planilla no tenía más remedio que inventar una dirección para las 225
-- personas que llegaron sin ella:
--
--     0927127886@pendiente.itsanet.local
--
-- Eso tiene tres problemas, y ninguno es cosmético:
--
--   1. Es falso. El sistema afirma que esa persona tiene ese correo, y
--      cualquiera que exporte la nómina se lleva 225 direcciones inventadas.
--   2. El dominio no existe, así que el código de acceso se envía a la nada.
--      Se ve en el formulario de primer ingreso, que muestra la dirección
--      falsa como si fuera un dato de la persona.
--   3. Los correos aquí son personales, no institucionales. La empresa no
--      puede fabricarlos: los registra cada quien cuando entra.
--
-- El campo pasa a admitir nulo. Nulo es exactamente lo que hay que decir:
-- «no sabemos». El alta guiada ya existe para que la propia persona lo
-- registre, y `correo_pendiente` sigue marcando a quién le falta.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. El campo admite «no sabemos»
-- =========================================================================

alter table public.users alter column email drop not null;

-- El formato se sigue exigiendo cuando hay algo que validar. `citext` no
-- cambia eso; lo que cambia es que ahora un nulo no entra a la comprobación.
alter table public.users drop constraint if exists users_email_formato;
alter table public.users add constraint users_email_formato
  check (email is null or email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$');

comment on column public.users.email is
  'Correo personal donde la persona recibe su código de acceso. Nulo mientras no lo haya registrado: la empresa no lo inventa.';

-- =========================================================================
-- B. Las direcciones inventadas se borran
--
-- Se reconocen por el dominio marcador que puso la carga. No se toca ninguna
-- dirección real, ni siquiera la de quien tenga `correo_pendiente` mal
-- puesto: lo que se borra es lo que el sistema se inventó.
-- =========================================================================

do $limpiar$
declare v_n int;
begin
  with borrados as (
    update public.users
       set email = null, correo_pendiente = true
     where email::text like '%@pendiente.itsanet.local'
     returning 1
  )
  select count(*) into v_n from borrados;

  if v_n > 0 then
    raise notice 'Borradas % direcciones inventadas por la carga.', v_n;
  end if;
end;
$limpiar$;

-- Y `correo_pendiente` deja de poder contradecir al campo: si no hay correo,
-- está pendiente; si lo hay y es real, no.
update public.users set correo_pendiente = true  where email is null and not correo_pendiente;

-- =========================================================================
-- C. Nadie se queda sin poder entrar por esto
--
-- `puede_completar_ficha` es lo que decide si la pantalla de acceso ofrece
-- el alta guiada. Se ajusta para que alcance también a quien ya no tiene
-- ninguna dirección, que es el caso nuevo.
-- =========================================================================

create or replace function public.puede_completar_ficha(p_cedula text)
returns boolean
language sql
stable
security definer
set search_path = public
as $pcf$
  -- Devuelve booleano y nada más: no filtra si la cédula existe cuando la
  -- respuesta es falsa. La cédula es casi pública en Ecuador y esta función
  -- responde sin autenticación.
  select exists (
    select 1 from public.users
     where cedula = p_cedula and activo and not ficha_completa
       and (correo_pendiente or email is null)
  );
$pcf$;

-- =========================================================================
-- D. A quién le falta, de un vistazo
-- =========================================================================

-- `create or replace` no admite cambiar los nombres de las columnas, y
-- esta vista gana algunas. Se suelta y se vuelve a crear.
drop view if exists public.v_sin_correo;

create view public.v_sin_correo as
select u.id, u.cedula, u.nombre, u.cargo, u.departamento, u.ciudad,
       coalesce(u.region, 'sierra') as region,
       u.telefono, u.fecha_ingreso,
       j.nombre as jefe,
       u.fecha_nacimiento is not null as puede_probar_identidad
  from public.users u
  left join public.users j on j.id = u.jefe_id
 where u.activo and (u.email is null or u.correo_pendiente)
 order by u.nombre;

grant select on public.v_sin_correo to authenticated;

comment on view public.v_sin_correo is
  'Quiénes no pueden recibir su código todavía. `puede_probar_identidad` dice si el alta guiada les alcanza: necesita fecha de nacimiento y fecha de ingreso en el expediente.';
