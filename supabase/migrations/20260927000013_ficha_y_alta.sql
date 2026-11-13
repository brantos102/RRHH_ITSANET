-- ---------------------------------------------------------------------------
-- 0013 · Alta guiada sin correo y ficha personal editable.
--
-- Dos problemas del mundo real:
--
-- 1. 230 de 351 personas no tienen correo en la planilla, y el acceso es por
--    código al correo. Hoy no pueden entrar y no hay forma de decírselo en
--    la pantalla de acceso sin revelar qué cédulas existen. La salida es que
--    la propia persona complete su ficha la primera vez: sabe su cédula, que
--    es exactamente lo que el sistema necesita para reconocerla.
--
-- 2. Un teléfono cambia, una dirección cambia, el contacto de emergencia
--    cambia. Obligar a que Talento Humano teclee cada uno es un cuello de
--    botella. Pero el nombre, el correo o el estado civil sí deben validarse:
--    de ahí salen documentos. Se separa lo que la persona corrige sola de lo
--    que pasa por revisión.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. Datos que faltaban en la ficha
-- =========================================================================

alter table public.users add column if not exists foto_url text;
alter table public.users add column if not exists ficha_completa boolean not null default false;
alter table public.users add column if not exists ficha_completada_en timestamptz;

comment on column public.users.ficha_completa is
  'La persona ya completó sus datos de contacto la primera vez que entró.';

-- Quien ya tiene correo real y teléfono se considera completo: no hay por
-- qué molestarlo con un formulario que no aporta nada.
update public.users
   set ficha_completa = true
 where not correo_pendiente and telefono is not null and not ficha_completa;

-- =========================================================================
-- B. Alta: la persona se identifica por cédula y completa lo que falta
--
-- No se permite cambiar el correo de quien YA tiene uno real: eso sería una
-- forma de apropiarse de una cuenta ajena conociendo solo una cédula, que es
-- un dato público. El alta guiada solo alcanza a quien tiene correo
-- pendiente, y una vez usada deja de estar disponible.
-- =========================================================================

create table if not exists public.altas_pendientes (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.users(id) on delete cascade,
  cedula       text not null,
  token        uuid not null default gen_random_uuid(),
  expira_en    timestamptz not null default now() + interval '30 minutes',
  usado_en     timestamptz,
  ip           inet,
  created_at   timestamptz not null default now()
);

create index if not exists altas_pendientes_token_idx on public.altas_pendientes (token);
create index if not exists altas_pendientes_user_idx on public.altas_pendientes (user_id, created_at desc);

alter table public.altas_pendientes enable row level security;

comment on table public.altas_pendientes is
  'Permiso temporal para completar la ficha de quien no tiene correo registrado. Dura 30 minutos y se usa una sola vez.';

create or replace function public.puede_completar_ficha(p_cedula text)
returns boolean
language sql
stable
security definer
set search_path = public
as $pcf$
  -- Solo quien existe, está activo y no tiene correo real. Devuelve booleano
  -- y nada más: no filtra si la cédula existe cuando la respuesta es falsa.
  select exists (
    select 1 from public.users
     where cedula = p_cedula and activo and correo_pendiente and not ficha_completa
  );
$pcf$;

-- =========================================================================
-- C. Qué puede cambiar cada quien
--
-- Tres niveles, y la diferencia importa:
--
--   libre     La persona lo corrige sola. Son datos que solo ella conoce y
--             que cambian seguido: teléfono, contacto de emergencia,
--             dirección, foto. Que Talento Humano teclee 351 teléfonos es
--             un cuello de botella sin ningún beneficio.
--   revisado  Cambia, pero Talento Humano lo valida antes de que rija. De
--             estos datos salen documentos: nombre, correo, estado civil,
--             cargas familiares, discapacidad.
--   bloqueado No se toca desde la ficha. Cédula (es la llave de todo),
--             fecha de ingreso, cargo, área, jefe, rol, saldo de vacaciones:
--             son decisiones de la empresa, no del interesado.
-- =========================================================================

create table if not exists public.campos_ficha (
  campo       text primary key,
  etiqueta    text not null,
  nivel       text not null check (nivel in ('libre', 'revisado', 'bloqueado')),
  ayuda       text,
  orden       integer not null default 100
);

insert into public.campos_ficha (campo, etiqueta, nivel, ayuda, orden) values
  ('telefono',             'Teléfono personal',     'libre',
   'Obligatorio: es como se le ubica si hay una urgencia con su solicitud.', 10),
  ('telefono_alternativo', 'Teléfono de emergencia','libre',
   'De un familiar o allegado, para avisar si algo ocurre en la jornada.', 20),
  ('direccion',            'Dirección domiciliaria','libre', null, 30),
  ('ciudad',               'Ciudad',                'revisado',
   'Define qué equipo de Talento Humano atiende sus solicitudes.', 40),
  ('foto_url',             'Foto de perfil',        'libre', null, 50),
  ('tipo_sangre',          'Tipo de sangre',        'libre',
   'Útil en una emergencia. No se comparte con nadie fuera de Talento Humano.', 60),
  ('email',                'Correo institucional',  'revisado',
   'Es donde llega su código de acceso: el cambio se valida antes de regir.', 70),
  ('nombre',              'Nombre completo',        'revisado',
   'Debe coincidir con su cédula: de aquí salen los documentos.', 80),
  ('estado_civil',        'Estado civil',           'revisado', null, 90),
  ('tiene_discapacidad',  'Discapacidad',           'revisado',
   'Requiere carné del CONADIS para los permisos que la ley reconoce.', 100),
  ('cedula',              'Cédula',                 'bloqueado',
   'Identifica su expediente completo. Un error se corrige con Talento Humano.', 200),
  ('fecha_ingreso',       'Fecha de ingreso',       'bloqueado',
   'De ella dependen sus días de vacaciones. La maneja Talento Humano.', 210),
  ('cargo',               'Cargo',                  'bloqueado', null, 220),
  ('departamento',        'Área',                   'bloqueado', null, 230),
  ('jefe_id',             'Jefe inmediato',         'bloqueado', null, 240),
  ('dias_vacaciones',     'Saldo de vacaciones',    'bloqueado', null, 250)
on conflict (campo) do update
  set etiqueta = excluded.etiqueta, nivel = excluded.nivel,
      ayuda = excluded.ayuda, orden = excluded.orden;

alter table public.campos_ficha enable row level security;
drop policy if exists campos_ficha_lectura on public.campos_ficha;
create policy campos_ficha_lectura on public.campos_ficha
  for select to authenticated using (true);
grant select on public.campos_ficha to authenticated;

-- =========================================================================
-- D. Cambios que esperan validación
-- =========================================================================

create table if not exists public.cambios_ficha (
  id            bigint generated by default as identity primary key,
  user_id       uuid not null references public.users(id) on delete cascade,
  campo         text not null references public.campos_ficha(campo),
  valor_anterior text,
  valor_nuevo   text not null,
  motivo        text,
  estado        text not null default 'pendiente'
                check (estado in ('pendiente', 'aprobado', 'rechazado')),
  resuelto_por  uuid references public.users(id) on delete set null,
  resuelto_en   timestamptz,
  motivo_rechazo text,
  created_at    timestamptz not null default now()
);

create index if not exists cambios_ficha_pendientes_idx
  on public.cambios_ficha (estado, created_at) where estado = 'pendiente';
create index if not exists cambios_ficha_usuario_idx
  on public.cambios_ficha (user_id, created_at desc);

comment on table public.cambios_ficha is
  'Cambios de ficha que Talento Humano debe validar antes de que rijan. Queda el valor anterior para poder revertir.';

alter table public.cambios_ficha enable row level security;

drop policy if exists cambios_ficha_propios on public.cambios_ficha;
create policy cambios_ficha_propios on public.cambios_ficha
  for select to authenticated
  using (user_id = auth.uid() or is_rrhh_o_admin());

drop policy if exists cambios_ficha_sin_edicion on public.cambios_ficha;
create policy cambios_ficha_sin_edicion on public.cambios_ficha
  for update to authenticated using (is_rrhh_o_admin());

create or replace view public.v_cambios_ficha_pendientes as
select c.id, c.user_id, u.cedula, u.nombre as persona, u.departamento, u.ciudad,
       coalesce(u.region, 'sierra') as region,
       c.campo, f.etiqueta, c.valor_anterior, c.valor_nuevo, c.motivo, c.created_at
  from public.cambios_ficha c
  join public.users u on u.id = c.user_id
  join public.campos_ficha f on f.campo = c.campo
 where c.estado = 'pendiente'
 order by c.created_at;

grant select on public.v_cambios_ficha_pendientes to authenticated;

-- =========================================================================
-- E. Aplicar los cambios
-- =========================================================================

create or replace function public.actualizar_ficha_libre(
  p_user_id uuid,
  p_campos  jsonb
) returns public.users
language plpgsql
security definer
set search_path = public
as $afl$
declare
  v_usuario public.users;
  v_campo   text;
  v_valor   text;
  v_nivel   text;
begin
  for v_campo, v_valor in select key, value #>> '{}' from jsonb_each(p_campos)
  loop
    select nivel into v_nivel from public.campos_ficha where campo = v_campo;

    if v_nivel is null then
      raise exception 'El campo "%" no forma parte de la ficha', v_campo;
    end if;

    -- La comprobación vive aquí y no en el backend: es la última línea, y
    -- la única que no puede saltarse un cliente alterado.
    if v_nivel <> 'libre' then
      raise exception 'El campo "%" no se corrige desde la ficha: requiere validación de Talento Humano', v_campo;
    end if;

    execute format('update public.users set %I = $1 where id = $2', v_campo)
      using nullif(btrim(coalesce(v_valor, '')), ''), p_user_id;
  end loop;

  select * into v_usuario from public.users where id = p_user_id;
  return v_usuario;
end;
$afl$;

revoke all on function public.actualizar_ficha_libre(uuid, jsonb) from public;

create or replace function public.solicitar_cambio_ficha(
  p_user_id uuid,
  p_campo   text,
  p_valor   text,
  p_motivo  text default null
) returns bigint
language plpgsql
security definer
set search_path = public
as $scf$
declare
  v_nivel    text;
  v_anterior text;
  v_id       bigint;
begin
  select nivel into v_nivel from public.campos_ficha where campo = p_campo;

  if v_nivel is null then
    raise exception 'El campo "%" no forma parte de la ficha', p_campo;
  end if;
  if v_nivel = 'bloqueado' then
    raise exception 'El campo "%" no se modifica desde la ficha. Escriba a Talento Humano si hay un error.', p_campo;
  end if;
  if v_nivel = 'libre' then
    raise exception 'El campo "%" se corrige directamente, sin pasar por revisión', p_campo;
  end if;
  if length(btrim(coalesce(p_valor, ''))) = 0 then
    raise exception 'El nuevo valor no puede quedar vacío';
  end if;

  execute format('select %I::text from public.users where id = $1', p_campo)
    into v_anterior using p_user_id;

  if v_anterior is not distinct from btrim(p_valor) then
    raise exception 'El valor es el mismo que ya está registrado';
  end if;

  -- Un solo cambio pendiente por campo: pedir tres veces lo mismo solo
  -- entorpece la bandeja de quien revisa.
  update public.cambios_ficha
     set estado = 'rechazado',
         motivo_rechazo = 'Reemplazado por una solicitud posterior',
         resuelto_en = now()
   where user_id = p_user_id and campo = p_campo and estado = 'pendiente';

  insert into public.cambios_ficha (user_id, campo, valor_anterior, valor_nuevo, motivo)
  values (p_user_id, p_campo, v_anterior, btrim(p_valor), nullif(btrim(coalesce(p_motivo,'')), ''))
  returning id into v_id;

  return v_id;
end;
$scf$;

revoke all on function public.solicitar_cambio_ficha(uuid, text, text, text) from public;

create or replace function public.resolver_cambio_ficha(
  p_id      bigint,
  p_aprobar boolean,
  p_por     uuid,
  p_motivo  text default null
) returns public.cambios_ficha
language plpgsql
security definer
set search_path = public
as $rcf$
declare
  v_cambio public.cambios_ficha;
begin
  select * into v_cambio from public.cambios_ficha where id = p_id for update;
  if not found then
    raise exception 'El cambio no existe';
  end if;
  if v_cambio.estado <> 'pendiente' then
    raise exception 'Este cambio ya fue resuelto';
  end if;

  if p_aprobar then
    execute format('update public.users set %I = $1 where id = $2', v_cambio.campo)
      using v_cambio.valor_nuevo, v_cambio.user_id;

    -- Si se validó el correo, la persona deja de estar en la lista de
    -- pendientes: ya puede recibir su código.
    if v_cambio.campo = 'email' then
      update public.users set correo_pendiente = false where id = v_cambio.user_id;
    end if;
  elsif length(btrim(coalesce(p_motivo, ''))) < 5 then
    raise exception 'Indique por qué se rechaza: la persona debe saber qué corregir';
  end if;

  update public.cambios_ficha
     set estado = case when p_aprobar then 'aprobado' else 'rechazado' end,
         resuelto_por = p_por,
         resuelto_en = now(),
         motivo_rechazo = case when p_aprobar then null else btrim(p_motivo) end
   where id = p_id
  returning * into v_cambio;

  return v_cambio;
end;
$rcf$;

revoke all on function public.resolver_cambio_ficha(bigint, boolean, uuid, text) from public;
