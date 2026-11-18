-- ============================================================================
-- 0015 · Una persona no puede estar ausente dos veces los mismos días
-- ============================================================================
-- Se detectó probando con datos acumulados: una misma colaboradora tenía cinco
-- ausencias aprobadas que empezaban el mismo día. Nada lo impedía.
--
-- Las consecuencias no son cosméticas:
--   * el saldo se descuenta una vez por solicitud, así que se pagan dos veces
--     los mismos días de vacaciones;
--   * garita acepta varios QR válidos para la misma fecha;
--   * el calendario del equipo pinta una cualquiera de las solapadas, de modo
--     que el jefe ve un folio y Talento Humano otro para el mismo día —fue
--     justo así como salió a la luz.
--
-- Lo que sí debe seguir permitido: dos permisos por horas el mismo día en
-- horarios que no se pisan (una cita a las 09:00 y un trámite a las 16:00).
-- Esa es la única excepción.
--
-- Idempotente: se puede volver a ejecutar sin efectos.

-- --------------------------------------------------------------- detección
create or replace function public.ausencia_solapada(
  p_user        uuid,
  p_desde       date,
  p_hasta       date,
  p_hora_inicio time default null,
  p_hora_fin    time default null,
  p_excluir     uuid default null
) returns table (
  request_id   uuid,
  folio        bigint,
  fecha_inicio date,
  fecha_fin    date,
  estado       public.request_status,
  por_horas    boolean
)
language sql
stable
security definer
set search_path = public
as $solape$
  select r.id, r.folio, r.fecha_inicio, r.fecha_fin, r.estado,
         (r.hora_inicio is not null and r.fecha_inicio = r.fecha_fin)
  from public.requests r
  where r.user_id = p_user
    -- Lo cancelado y lo rechazado libera las fechas; lo que espera decisión,
    -- no: pedir dos veces los mismos días es el error que se quiere frenar,
    -- y frenarlo al pedir es más barato que descubrirlo al aprobar.
    and r.estado in ('pendiente_jefe', 'pendiente_rrhh', 'pendiente_anulacion', 'aprobado')
    and (p_excluir is null or r.id <> p_excluir)
    and r.fecha_inicio <= p_hasta
    and r.fecha_fin >= p_desde
    -- Única excepción: ambos son permisos de horas del mismo día y los
    -- horarios no se pisan. Se comparan con <= y >= a propósito: salir a las
    -- 12:00 de uno y entrar a las 12:00 del otro no es un conflicto.
    and not (
          p_hora_inicio is not null and p_hora_fin is not null and p_desde = p_hasta
      and r.hora_inicio is not null and r.hora_fin is not null
      and r.fecha_inicio = r.fecha_fin and r.fecha_inicio = p_desde
      and (p_hora_fin <= r.hora_inicio or p_hora_inicio >= r.hora_fin)
    )
  order by r.fecha_inicio, r.folio
  limit 1;
$solape$;

comment on function public.ausencia_solapada(uuid, date, date, time, time, uuid) is
  'Primera ausencia viva de la persona que se pisa con el rango dado, o nada. '
  'Dos permisos por horas del mismo día en horarios distintos no se pisan.';

-- ------------------------------------------------- al crear la solicitud
-- Se añade a la ruta de aprobación, que ya corre BEFORE INSERT y devuelve el
-- error de inmediato: así el formulario lo muestra en vez de guardar una fila
-- que alguien tendría que anular después.
create or replace function public.tg_requests_ruta_aprobacion()
returns trigger
language plpgsql
as $ruta$
declare
  v_minimo       numeric;
  v_anticipacion integer;
  v_calendario   integer;
  v_dias_aviso   integer;
  v_choque       record;
begin
  -- Antes que cualquier regla de política: si la persona ya está ausente esos
  -- días, lo demás no importa.
  select * into v_choque
    from public.ausencia_solapada(new.user_id, new.fecha_inicio, new.fecha_fin,
                                 new.hora_inicio, new.hora_fin, new.id);
  if v_choque.request_id is not null then
    raise exception
      'Ya tiene una ausencia registrada del % al % (solicitud Nº %, %). No se puede estar ausente dos veces los mismos días: anule esa solicitud o elija otras fechas.',
      to_char(v_choque.fecha_inicio, 'DD/MM/YYYY'),
      to_char(v_choque.fecha_fin, 'DD/MM/YYYY'),
      coalesce(v_choque.folio::text, 'sin folio'),
      replace(v_choque.estado::text, '_', ' ')
      using errcode = 'P0001', hint = 'solape|' || coalesce(v_choque.folio::text, '');
  end if;

  new.ruta_aprobacion := 'estandar';

  if new.tipo = 'vacacion' then
    select coalesce(nullif(valor, '')::numeric, 0) into v_minimo
      from public.app_config where clave = 'vacaciones_bloque_minimo';

    select coalesce(nullif(valor, '')::integer, 0) into v_anticipacion
      from public.app_config where clave = 'vacaciones_anticipacion_dias';

    -- El mínimo se mide en días de AUSENCIA, no en los que se descuentan
    -- del saldo. Un feriado dentro del rango no acorta el descanso: la
    -- persona igual está fuera. Medirlo contra `dias_solicitados` —que
    -- excluye feriados— hacía imposible tomar la semana de Navidad.
    v_calendario := (new.fecha_fin - new.fecha_inicio) + 1;
    v_dias_aviso := new.fecha_inicio - current_date;

    if coalesce(v_anticipacion, 0) > 0 and v_dias_aviso < v_anticipacion
       and not new.bloque_menor_justificado then
      raise exception
        'Las vacaciones se comunican con % días de anticipación y usted avisa con % (Lineamiento 1 de Talento Humano). Su jefe necesita ese tiempo para organizar quién cubre el puesto. Si el caso no admite espera, márquelo como excepción y explíquelo.',
        v_anticipacion, greatest(v_dias_aviso, 0)
        using errcode = 'P0001', hint = 'anticipacion|' || v_anticipacion::text;
    end if;

    if coalesce(v_minimo, 0) > 0 and v_calendario < v_minimo then
      if not new.bloque_menor_justificado then
        raise exception
          'Las vacaciones se toman en bloques de al menos % días seguidos y usted pidió %. Si su caso lo amerita, márquelo como excepción, explique el motivo y adjunte el respaldo: la autoriza Talento Humano, no su jefe.',
          v_minimo, v_calendario
          using errcode = 'P0001', hint = 'bloque_minimo|' || v_minimo::text;
      end if;

      if length(btrim(coalesce(new.justificacion, ''))) < 30 then
        raise exception
          'Para tomar menos de % días debe justificarlo por escrito, con al menos 30 caracteres: quien autoriza la excepción necesita entender por qué se aparta de la política.',
          v_minimo;
      end if;
    end if;

    -- Apartarse de la política y comprometer días que no existen son las
    -- dos decisiones que no le corresponden a la jefatura inmediata.
    if new.bloque_menor_justificado or new.es_adelanto then
      new.ruta_aprobacion := 'rrhh_primero';
      new.estado := 'pendiente_rrhh';
    end if;
  else
    new.bloque_menor_justificado := false;
  end if;

  return new;
end;
$ruta$;

-- --------------------------------------------- al ajustar lo ya otorgado
-- Extender una ausencia puede meterla encima de otra: el mismo cuidado que al
-- crear. Se excluye la propia solicitud, que obviamente se pisa consigo misma.
create or replace function public.ajustar_ausencia(
  p_request_id uuid,
  p_inicio     date,
  p_fin        date,
  p_motivo     text,
  p_resolucion text,
  p_por        uuid
) returns public.requests
language plpgsql
security definer
set search_path = public
as $ajuste$
declare
  v_sol    public.requests;
  v_dias   numeric(6,2);
  v_choque record;
begin
  select * into v_sol from public.requests where id = p_request_id for update;
  if not found then
    raise exception 'La solicitud no existe';
  end if;

  if v_sol.estado <> 'aprobado' then
    raise exception 'Solo se ajusta una ausencia ya aprobada (esta está en %)', v_sol.estado;
  end if;

  if p_fin < p_inicio then
    raise exception 'La fecha de fin no puede ser anterior a la de inicio';
  end if;

  if length(btrim(coalesce(p_motivo, ''))) < 15 or length(btrim(coalesce(p_resolucion, ''))) < 15 then
    raise exception 'El ajuste exige explicar el caso y la resolución (mínimo 15 caracteres cada uno)';
  end if;

  -- Lo único que esta migración añade a la función: extender una ausencia
  -- puede meterla encima de otra de la misma persona. Se excluye la propia,
  -- que por definición se pisa consigo misma.
  select * into v_choque
    from public.ausencia_solapada(v_sol.user_id, p_inicio, p_fin,
                                 v_sol.hora_inicio, v_sol.hora_fin, v_sol.id);
  if v_choque.request_id is not null then
    raise exception
      'El nuevo rango se cruza con otra ausencia de la misma persona: del % al % (solicitud Nº %). Resuelva esa antes de extender esta.',
      to_char(v_choque.fecha_inicio, 'DD/MM/YYYY'),
      to_char(v_choque.fecha_fin, 'DD/MM/YYYY'),
      coalesce(v_choque.folio::text, 'sin folio')
      using errcode = 'P0001', hint = 'solape|' || coalesce(v_choque.folio::text, '');
  end if;

  v_dias := public.calcular_dias(v_sol.tipo, p_inicio, p_fin);

  -- El saldo solo se mueve en vacaciones; un permiso remunerado no lo toca.
  if v_sol.tipo = 'vacacion' and v_dias <> v_sol.dias_solicitados then
    perform public.reversar_vacaciones(v_sol.user_id, v_sol.dias_solicitados,
                                       v_sol.id, v_sol.fines_semana);
    perform public.consumir_vacaciones(v_sol.user_id, v_dias, v_sol.id,
                                       v_sol.fines_semana, p_por);
  end if;

  insert into public.request_adjustments
    (request_id, fecha_inicio_ant, fecha_fin_ant, fecha_inicio_nueva, fecha_fin_nueva,
     dias_ant, dias_nuevos, motivo, resolucion, ajustado_por)
  values
    (v_sol.id, v_sol.fecha_inicio, v_sol.fecha_fin, p_inicio, p_fin,
     v_sol.dias_solicitados, v_dias, btrim(p_motivo), btrim(p_resolucion), p_por);

  -- `true`: vive solo dentro de esta transacción.
  perform set_config('app.ajuste_en_curso', '1', true);

  update public.requests set
    fecha_inicio = p_inicio,
    fecha_fin    = p_fin,
    qr_expira_en = (p_fin + 1)::timestamptz,   -- garita debe reconocer el nuevo fin
    ajustada_en  = now(),
    ajustada_por = p_por,
    updated_at   = now()
  where id = v_sol.id
  returning * into v_sol;

  perform set_config('app.ajuste_en_curso', '0', true);
  return v_sol;
end
$ajuste$;

-- Índice para que la comprobación no recorra la tabla en cada solicitud.
create index if not exists requests_solape_idx
  on public.requests (user_id, fecha_inicio, fecha_fin)
  where estado in ('pendiente_jefe', 'pendiente_rrhh', 'pendiente_anulacion', 'aprobado');
