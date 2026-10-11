-- ---------------------------------------------------------------------------
-- 0043 · El turno del domingo existía; el permiso para ese turno, no.
--
-- calcular_dias() descarta sábados, domingos y feriados. Para vacaciones y
-- para permisos de varios días eso es lo correcto. Pero esta empresa tiene
-- GARITA —puesto cubierto los siete días— y tiene operarios con turnos de
-- fin de semana. A esa gente el sistema le rechazaba el permiso por horas
-- con este mensaje:
--
--     «El rango de fechas no genera días computables (feriados/fin de semana).»
--
-- Es decir: el guardia que cubre el domingo y necesita dos horas para una
-- diligencia no podía ni registrar la solicitud, y el mensaje le hablaba de
-- feriados. No es un caso de borde: es el personal de garita, todos los
-- domingos del año.
--
-- CÓMO SE ARREGLA SIN TOCAR NADA MÁS. Solo cuando se cumplen las dos
-- condiciones a la vez: no es vacación y es un único día (fecha de inicio
-- igual a fecha de fin). Las vacaciones, los permisos de varios días y el
-- cálculo de saldos quedan exactamente como estaban. Un rango de lunes a
-- lunes sigue contando cinco días y no siete.
--
-- Se encontró porque la suite de pruebas se caía los sábados y los domingos
-- —dieciocho pruebas— y el calendario no es una excusa válida para un fallo.
--
-- La función se reemplaza DESDE SU DEFINICIÓN VIVA (la que dejó la 0017),
-- añadiendo un solo bloque antes de la validación. Idempotente.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.tg_requests_before_insert()
 RETURNS trigger
 LANGUAGE plpgsql
AS $function$
declare
  v_saldo    numeric(6,2);
  v_jefe     uuid;
  v_ingreso  date;
  v_pt       public.permission_types%rowtype;
  v_fds_req  int;
  v_sug      date[];
begin
  select u.dias_vacaciones, u.jefe_id, u.fecha_ingreso
    into v_saldo, v_jefe, v_ingreso
  from public.users u where u.id = new.user_id and u.activo;

  if v_ingreso is null then
    raise exception 'Usuario % no existe o está inactivo', new.user_id;
  end if;

  -- Asegurar que el empleado tenga sus períodos generados
  perform public.generar_periodos_vacaciones(new.user_id);
  select dias_vacaciones into v_saldo from public.users where id = new.user_id;

  new.dias_solicitados   := public.calcular_dias(new.tipo, new.fecha_inicio, new.fecha_fin);
  new.saldo_al_solicitar := v_saldo;
  new.jefe_id            := coalesce(new.jefe_id, v_jefe);
  new.estado             := 'pendiente_jefe';
  new.fines_semana       := public.fines_de_semana_completos(new.fecha_inicio, new.fecha_fin);

  if new.hora_inicio is not null and new.hora_fin is not null then
    new.horas_solicitadas := round(extract(epoch from (new.hora_fin - new.hora_inicio)) / 3600.0, 2);
  end if;

  -- UN PERMISO DE UN SOLO DÍA CUENTA AUNQUE EL DÍA NO SEA HÁBIL.
  -- calcular_dias() descarta sábados, domingos y feriados, y eso es correcto
  -- para vacaciones y para permisos de varios días. Pero en una empresa con
  -- garita y con operarios hay gente trabajando el domingo, y a esa gente el
  -- sistema le rechazaba el permiso con un mensaje sobre feriados: el turno
  -- existía y el permiso no se podía pedir. Quien pide un día concreto está
  -- pidiendo ausentarse de un turno que SÍ está cubriendo, así que ese día
  -- cuenta como uno. Un rango de varios días no se toca: ahí descartar el
  -- fin de semana sigue siendo lo correcto.
  if new.dias_solicitados <= 0
     and new.tipo <> 'vacacion'
     and new.fecha_inicio = new.fecha_fin then
    new.dias_solicitados := 1;
  end if;

  if new.dias_solicitados <= 0 then
    raise exception 'El rango de fechas no genera días computables (feriados/fin de semana).';
  end if;

  -- ---- Reglas de VACACIONES ----
  if new.tipo = 'vacacion' then
    new.es_adelanto := (new.dias_solicitados > v_saldo);

    -- Regla de los fines de semana obligatorios
    v_fds_req := public.fines_semana_pendientes(new.user_id);
    -- Una excepción al bloque mínimo queda fuera de esta regla. Exigirle un
    -- fin de semana completo a quien pide dos días por una urgencia es pedirle
    -- justo lo que la excepción existe para no exigir: el sistema le respondía
    -- «use 2026-11-07 a 2026-11-10», o sea cuatro días, a quien necesitaba dos.
    if v_fds_req > 0 and new.fines_semana = 0 and not new.omitir_regla_fds
       and not coalesce(new.bloque_menor_justificado, false)
       and (extract(isodow from new.fecha_fin) = 5 or extract(isodow from new.fecha_inicio) = 1) then
      v_sug := public.sugerir_rango_con_fin_de_semana(new.fecha_inicio, new.fecha_fin);
      raise exception
        'Le faltan % fin(es) de semana obligatorio(s) por consumir. La solicitud debe incluir sábado y domingo: use % a %',
        v_fds_req, v_sug[1], v_sug[2]
        using errcode = 'P0001', hint = v_sug[1]::text || '|' || v_sug[2]::text;
    end if;

  -- ---- Reglas de PERMISOS ----
  else
    select * into v_pt from public.permission_types where id = new.permission_type_id and activo;
    if v_pt.id is null then
      raise exception 'Tipo de permiso inválido o inactivo';
    end if;

    new.es_adelanto := v_pt.descuenta_vacaciones and new.dias_solicitados > v_saldo;

    if v_pt.requiere_justificacion
       and (new.justificacion is null or length(btrim(new.justificacion)) < 10) then
      raise exception 'El permiso "%" requiere justificación de al menos 10 caracteres', v_pt.nombre;
    end if;

    if v_pt.max_dias is not null and new.dias_solicitados > v_pt.max_dias then
      raise exception 'El permiso "%" admite un máximo de % día(s); solicitó %',
        v_pt.nombre, v_pt.max_dias, new.dias_solicitados;
    end if;

    if v_pt.max_horas is not null and new.horas_solicitadas is not null
       and new.horas_solicitadas > v_pt.max_horas then
      raise exception 'El permiso "%" admite un máximo de % hora(s); solicitó %',
        v_pt.nombre, v_pt.max_horas, new.horas_solicitadas;
    end if;
  end if;

  return new;
end;
$function$

;
