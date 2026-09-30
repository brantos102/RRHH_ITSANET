-- ---------------------------------------------------------------------------
-- 0019 · Primer ingreso: correo, teléfonos, cargo y jefe.
--
-- Tres cosas que la práctica dejó al descubierto:
--
-- 1. Quien no tenía correo quedó registrado con uno genérico del estilo
--    «0927127886@pendiente.itsanet.local». Esa dirección no existe: el
--    código de acceso se envía a la nada. La ficha guiada ya resuelve el
--    alta, pero el correo que la persona declara después —al cambiar de
--    proveedor, al pasar de personal a institucional— entraba por la cola
--    de revisión de Talento Humano. No hace falta: basta con comprobar que
--    la dirección es suya, y eso lo comprueba la dirección misma.
--
--    Se agrega un cuarto nivel de campo, «confirmado»: lo cambia la propia
--    persona, sin que nadie apruebe nada, pero no rige hasta que abre el
--    enlace que le llega a la dirección nueva. Mientras tanto sigue
--    entrando con la anterior, así que un error de tecleo no deja a nadie
--    afuera.
--
-- 2. El cargo y el jefe estaban «bloqueados»: si la planilla los traía mal
--    —y trae diez personas sin jefe—, la única salida era escribir a
--    Talento Humano por fuera del sistema. Pasan a «revisado»: la persona
--    señala cuál es el correcto y Talento Humano lo confirma. Quien decide
--    sigue siendo la empresa; lo que cambia es que ahora el aviso llega por
--    un camino que deja rastro.
--
-- 3. `resolver_cambio_ficha` escribía el valor aprobado como texto. Para
--    `jefe_id`, que es uuid, eso falla en el momento de aprobar: el error
--    aparecía recién al final, cuando alguien de Talento Humano ya había
--    revisado el pedido. Ahora el valor se convierte al tipo real de la
--    columna.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. Un cuarto nivel: «confirmado»
-- =========================================================================

alter table public.campos_ficha drop constraint if exists campos_ficha_nivel_check;
alter table public.campos_ficha add constraint campos_ficha_nivel_check
  check (nivel in ('libre', 'revisado', 'confirmado', 'bloqueado'));

update public.campos_ficha
   set nivel = 'confirmado',
       ayuda = 'Es donde llega su código de acceso. Lo cambia usted mismo: '
               'rige cuando abra el enlace que le enviamos a la dirección nueva.'
 where campo = 'email';

update public.campos_ficha
   set nivel = 'revisado',
       ayuda = 'Si el registrado no es el suyo, señale el correcto. '
               'Talento Humano lo confirma antes de que rija.'
 where campo in ('cargo', 'jefe_id');

-- =========================================================================
-- B. Confirmación de correo
--
-- No se toca `users.email` hasta que el enlace se abre. Si se tocara antes,
-- un dedazo dejaría a la persona sin forma de recibir el código —ni el de
-- acceso ni el de confirmación— y habría que llamar a Talento Humano para
-- algo que el sistema puede resolver solo.
-- =========================================================================

create table if not exists public.confirmaciones_correo (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references public.users(id) on delete cascade,
  email       text not null,
  token       uuid not null default gen_random_uuid(),
  expira_en   timestamptz not null default now() + interval '24 hours',
  confirmado_en timestamptz,
  ip          inet,
  created_at  timestamptz not null default now()
);

create index if not exists confirmaciones_correo_token_idx
  on public.confirmaciones_correo (token);
create index if not exists confirmaciones_correo_usuario_idx
  on public.confirmaciones_correo (user_id, created_at desc);

comment on table public.confirmaciones_correo is
  'Correo declarado por la persona que todavía no rige. Se aplica cuando abre el enlace, dentro de las 24 horas.';

alter table public.confirmaciones_correo enable row level security;

drop policy if exists confirmaciones_correo_propias on public.confirmaciones_correo;
create policy confirmaciones_correo_propias on public.confirmaciones_correo
  for select to authenticated
  using (user_id = auth.uid() or is_rrhh_o_admin());

create or replace function public.pedir_confirmacion_correo(
  p_user_id uuid,
  p_email   text,
  p_ip      inet default null
) returns public.confirmaciones_correo
language plpgsql
security definer
set search_path = public
as $pcc$
declare
  v_email  text := lower(btrim(coalesce(p_email, '')));
  v_actual text;
  v_fila   public.confirmaciones_correo;
begin
  if v_email !~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$' then
    raise exception 'La dirección de correo no tiene un formato válido';
  end if;

  select lower(email) into v_actual from public.users where id = p_user_id;
  if v_actual is null then
    raise exception 'La persona no existe';
  end if;
  if v_actual = v_email then
    raise exception 'Ese correo ya es el suyo';
  end if;

  if exists (select 1 from public.users
              where lower(email) = v_email and id <> p_user_id) then
    raise exception 'Ese correo ya está registrado por otra persona';
  end if;

  -- Una confirmación viva por persona: pedirla de nuevo invalida la anterior,
  -- para que un enlace viejo en la bandeja no aplique una dirección que la
  -- persona ya descartó.
  delete from public.confirmaciones_correo
   where user_id = p_user_id and confirmado_en is null;

  insert into public.confirmaciones_correo (user_id, email, ip)
  values (p_user_id, v_email, p_ip)
  returning * into v_fila;

  return v_fila;
end;
$pcc$;

revoke all on function public.pedir_confirmacion_correo(uuid, text, inet) from public;

create or replace function public.confirmar_correo(p_token uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $cc$
declare
  v_fila public.confirmaciones_correo;
  v_nombre text;
begin
  select * into v_fila from public.confirmaciones_correo
   where token = p_token and confirmado_en is null and expira_en > now()
   for update;

  if not found then
    return jsonb_build_object(
      'confirmado', false,
      'motivo', 'El enlace ya se usó o venció. Pida uno nuevo desde su ficha.');
  end if;

  -- Entre el pedido y la confirmación alguien pudo tomar esa dirección.
  if exists (select 1 from public.users
              where lower(email) = lower(v_fila.email) and id <> v_fila.user_id) then
    return jsonb_build_object(
      'confirmado', false,
      'motivo', 'Esa dirección quedó registrada por otra persona. Escriba a Talento Humano.');
  end if;

  update public.users
     set email = v_fila.email,
         correo_pendiente = false
   where id = v_fila.user_id
  returning nombre into v_nombre;

  update public.confirmaciones_correo
     set confirmado_en = now() where id = v_fila.id;

  return jsonb_build_object(
    'confirmado', true,
    'nombre', v_nombre,
    'email', v_fila.email);
end;
$cc$;

revoke all on function public.confirmar_correo(uuid) from public;

-- =========================================================================
-- C. El correo ya no pasa por la cola de revisión
-- =========================================================================

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
  if v_nivel = 'confirmado' then
    raise exception 'El campo "%" no lo aprueba nadie: se confirma desde el enlace que llega al correo nuevo', p_campo;
  end if;
  if length(btrim(coalesce(p_valor, ''))) = 0 then
    raise exception 'El nuevo valor no puede quedar vacío';
  end if;

  execute format('select %I::text from public.users where id = $1', p_campo)
    into v_anterior using p_user_id;

  if v_anterior is not distinct from btrim(p_valor) then
    raise exception 'El valor es el mismo que ya está registrado';
  end if;

  -- El jefe se señala por su identificador: se comprueba aquí que exista y
  -- que no sea la propia persona, para que el error salga al pedirlo y no
  -- al aprobarlo.
  if p_campo = 'jefe_id' then
    if btrim(p_valor) = p_user_id::text then
      raise exception 'Nadie puede ser su propio jefe';
    end if;
    if not exists (select 1 from public.users
                    where id = btrim(p_valor)::uuid and activo) then
      raise exception 'La jefatura señalada no existe o no está activa';
    end if;
  end if;

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

-- =========================================================================
-- D. Aprobar un cambio escribe el tipo real de la columna
-- =========================================================================

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
  v_tipo   text;
begin
  select * into v_cambio from public.cambios_ficha where id = p_id for update;
  if not found then
    raise exception 'El cambio no existe';
  end if;
  if v_cambio.estado <> 'pendiente' then
    raise exception 'Este cambio ya fue resuelto';
  end if;

  if p_aprobar then
    -- `jefe_id` es uuid y el valor viaja como texto: sin esta conversión la
    -- aprobación fallaba, y fallaba recién al aprobar, después de que
    -- alguien ya había revisado el pedido.
    select data_type into v_tipo
      from information_schema.columns
     where table_schema = 'public' and table_name = 'users'
       and column_name = v_cambio.campo;

    execute format('update public.users set %I = $1::text::%s where id = $2',
                   v_cambio.campo, coalesce(v_tipo, 'text'))
      using v_cambio.valor_nuevo, v_cambio.user_id;

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

-- =========================================================================
-- E. Con quién se puede emparejar un jefe
--
-- Solo nombre, cargo y área: lo mínimo para reconocer a la persona en una
-- lista. Ni cédula ni correo ni teléfono, que no hacen falta para elegir y
-- son datos personales de terceros (LOPDP, Art. 10: minimización).
-- =========================================================================

create or replace view public.v_jefaturas as
select u.id, u.nombre, u.cargo, u.departamento,
       coalesce(u.region, 'sierra') as region,
       (select count(*) from public.users s where s.jefe_id = u.id and s.activo) as a_cargo
  from public.users u
 where u.activo
   and (u.rol in ('jefe', 'rrhh', 'admin')
        or exists (select 1 from public.users s where s.jefe_id = u.id and s.activo))
 order by u.nombre;

grant select on public.v_jefaturas to authenticated;

comment on view public.v_jefaturas is
  'Quiénes pueden figurar como jefe inmediato. Sin datos de contacto: solo lo necesario para elegir en una lista.';

-- =========================================================================
-- F. Qué confirmó la persona al entrar por primera vez
--
-- Que alguien diga «mi cargo está bien» es un dato con valor propio: deja
-- constancia de que la planilla se revisó contra quien la vive, y permite
-- a Talento Humano separar lo verificado de lo que nadie miró nunca.
-- =========================================================================

alter table public.users
  add column if not exists cargo_confirmado_en timestamptz,
  add column if not exists jefe_confirmado_en  timestamptz;

comment on column public.users.cargo_confirmado_en is
  'Cuándo la propia persona confirmó que el cargo registrado es el suyo.';
comment on column public.users.jefe_confirmado_en is
  'Cuándo la propia persona confirmó que el jefe registrado es el suyo.';

create or replace view public.v_ficha_sin_confirmar as
select u.id, u.cedula, u.nombre, u.cargo, u.departamento, u.ciudad,
       coalesce(u.region, 'sierra') as region,
       j.nombre as jefe,
       u.correo_pendiente,
       u.cargo_confirmado_en is not null as cargo_confirmado,
       u.jefe_confirmado_en  is not null as jefe_confirmado
  from public.users u
  left join public.users j on j.id = u.jefe_id
 where u.activo
   and (u.correo_pendiente
        or u.cargo_confirmado_en is null
        or u.jefe_confirmado_en is null
        or u.jefe_id is null);

grant select on public.v_ficha_sin_confirmar to authenticated;

comment on view public.v_ficha_sin_confirmar is
  'A quiénes les falta confirmar correo, cargo o jefe. Es la lista de trabajo de Talento Humano para depurar la planilla.';

-- =========================================================================
-- G. La bandeja muestra nombres, no identificadores
--
-- Un pedido de cambio de jefe llegaba a Talento Humano así:
--
--   144335b0-f405-4d4c-84ac-db1246babb50 → df160da3-d920-496b-8239-855e81499074
--
-- Nadie puede confirmar eso. El valor viaja como identificador porque es lo
-- que se escribe en la columna, pero quien revisa necesita leer a quién
-- señalaron. Se resuelve aquí, donde ya están los dos extremos, y no en la
-- pantalla: el catálogo de jefaturas excluye a quien lo consulta, así que un
-- administrador señalado como jefe no aparecía en su propia lista y se
-- quedaba sin traducir justo en el caso más común.
-- =========================================================================

drop view if exists public.v_cambios_ficha_pendientes;

create view public.v_cambios_ficha_pendientes as
select c.id, c.user_id, u.cedula, u.nombre as persona, u.departamento, u.ciudad,
       coalesce(u.region, 'sierra') as region,
       c.campo, f.etiqueta, c.valor_anterior, c.valor_nuevo, c.motivo, c.created_at,
       case when c.campo = 'jefe_id'
            then coalesce((select j.nombre from public.users j
                            where j.id::text = c.valor_anterior), c.valor_anterior)
            else c.valor_anterior end as anterior_legible,
       case when c.campo = 'jefe_id'
            then coalesce((select j.nombre from public.users j
                            where j.id::text = c.valor_nuevo), c.valor_nuevo)
            else c.valor_nuevo end as nuevo_legible
  from public.cambios_ficha c
  join public.users u on u.id = c.user_id
  join public.campos_ficha f on f.campo = c.campo
 where c.estado = 'pendiente'
 order by c.created_at;

grant select on public.v_cambios_ficha_pendientes to authenticated;
