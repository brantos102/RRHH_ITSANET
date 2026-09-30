-- ---------------------------------------------------------------------------
-- 0026 · El panel del día en la garita.
--
-- La garita ya sabía validar un código y ya registraba la salida y el regreso
-- (migración 0018). Lo que faltaba era la vista de conjunto: el guardia tenía
-- una lista de quién tiene permiso hoy, pero no de en qué punto va cada uno.
--
-- La pregunta que se hace un guardia a las cuatro de la tarde no es «¿quién
-- tiene permiso?» sino «¿quién está fuera y ya debería haber vuelto?». Eso
-- hay que poder verlo sin escanear nada y sin abrir una solicitud por una.
--
-- Cinco situaciones, y cada una pide algo distinto:
--
--   sin_salir       Tiene permiso y todavía no lo usó. Puede que no lo use.
--   fuera           Salió y tiene que volver hoy. Se le espera.
--   fuera_atrasado  Salió, tenía que volver y pasó la hora. Es lo único
--                   que exige actuar, y por eso es lo que va primero.
--   no_vuelve_hoy   Salió por una ausencia de jornada completa. No vuelve
--                   hoy, y tratarlo como atrasado sería una falsa alarma.
--   completo        Salió y volvió. No hay nada que hacer.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

create or replace view public.v_garita_hoy as
with movimientos as (
  select r.id as request_id,
         min(a.created_at) filter (
           where a.tipo_acceso = 'salida_empleado' and a.autorizado) as salio_en
    from public.requests r
    left join public.access_logs a on a.request_id = r.id
   group by r.id
)
select
  r.id                as request_id,
  r.folio,
  u.id                as user_id,
  u.cedula,
  u.nombre,
  u.cargo,
  u.departamento,
  r.tipo::text        as tipo,
  pt.nombre           as categoria,
  r.fecha_inicio,
  r.fecha_fin,
  r.hora_inicio,
  r.hora_fin,
  m.salio_en,
  r.retorno_en,
  r.retorno_exceso_minutos,
  -- Un permiso por horas del mismo día es el único que obliga a volver hoy.
  (r.hora_fin is not null and r.fecha_inicio = r.fecha_fin) as debe_volver_hoy,
  case when r.hora_fin is not null and r.fecha_inicio = r.fecha_fin
       then (r.fecha_fin + r.hora_fin)::timestamptz end     as se_espera_a_las,
  case
    when m.salio_en is null                                  then 'sin_salir'
    when r.retorno_en is not null                            then 'completo'
    when not (r.hora_fin is not null and r.fecha_inicio = r.fecha_fin)
                                                             then 'no_vuelve_hoy'
    when now() > (r.fecha_fin + r.hora_fin)::timestamptz     then 'fuera_atrasado'
    else 'fuera'
  end as situacion,
  -- Cuánto lleva de atraso, para poder ordenarlo y decirlo sin calcular.
  case when m.salio_en is not null and r.retorno_en is null
        and r.hora_fin is not null and r.fecha_inicio = r.fecha_fin
        and now() > (r.fecha_fin + r.hora_fin)::timestamptz
       then round(extract(epoch from (now() - (r.fecha_fin + r.hora_fin)::timestamptz)) / 60.0)
  end as minutos_de_atraso
from public.requests r
join public.users u on u.id = r.user_id
left join public.permission_types pt on pt.id = r.permission_type_id
left join movimientos m on m.request_id = r.id
where r.estado = 'aprobado'
  and current_date between r.fecha_inicio and r.fecha_fin;

grant select on public.v_garita_hoy to authenticated;

comment on view public.v_garita_hoy is
  'Quién tiene permiso hoy y en qué punto va: sin salir, fuera, fuera y atrasado, no vuelve hoy, o completo. Lo único que exige actuar es «fuera_atrasado».';
