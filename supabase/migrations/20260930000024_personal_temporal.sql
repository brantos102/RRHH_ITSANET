-- ---------------------------------------------------------------------------
-- 0024 · Personal temporal: quién vino, cuánto estuvo y cuánto se le paga.
--
-- Es un sistema pequeño dentro del grande, y con otra lógica. El personal de
-- planta tiene expediente, vacaciones y jefe; el temporal viene por jornadas
-- y se le paga por lo que trabajó esa semana. Mezclarlos en `users` habría
-- dado una persona con saldo de vacaciones que nadie le debe, un jefe que no
-- tiene y un acceso al sistema que no necesita.
--
-- Lo que la empresa necesita de aquí es una sola cosa, dicha por Talento
-- Humano: cuántos días u horas hizo cada operario esta semana, para pagarle.
-- De eso se sigue la regla más importante:
--
--   NADIE PUEDE QUEDAR SIN SALIDA REGISTRADA.
--
-- Una jornada sin cerrar no es un detalle de la bitácora: es una jornada que
-- no se puede pagar, o que se paga a ojo. El sistema las señala, no las
-- inventa: no hay «salida automática a las 18:00», porque eso convierte un
-- dato faltante en un dato falso, que es peor.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. Quiénes son
-- =========================================================================

create table if not exists public.personal_temporal (
  id            uuid primary key default gen_random_uuid(),
  cedula        text not null unique
                  constraint temporal_cedula_valida check (public.es_cedula_valida(cedula)),
  nombre        text not null,
  labor         text,
  -- Quién lo contrata: proveedor, contratista o directamente la empresa.
  proveedor     text,
  telefono      text,
  -- Lo que se le paga por hora. Puede faltar —hay quien se paga por obra o
  -- por acuerdo—, y entonces el informe da horas sin valorar, que sigue
  -- siendo lo que la garita presenció.
  valor_hora    numeric(8,2) check (valor_hora is null or valor_hora >= 0),
  activo        boolean not null default true,
  observacion   text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists temporal_activo_idx on public.personal_temporal (activo, nombre);

comment on table public.personal_temporal is
  'Operarios temporales. No son usuarios del sistema: no tienen acceso, ni vacaciones, ni jefe. Vienen por jornadas.';

drop trigger if exists temporal_updated on public.personal_temporal;
create trigger temporal_updated before update on public.personal_temporal
  for each row execute function public.tg_set_updated_at();

alter table public.personal_temporal enable row level security;
drop policy if exists temporal_lectura on public.personal_temporal;
create policy temporal_lectura on public.personal_temporal
  for select to authenticated using (true);

-- =========================================================================
-- B. Las jornadas
--
-- Una fila por persona y día. La entrada se registra al llegar y la salida
-- al irse; entre las dos hay una jornada abierta, que es exactamente lo que
-- hay que vigilar.
-- =========================================================================

create table if not exists public.jornadas_temporales (
  id            uuid primary key default gen_random_uuid(),
  temporal_id   uuid not null references public.personal_temporal(id) on delete cascade,
  fecha         date not null default current_date,
  entrada_en    timestamptz not null default now(),
  salida_en     timestamptz,
  -- Se calculan al cerrar, no al consultar: el informe de la semana pasada
  -- no puede cambiar porque alguien corrigió un redondeo.
  horas         numeric(5,2),
  registro_entrada uuid references public.users(id) on delete set null,
  registro_salida  uuid references public.users(id) on delete set null,
  observacion   text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint jornada_salida_posterior
    check (salida_en is null or salida_en >= entrada_en),
  -- Una jornada por persona y día: si alguien sale y vuelve el mismo día, se
  -- corrige la que hay. Dos filas del mismo día se pagan dos veces.
  constraint jornada_unica_por_dia unique (temporal_id, fecha)
);

create index if not exists jornadas_fecha_idx on public.jornadas_temporales (fecha desc);
create index if not exists jornadas_abiertas_idx
  on public.jornadas_temporales (temporal_id) where salida_en is null;

comment on table public.jornadas_temporales is
  'Una fila por operario y día. Sin salida registrada, la jornada no se puede pagar: el sistema la señala y no la inventa.';

drop trigger if exists jornadas_updated on public.jornadas_temporales;
create trigger jornadas_updated before update on public.jornadas_temporales
  for each row execute function public.tg_set_updated_at();

alter table public.jornadas_temporales enable row level security;
drop policy if exists jornadas_lectura on public.jornadas_temporales;
create policy jornadas_lectura on public.jornadas_temporales
  for select to authenticated using (true);

-- =========================================================================
-- C. Registrar la llegada y la salida
-- =========================================================================

create or replace function public.temporal_registrar_entrada(
  p_temporal_id uuid,
  p_por         uuid,
  p_observacion text default null
) returns jsonb
language plpgsql
security definer
set search_path = public
as $tre$
declare
  v_persona public.personal_temporal;
  v_jornada public.jornadas_temporales;
begin
  select * into v_persona from public.personal_temporal where id = p_temporal_id;
  if not found then
    raise exception 'Ese operario no está registrado';
  end if;
  if not v_persona.activo then
    raise exception '% ya no está activo. Reactívelo antes de registrar su jornada.',
                    v_persona.nombre;
  end if;

  select * into v_jornada from public.jornadas_temporales
   where temporal_id = p_temporal_id and fecha = current_date;

  if found then
    if v_jornada.salida_en is null then
      raise exception '% ya tiene su entrada registrada hoy a las %. Lo que falta es su salida.',
                      v_persona.nombre, to_char(v_jornada.entrada_en, 'HH24:MI');
    end if;
    raise exception '% ya cumplió su jornada de hoy (% a %).',
                    v_persona.nombre,
                    to_char(v_jornada.entrada_en, 'HH24:MI'),
                    to_char(v_jornada.salida_en, 'HH24:MI');
  end if;

  insert into public.jornadas_temporales
      (temporal_id, registro_entrada, observacion)
  values (p_temporal_id, p_por, nullif(btrim(coalesce(p_observacion, '')), ''))
  returning * into v_jornada;

  return jsonb_build_object(
    'jornada_id', v_jornada.id,
    'nombre',     v_persona.nombre,
    'labor',      v_persona.labor,
    'entrada',    v_jornada.entrada_en,
    'movimiento', 'entrada');
end;
$tre$;

revoke all on function public.temporal_registrar_entrada(uuid, uuid, text) from public;

create or replace function public.temporal_registrar_salida(
  p_temporal_id uuid,
  p_por         uuid,
  p_observacion text default null
) returns jsonb
language plpgsql
security definer
set search_path = public
as $trs$
declare
  v_persona public.personal_temporal;
  v_jornada public.jornadas_temporales;
  v_horas   numeric(5,2);
begin
  select * into v_persona from public.personal_temporal where id = p_temporal_id;
  if not found then
    raise exception 'Ese operario no está registrado';
  end if;

  select * into v_jornada from public.jornadas_temporales
   where temporal_id = p_temporal_id and fecha = current_date
   for update;

  if not found then
    raise exception 'No hay entrada registrada hoy para %. No puede salir quien no entró.',
                    v_persona.nombre;
  end if;
  if v_jornada.salida_en is not null then
    raise exception '% ya registró su salida hoy a las %.',
                    v_persona.nombre, to_char(v_jornada.salida_en, 'HH24:MI');
  end if;

  v_horas := round(extract(epoch from (now() - v_jornada.entrada_en)) / 3600.0, 2);

  update public.jornadas_temporales
     set salida_en = now(),
         horas     = v_horas,
         registro_salida = p_por,
         observacion = coalesce(nullif(btrim(coalesce(p_observacion, '')), ''), observacion)
   where id = v_jornada.id
  returning * into v_jornada;

  return jsonb_build_object(
    'jornada_id', v_jornada.id,
    'nombre',     v_persona.nombre,
    'entrada',    v_jornada.entrada_en,
    'salida',     v_jornada.salida_en,
    'horas',      v_horas,
    'movimiento', 'salida');
end;
$trs$;

revoke all on function public.temporal_registrar_salida(uuid, uuid, text) from public;

-- =========================================================================
-- D. Cerrar a mano una jornada que quedó abierta
--
-- Pasa: alguien se fue sin timbrar. La salida la pone Talento Humano con la
-- hora que corresponda y queda constancia de que la puso una persona y no
-- la garita. No se inventa una hora por omisión, que sería convertir un dato
-- faltante en uno falso.
-- =========================================================================

create or replace function public.temporal_cerrar_jornada(
  p_jornada_id uuid,
  p_salida     timestamptz,
  p_por        uuid,
  p_motivo     text
) returns jsonb
language plpgsql
security definer
set search_path = public
as $tcj$
declare
  v_jornada public.jornadas_temporales;
  v_rol     text;
  v_horas   numeric(5,2);
begin
  select rol into v_rol from public.users where id = p_por;
  if v_rol is null or v_rol not in ('rrhh', 'admin') then
    raise exception 'Solo Talento Humano cierra a mano una jornada';
  end if;
  if length(btrim(coalesce(p_motivo, ''))) < 10 then
    raise exception 'Explique por qué se cierra a mano: queda en la bitácora';
  end if;

  select * into v_jornada from public.jornadas_temporales
   where id = p_jornada_id for update;
  if not found then
    raise exception 'Esa jornada no existe';
  end if;
  if v_jornada.salida_en is not null then
    raise exception 'Esa jornada ya está cerrada';
  end if;
  if p_salida < v_jornada.entrada_en then
    raise exception 'La salida no puede ser anterior a la entrada';
  end if;

  v_horas := round(extract(epoch from (p_salida - v_jornada.entrada_en)) / 3600.0, 2);

  update public.jornadas_temporales
     set salida_en = p_salida,
         horas     = v_horas,
         registro_salida = p_por,
         observacion = btrim(coalesce(observacion || ' · ', '')) ||
                       'Cerrada a mano: ' || btrim(p_motivo)
   where id = p_jornada_id
  returning * into v_jornada;

  return jsonb_build_object('jornada_id', v_jornada.id, 'horas', v_horas,
                            'salida', v_jornada.salida_en);
end;
$tcj$;

revoke all on function public.temporal_cerrar_jornada(uuid, timestamptz, uuid, text) from public;

-- =========================================================================
-- E. Lo que Talento Humano mira
-- =========================================================================

-- Quién está dentro ahora mismo.
create or replace view public.v_temporales_dentro as
select j.id as jornada_id, t.id as temporal_id, t.cedula, t.nombre, t.labor,
       t.proveedor, j.entrada_en,
       round(extract(epoch from (now() - j.entrada_en)) / 3600.0, 2) as horas_hasta_ahora
  from public.jornadas_temporales j
  join public.personal_temporal t on t.id = j.temporal_id
 where j.fecha = current_date and j.salida_en is null
 order by j.entrada_en;

grant select on public.v_temporales_dentro to authenticated;

-- Las que quedaron sin cerrar, de cualquier día. Es la lista que no puede
-- tener nada antes de pagar la semana.
create or replace view public.v_jornadas_sin_cerrar as
select j.id as jornada_id, t.id as temporal_id, t.cedula, t.nombre, t.labor,
       t.proveedor, j.fecha, j.entrada_en,
       current_date - j.fecha as dias_sin_cerrar
  from public.jornadas_temporales j
  join public.personal_temporal t on t.id = j.temporal_id
 where j.salida_en is null and j.fecha < current_date
 order by j.fecha, t.nombre;

grant select on public.v_jornadas_sin_cerrar to authenticated;

comment on view public.v_jornadas_sin_cerrar is
  'Jornadas de días pasados sin salida registrada. Una jornada sin cerrar no se puede pagar: esta lista debe estar vacía antes de liquidar la semana.';

-- Lo que se debe pagar, por semana.
create or replace function public.temporal_semana(
  p_desde date default null,
  p_hasta date default null
) returns table (
  temporal_id   uuid,
  cedula        text,
  nombre        text,
  labor         text,
  proveedor     text,
  dias          bigint,
  horas         numeric,
  valor_hora    numeric,
  total         numeric,
  sin_cerrar    bigint
)
language sql
stable
as $ts$
  -- Por omisión, la semana en curso de lunes a domingo.
  with rango as (
    select coalesce(p_desde, (current_date - ((extract(isodow from current_date)::int - 1)))) as desde,
           coalesce(p_hasta, (current_date - ((extract(isodow from current_date)::int - 1)) + 6)) as hasta
  )
  select t.id, t.cedula, t.nombre, t.labor, t.proveedor,
         count(*) filter (where j.salida_en is not null)      as dias,
         coalesce(sum(j.horas), 0)                            as horas,
         t.valor_hora,
         case when t.valor_hora is null then null
              else round(coalesce(sum(j.horas), 0) * t.valor_hora, 2) end as total,
         count(*) filter (where j.salida_en is null)          as sin_cerrar
    from public.personal_temporal t
    join public.jornadas_temporales j on j.temporal_id = t.id
    join rango r on j.fecha between r.desde and r.hasta
   group by t.id, t.cedula, t.nombre, t.labor, t.proveedor, t.valor_hora
   order by t.nombre;
$ts$;

comment on function public.temporal_semana(date, date) is
  'Lo trabajado por cada operario temporal en el rango, para pagarle. `sin_cerrar` cuenta las jornadas sin salida: mientras no sea cero, el total está incompleto.';
