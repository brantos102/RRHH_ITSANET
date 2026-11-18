-- =====================================================================
--  Migración 0006 — Anulación autorizada, administración e informes
--
--  1. Anulación de solicitudes aprobadas (requiere autorización de RRHH)
--  2. Vista de garita con lo que el guardia necesita ver
--  3. Vista de informes con todas las dimensiones filtrables
--  4. Registro de quién administra qué
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. ANULACIÓN AUTORIZADA
--    Cancelar algo ya aprobado devuelve días y anula un QR emitido:
--    no puede ser una decisión unilateral del solicitante.
-- ---------------------------------------------------------------------
do $$
begin
  if not exists (
    select 1 from pg_enum e join pg_type t on t.oid = e.enumtypid
    where t.typname = 'request_status' and e.enumlabel = 'pendiente_anulacion'
  ) then
    alter type public.request_status add value 'pendiente_anulacion' before 'aprobado';
  end if;
end$$;

alter table public.requests
  add column if not exists anulacion_motivo       text,
  add column if not exists anulacion_solicitada_en timestamptz,
  add column if not exists anulacion_resuelta_por uuid references public.users(id) on delete set null,
  add column if not exists anulacion_resuelta_en  timestamptz,
  add column if not exists anulacion_rechazada_motivo text;

comment on column public.requests.anulacion_motivo is
  'Por qué el empleado pide dejar sin efecto una solicitud ya aprobada.';

create index if not exists idx_requests_anulacion on public.requests (estado)
  where estado = 'pendiente_anulacion';

-- 1.1 La máquina de estados admite el circuito de anulación
create or replace function public.tg_requests_before_update()
returns trigger
language plpgsql
as $$
declare
  v_descuenta boolean := false;
begin
  if (new.fecha_inicio, new.fecha_fin, new.tipo) is distinct from (old.fecha_inicio, old.fecha_fin, old.tipo) then
    if old.estado <> 'pendiente_jefe' then
      raise exception 'No se pueden modificar las fechas de una solicitud en estado %', old.estado;
    end if;
    new.dias_solicitados := public.calcular_dias(new.tipo, new.fecha_inicio, new.fecha_fin);
    new.fines_semana     := public.fines_de_semana_completos(new.fecha_inicio, new.fecha_fin);
  end if;

  if new.estado is distinct from old.estado then
    if not (
         (old.estado = 'pendiente_jefe'      and new.estado in ('pendiente_rrhh', 'rechazado', 'cancelado'))
      or (old.estado = 'pendiente_rrhh'      and new.estado in ('aprobado', 'rechazado', 'cancelado'))
      -- Anular algo aprobado pasa por Talento Humano; cancelarlo directo queda
      -- reservado a RRHH, que es quien responde por el saldo y por el QR emitido.
      or (old.estado = 'aprobado'            and new.estado in ('pendiente_anulacion', 'cancelado'))
      or (old.estado = 'pendiente_anulacion' and new.estado in ('cancelado', 'aprobado'))
    ) then
      raise exception 'Transición de estado inválida: % -> %', old.estado, new.estado;
    end if;

    if new.estado = 'pendiente_rrhh' then
      new.jefe_aprobado_en := coalesce(new.jefe_aprobado_en, now());
    end if;

    if new.estado = 'rechazado' then
      new.rechazado_en := coalesce(new.rechazado_en, now());
    end if;

    if new.estado = 'pendiente_anulacion' then
      new.anulacion_solicitada_en := coalesce(new.anulacion_solicitada_en, now());
    end if;

    -- Anulación denegada: la solicitud vuelve a estar vigente
    if new.estado = 'aprobado' and old.estado = 'pendiente_anulacion' then
      new.anulacion_resuelta_en := coalesce(new.anulacion_resuelta_en, now());
      return new;                      -- el saldo no se tocó, no hay nada que revertir
    end if;

    if new.tipo = 'vacacion' then
      v_descuenta := true;
    else
      select coalesce(descuenta_vacaciones, false) into v_descuenta
      from public.permission_types where id = new.permission_type_id;
    end if;

    if new.estado = 'aprobado' then
      new.rrhh_aprobado_en := coalesce(new.rrhh_aprobado_en, now());
      new.qr_hash          := coalesce(new.qr_hash, gen_random_uuid());
      new.qr_emitido_en    := coalesce(new.qr_emitido_en, now());
      new.qr_expira_en     := coalesce(new.qr_expira_en, (new.fecha_fin + 1)::timestamptz);

      if v_descuenta then
        perform public.consumir_vacaciones(
          new.user_id, new.dias_solicitados, new.id, new.fines_semana, new.rrhh_aprobado_por);
      end if;
    end if;

    -- Se devuelve el saldo al cancelar, venga de una aprobada o de una anulación
    if new.estado = 'cancelado' and old.estado in ('aprobado', 'pendiente_anulacion') and v_descuenta then
      perform public.reversar_vacaciones(
        new.user_id, new.dias_solicitados, new.id, new.fines_semana);
      new.anulacion_resuelta_en := coalesce(new.anulacion_resuelta_en, now());
      -- Un QR anulado deja de servir en garita
      new.qr_expira_en := now();
    end if;
  end if;

  return new;
end;
$$;

-- 1.2 Aviso de anulación pendiente a Talento Humano
create or replace function public.tg_requests_notificar()
returns trigger
language plpgsql
as $$
declare
  v_nombre text;
  v_dest   uuid;
begin
  select nombre into v_nombre from public.users where id = new.user_id;

  if tg_op = 'INSERT' then
    if new.jefe_id is not null then
      insert into public.notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      values (new.jefe_id, 'solicitud_pendiente', 'info',
        format('Nueva solicitud de %s', v_nombre),
        format('%s solicitó %s del %s al %s (%s días). Requiere su aprobación.',
               v_nombre, new.tipo, to_char(new.fecha_inicio,'DD/MM/YYYY'),
               to_char(new.fecha_fin,'DD/MM/YYYY'), new.dias_solicitados),
        'requests', new.id::text, '/dashboard.html#aprobaciones');
    end if;

  elsif tg_op = 'UPDATE' and new.estado is distinct from old.estado then
    if new.estado = 'pendiente_rrhh' then
      for v_dest in select id from public.users where rol in ('rrhh','admin') and activo loop
        insert into public.notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
        values (v_dest, 'solicitud_pendiente', 'info',
          format('Solicitud Nº %s de %s aprobada por el jefe', coalesce(new.folio, 0), v_nombre),
          format('La solicitud de %s (%s al %s) espera la aprobación de Talento Humano.',
                 v_nombre, to_char(new.fecha_inicio,'DD/MM/YYYY'), to_char(new.fecha_fin,'DD/MM/YYYY')),
          'requests', new.id::text, '/dashboard.html#aprobaciones');
      end loop;

    elsif new.estado = 'pendiente_anulacion' then
      for v_dest in select id from public.users where rol in ('rrhh','admin') and activo loop
        insert into public.notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
        values (v_dest, 'solicitud_pendiente', 'advertencia',
          format('%s pide anular la solicitud Nº %s', v_nombre, coalesce(new.folio, 0)),
          format('Motivo: %s. Si se autoriza, se devuelven %s día(s) y el código QR deja de servir.',
                 coalesce(new.anulacion_motivo, 'no indicado'), new.dias_solicitados),
          'requests', new.id::text, '/dashboard.html#aprobaciones');
      end loop;

    elsif new.estado = 'aprobado' and old.estado = 'pendiente_anulacion' then
      insert into public.notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      values (new.user_id, 'solicitud_rechazada', 'advertencia',
        format('No se autorizó anular su solicitud Nº %s', coalesce(new.folio, 0)),
        format('Su solicitud del %s al %s sigue vigente. Motivo: %s',
               to_char(new.fecha_inicio,'DD/MM/YYYY'), to_char(new.fecha_fin,'DD/MM/YYYY'),
               coalesce(new.anulacion_rechazada_motivo, 'no especificado')),
        'requests', new.id::text, '/dashboard.html');

    elsif new.estado = 'aprobado' then
      insert into public.notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      values (new.user_id, 'solicitud_aprobada', 'info',
        format('Su solicitud Nº %s fue aprobada', coalesce(new.folio, 0)),
        format('Su solicitud del %s al %s fue aprobada. Ya puede descargar su código QR de salida.',
               to_char(new.fecha_inicio,'DD/MM/YYYY'), to_char(new.fecha_fin,'DD/MM/YYYY')),
        'requests', new.id::text, '/dashboard.html');

    elsif new.estado = 'rechazado' then
      insert into public.notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      values (new.user_id, 'solicitud_rechazada', 'advertencia',
        format('Su solicitud Nº %s fue rechazada', coalesce(new.folio, 0)),
        format('Su solicitud del %s al %s fue rechazada. Motivo: %s',
               to_char(new.fecha_inicio,'DD/MM/YYYY'), to_char(new.fecha_fin,'DD/MM/YYYY'),
               coalesce(new.motivo_rechazo, 'no especificado')),
        'requests', new.id::text, '/dashboard.html');

    elsif new.estado = 'cancelado' and old.estado = 'pendiente_anulacion' then
      insert into public.notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      values (new.user_id, 'informativo', 'info',
        format('Se anuló su solicitud Nº %s', coalesce(new.folio, 0)),
        format('Talento Humano autorizó la anulación. Se devolvieron %s día(s) a su saldo.',
               new.dias_solicitados),
        'requests', new.id::text, '/dashboard.html');
    end if;
  end if;

  return null;
end;
$$;

-- ---------------------------------------------------------------------
-- 2. GARITA: lo que el guardia necesita, y nada más
-- ---------------------------------------------------------------------
drop view if exists public.v_garita_actividad;
create view public.v_garita_actividad as
select
  r.id              as request_id,
  r.folio,
  r.qr_hash,
  r.tipo,
  pt.nombre         as tipo_permiso,
  r.estado,
  r.fecha_inicio,
  r.fecha_fin,
  r.hora_inicio,
  r.hora_fin,
  r.qr_usado_en,
  r.qr_expira_en,
  u.id              as user_id,
  u.cedula,
  u.nombre,
  u.departamento,
  u.cargo,
  u.telefono,
  (current_date between r.fecha_inicio and r.fecha_fin) as vigente_hoy,
  (select count(*) from public.request_signatures rs where rs.request_id = r.id) as firmas,
  j.nombre          as autorizado_por_jefe,
  h.nombre          as autorizado_por_rrhh
from public.requests r
join public.users u on u.id = r.user_id
left join public.users j on j.id = r.jefe_aprobado_por
left join public.users h on h.id = r.rrhh_aprobado_por
left join public.permission_types pt on pt.id = r.permission_type_id
where r.estado in ('pendiente_jefe', 'pendiente_rrhh', 'pendiente_anulacion', 'aprobado')
  and r.fecha_fin >= current_date - 1
  and public.is_guardia();

grant select on public.v_garita_actividad to authenticated;

-- ---------------------------------------------------------------------
-- 3. INFORMES: una fila por solicitud con todas las dimensiones
-- ---------------------------------------------------------------------
drop view if exists public.v_informe_solicitudes;
create view public.v_informe_solicitudes as
select
  r.id                as solicitud_id,
  r.folio,
  r.created_at::date  as fecha_solicitud,
  r.fecha_inicio,
  r.fecha_fin,
  r.dias_solicitados,
  r.horas_solicitadas,
  r.tipo::text        as tipo,
  coalesce(pt.nombre, case r.tipo when 'vacacion' then 'Vacaciones' else 'Permiso' end) as tipo_detalle,
  r.estado::text      as estado,
  u.id                as user_id,
  u.cedula,
  u.nombre            as solicitante,
  u.departamento,
  u.cargo,
  u.tipo_contrato::text as tipo_contrato,
  j.nombre            as jefe,
  h.nombre            as rrhh,
  rp.nombre           as reemplazo,
  r.es_adelanto,
  r.descripcion,
  r.motivo_rechazo,
  r.rechazado_en_etapa,
  r.jefe_aprobado_en,
  r.rrhh_aprobado_en,
  r.rechazado_en,
  r.qr_usado_en,
  (select count(*) from public.request_attachments a where a.request_id = r.id) as adjuntos
from public.requests r
join public.users u on u.id = r.user_id
left join public.users j on j.id = coalesce(r.jefe_aprobado_por, r.jefe_id)
left join public.users h on h.id = r.rrhh_aprobado_por
left join public.users rp on rp.id = r.reemplazo_id
left join public.permission_types pt on pt.id = r.permission_type_id;

comment on view public.v_informe_solicitudes is
  'Base de los informes: una fila por solicitud con solicitante, jefe, RRHH, departamento, cargo y tipo.';

grant select on public.v_informe_solicitudes to authenticated;

-- ---------------------------------------------------------------------
-- 4. RLS de lo nuevo
-- ---------------------------------------------------------------------
-- El informe lo consulta el backend con credenciales de servicio, pero si
-- alguien llega por PostgREST, que solo vea lo que le toca.
drop policy if exists requests_select on public.requests;
create policy requests_select on public.requests
  for select to authenticated
  using (
    user_id = public.current_user_id()
    or jefe_id = public.current_user_id()
    or reemplazo_id = public.current_user_id()
    or public.is_rrhh_o_admin()
    or (public.is_guardia() and estado = 'aprobado')
  );

-- ---------------------------------------------------------------------
-- 5. Un intento denegado debe quedar registrado aunque no se sepa quién fue
--
--    El CHECK exigía identificar a la persona, así que un código ilegible o
--    inexistente hacía fallar la inserción y el intento NO se guardaba: se
--    perdía justo la evidencia más relevante para seguridad.
-- ---------------------------------------------------------------------
alter table public.access_logs drop constraint if exists access_logs_identifica_persona;
alter table public.access_logs add constraint access_logs_identifica_persona
  check (
    user_id is not null or visitor_id is not null or cedula is not null
    -- Un intento denegado puede no identificar a nadie: es precisamente lo
    -- que hay que poder auditar después.
    or tipo_acceso = 'acceso_denegado'
  );
