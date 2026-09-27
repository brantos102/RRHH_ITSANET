-- ---------------------------------------------------------------------------
-- 0011 · La carga de saldos deja de ser cuadrática.
--
-- `cargar_saldo_inicial` llamaba a `caducar_periodos_vencidos()`, que
-- refresca el saldo de TODA la planilla. Cargar 351 personas disparaba
-- 351 × 351 refrescos: la carga inicial no terminaba, y en el editor SQL
-- de Supabase habría chocado contra el límite de tiempo por sentencia.
--
-- Caducar los períodos de una persona no requiere tocar a las demás. Se
-- separa esa parte y `cargar_saldo_inicial` usa la versión acotada. La
-- función global sigue existiendo para el trabajo programado, que sí debe
-- recorrer a todos.
-- ---------------------------------------------------------------------------

create or replace function public.caducar_periodos_de(p_user_id uuid)
returns integer
language plpgsql
as $cad$
declare v_n int;
begin
  with vencidos as (
    update public.vacation_periods
       set caducado = true
     where user_id = p_user_id
       and not caducado and vence_en < current_date and dias_saldo > 0
     returning 1
  )
  select count(*) into v_n from vencidos;

  perform public.refrescar_saldo_vacaciones(p_user_id);
  return v_n;
end;
$cad$;

comment on function public.caducar_periodos_de(uuid) is
  'Caduca los períodos vencidos de una sola persona. La versión global recorre la planilla entera y no debe usarse dentro de un bucle.';

create or replace function public.cargar_saldo_inicial(
  p_user_id uuid,
  p_saldo_real numeric,
  p_fds_ya_consumidos integer default 0
) returns numeric
language plpgsql
as $carga$
declare
  v_asignado  numeric;
  v_ajuste    numeric;
  v_restante  numeric;
  r           record;
  v_toma      numeric;
begin
  perform public.generar_periodos_vacaciones(p_user_id);
  perform public.caducar_periodos_de(p_user_id);     -- solo esta persona

  select coalesce(sum(dias_asignados), 0) into v_asignado
  from public.vacation_periods where user_id = p_user_id and not caducado;

  v_ajuste := v_asignado - p_saldo_real;   -- días ya tomados históricamente
  if v_ajuste < 0 then
    raise exception 'El saldo indicado (%) supera lo devengado no caducado (%)', p_saldo_real, v_asignado;
  end if;

  update public.vacation_periods set dias_consumidos = 0
   where user_id = p_user_id and not caducado;

  v_restante := v_ajuste;
  for r in select id, dias_asignados from public.vacation_periods
            where user_id = p_user_id and not caducado and dias_asignados > 0
            order by periodo
  loop
    exit when v_restante <= 0;
    v_toma := least(r.dias_asignados, v_restante);
    update public.vacation_periods set dias_consumidos = v_toma where id = r.id;
    v_restante := v_restante - v_toma;
  end loop;

  update public.vacation_periods
     set fines_semana_consumidos = least(p_fds_ya_consumidos, fines_semana_obligatorios)
   where id = (select id from public.vacation_periods
                where user_id = p_user_id and not caducado order by periodo limit 1);

  insert into public.vacation_movements
    (user_id, dias, saldo_previo, saldo_nuevo, motivo)
  values (p_user_id, 0, 0, p_saldo_real, 'Carga de saldo inicial (migración de datos)');

  return public.refrescar_saldo_vacaciones(p_user_id);
end;
$carga$;

-- ---------------------------------------------------------------------------
-- Un período creado retroactivamente ya puede nacer caducado
--
-- `generar_periodos_vacaciones` creaba todos los períodos desde el ingreso y
-- recién después alguien llamaba a la caducidad. Entre una cosa y otra, el
-- saldo se refrescaba sumando períodos que llevaban años vencidos: para
-- quien tiene 18 años en la empresa daba 370 días y chocaba contra el tope
-- de la columna. En la práctica dejaba fuera a toda la gente con más de
-- tres o cuatro años, que es la mayoría de la planilla.
--
-- Un período que nace con la fecha de vencimiento pasada está caducado desde
-- el primer momento: la acumulación máxima son 3 años (Art. 75 del Código
-- del Trabajo). Se marca al insertarlo, no después.
-- ---------------------------------------------------------------------------

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
  v_vence   date;
  v_creados int := 0;
  v_parcial numeric;
begin
  select fecha_ingreso into v_ingreso from public.users where id = p_user_id;
  if v_ingreso is null then
    raise exception 'Usuario % no existe', p_user_id;
  end if;

  v_anios := public.anios_cumplidos(v_ingreso);

  for k in 1..greatest(v_anios, 0) loop
    v_hasta := (v_ingreso + make_interval(years => k))::date - 1;
    v_vence := (v_hasta + make_interval(years => v_acum))::date;
    insert into public.vacation_periods
      (user_id, periodo, fecha_desde, fecha_hasta, dias_asignados,
       fines_semana_obligatorios, devengado, vence_en, caducado)
    values
      (p_user_id, k, (v_ingreso + make_interval(years => k - 1))::date, v_hasta,
       public.dias_por_antiguedad(k), v_fds, true, v_vence,
       v_vence < current_date)
    on conflict (user_id, periodo) do update
      set dias_asignados = excluded.dias_asignados,
          devengado      = true,
          vence_en       = excluded.vence_en
      where not public.vacation_periods.devengado;
    v_creados := v_creados + 1;
  end loop;

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
    set dias_asignados = greatest(public.vacation_periods.dias_asignados, excluded.dias_asignados)
    where not public.vacation_periods.devengado;

  perform public.refrescar_saldo_vacaciones(p_user_id);
  return v_creados;
end;
$gen$;

-- ---------------------------------------------------------------------------
-- Un saldo negativo de la planilla se conserva
--
-- Diez personas vienen con saldo negativo: ya tomaron días que todavía no
-- devengan. El bucle de consumo solo podía descontar hasta lo asignado, de
-- modo que esos saldos se redondeaban a cero y la empresa perdía el
-- registro de 21 días adelantados. El remanente se carga sobre el último
-- período, que es donde corresponde: es deuda contra lo que viene.
-- ---------------------------------------------------------------------------

create or replace function public.cargar_saldo_inicial(
  p_user_id uuid,
  p_saldo_real numeric,
  p_fds_ya_consumidos integer default 0
) returns numeric
language plpgsql
as $carga$
declare
  v_asignado  numeric;
  v_ajuste    numeric;
  v_restante  numeric;
  r           record;
  v_toma      numeric;
  v_ultimo    uuid;
begin
  perform public.generar_periodos_vacaciones(p_user_id);
  perform public.caducar_periodos_de(p_user_id);

  select coalesce(sum(dias_asignados), 0) into v_asignado
  from public.vacation_periods where user_id = p_user_id and not caducado;

  v_ajuste := v_asignado - p_saldo_real;   -- días ya tomados históricamente
  if v_ajuste < 0 then
    raise exception 'El saldo indicado (%) supera lo devengado no caducado (%)', p_saldo_real, v_asignado;
  end if;

  update public.vacation_periods set dias_consumidos = 0
   where user_id = p_user_id and not caducado;

  v_restante := v_ajuste;
  for r in select id, dias_asignados from public.vacation_periods
            where user_id = p_user_id and not caducado and dias_asignados > 0
            order by periodo
  loop
    exit when v_restante <= 0;
    v_toma := least(r.dias_asignados, v_restante);
    update public.vacation_periods set dias_consumidos = v_toma where id = r.id;
    v_restante := v_restante - v_toma;
  end loop;

  -- Lo que no alcanzó a descontarse es un adelanto real: se anota en el
  -- período más reciente para que el saldo quede en negativo, como está en
  -- la planilla, en vez de perderse.
  if v_restante > 0 then
    select id into v_ultimo from public.vacation_periods
     where user_id = p_user_id and not caducado
     order by periodo desc limit 1;
    if v_ultimo is not null then
      update public.vacation_periods
         set dias_consumidos = dias_consumidos + v_restante
       where id = v_ultimo;
    end if;
  end if;

  update public.vacation_periods
     set fines_semana_consumidos = least(p_fds_ya_consumidos, fines_semana_obligatorios)
   where id = (select id from public.vacation_periods
                where user_id = p_user_id and not caducado order by periodo limit 1);

  insert into public.vacation_movements
    (user_id, dias, saldo_previo, saldo_nuevo, motivo)
  values (p_user_id, 0, 0, p_saldo_real, 'Carga de saldo inicial (migración de datos)');

  return public.refrescar_saldo_vacaciones(p_user_id);
end;
$carga$;
