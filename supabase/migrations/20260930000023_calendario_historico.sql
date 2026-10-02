-- ---------------------------------------------------------------------------
-- 0023 · El calendario del equipo no tenía pasado.
--
-- La vista que lo alimenta terminaba así:
--
--     where r.estado in ('pendiente_jefe', 'pendiente_rrhh', 'aprobado')
--       and r.fecha_fin >= current_date - 31
--
-- Esa última línea recorta todo lo que terminó hace más de un mes. Al
-- retroceder al mes anterior el calendario aparecía en blanco —no porque
-- nadie hubiera faltado, sino porque la vista ya no lo contaba—, y no había
-- ninguna pantalla donde consultar las ausencias históricas.
--
-- El recorte tenía sentido cuando la vista solo servía para «quién falta
-- ahora». Pero el propio extremo de la API ya filtra por el rango de fechas
-- que se le pide, así que el límite estaba puesto dos veces y en el lugar
-- equivocado: el de arriba decide qué mes se mira, el de abajo impedía que
-- ese mes fuera uno pasado.
--
-- Se agregan también las ausencias anuladas, marcadas como tales. Un jefe
-- que mira atrás necesita saber que una ausencia se anuló; verla
-- desaparecer del calendario sin rastro es lo que hace que nadie confíe en
-- el calendario.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

drop view if exists public.v_calendario_equipo;

create view public.v_calendario_equipo as
select
  r.id            as request_id,
  r.folio,
  u.id            as user_id,
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
  -- Solo la naturaleza general de la ausencia, nunca la categoría del
  -- permiso: que alguien esté en cita médica es un dato de salud y no se
  -- exhibe en una grilla mensual (LOPDP, Art. 4).
  case r.tipo when 'vacacion' then 'Vacaciones' else 'Permiso' end as motivo_general,
  r.reemplazo_id,
  s.nombre        as reemplazo_nombre,
  r.ajustada_en,
  -- Lo pasado se distingue de lo que viene sin tener que comparar fechas en
  -- cada pantalla.
  r.fecha_fin < current_date as ya_ocurrio
from public.requests r
join public.users u on u.id = r.user_id
left join public.users s on s.id = r.reemplazo_id
where r.estado in ('pendiente_jefe', 'pendiente_rrhh', 'pendiente_anulacion',
                   'aprobado', 'cancelado');

comment on view public.v_calendario_equipo is
  'Ausencias del equipo, pasadas y futuras, para planificar y para consultar. Muestra quién y cuándo, nunca el motivo detallado (LOPDP Art. 4). El recorte por fechas lo hace quien consulta, no la vista.';

grant select on public.v_calendario_equipo to authenticated;
