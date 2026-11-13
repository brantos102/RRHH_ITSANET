-- =====================================================================
--  Migración 0005 — Número de solicitud, reemplazo, etapa de rechazo
--                   y calendario de ausencias del equipo
--
--  Inspirada en lo que funciona de los sistemas de vacaciones en uso:
--  un folio que la gente pueda mencionar, saber quién cubre al ausente,
--  distinguir quién rechazó, y ver quién más está fuera esos días.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. NÚMERO DE SOLICITUD
--    El UUID sirve a la máquina; la gente necesita decir «la 57».
-- ---------------------------------------------------------------------
create sequence if not exists public.requests_folio_seq;

alter table public.requests add column if not exists folio bigint;

create unique index if not exists idx_requests_folio on public.requests (folio);

create or replace function public.tg_requests_folio()
returns trigger language plpgsql as $$
begin
  if new.folio is null then
    new.folio := nextval('public.requests_folio_seq');
  end if;
  return new;
end;
$$;

drop trigger if exists requests_folio on public.requests;
create trigger requests_folio before insert on public.requests
  for each row execute function public.tg_requests_folio();

-- Folios para lo que ya existe, en orden de creación
do $$
begin
  if exists (select 1 from public.requests where folio is null) then
    update public.requests r set folio = n.orden
      from (select id, row_number() over (order by created_at) as orden
              from public.requests where folio is null) n
     where r.id = n.id;
    perform setval('public.requests_folio_seq', coalesce((select max(folio) from public.requests), 0) + 1, false);
  end if;
end$$;

comment on column public.requests.folio is
  'Número correlativo legible. Es el que se menciona por teléfono o en un correo.';

-- ---------------------------------------------------------------------
-- 2. REEMPLAZO: quién asume las funciones durante la ausencia
-- ---------------------------------------------------------------------
alter table public.requests
  add column if not exists reemplazo_id uuid references public.users(id) on delete set null;

alter table public.requests drop constraint if exists requests_reemplazo_distinto;
alter table public.requests add constraint requests_reemplazo_distinto
  check (reemplazo_id is null or reemplazo_id <> user_id);

create index if not exists idx_requests_reemplazo on public.requests (reemplazo_id);

comment on column public.requests.reemplazo_id is
  'Compañero que cubre las funciones. El jefe decide sabiendo quién asume el puesto.';

-- ---------------------------------------------------------------------
-- 3. ETAPA DEL RECHAZO: no es lo mismo que lo rechace el jefe o RRHH
-- ---------------------------------------------------------------------
alter table public.requests
  add column if not exists rechazado_en_etapa text
    check (rechazado_en_etapa is null or rechazado_en_etapa in ('jefe', 'rrhh'));

-- Se deduce del estado previo dentro del propio trigger de estados
create or replace function public.tg_requests_marcar_etapa()
returns trigger language plpgsql as $$
begin
  if new.estado = 'rechazado' and old.estado in ('pendiente_jefe', 'pendiente_rrhh') then
    new.rechazado_en_etapa := case old.estado
      when 'pendiente_jefe' then 'jefe' else 'rrhh' end;
  end if;
  return new;
end;
$$;

drop trigger if exists requests_marcar_etapa on public.requests;
create trigger requests_marcar_etapa before update on public.requests
  for each row when (new.estado is distinct from old.estado)
  execute function public.tg_requests_marcar_etapa();

-- Rellenar lo ya rechazado, según quién figura como decisor
update public.requests r
   set rechazado_en_etapa = case
         when r.rechazado_por = r.jefe_id then 'jefe' else 'rrhh' end
 where r.estado = 'rechazado' and r.rechazado_en_etapa is null;

-- ---------------------------------------------------------------------
-- 4. DESGLOSE DE DÍAS: cuántos se descuentan y cuántos no
--    «Días a descontar: 3 · Días no laborables: 0» explica el número.
-- ---------------------------------------------------------------------
create or replace function public.desglose_dias(
  p_tipo public.request_type, p_inicio date, p_fin date
)
returns jsonb
language sql
stable
as $$
  with dias as (
    select d.dia::date as fecha,
           extract(isodow from d.dia) between 6 and 7 as fin_de_semana,
           (select f.nombre from public.feriados f where f.fecha = d.dia::date and f.activo) as feriado
    from generate_series(p_inicio, p_fin, interval '1 day') as d(dia)
  )
  select jsonb_build_object(
    'total_calendario', (select count(*) from dias),
    'dias_descontar',   public.calcular_dias(p_tipo, p_inicio, p_fin),
    'dias_no_laborables', (
      select count(*) from dias
      where feriado is not null
         or (p_tipo = 'permiso' and fin_de_semana)
    ),
    'fines_de_semana', (select count(*) from dias where fin_de_semana),
    'feriados', coalesce((
      select jsonb_agg(jsonb_build_object('fecha', fecha, 'nombre', feriado) order by fecha)
      from dias where feriado is not null
    ), '[]'::jsonb)
  );
$$;

comment on function public.desglose_dias is
  'Explica de qué se compone el rango: cuántos días se descuentan, cuántos no y qué feriados caen dentro.';

-- Se añade el desglose a la previsualización que ya usa el frontend
create or replace function public.previsualizar_solicitud(
  p_user_id uuid,
  p_tipo    public.request_type,
  p_inicio  date,
  p_fin     date,
  p_permission_type_id smallint default null
)
returns jsonb
language plpgsql
stable
as $$
declare
  v_dias      numeric;
  v_saldo     numeric;
  v_fds       int;
  v_fds_pend  int;
  v_pt        public.permission_types%rowtype;
  v_sug       date[];
  v_avisos    text[] := '{}';
  v_ok        boolean := true;
  v_desglose  jsonb;
begin
  select dias_vacaciones into v_saldo from public.users where id = p_user_id;
  v_dias     := public.calcular_dias(p_tipo, p_inicio, p_fin);
  v_fds      := public.fines_de_semana_completos(p_inicio, p_fin);
  v_fds_pend := public.fines_semana_pendientes(p_user_id);
  v_sug      := array[p_inicio, p_fin];
  v_desglose := public.desglose_dias(p_tipo, p_inicio, p_fin);

  if v_dias <= 0 then
    v_ok := false;
    v_avisos := v_avisos || 'El rango seleccionado no genera días computables.';
  end if;

  if p_tipo = 'vacacion' then
    if v_dias > v_saldo then
      v_avisos := v_avisos || format(
        'Supera su saldo (%s días disponibles). Debe registrar una justificación: se tomará como días adelantados.',
        v_saldo);
    end if;

    if v_fds_pend > 0 and v_fds = 0
       and (extract(isodow from p_fin) = 5 or extract(isodow from p_inicio) = 1) then
      v_ok  := false;
      v_sug := public.sugerir_rango_con_fin_de_semana(p_inicio, p_fin);
      v_avisos := v_avisos || format(
        'Le faltan %s fin(es) de semana obligatorio(s). La solicitud debe incluir sábado y domingo: %s a %s (%s días).',
        v_fds_pend, v_sug[1], v_sug[2], public.calcular_dias(p_tipo, v_sug[1], v_sug[2]));
    end if;
  else
    select * into v_pt from public.permission_types where id = p_permission_type_id and activo;
    if v_pt.id is null then
      v_ok := false;
      v_avisos := v_avisos || 'Debe seleccionar un tipo de permiso válido.';
    else
      if v_pt.requiere_adjunto then
        v_avisos := v_avisos || format('El permiso "%s" exige adjuntar respaldo.', v_pt.nombre);
      end if;
      if v_pt.requiere_firma then
        v_avisos := v_avisos || 'Debe firmar electrónicamente la solicitud.';
      end if;
      if v_pt.max_dias is not null and v_dias > v_pt.max_dias then
        v_ok := false;
        v_avisos := v_avisos || format('Máximo %s día(s) para este permiso.', v_pt.max_dias);
      end if;
      if v_pt.descuenta_vacaciones then
        v_avisos := v_avisos || 'Este permiso se descuenta de su saldo de vacaciones.';
      end if;
    end if;
  end if;

  return jsonb_build_object(
    'valido',                 v_ok,
    'dias',                   v_dias,
    'saldo_actual',           v_saldo,
    'saldo_despues',          case when p_tipo = 'vacacion' then v_saldo - v_dias else v_saldo end,
    'fines_semana_incluidos', v_fds,
    'fines_semana_pendientes',v_fds_pend,
    'requiere_justificacion', (p_tipo = 'vacacion' and v_dias > v_saldo)
                              or coalesce(v_pt.requiere_justificacion, false),
    'requiere_adjunto',       coalesce(v_pt.requiere_adjunto, false),
    'requiere_firma',         coalesce(v_pt.requiere_firma, p_tipo = 'permiso'),
    'rango_sugerido',         jsonb_build_object('inicio', v_sug[1], 'fin', v_sug[2]),
    'avisos',                 to_jsonb(v_avisos),
    'desglose',               v_desglose
  );
end;
$$;

-- ---------------------------------------------------------------------
-- 5. CALENDARIO DE AUSENCIAS DEL EQUIPO
--    Para no aprobar dos ausencias del mismo puesto la misma semana.
--
--    LOPDP: entre compañeros se muestra QUIÉN y CUÁNDO, nunca POR QUÉ.
--    El motivo de un permiso médico es un dato de salud (Art. 4).
-- ---------------------------------------------------------------------
drop view if exists public.v_calendario_equipo;
create view public.v_calendario_equipo as
select
  r.id            as request_id,
  r.folio,
  u.id            as user_id,
  u.nombre,
  u.departamento,
  u.jefe_id,
  r.fecha_inicio,
  r.fecha_fin,
  r.estado,
  -- Solo la naturaleza general de la ausencia, sin la categoría del permiso
  case r.tipo when 'vacacion' then 'Vacaciones' else 'Permiso' end as motivo_general,
  r.reemplazo_id,
  s.nombre        as reemplazo_nombre
from public.requests r
join public.users u on u.id = r.user_id
left join public.users s on s.id = r.reemplazo_id
where r.estado in ('pendiente_jefe', 'pendiente_rrhh', 'aprobado')
  and r.fecha_fin >= current_date - 31;

comment on view public.v_calendario_equipo is
  'Ausencias del equipo para planificar. Muestra quién y cuándo, nunca el motivo detallado (LOPDP Art. 4).';

grant select on public.v_calendario_equipo to authenticated;

-- ---------------------------------------------------------------------
-- 6. Trazabilidad: folio, reemplazo y etapa del rechazo en las vistas
-- ---------------------------------------------------------------------
drop view if exists public.v_trazabilidad_solicitudes;
create view public.v_trazabilidad_solicitudes as
select
  r.id                     as solicitud_id,
  r.folio,
  u.cedula,
  u.nombre                 as empleado,
  u.departamento,
  u.cargo,
  r.tipo,
  pt.nombre                as categoria_permiso,
  pt.legal_ref             as base_legal,
  r.fecha_inicio,
  r.fecha_fin,
  r.hora_inicio,
  r.hora_fin,
  r.dias_solicitados,
  r.horas_solicitadas,
  r.fines_semana,
  r.es_adelanto,
  r.descripcion,
  r.justificacion,
  rp.nombre                as reemplazo,
  r.estado,
  r.created_at             as fecha_solicitud,
  j.nombre                 as jefe,
  r.jefe_aprobado_en,
  h.nombre                 as aprobador_rrhh,
  r.rrhh_aprobado_en,
  x.nombre                 as rechazado_por,
  r.rechazado_en_etapa,
  r.rechazado_en,
  r.motivo_rechazo,
  r.qr_emitido_en,
  r.qr_usado_en,
  (select count(*) from public.request_attachments a where a.request_id = r.id) as adjuntos,
  (select count(*) from public.request_signatures s where s.request_id = r.id)  as firmas,
  case r.estado
    when 'aprobado'  then 'Aprobada'
    when 'rechazado' then 'Rechazada por ' || case r.rechazado_en_etapa
                            when 'jefe' then 'el jefe inmediato' else 'Talento Humano' end
    when 'cancelado' then 'Cancelada'
    else 'En trámite'
  end as resultado
from public.requests r
join public.users u on u.id = r.user_id
left join public.users j on j.id = r.jefe_id
left join public.users h on h.id = r.rrhh_aprobado_por
left join public.users x on x.id = r.rechazado_por
left join public.users rp on rp.id = r.reemplazo_id
left join public.permission_types pt on pt.id = r.permission_type_id;

grant select on public.v_trazabilidad_solicitudes to authenticated;
