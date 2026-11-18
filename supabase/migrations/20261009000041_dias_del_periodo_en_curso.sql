-- ---------------------------------------------------------------------------
-- 0041 · «A este año le tocan N días» decía uno menos.
--
-- Quien lleva 7 años CUMPLIDOS está cursando su período 8. El sistema asigna
-- los días por el número de período —así se generaron: el 6 valió 16, el 7
-- valió 17—, pero la línea informativa los calculaba por los años cumplidos.
-- Resultado: a esa persona la pantalla le decía 17 cuando su período en
-- curso va a consolidar 18.
--
-- EL SALDO NUNCA ESTUVO MAL. El año en curso devenga sobre la base de quince
-- días (1,25 al mes), no sobre el tope del período, así que ni el saldo ni
-- los 4.085 días consolidados cambian con esto. Lo que estaba mal era lo que
-- se le decía a la persona sobre lo que va a recibir, y es justo el número
-- que Talento Humano contrasta contra su hoja.
--
-- Afecta solo a quienes pasan de cinco años de servicio: por debajo, todos
-- los períodos valen quince.
--
-- La función se reemplaza desde su definición VIVA, cambiando esa sola
-- línea. Idempotente.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.explicar_saldo_base(p_user_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
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
    -- El PERÍODO EN CURSO, no los años ya cumplidos. Quien lleva 7 años
    -- cumplidos está cursando su período 8, y ese período vale 18 días, no
    -- 17. Se calculaba con los años cumplidos y la línea «a este año le
    -- tocan N días» quedaba un día por debajo de lo que el propio sistema
    -- asigna al cerrar el período. El saldo nunca estuvo mal —el año en
    -- curso devenga sobre la base de 15—; lo que estaba mal era lo que se
    -- le decía a la persona que va a recibir.
    'dias_por_anio_actual', public.dias_por_antiguedad(greatest(v_anios, 0) + 1),
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
$function$
