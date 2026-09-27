-- ---------------------------------------------------------------------------
-- 0009 · Campos de la planilla real de ITSANET.
--
-- La planilla con la que Talento Humano viene trabajando tiene información
-- que el sistema no guardaba y que sí necesita: en qué bodega está la
-- persona, a qué cliente atiende, a qué centro de costo se imputa, hasta
-- cuándo va su contrato. Sin eso, un informe por cliente o un filtro por
-- bodega son imposibles, y son justo los que pide la operación.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

alter table public.users add column if not exists bodega text;
alter table public.users add column if not exists centro_costo text;
alter table public.users add column if not exists cliente text;
alter table public.users add column if not exists genero text;
alter table public.users add column if not exists contrato_fin date;
alter table public.users add column if not exists correo_pendiente boolean not null default false;

comment on column public.users.bodega is
  'Bodega o sede donde presta servicios. Viene de la planilla de Talento Humano.';
comment on column public.users.centro_costo is
  'Centro de costo al que se imputa. Permite informes por CECO.';
comment on column public.users.cliente is
  'Cliente al que está asignada la persona (Conecel, Difare, Flexnet…).';
comment on column public.users.contrato_fin is
  'Fin del contrato vigente. Distinto de `fecha_salida`, que marca una baja efectiva.';
comment on column public.users.correo_pendiente is
  'La dirección registrada es un marcador, no un buzón real: esta persona NO puede recibir su código de acceso.';

do $g$
begin
  if not exists (select 1 from pg_constraint where conname = 'users_genero_valido') then
    alter table public.users add constraint users_genero_valido
      check (genero is null or genero in ('Masculino', 'Femenino', 'Otro'));
  end if;
end
$g$;

create index if not exists users_bodega_idx on public.users (bodega) where activo;
create index if not exists users_cliente_idx on public.users (cliente) where activo;
create index if not exists users_correo_pendiente_idx on public.users (correo_pendiente)
  where correo_pendiente and activo;

-- =========================================================================
-- Quién no puede entrar todavía
--
-- El acceso es por código al correo institucional. Quien no tiene correo
-- registrado no puede entrar, y eso no se puede decir en la pantalla de
-- acceso sin revelar qué cédulas existen. La lista vive aquí, para que
-- Talento Humano la trabaje: es una tarea suya, no del colaborador.
-- =========================================================================

create or replace view public.v_sin_correo as
select u.cedula, u.nombre, u.cargo, u.departamento, u.bodega, u.cliente,
       u.ciudad, u.telefono, u.fecha_ingreso,
       j.nombre as jefe
  from public.users u
  left join public.users j on j.id = u.jefe_id
 where u.activo and u.correo_pendiente
 order by u.departamento nulls last, u.nombre;

comment on view public.v_sin_correo is
  'Personas activas sin correo real: no pueden recibir su código de acceso. Talento Humano debe completarlo.';

grant select on public.v_sin_correo to authenticated;
