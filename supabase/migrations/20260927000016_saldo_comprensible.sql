-- ============================================================================
-- 0016 · Que el saldo diga lo que significa, y que Talento Humano pueda corregirlo
-- ============================================================================
-- La tarjeta del panel mostraba «45 días» en grande y debajo «De 1 período(s):
-- año 6 (8.75)». Dos números que no se parecen, presentados como si fueran lo
-- mismo. No era un error de cálculo: son cosas distintas.
--
--   * Los años de servicio YA CUMPLIDOS generan días ganados (Art. 69 CT), que
--     se pueden acumular hasta tres años (Art. 75 CT). Esos son exigibles hoy.
--   * El año EN CURSO acumula 1,25 días por mes trabajado. Todavía no se
--     cumple el año, así que tomarlos es un adelanto y lo autoriza Talento
--     Humano.
--
-- Juntarlos en una sola cifra hace que nadie entienda cuánto puede pedir. Aquí
-- se separan en el origen, para que la pantalla no tenga que adivinar.
--
-- Se añade además el diagnóstico de desalineación: `users.dias_vacaciones` es
-- una copia cacheada de la suma de los períodos y, si alguna vez quedan
-- distintos, el titular miente sin que nadie se entere. Ahora se detecta y se
-- repara.
--
-- Idempotente: se puede volver a ejecutar sin efectos.

-- ------------------------------------------------- desglose de una persona
create or replace function public.saldo_desglosado(p_user_id uuid)
returns table (
  dias_ganados        numeric,   -- años cumplidos, exigibles hoy
  dias_en_curso       numeric,   -- lo acumulado del año en marcha
  dias_caducados      numeric,   -- se perdieron por el Art. 75
  saldo_cacheado      numeric,   -- lo que guarda users.dias_vacaciones
  desalineado         boolean,   -- el caché no coincide con los períodos
  periodos_ganados    integer,
  proximo_vence_en    date,
  proximo_dias        numeric
)
language sql
stable
security definer
set search_path = public
as $desglose$
  with p as (
    select * from public.vacation_periods where user_id = p_user_id
  ),
  prox as (
    select vence_en, dias_saldo from p
    where devengado and not caducado and dias_saldo > 0
    order by vence_en limit 1
  )
  select
    coalesce((select sum(dias_saldo) from p where devengado and not caducado), 0),
    coalesce((select sum(dias_saldo) from p where not devengado and not caducado), 0),
    coalesce((select sum(dias_saldo) from p where caducado), 0),
    coalesce((select dias_vacaciones from public.users where id = p_user_id), 0),
    coalesce((select dias_vacaciones from public.users where id = p_user_id), 0)
      is distinct from coalesce((select sum(dias_saldo) from p where not caducado), 0),
    (select count(*)::int from p where devengado and not caducado and dias_saldo > 0),
    (select vence_en from prox),
    (select dias_saldo from prox);
$desglose$;

comment on function public.saldo_desglosado(uuid) is
  'Separa lo ganado (años cumplidos, exigible) de lo que se acumula en el año '
  'en curso (adelanto, lo autoriza Talento Humano). Junto en una sola cifra, '
  'el saldo no se entiende.';

-- ------------------------------------------- la explicación de siempre
-- Copia literal de la función que ya existía, con otro nombre. Se separa para
-- que la nueva `explicar_saldo` solo añada claves y no haya que reescribir de
-- memoria lo que ya funcionaba: cualquier diferencia al transcribirlo sería
-- una regresión silenciosa.
create or replace function public.explicar_saldo_base(p_user_id uuid)
returns jsonb
language plpgsql
stable
as $$
declare
  v_u        record;
  v_anios    int;
  v_periodos jsonb;
  v_legal    jsonb;
  v_prox     record;
begin
  select id, nombre, fecha_ingreso, dias_vacaciones into v_u
  from public.users where id = p_user_id;

  if v_u.id is null then
    return jsonb_build_object('error', 'Usuario no encontrado');
  end if;

  v_anios := public.anios_cumplidos(v_u.fecha_ingreso);

  select jsonb_agg(jsonb_build_object(
           'periodo',      p.periodo,
           'desde',        p.fecha_desde,
           'hasta',        p.fecha_hasta,
           'asignados',    p.dias_asignados,
           'consumidos',   p.dias_consumidos,
           'saldo',        p.dias_saldo,
           'vence_en',     p.vence_en,
           'caducado',     p.caducado,
           'devengado',    p.devengado,
           'explicacion',  case
             when not p.devengado then 'Período en curso: aún no cumple el año de servicio.'
             when p.caducado then format('Caducó el %s por acumulación mayor a %s años (Art. 75 CT).',
                                         to_char(p.vence_en,'DD/MM/YYYY'), public.cfg_int('acumulacion_max_anios'))
             when p.periodo < public.cfg_int('vacaciones_anio_dia_extra')
               then format('Año %s de servicio: %s días base (Art. 69 CT).', p.periodo, p.dias_asignados)
             else format('Año %s de servicio: %s días base + %s día(s) por antigüedad (Art. 69 CT).',
                         p.periodo, public.cfg_int('vacaciones_dias_base'),
                         p.dias_asignados - public.cfg_int('vacaciones_dias_base'))
           end)
         order by p.periodo)
    into v_periodos
  from public.vacation_periods p where p.user_id = p_user_id;

  select p.periodo, p.vence_en, p.dias_saldo into v_prox
  from public.vacation_periods p
  where p.user_id = p_user_id and not p.caducado and p.dias_saldo > 0
  order by p.vence_en limit 1;

  select jsonb_agg(jsonb_build_object(
           'codigo', l.codigo, 'norma', l.norma, 'articulo', l.articulo,
           'titulo', l.titulo, 'texto', l.texto) order by l.orden)
    into v_legal
  from public.legal_references l
  where l.codigo in ('CT_ART_69','CT_ART_75','CT_ART_73','CT_ART_74');

  return jsonb_build_object(
    'empleado',        v_u.nombre,
    'fecha_ingreso',   v_u.fecha_ingreso,
    'anios_servicio',  v_anios,
    'saldo_total',     v_u.dias_vacaciones,
    'dias_por_anio_actual', public.dias_por_antiguedad(greatest(v_anios, 1)),
    'fines_semana_pendientes', public.fines_semana_pendientes(p_user_id),
    'regla_antiguedad', format(
      '%s días por año cumplido. Desde el año %s se suma 1 día por cada año de servicio, hasta un máximo de %s días adicionales (%s días en total).',
      public.cfg_int('vacaciones_dias_base'), public.cfg_int('vacaciones_anio_dia_extra'),
      public.cfg_int('vacaciones_dias_extra_max'),
      public.cfg_int('vacaciones_dias_base') + public.cfg_int('vacaciones_dias_extra_max')),
    'regla_fines_semana', format(
      'De los %s días del período, %s deben corresponder a %s fines de semana completos.',
      public.cfg_int('vacaciones_dias_base'), public.cfg_int('fines_semana_obligatorios') * 2,
      public.cfg_int('fines_semana_obligatorios')),
    'proximo_vencimiento', case when v_prox.periodo is null then null else jsonb_build_object(
      'periodo', v_prox.periodo, 'vence_en', v_prox.vence_en, 'dias_en_riesgo', v_prox.dias_saldo) end,
    'periodos',        coalesce(v_periodos, '[]'::jsonb),
    'base_legal',      coalesce(v_legal, '[]'::jsonb)
  );
end;
$$;

-- --------------------------------------------- se añade a explicar_saldo()
-- Se conservan todas las claves que ya devolvía: la pantalla vieja seguiría
-- funcionando igual.
create or replace function public.explicar_saldo(p_user_id uuid)
returns jsonb
language plpgsql
stable
as $expl$
declare
  v_base jsonb;
  v_d    record;
begin
  v_base := public.explicar_saldo_base(p_user_id);
  if v_base ? 'error' then
    return v_base;
  end if;

  select * into v_d from public.saldo_desglosado(p_user_id);

  return v_base || jsonb_build_object(
    'dias_ganados',       v_d.dias_ganados,
    'dias_en_curso',      v_d.dias_en_curso,
    'dias_caducados',     v_d.dias_caducados,
    'periodos_ganados',   v_d.periodos_ganados,
    'proximo_vence_en',   v_d.proximo_vence_en,
    'proximo_dias',       v_d.proximo_dias,
    'saldo_desalineado',  v_d.desalineado
  );
end;
$expl$;

-- ------------------------------------------------- reparar la desalineación
create or replace function public.recalcular_saldos(p_user_id uuid default null)
returns integer
language plpgsql
security definer
set search_path = public
as $recalc$
declare
  v_n integer := 0;
  r   record;
begin
  for r in
    select id from public.users
    where activo and (p_user_id is null or id = p_user_id)
  loop
    perform public.refrescar_saldo_vacaciones(r.id);
    v_n := v_n + 1;
  end loop;
  return v_n;
end;
$recalc$;

comment on function public.recalcular_saldos(uuid) is
  'Vuelve a calcular el saldo cacheado a partir de los períodos. Para Talento '
  'Humano, cuando el diagnóstico detecte una diferencia.';

-- Vista de control: quién tiene el caché distinto de sus períodos.
create or replace view public.v_saldos_desalineados as
select u.cedula, u.nombre, u.departamento,
       u.dias_vacaciones as saldo_mostrado,
       coalesce(sum(p.dias_saldo) filter (where not p.caducado), 0) as saldo_real,
       u.dias_vacaciones - coalesce(sum(p.dias_saldo) filter (where not p.caducado), 0)
         as diferencia
from public.users u
left join public.vacation_periods p on p.user_id = u.id
where u.activo
group by u.id, u.cedula, u.nombre, u.departamento, u.dias_vacaciones
having u.dias_vacaciones
       is distinct from coalesce(sum(p.dias_saldo) filter (where not p.caducado), 0);

comment on view public.v_saldos_desalineados is
  'Personas cuyo saldo mostrado no coincide con la suma de sus períodos. '
  'Debería estar siempre vacía; si no lo está, `recalcular_saldos()` lo corrige.';

-- ============================================================================
-- Fines de semana obligatorios: corregibles solo por Talento Humano
-- ============================================================================
-- El panel puede decir «2 fines de semana pendientes» cuando la persona ya los
-- tomó antes de que existiera el sistema. Eso no se arregla solo: hay que
-- poder corregirlo, y que quede constancia de quién lo hizo y por qué.
create or replace function public.corregir_fines_semana(
  p_user_id  uuid,
  p_periodo  integer,
  p_consumidos integer,
  p_motivo   text,
  p_por      uuid
) returns public.vacation_periods
language plpgsql
security definer
set search_path = public
as $fds$
declare
  v_p      public.vacation_periods;
  v_rol    public.user_role;
  v_antes  integer;
begin
  select rol into v_rol from public.users where id = p_por;
  if v_rol not in ('rrhh', 'admin') then
    raise exception 'Solo Talento Humano puede corregir los fines de semana obligatorios';
  end if;

  if length(btrim(coalesce(p_motivo, ''))) < 15 then
    raise exception 'Explique la corrección en al menos 15 caracteres: queda como constancia';
  end if;

  select * into v_p from public.vacation_periods
   where user_id = p_user_id and periodo = p_periodo for update;
  if not found then
    raise exception 'La persona no tiene un período %', p_periodo;
  end if;

  if p_consumidos < 0 or p_consumidos > v_p.fines_semana_obligatorios then
    raise exception 'Los fines de semana consumidos van de 0 a % en este período',
      v_p.fines_semana_obligatorios;
  end if;

  v_antes := v_p.fines_semana_consumidos;

  update public.vacation_periods
     set fines_semana_consumidos = p_consumidos, updated_at = now()
   where id = v_p.id
  returning * into v_p;

  insert into public.audit_logs (user_id, accion, detalle)
  values (p_por, 'fines_semana_corregidos',
          jsonb_build_object('empleado', p_user_id, 'periodo', p_periodo,
                             'antes', v_antes, 'despues', p_consumidos,
                             'motivo', btrim(p_motivo)));
  return v_p;
end;
$fds$;
