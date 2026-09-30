-- ---------------------------------------------------------------------------
-- 0034 · El personal temporal deja de llevar dinero.
--
-- El módulo guardaba un valor por hora y calculaba cuánto se le debía a cada
-- operario. No le corresponde, y por dos razones distintas.
--
-- La primera es de fondo: quien decide cuánto se paga es Finanzas, con el
-- contrato del proveedor delante. Un sistema de control de acceso que
-- imprime un total en dólares invita a tomarlo por la cifra buena, y cuando
-- la tarifa cambia y nadie la actualiza aquí, la cifra sigue saliendo,
-- igual de convincente y ya equivocada.
--
-- La segunda es de protección de datos: la remuneración de una persona es un
-- dato que solo debe estar donde hace falta, y aquí no hacía falta.
--
-- LO QUE EL SISTEMA SÍ SABE, Y NADIE MÁS: quién vino, a qué hora entró y a
-- qué hora salió. Eso es lo que la garita presenció y es lo único que puede
-- sostener. Con las horas en la mano, Finanzas aplica la tarifa que
-- corresponda.
--
-- Se borra la columna, no se deja de usar: una columna que nadie llena vuelve
-- a llenarse sola el día que alguien la vea vacía y crea que falta un dato.
-- Estaba vacía en toda la planilla, así que no se pierde nada.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- La vista depende de la columna: primero se va la vista.
drop view if exists public.v_temporal_semana;

-- =========================================================================
-- A. La liquidación de la semana, en horas
-- =========================================================================

drop function if exists public.temporal_semana(date, date);

create or replace function public.temporal_semana(
  p_desde date default null,
  p_hasta date default null
) returns table (
  temporal_id   uuid,
  cedula        text,
  nombre        text,
  labor         text,
  proveedor     text,
  jornadas      bigint,
  horas         numeric,
  sin_cerrar    bigint,
  primera       date,
  ultima        date
)
language sql
stable
security definer
set search_path = public
as $ts$
  -- De lunes a domingo de la semana en curso cuando no se dice otra cosa:
  -- es como se liquida, y pedir las dos fechas cada vez sobra.
  with rango as (
    select coalesce(p_desde, date_trunc('week', current_date)::date) as desde,
           coalesce(p_hasta, (date_trunc('week', current_date) + interval '6 days')::date) as hasta
  )
  select t.id, t.cedula, t.nombre, t.labor, t.proveedor,
         count(j.id)                                              as jornadas,
         coalesce(sum(j.horas), 0)::numeric                       as horas,
         count(j.id) filter (where j.salida_en is null)            as sin_cerrar,
         min(j.fecha)                                             as primera,
         max(j.fecha)                                             as ultima
    from public.personal_temporal t
    join public.jornadas_temporales j on j.temporal_id = t.id
    cross join rango r
   where j.fecha between r.desde and r.hasta
   group by t.id, t.cedula, t.nombre, t.labor, t.proveedor
   order by t.nombre;
$ts$;

comment on function public.temporal_semana(date, date) is
  'Horas por operario en el rango. Sin importes: el sistema sabe cuánto estuvo cada quien, no cuánto se le paga.';

-- =========================================================================
-- B. Fuera la tarifa
-- =========================================================================

alter table public.personal_temporal drop column if exists valor_hora;

comment on table public.personal_temporal is
  'Operarios temporales, identificados por su cédula. No son usuarios del sistema: no tienen acceso, ni vacaciones, ni jefe. El sistema registra quién vino y cuánto estuvo; cuánto se le paga lo decide Finanzas.';

-- =========================================================================
-- C. El detalle jornada a jornada, para el informe
--
-- Una fila por día trabajado, con todo lo que Finanzas necesita para
-- sustentar el pago y nada más. Se filtra por fuera; la vista no decide.
-- =========================================================================

drop view if exists public.v_jornadas_detalle;
create view public.v_jornadas_detalle as
select j.id                       as jornada_id,
       t.id                       as temporal_id,
       t.cedula,
       t.nombre,
       t.labor,
       t.proveedor,
       t.activo,
       j.fecha,
       j.entrada_en,
       j.salida_en,
       j.horas,
       j.salida_en is null        as sin_cerrar,
       -- Quién registró cada extremo: una jornada cerrada a mano por Talento
       -- Humano no es lo mismo que una que presenció la garita, y quien
       -- autoriza el pago tiene derecho a distinguirlas.
       e.nombre                   as registro_entrada,
       s.nombre                   as registro_salida,
       j.observacion
  from public.jornadas_temporales j
  join public.personal_temporal t on t.id = j.temporal_id
  left join public.users e on e.id = j.registro_entrada
  left join public.users s on s.id = j.registro_salida;

comment on view public.v_jornadas_detalle is
  'Una fila por jornada, con quién registró la entrada y la salida. Base de los informes que se presentan a Finanzas.';

grant select on public.v_jornadas_detalle to authenticated;
