-- ---------------------------------------------------------------------------
-- 0032 · El calendario del equipo recuerda lo que pasó antes del sistema.
--
-- Se cargaron 3.303 vacaciones de la hoja de Talento Humano y el calendario
-- del equipo seguía en blanco al retroceder de mes. No porque nadie hubiera
-- faltado: porque la vista solo mira `requests`, y esas vacaciones no son
-- solicitudes. No tienen folio, no pasaron por un jefe y no tienen código QR,
-- por eso viven en su propia tabla.
--
-- Un calendario que enseña lo de este año y nada de lo anterior no sirve para
-- lo que se usa un calendario de equipo: mirar cómo se repartieron las
-- vacaciones el año pasado antes de aprobar las de este.
--
-- SE MARCAN, NO SE MEZCLAN. Cada fila dice de dónde viene. Quien ve una
-- ausencia de 2019 tiene derecho a saber si se tramitó por aquí o si es un
-- registro que Talento Humano llevaba en su hoja, entre otras cosas porque
-- de la segunda no hay solicitud que abrir ni motivo que consultar.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

drop view if exists public.v_calendario_equipo;
create view public.v_calendario_equipo as
-- Lo que se tramitó por el sistema.
select r.id                as request_id,
       null::bigint        as historico_id,
       'solicitud'::text   as procedencia,
       r.folio,
       u.id                as user_id,
       u.nombre,
       u.cargo,
       u.departamento,
       u.jefe_id,
       r.fecha_inicio,
       r.fecha_fin,
       r.hora_inicio,
       r.hora_fin,
       r.dias_solicitados,
       r.estado,
       case r.tipo when 'vacacion' then 'Vacaciones' else 'Permiso' end as motivo_general,
       r.reemplazo_id,
       s.nombre            as reemplazo_nombre,
       r.ajustada_en,
       r.fecha_fin < current_date as ya_ocurrio
  from public.requests r
  join public.users u on u.id = r.user_id
  left join public.users s on s.id = r.reemplazo_id
 where r.estado = any (array['pendiente_jefe', 'pendiente_rrhh', 'pendiente_anulacion',
                             'aprobado', 'cancelado']::request_status[])

union all

-- Y lo que Talento Humano anotó antes de que el sistema existiera.
--
-- Va como aprobado porque lo está: son vacaciones que la persona gozó. Lo
-- que no tiene es expediente —ni folio, ni horas, ni reemplazo— y eso se ve
-- en las columnas vacías y en `procedencia`, no hay que deducirlo.
select null::uuid          as request_id,
       h.id                as historico_id,
       'historico'::text   as procedencia,
       null::bigint        as folio,
       u.id                as user_id,
       u.nombre,
       u.cargo,
       u.departamento,
       u.jefe_id,
       h.fecha_inicio,
       h.fecha_fin,
       null::time          as hora_inicio,
       null::time          as hora_fin,
       h.dias              as dias_solicitados,
       'aprobado'::request_status as estado,
       'Vacaciones'::text  as motivo_general,
       null::uuid          as reemplazo_id,
       null::text          as reemplazo_nombre,
       null::timestamptz   as ajustada_en,
       true                as ya_ocurrio
  from public.vacaciones_historicas h
  join public.users u on u.id = h.user_id
 where u.activo;

comment on view public.v_calendario_equipo is
  'Las ausencias del equipo, de antes y de ahora. `procedencia` dice cuáles se tramitaron aquí y cuáles vienen de la hoja de Talento Humano: nunca se presentan mezcladas sin distinguir.';

grant select on public.v_calendario_equipo to authenticated;
