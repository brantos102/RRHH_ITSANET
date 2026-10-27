-- =====================================================================
--  Migración 0002 — Reglas de negocio Ecuador
--
--  1. Configuración parametrizable (app_config)
--  2. Vacaciones por antigüedad: 15 días + 1 día por año desde el 6to
--  3. Períodos anuales devengados (vacation_periods) y consumo FIFO
--  4. Regla de los 2 fines de semana obligatorios por período
--  5. Catálogo de tipos de permiso (permission_types) — normativa EC
--  6. Adjuntos de respaldo (request_attachments)
--  7. Firmas electrónicas (signatures + request_signatures)
--  8. Descripción obligatoria de máx. 200 caracteres
--  9. Función de previsualización para el frontend
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. CONFIGURACIÓN PARAMETRIZABLE
-- ---------------------------------------------------------------------
create table if not exists public.app_config (
  clave       text primary key,
  valor       text not null,
  descripcion text,
  updated_at  timestamptz not null default now()
);

insert into public.app_config (clave, valor, descripcion) values
  ('vacaciones_dias_base',       '15', 'Días de vacaciones por año cumplido (Art. 69 Código del Trabajo)'),
  ('vacaciones_anio_dia_extra',  '6',  'Año de antigüedad desde el cual se suma 1 día adicional por año'),
  ('vacaciones_dias_extra_max',  '15', 'Tope de días adicionales por antigüedad (15 => máximo 30 días)'),
  ('fines_semana_obligatorios',  '2',  'Fines de semana completos que deben consumirse en cada período'),
  ('acumulacion_max_anios',      '3',  'Años que un período puede acumularse antes de caducar (Art. 75)'),
  ('descripcion_max_chars',      '200','Longitud máxima de la descripción de la solicitud')
on conflict (clave) do nothing;

create or replace function public.cfg_int(p_clave text)
returns int language sql stable as
$$ select valor::int from public.app_config where clave = p_clave $$;

drop trigger if exists set_updated_at on public.app_config;
create trigger set_updated_at before update on public.app_config
  for each row execute function public.tg_set_updated_at();

-- ---------------------------------------------------------------------
-- 2. DÍAS DE VACACIONES SEGÚN ANTIGÜEDAD
-- ---------------------------------------------------------------------
-- Art. 69 CT: 15 días por año cumplido; desde el 6to año, 1 día adicional
-- por cada año de servicio, hasta un tope (por defecto 15 => 30 días).
create or replace function public.dias_por_antiguedad(p_anios int)
returns numeric
language sql
stable
as $$
  select case
    when p_anios <= 0 then 0
    when p_anios < public.cfg_int('vacaciones_anio_dia_extra')
      then public.cfg_int('vacaciones_dias_base')::numeric
    else public.cfg_int('vacaciones_dias_base')
       + least(p_anios - (public.cfg_int('vacaciones_anio_dia_extra') - 1),
               public.cfg_int('vacaciones_dias_extra_max'))
  end::numeric;
$$;

comment on function public.dias_por_antiguedad is
  'Días de vacaciones que devenga el año N de servicio: 15 hasta el 5to año, 16 el 6to, 17 el 7mo, etc.';

-- Años completos de servicio a una fecha dada
create or replace function public.anios_cumplidos(p_fecha_ingreso date, p_corte date default current_date)
returns int
language sql
stable
as $$
  select greatest(0, extract(year from age(p_corte, p_fecha_ingreso))::int);
$$;

-- ---------------------------------------------------------------------
-- 3. PERÍODOS ANUALES DE VACACIONES
-- ---------------------------------------------------------------------
create table if not exists public.vacation_periods (
  id                       uuid primary key default gen_random_uuid(),
  user_id                  uuid not null references public.users(id) on delete cascade,
  periodo                  int  not null,          -- 1 = primer año de servicio
  fecha_desde              date not null,
  fecha_hasta              date not null,          -- fin del año de servicio
  dias_asignados           numeric(6,2) not null default 0,
  dias_consumidos          numeric(6,2) not null default 0,
  dias_saldo               numeric(6,2) generated always as (dias_asignados - dias_consumidos) stored,
  fines_semana_obligatorios int not null default 2,
  fines_semana_consumidos   int not null default 0,
  devengado                boolean not null default false,  -- el año ya se cumplió
  vence_en                 date,
  caducado                 boolean not null default false,
  created_at               timestamptz not null default now(),
  updated_at               timestamptz not null default now(),
  unique (user_id, periodo)
);

comment on table public.vacation_periods is
  'Un registro por año de servicio. El saldo del empleado es la suma de los saldos no caducados.';
comment on column public.vacation_periods.devengado is
  'false = período anticipado (el año aún no se cumple); puede quedar en saldo negativo por días adelantados.';

create index if not exists idx_vac_periods_user on public.vacation_periods (user_id, periodo);
create index if not exists idx_vac_periods_abiertos on public.vacation_periods (user_id)
  where not caducado and dias_asignados > dias_consumidos;

drop trigger if exists set_updated_at on public.vacation_periods;
create trigger set_updated_at before update on public.vacation_periods
  for each row execute function public.tg_set_updated_at();

-- 3.1 Recalcular el saldo cacheado en users.dias_vacaciones
create or replace function public.refrescar_saldo_vacaciones(p_user_id uuid)
returns numeric
language plpgsql
as $$
declare v_saldo numeric(6,2);
begin
  select coalesce(sum(dias_saldo), 0) into v_saldo
  from public.vacation_periods
  where user_id = p_user_id and not caducado;

  update public.users set dias_vacaciones = v_saldo where id = p_user_id;
  return v_saldo;
end;
$$;

create or replace function public.tg_vac_periods_sync()
returns trigger language plpgsql as $$
begin
  perform public.refrescar_saldo_vacaciones(coalesce(new.user_id, old.user_id));
  return null;
end;
$$;

drop trigger if exists vac_periods_sync on public.vacation_periods;
create trigger vac_periods_sync after insert or update or delete on public.vacation_periods
  for each row execute function public.tg_vac_periods_sync();

-- 3.2 Generar / actualizar los períodos de un empleado
create or replace function public.generar_periodos_vacaciones(p_user_id uuid)
returns int
language plpgsql
as $$
declare
  v_ingreso date;
  v_anios   int;
  v_fds     int := public.cfg_int('fines_semana_obligatorios');
  v_acum    int := public.cfg_int('acumulacion_max_anios');
  k         int;
  v_hasta   date;
  v_creados int := 0;
begin
  select fecha_ingreso into v_ingreso from public.users where id = p_user_id;
  if v_ingreso is null then
    raise exception 'Usuario % no existe', p_user_id;
  end if;

  v_anios := public.anios_cumplidos(v_ingreso);

  -- Períodos ya devengados (años cumplidos)
  for k in 1..greatest(v_anios, 0) loop
    v_hasta := (v_ingreso + make_interval(years => k))::date - 1;
    insert into public.vacation_periods
      (user_id, periodo, fecha_desde, fecha_hasta, dias_asignados,
       fines_semana_obligatorios, devengado, vence_en)
    values
      (p_user_id, k, (v_ingreso + make_interval(years => k - 1))::date, v_hasta,
       public.dias_por_antiguedad(k), v_fds, true,
       (v_hasta + make_interval(years => v_acum))::date)
    on conflict (user_id, periodo) do update
      set dias_asignados = excluded.dias_asignados,
          devengado      = true,
          vence_en       = excluded.vence_en
      where not public.vacation_periods.devengado;   -- solo completa períodos anticipados
    v_creados := v_creados + 1;
  end loop;

  -- Período en curso (aún no devengado): permite tomar días adelantados
  k       := v_anios + 1;
  v_hasta := (v_ingreso + make_interval(years => k))::date - 1;
  insert into public.vacation_periods
    (user_id, periodo, fecha_desde, fecha_hasta, dias_asignados,
     fines_semana_obligatorios, devengado, vence_en)
  values
    (p_user_id, k, (v_ingreso + make_interval(years => k - 1))::date, v_hasta,
     0, v_fds, false, (v_hasta + make_interval(years => v_acum))::date)
  on conflict (user_id, periodo) do nothing;

  perform public.refrescar_saldo_vacaciones(p_user_id);
  return v_creados;
end;
$$;

comment on function public.generar_periodos_vacaciones is
  'Crea/actualiza los períodos anuales del empleado y refresca su saldo. Idempotente.';

-- 3.3 Caducidad por acumulación (Art. 75): ejecutar periódicamente
create or replace function public.caducar_periodos_vencidos()
returns int
language plpgsql
as $$
declare v_n int;
begin
  with vencidos as (
    update public.vacation_periods
       set caducado = true
     where not caducado and vence_en < current_date and dias_saldo > 0
     returning user_id
  )
  select count(*) into v_n from vencidos;

  perform public.refrescar_saldo_vacaciones(u.id)
  from public.users u where u.activo;

  return v_n;
end;
$$;

-- 3.4 Consumo FIFO del saldo
create or replace function public.consumir_vacaciones(
  p_user_id uuid, p_dias numeric, p_request_id uuid, p_fds int default 0, p_por uuid default null
)
returns void
language plpgsql
as $$
declare
  r            record;
  v_restante   numeric := p_dias;
  v_toma       numeric;
  v_saldo_prev numeric;
  v_ultimo     uuid;
begin
  select coalesce(sum(dias_saldo), 0) into v_saldo_prev
  from public.vacation_periods where user_id = p_user_id and not caducado;

  for r in
    select id, dias_saldo from public.vacation_periods
     where user_id = p_user_id and not caducado and dias_saldo > 0
     order by periodo
  loop
    exit when v_restante <= 0;
    v_toma := least(r.dias_saldo, v_restante);
    update public.vacation_periods
       set dias_consumidos = dias_consumidos + v_toma
     where id = r.id;
    v_restante := v_restante - v_toma;
  end loop;

  -- Días adelantados: se cargan al período en curso (queda en saldo negativo)
  if v_restante > 0 then
    select id into v_ultimo from public.vacation_periods
     where user_id = p_user_id and not caducado order by periodo desc limit 1;
    if v_ultimo is null then
      raise exception 'El empleado no tiene períodos de vacaciones generados';
    end if;
    update public.vacation_periods
       set dias_consumidos = dias_consumidos + v_restante where id = v_ultimo;
  end if;

  -- Fines de semana completos consumidos: se cargan al período más antiguo abierto
  if p_fds > 0 then
    update public.vacation_periods
       set fines_semana_consumidos = fines_semana_consumidos + p_fds
     where id = (select id from public.vacation_periods
                  where user_id = p_user_id and not caducado order by periodo limit 1);
  end if;

  insert into public.vacation_movements
    (user_id, request_id, dias, saldo_previo, saldo_nuevo, motivo, created_by)
  select p_user_id, p_request_id, -p_dias, v_saldo_prev,
         coalesce(sum(dias_saldo), 0), 'Consumo de vacaciones aprobadas', p_por
  from public.vacation_periods where user_id = p_user_id and not caducado;
end;
$$;

-- 3.5 Reversa (cancelación)
create or replace function public.reversar_vacaciones(
  p_user_id uuid, p_dias numeric, p_request_id uuid, p_fds int default 0
)
returns void
language plpgsql
as $$
declare
  r            record;
  v_restante   numeric := p_dias;
  v_devuelve   numeric;
  v_saldo_prev numeric;
begin
  select coalesce(sum(dias_saldo), 0) into v_saldo_prev
  from public.vacation_periods where user_id = p_user_id and not caducado;

  -- Se devuelve en orden inverso al consumo (LIFO sobre lo consumido)
  for r in
    select id, dias_consumidos from public.vacation_periods
     where user_id = p_user_id and not caducado and dias_consumidos > 0
     order by periodo desc
  loop
    exit when v_restante <= 0;
    v_devuelve := least(r.dias_consumidos, v_restante);
    update public.vacation_periods
       set dias_consumidos = dias_consumidos - v_devuelve
     where id = r.id;
    v_restante := v_restante - v_devuelve;
  end loop;

  if p_fds > 0 then
    update public.vacation_periods
       set fines_semana_consumidos = greatest(0, fines_semana_consumidos - p_fds)
     where id = (select id from public.vacation_periods
                  where user_id = p_user_id and not caducado order by periodo limit 1);
  end if;

  insert into public.vacation_movements
    (user_id, request_id, dias, saldo_previo, saldo_nuevo, motivo)
  select p_user_id, p_request_id, p_dias, v_saldo_prev,
         coalesce(sum(dias_saldo), 0), 'Reversa por cancelación de solicitud'
  from public.vacation_periods where user_id = p_user_id and not caducado;
end;
$$;

-- 3.6 Carga del saldo real al migrar empleados existentes
-- RRHH ya tiene un saldo por empleado (planilla/Excel). Esta función genera
-- los períodos históricos y ajusta el consumo para que el saldo cuadre.
create or replace function public.cargar_saldo_inicial(
  p_user_id uuid, p_saldo_real numeric, p_fds_ya_consumidos int default 0
)
returns numeric
language plpgsql
as $$
declare
  v_asignado  numeric;
  v_ajuste    numeric;
  v_restante  numeric;
  r           record;
  v_toma      numeric;
begin
  perform public.generar_periodos_vacaciones(p_user_id);
  perform public.caducar_periodos_vencidos();

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
$$;

comment on function public.cargar_saldo_inicial is
  'Migración de datos: genera los períodos del empleado y cuadra su saldo con el que RRHH tiene registrado.';

-- ---------------------------------------------------------------------
-- 4. REGLA DE LOS FINES DE SEMANA OBLIGATORIOS
-- ---------------------------------------------------------------------
-- Cuenta los fines de semana COMPLETOS (sábado + domingo) dentro del rango.
create or replace function public.fines_de_semana_completos(p_inicio date, p_fin date)
returns int
language sql
stable
as $$
  select count(*)::int
  from generate_series(p_inicio, p_fin, interval '1 day') as d(dia)
  where extract(isodow from d.dia) = 6            -- sábado
    and d.dia::date + 1 <= p_fin                  -- con su domingo dentro del rango
$$;

comment on function public.fines_de_semana_completos is
  'Fines de semana completos (sábado y domingo) contenidos en el rango.';

-- Fines de semana que al empleado aún le faltan por consumir en su período activo
create or replace function public.fines_semana_pendientes(p_user_id uuid)
returns int
language sql
stable
as $$
  select coalesce(
    (select greatest(0, fines_semana_obligatorios - fines_semana_consumidos)
       from public.vacation_periods
      where user_id = p_user_id and not caducado
      order by periodo limit 1), 0);
$$;

-- Rango corregido que incluye el fin de semana adyacente
create or replace function public.sugerir_rango_con_fin_de_semana(p_inicio date, p_fin date)
returns date[]
language sql
immutable
as $$
  select case
    -- Termina viernes: se extiende hasta el domingo
    when extract(isodow from p_fin) = 5 then array[p_inicio, p_fin + 2]
    -- Empieza lunes: se adelanta al sábado anterior
    when extract(isodow from p_inicio) = 1 then array[p_inicio - 2, p_fin]
    else array[p_inicio, p_fin]
  end;
$$;

-- ---------------------------------------------------------------------
-- 5. CATÁLOGO DE TIPOS DE PERMISO
-- ---------------------------------------------------------------------
create table if not exists public.permission_types (
  id                    smallserial primary key,
  codigo                text not null unique,
  nombre                text not null,
  descripcion           text,
  requiere_adjunto      boolean not null default false,
  requiere_justificacion boolean not null default true,
  requiere_firma        boolean not null default true,
  remunerado            boolean not null default true,
  descuenta_vacaciones  boolean not null default false,
  max_dias              numeric(6,2),
  max_horas             numeric(5,2),
  base_legal            text,
  orden                 int not null default 100,
  activo                boolean not null default true,
  created_at            timestamptz not null default now()
);

comment on table public.permission_types is
  'Catálogo configurable por RRHH. Define qué exige cada tipo de permiso (respaldo, firma, descuento).';

insert into public.permission_types
  (codigo, nombre, requiere_adjunto, requiere_justificacion, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden) values
  ('cita_medica',           'Cita médica',                          true,  true,  true,  false, 1,    8,  'Art. 42 CT / Reglamento IESS', 10),
  ('enfermedad',            'Enfermedad (certificado médico)',      true,  true,  true,  false, null, null,'Art. 42 num. 9 CT / IESS',    20),
  ('calamidad_domestica',   'Calamidad doméstica',                  true,  true,  true,  false, 3,    null,'Art. 42 num. 30 CT',          30),
  ('fallecimiento_familiar','Fallecimiento de familiar',            true,  true,  true,  false, 3,    null,'Art. 42 num. 30 CT',          40),
  ('maternidad',            'Licencia por maternidad',              true,  false, true,  false, 84,   null,'Art. 152 CT',                 50),
  ('paternidad',            'Licencia por paternidad',              true,  false, true,  false, 15,   null,'Art. 152 CT',                 60),
  ('lactancia',             'Permiso de lactancia',                 false, false, true,  false, null, 2,  'Art. 155 CT',                  70),
  ('matrimonio',            'Matrimonio o unión de hecho',          true,  false, true,  false, 3,    null,'Art. 42 num. 30 CT',          80),
  ('estudios',              'Estudios o capacitación',              true,  true,  true,  false, null, null,'Art. 42 num. 29 CT',          90),
  ('tramite_gobierno',      'Trámite ante entidad pública',         true,  true,  true,  false, 1,    8,  'Art. 42 CT',                   100),
  ('citacion_judicial',     'Citación judicial o notarial',         true,  true,  true,  false, null, null,'Art. 42 CT',                  110),
  ('sufragio',              'Sufragio electoral',                   false, false, true,  false, 1,    null,'Código de la Democracia',     120),
  ('donacion_sangre',       'Donación de sangre',                   true,  false, true,  false, 1,    4,  'Ley Orgánica de Salud',        130),
  ('cuidado_discapacidad',  'Cuidado de persona con discapacidad',  true,  true,  true,  false, null, 2,  'LOD Art. 49',                  140),
  ('caso_fortuito',         'Caso fortuito o fuerza mayor',         false, true,  true,  false, null, null,'Art. 30 Código Civil',        150),
  ('permiso_personal',      'Asunto personal (con cargo a vacaciones)', false, true, true, true, 3,   8,  'Acuerdo interno',              160)
on conflict (codigo) do nothing;

-- ---------------------------------------------------------------------
-- 6. NUEVAS COLUMNAS EN REQUESTS
-- ---------------------------------------------------------------------
alter table public.requests
  add column if not exists permission_type_id smallint references public.permission_types(id),
  add column if not exists descripcion        text,
  add column if not exists fines_semana       int not null default 0,
  add column if not exists omitir_regla_fds   boolean not null default false,
  add column if not exists horas_solicitadas  numeric(5,2);

-- Migrar el antiguo campo `motivo` a `descripcion`
do $$
begin
  if exists (select 1 from information_schema.columns
              where table_schema='public' and table_name='requests' and column_name='motivo') then
    update public.requests set descripcion = coalesce(descripcion, left(motivo, 200)) where motivo is not null;
    alter table public.requests drop column motivo;
  end if;
end$$;

alter table public.requests drop constraint if exists requests_descripcion_max;
alter table public.requests add constraint requests_descripcion_max
  check (descripcion is null or length(descripcion) <= 200);

alter table public.requests drop constraint if exists requests_permiso_categorizado;
alter table public.requests add constraint requests_permiso_categorizado
  check (tipo <> 'permiso' or permission_type_id is not null);

alter table public.requests drop constraint if exists requests_descripcion_obligatoria;
alter table public.requests add constraint requests_descripcion_obligatoria
  check (descripcion is not null and length(btrim(descripcion)) >= 5);

create index if not exists idx_requests_permission_type on public.requests (permission_type_id);

-- ---------------------------------------------------------------------
-- 7. ADJUNTOS DE RESPALDO
-- ---------------------------------------------------------------------
create table if not exists public.request_attachments (
  id            uuid primary key default gen_random_uuid(),
  request_id    uuid not null references public.requests(id) on delete cascade,
  storage_path  text not null,                     -- ruta en el bucket 'solicitudes'
  nombre_archivo text not null,
  mime_type     text not null,
  tamano_bytes  bigint not null check (tamano_bytes > 0 and tamano_bytes <= 10485760),
  hash_sha256   text,
  subido_por    uuid references public.users(id) on delete set null,
  created_at    timestamptz not null default now(),
  constraint request_attachments_mime_permitido check (
    mime_type in ('image/jpeg','image/png','image/webp','image/heic','application/pdf')
  )
);

comment on table public.request_attachments is
  'Respaldos de la solicitud (foto/scan de cita médica, certificado, citación). Archivo en Supabase Storage.';

create index if not exists idx_attachments_request on public.request_attachments (request_id);

-- ---------------------------------------------------------------------
-- 8. FIRMAS ELECTRÓNICAS
-- ---------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_type where typname = 'signature_kind') then
    create type public.signature_kind as enum ('dibujada', 'imagen', 'certificado');
  end if;
end$$;

create table if not exists public.signatures (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.users(id) on delete cascade,
  tipo         public.signature_kind not null default 'dibujada',
  contenido    text,                 -- SVG/PNG en data URI para firmas dibujadas
  storage_path text,                 -- o ruta en Storage para imagen/certificado
  hash_sha256  text not null,
  activa       boolean not null default true,
  created_at   timestamptz not null default now(),
  constraint signatures_tiene_contenido check (contenido is not null or storage_path is not null)
);

comment on table public.signatures is
  'Firma registrada del usuario: dibujada con el mouse, imagen subida o certificado oficial.';

-- Una sola firma activa por usuario
create unique index if not exists idx_signature_activa
  on public.signatures (user_id) where activa;

create table if not exists public.request_signatures (
  id           uuid primary key default gen_random_uuid(),
  request_id   uuid not null references public.requests(id) on delete cascade,
  user_id      uuid not null references public.users(id) on delete cascade,
  rol_firma    text not null check (rol_firma in ('solicitante','jefe','rrhh')),
  signature_id uuid references public.signatures(id) on delete set null,
  hash_sha256  text not null,        -- congelado: cambiar la firma no altera lo ya firmado
  firmado_en   timestamptz not null default now(),
  ip           inet,
  user_agent   text,
  unique (request_id, rol_firma)
);

comment on table public.request_signatures is
  'Instantánea de la firma en el momento de firmar. Cambiar la firma registrada no altera solicitudes pasadas.';

create index if not exists idx_request_signatures on public.request_signatures (request_id);

-- ---------------------------------------------------------------------
-- 9. TRIGGERS ACTUALIZADOS
-- ---------------------------------------------------------------------

-- 9.1 INSERT: cálculo de días, fines de semana y validaciones
create or replace function public.tg_requests_before_insert()
returns trigger
language plpgsql
as $$
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

  if new.dias_solicitados <= 0 then
    raise exception 'El rango de fechas no genera días computables (feriados/fin de semana).';
  end if;

  -- ---- Reglas de VACACIONES ----
  if new.tipo = 'vacacion' then
    new.es_adelanto := (new.dias_solicitados > v_saldo);

    -- Regla de los fines de semana obligatorios
    v_fds_req := public.fines_semana_pendientes(new.user_id);
    if v_fds_req > 0 and new.fines_semana = 0 and not new.omitir_regla_fds
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
$$;

-- 9.2 Validación diferida: adjuntos y firma (se evalúan al COMMIT)
create or replace function public.tg_requests_validar_requisitos()
returns trigger
language plpgsql
as $$
declare
  v_pt        public.permission_types%rowtype;
  v_adjuntos  int;
  v_firmas    int;
begin
  -- Se ejecuta al COMMIT: la solicitud pudo haberse eliminado en la misma
  -- transacción (o por cascada al borrar el empleado). En ese caso no hay nada que validar.
  if not exists (select 1 from public.requests where id = new.id) then
    return null;
  end if;

  select count(*) into v_adjuntos from public.request_attachments where request_id = new.id;
  select count(*) into v_firmas   from public.request_signatures
    where request_id = new.id and rol_firma = 'solicitante';

  if new.tipo = 'permiso' then
    select * into v_pt from public.permission_types where id = new.permission_type_id;

    if v_pt.requiere_adjunto and v_adjuntos = 0 then
      raise exception 'El permiso "%" exige adjuntar el respaldo (certificado, cita o documento)', v_pt.nombre;
    end if;

    if v_pt.requiere_firma and v_firmas = 0 then
      raise exception 'El permiso "%" exige la firma electrónica del solicitante', v_pt.nombre;
    end if;
  end if;

  return null;
end;
$$;

drop trigger if exists requests_validar_requisitos on public.requests;
create constraint trigger requests_validar_requisitos
  after insert on public.requests
  deferrable initially deferred
  for each row execute function public.tg_requests_validar_requisitos();

-- 9.3 UPDATE: flujo de estados, QR y consumo/reversa por períodos
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
         (old.estado = 'pendiente_jefe' and new.estado in ('pendiente_rrhh', 'rechazado', 'cancelado'))
      or (old.estado = 'pendiente_rrhh' and new.estado in ('aprobado', 'rechazado', 'cancelado'))
      or (old.estado = 'aprobado'       and new.estado = 'cancelado')
    ) then
      raise exception 'Transición de estado inválida: % -> %', old.estado, new.estado;
    end if;

    if new.estado = 'pendiente_rrhh' then
      new.jefe_aprobado_en := coalesce(new.jefe_aprobado_en, now());
    end if;

    if new.estado = 'rechazado' then
      new.rechazado_en := coalesce(new.rechazado_en, now());
    end if;

    -- ¿Esta solicitud descuenta saldo de vacaciones?
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

    if new.estado = 'cancelado' and old.estado = 'aprobado' and v_descuenta then
      perform public.reversar_vacaciones(
        new.user_id, new.dias_solicitados, new.id, new.fines_semana);
    end if;
  end if;

  return new;
end;
$$;

-- ---------------------------------------------------------------------
-- 10. PREVISUALIZACIÓN PARA EL FRONTEND
-- ---------------------------------------------------------------------
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
begin
  select dias_vacaciones into v_saldo from public.users where id = p_user_id;
  v_dias     := public.calcular_dias(p_tipo, p_inicio, p_fin);
  v_fds      := public.fines_de_semana_completos(p_inicio, p_fin);
  v_fds_pend := public.fines_semana_pendientes(p_user_id);
  v_sug      := array[p_inicio, p_fin];

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
    'avisos',                 to_jsonb(v_avisos)
  );
end;
$$;

comment on function public.previsualizar_solicitud is
  'Valida una solicitud antes de enviarla y devuelve días, saldo, avisos y rango sugerido. Para el frontend.';

-- ---------------------------------------------------------------------
-- 11. RLS DE LAS NUEVAS TABLAS
-- ---------------------------------------------------------------------
alter table public.app_config         enable row level security;
alter table public.vacation_periods   enable row level security;
alter table public.permission_types   enable row level security;
alter table public.request_attachments enable row level security;
alter table public.signatures         enable row level security;
alter table public.request_signatures enable row level security;

drop policy if exists app_config_select on public.app_config;
create policy app_config_select on public.app_config
  for select to authenticated using (true);
drop policy if exists app_config_admin on public.app_config;
create policy app_config_admin on public.app_config
  for all to authenticated using (public.is_rrhh_o_admin()) with check (public.is_rrhh_o_admin());

drop policy if exists vac_periods_select on public.vacation_periods;
create policy vac_periods_select on public.vacation_periods
  for select to authenticated
  using (user_id = public.current_user_id()
         or user_id in (select id from public.users where jefe_id = public.current_user_id())
         or public.is_rrhh_o_admin());

drop policy if exists permission_types_select on public.permission_types;
create policy permission_types_select on public.permission_types
  for select to authenticated using (activo or public.is_rrhh_o_admin());
drop policy if exists permission_types_admin on public.permission_types;
create policy permission_types_admin on public.permission_types
  for all to authenticated using (public.is_rrhh_o_admin()) with check (public.is_rrhh_o_admin());

drop policy if exists attachments_select on public.request_attachments;
create policy attachments_select on public.request_attachments
  for select to authenticated
  using (exists (select 1 from public.requests r where r.id = request_id
                   and (r.user_id = public.current_user_id()
                        or r.jefe_id = public.current_user_id()
                        or public.is_rrhh_o_admin())));
drop policy if exists attachments_insert on public.request_attachments;
create policy attachments_insert on public.request_attachments
  for insert to authenticated
  with check (exists (select 1 from public.requests r where r.id = request_id
                        and r.user_id = public.current_user_id()));

drop policy if exists signatures_propias on public.signatures;
create policy signatures_propias on public.signatures
  for all to authenticated
  using (user_id = public.current_user_id() or public.is_rrhh_o_admin())
  with check (user_id = public.current_user_id());

drop policy if exists request_signatures_select on public.request_signatures;
create policy request_signatures_select on public.request_signatures
  for select to authenticated
  using (exists (select 1 from public.requests r where r.id = request_id
                   and (r.user_id = public.current_user_id()
                        or r.jefe_id = public.current_user_id()
                        or public.is_rrhh_o_admin()
                        or (public.is_guardia() and r.estado = 'aprobado'))));
drop policy if exists request_signatures_insert on public.request_signatures;
create policy request_signatures_insert on public.request_signatures
  for insert to authenticated with check (user_id = public.current_user_id());

grant select on public.app_config, public.vacation_periods, public.permission_types,
                public.request_attachments, public.signatures, public.request_signatures
  to authenticated;
grant insert on public.request_attachments, public.request_signatures to authenticated;
grant insert, update, delete on public.signatures to authenticated;
grant usage, select on all sequences in schema public to authenticated;

-- ---------------------------------------------------------------------
-- 12. VISTA DE GARITA ENRIQUECIDA (tipo de permiso + firmas)
-- ---------------------------------------------------------------------
drop view if exists public.v_garita_actividad;
create view public.v_garita_actividad as
select
  r.id              as request_id,
  r.qr_hash,
  r.tipo,
  pt.nombre         as tipo_permiso,
  r.estado,
  r.fecha_inicio,
  r.fecha_fin,
  r.hora_inicio,
  r.hora_fin,
  r.descripcion,
  r.qr_usado_en,
  u.id              as user_id,
  u.cedula,
  u.nombre,
  u.departamento,
  u.cargo,
  (current_date between r.fecha_inicio and r.fecha_fin) as vigente_hoy,
  (select count(*) from public.request_attachments a where a.request_id = r.id) as adjuntos,
  (select jsonb_agg(jsonb_build_object('rol', rs.rol_firma, 'firmado_en', rs.firmado_en,
                                       'hash', rs.hash_sha256))
     from public.request_signatures rs where rs.request_id = r.id) as firmas
from public.requests r
join public.users u on u.id = r.user_id
left join public.permission_types pt on pt.id = r.permission_type_id
where r.estado in ('pendiente_jefe', 'pendiente_rrhh', 'aprobado')
  and r.fecha_fin >= current_date - 1
  and public.is_guardia();

grant select on public.v_garita_actividad to authenticated;

-- Realtime para las nuevas tablas que el dashboard observa
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    begin alter publication supabase_realtime add table public.vacation_periods;
    exception when duplicate_object then null; end;
  end if;
end$$;
