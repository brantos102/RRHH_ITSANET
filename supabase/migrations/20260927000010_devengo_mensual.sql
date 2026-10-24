-- ---------------------------------------------------------------------------
-- 0010 · Las vacaciones se devengan mes a mes, no de golpe al cumplir el año.
--
-- Hasta ahora el período en curso valía 0 días hasta el aniversario: quien
-- llevaba once meses en la empresa tenía saldo cero. La planilla real de
-- Talento Humano acumula 1.25 días por mes trabajado —15 días al año
-- repartidos en doce— y es la forma correcta: el derecho se genera con el
-- trabajo prestado, no aparece completo un día concreto. Es también lo que
-- permite liquidar proporcionalmente a quien sale antes del aniversario.
--
-- El período en curso pasa a llevar la parte devengada, que crece cada mes.
-- Los períodos ya cumplidos no cambian: siguen valiendo lo que manda la
-- tabla de antigüedad.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

create or replace function public.dias_devengados_en_curso(
  p_ingreso date,
  p_periodo integer
) returns numeric
language sql
immutable
as $dev$
  -- Meses completos transcurridos dentro del período en curso, por la parte
  -- diaria que corresponde a ese año de antigüedad. Se acota a doce para que
  -- un período vencido sin renovar no acumule de más.
  select round(
    public.dias_por_antiguedad(p_periodo) *
    least(
      greatest(
        (extract(year  from age(current_date, (p_ingreso + make_interval(years => p_periodo - 1))::date)) * 12
         + extract(month from age(current_date, (p_ingreso + make_interval(years => p_periodo - 1))::date))),
        0),
      12) / 12.0,
    2)::numeric;
$dev$;

comment on function public.dias_devengados_en_curso(date, integer) is
  'Días de vacaciones ganados hasta hoy dentro del período en curso. 15 días al año equivalen a 1.25 por mes cumplido, que es como los calcula Talento Humano.';

create or replace function public.generar_periodos_vacaciones(p_user_id uuid)
returns integer
language plpgsql
as $gen$
declare
  v_ingreso date;
  v_anios   int;
  v_fds     int := public.cfg_int('fines_semana_obligatorios');
  v_acum    int := public.cfg_int('acumulacion_max_anios');
  k         int;
  v_hasta   date;
  v_creados int := 0;
  v_parcial numeric;
begin
  select fecha_ingreso into v_ingreso from public.users where id = p_user_id;
  if v_ingreso is null then
    raise exception 'Usuario % no existe', p_user_id;
  end if;

  v_anios := public.anios_cumplidos(v_ingreso);

  -- Períodos ya devengados (años cumplidos)
  for k in 1..greatest(v_anios, 0) loop
    v_hasta := (v_ingreso + make_interval(years => k))::date - 1;
    insert into public.vacation_periods
      (user_id, periodo, fecha_desde, fecha_hasta, dias_asignados,
       fines_semana_obligatorios, devengado, vence_en)
    values
      (p_user_id, k, (v_ingreso + make_interval(years => k - 1))::date, v_hasta,
       public.dias_por_antiguedad(k), v_fds, true,
       (v_hasta + make_interval(years => v_acum))::date)
    on conflict (user_id, periodo) do update
      set dias_asignados = excluded.dias_asignados,
          devengado      = true,
          vence_en       = excluded.vence_en
      where not public.vacation_periods.devengado;   -- solo completa períodos anticipados
    v_creados := v_creados + 1;
  end loop;

  -- Período en curso: lleva lo devengado hasta hoy, que crece cada mes.
  k         := v_anios + 1;
  v_hasta   := (v_ingreso + make_interval(years => k))::date - 1;
  v_parcial := public.dias_devengados_en_curso(v_ingreso, k);

  insert into public.vacation_periods
    (user_id, periodo, fecha_desde, fecha_hasta, dias_asignados,
     fines_semana_obligatorios, devengado, vence_en)
  values
    (p_user_id, k, (v_ingreso + make_interval(years => k - 1))::date, v_hasta,
     v_parcial, v_fds, false, (v_hasta + make_interval(years => v_acum))::date)
  on conflict (user_id, periodo) do update
    -- Se actualiza al alza únicamente: si el período ya tiene días
    -- consumidos o un ajuste manual de Talento Humano por encima de lo
    -- devengado, no se le quita nada a nadie por recalcular.
    set dias_asignados = greatest(public.vacation_periods.dias_asignados, excluded.dias_asignados)
    where not public.vacation_periods.devengado;

  perform public.refrescar_saldo_vacaciones(p_user_id);
  return v_creados;
end;
$gen$;
