-- =====================================================================
--  SISTEMA INTEGRADO DE PERMISOS, VACACIONES Y CONTROL DE GARITA
--  Migración 0001 — Esquema base (PostgreSQL / Supabase)
--
--  Contenido:
--    1. Extensiones y tipos ENUM
--    2. Funciones utilitarias (cédula módulo 10, días Ecuador)
--    3. Tablas: users, requests, vacation_movements,
--               visitors, access_logs, audit_logs, auth_otp
--    4. Índices
--    5. Triggers (updated_at, cálculo de días, flujo de estados, QR)
--    6. Helpers de sesión + Row Level Security
--    7. Vistas para Garita  +  publicación Realtime
--
--  Ejecutar en el SQL Editor de Supabase (o `supabase db push`).
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. EXTENSIONES Y TIPOS
-- ---------------------------------------------------------------------
create extension if not exists "pgcrypto";      -- gen_random_uuid(), digest()
create extension if not exists "citext";        -- emails case-insensitive

do $$
begin
  if not exists (select 1 from pg_type where typname = 'user_role') then
    create type public.user_role as enum ('admin', 'rrhh', 'jefe', 'empleado', 'guardia');
  end if;

  if not exists (select 1 from pg_type where typname = 'request_type') then
    create type public.request_type as enum ('permiso', 'vacacion');
  end if;

  if not exists (select 1 from pg_type where typname = 'request_status') then
    create type public.request_status as enum (
      'pendiente_jefe', 'pendiente_rrhh', 'aprobado', 'rechazado', 'cancelado'
    );
  end if;

  if not exists (select 1 from pg_type where typname = 'access_type') then
    create type public.access_type as enum (
      'salida_empleado', 'retorno_empleado', 'ingreso_visita', 'salida_visita', 'acceso_denegado'
    );
  end if;
end$$;

-- Catálogo de feriados nacionales: se crea aquí porque las funciones de
-- cálculo de días lo referencian al momento de compilarse.
create table if not exists public.feriados (
  fecha        date primary key,
  nombre       text not null,
  activo       boolean not null default true,
  created_at   timestamptz not null default now()
);

-- ---------------------------------------------------------------------
-- 2. FUNCIONES UTILITARIAS
-- ---------------------------------------------------------------------

-- 2.1 Validación de cédula ecuatoriana (algoritmo módulo 10)
create or replace function public.es_cedula_valida(p_cedula text)
returns boolean
language plpgsql
immutable
as $$
declare
  v_provincia int;
  v_tercer    int;
  v_suma      int := 0;
  v_digito    int;
  v_verif     int;
  i           int;
begin
  if p_cedula is null or p_cedula !~ '^[0-9]{10}$' then
    return false;
  end if;

  v_provincia := substring(p_cedula from 1 for 2)::int;
  v_tercer    := substring(p_cedula from 3 for 1)::int;

  -- Provincias 01..24 y 30 (ecuatorianos en el exterior). Tercer dígito < 6 = persona natural.
  if not ((v_provincia between 1 and 24) or v_provincia = 30) then
    return false;
  end if;
  if v_tercer > 5 then
    return false;
  end if;

  for i in 1..9 loop
    v_digito := substring(p_cedula from i for 1)::int;
    if i % 2 = 1 then                 -- posiciones impares: coeficiente 2
      v_digito := v_digito * 2;
      if v_digito > 9 then
        v_digito := v_digito - 9;
      end if;
    end if;                           -- posiciones pares: coeficiente 1
    v_suma := v_suma + v_digito;
  end loop;

  v_verif := (10 - (v_suma % 10)) % 10;
  return v_verif = substring(p_cedula from 10 for 1)::int;
end;
$$;

comment on function public.es_cedula_valida is
  'Valida una cédula ecuatoriana de 10 dígitos mediante el algoritmo módulo 10.';

-- 2.2 Días hábiles (excluye sábados, domingos y feriados nacionales)
create or replace function public.dias_habiles(p_inicio date, p_fin date)
returns integer
language sql
stable
as $$
  select count(*)::int
  from generate_series(p_inicio, p_fin, interval '1 day') as d(dia)
  where extract(isodow from d.dia) between 1 and 5
    and not exists (
      select 1 from public.feriados f
      where f.fecha = d.dia::date and f.activo
    );
$$;

-- 2.3 Regla Ecuador: los permisos se cuentan en días hábiles; las vacaciones
--     en días calendario (hábiles + fines de semana), descontando feriados.
create or replace function public.calcular_dias(
  p_tipo   public.request_type,
  p_inicio date,
  p_fin    date
)
returns numeric
language sql
stable
as $$
  select case
    when p_inicio is null or p_fin is null or p_fin < p_inicio then 0
    when p_tipo = 'permiso' then public.dias_habiles(p_inicio, p_fin)::numeric
    else (
      select count(*)::numeric
      from generate_series(p_inicio, p_fin, interval '1 day') as d(dia)
      where not exists (
        select 1 from public.feriados f
        where f.fecha = d.dia::date and f.activo
      )
    )
  end;
$$;

comment on function public.calcular_dias is
  'Regla Ecuador: permiso = días hábiles; vacación = días calendario (incluye fines de semana), sin feriados.';

-- 2.4 Trigger genérico de updated_at
create or replace function public.tg_set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------
-- 3. TABLAS
-- ---------------------------------------------------------------------

-- 3.1 Usuarios / empleados
create table if not exists public.users (
  id                uuid primary key default gen_random_uuid(),
  auth_user_id      uuid unique references auth.users(id) on delete set null,
  cedula            text not null unique
                      constraint users_cedula_valida check (public.es_cedula_valida(cedula)),
  nombre            text not null,
  email             citext not null unique
                      constraint users_email_formato check (email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  telefono          text,
  rol               public.user_role not null default 'empleado',
  cargo             text,
  departamento      text,
  jefe_id           uuid references public.users(id) on delete set null,
  dias_vacaciones   numeric(6,2) not null default 0
                      constraint users_dias_rango check (dias_vacaciones >= -60 and dias_vacaciones <= 365),
  fecha_ingreso     date not null,
  logros            jsonb not null default '[]'::jsonb,
  activo            boolean not null default true,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  constraint users_no_es_su_propio_jefe check (jefe_id is null or jefe_id <> id)
);

comment on column public.users.dias_vacaciones is
  'Saldo actual de vacaciones. Puede ser negativo cuando se aprueban días adelantados.';
comment on column public.users.logros is
  'Arreglo JSON de logros/reconocimientos: [{"titulo":"...","fecha":"2026-01-01","detalle":"..."}]';

-- Antigüedad calculada (para el dashboard del empleado)
create or replace function public.antiguedad_anios(p_fecha_ingreso date)
returns numeric
language sql
immutable
as $$
  select round(extract(epoch from (now() - p_fecha_ingreso::timestamptz)) / 31557600.0, 2)::numeric;
$$;

-- 3.2 Solicitudes de permiso / vacaciones
create table if not exists public.requests (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references public.users(id) on delete cascade,
  tipo               public.request_type not null,
  fecha_inicio       date not null,
  fecha_fin          date not null,
  hora_inicio        time,                          -- permisos por horas
  hora_fin           time,
  dias_solicitados   numeric(6,2) not null default 0,
  saldo_al_solicitar numeric(6,2) not null default 0,
  es_adelanto        boolean not null default false, -- toma de días adelantados
  motivo             text,
  justificacion      text,
  estado             public.request_status not null default 'pendiente_jefe',

  -- Flujo de aprobación secuencial
  jefe_id            uuid references public.users(id) on delete set null,
  jefe_token         uuid not null default gen_random_uuid(),
  jefe_aprobado_por  uuid references public.users(id) on delete set null,
  jefe_aprobado_en   timestamptz,
  rrhh_token         uuid not null default gen_random_uuid(),
  rrhh_aprobado_por  uuid references public.users(id) on delete set null,
  rrhh_aprobado_en   timestamptz,
  rechazado_por      uuid references public.users(id) on delete set null,
  rechazado_en       timestamptz,
  motivo_rechazo     text,

  -- Código QR emitido al aprobarse totalmente
  qr_hash            uuid unique,
  qr_emitido_en      timestamptz,
  qr_expira_en       timestamptz,
  qr_usado_en        timestamptz,
  qr_usos            int not null default 0,

  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),

  constraint requests_rango_fechas check (fecha_fin >= fecha_inicio),
  constraint requests_rango_horas  check (hora_fin is null or hora_inicio is null or hora_fin > hora_inicio),
  -- Regla de negocio: si excede el saldo, la justificación es obligatoria.
  constraint requests_justificacion_obligatoria check (
    tipo <> 'vacacion'
    or dias_solicitados <= saldo_al_solicitar
    or (justificacion is not null and length(btrim(justificacion)) >= 10)
  )
);

comment on table  public.requests is 'Solicitudes de permiso y vacaciones con flujo Jefe -> RRHH -> QR.';
comment on column public.requests.jefe_token is 'Token del link de aprobación enviado por correo al jefe inmediato.';
comment on column public.requests.rrhh_token is 'Token del link de aprobación enviado por correo a RRHH.';
comment on column public.requests.qr_hash    is 'UUID que viaja dentro del código QR y se valida en garita.';

-- 3.3 Movimientos del saldo de vacaciones (trazabilidad del débito/crédito)
create table if not exists public.vacation_movements (
  id           bigserial primary key,
  user_id      uuid not null references public.users(id) on delete cascade,
  request_id   uuid references public.requests(id) on delete set null,
  dias         numeric(6,2) not null,          -- negativo = consumo, positivo = acreditación
  saldo_previo numeric(6,2) not null,
  saldo_nuevo  numeric(6,2) not null,
  motivo       text not null,
  created_by   uuid references public.users(id) on delete set null,
  created_at   timestamptz not null default now()
);

-- 3.4 Visitantes / personal temporal
create table if not exists public.visitors (
  id              uuid primary key default gen_random_uuid(),
  cedula          text not null
                    constraint visitors_cedula_valida check (public.es_cedula_valida(cedula)),
  nombre          text not null,
  empresa         text,
  telefono        text,
  motivo_visita   text not null,
  a_quien_visita  uuid references public.users(id) on delete set null,
  a_quien_visita_texto text,
  registrado_por  uuid references public.users(id) on delete set null,
  ingreso_en      timestamptz not null default now(),
  salida_en       timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint visitors_salida_posterior check (salida_en is null or salida_en >= ingreso_en)
);

-- 3.5 Bitácora de accesos de garita
create table if not exists public.access_logs (
  id            bigserial primary key,
  user_id       uuid references public.users(id) on delete set null,
  cedula        text,                                   -- empleado o visitante
  visitor_id    uuid references public.visitors(id) on delete set null,
  request_id    uuid references public.requests(id) on delete set null,
  tipo_acceso   public.access_type not null,
  autorizado    boolean not null default true,
  observacion   text,
  guardia_id    uuid references public.users(id) on delete set null,
  ip            inet,
  user_agent    text,
  metadata      jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now(),
  constraint access_logs_identifica_persona check (
    user_id is not null or visitor_id is not null or cedula is not null
  )
);

-- 3.6 Bitácora general del sistema (trazabilidad de TODO movimiento)
create table if not exists public.audit_logs (
  id           bigserial primary key,
  user_id      uuid references public.users(id) on delete set null,
  cedula       text,
  accion       text not null,          -- login_otp_enviado, request_creada, request_aprobada_jefe, ...
  entidad      text,                   -- requests, users, visitors, ...
  entidad_id   text,
  ip           inet,
  user_agent   text,
  detalle      jsonb not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);

-- 3.7 Tokens OTP de acceso (login por cédula + código al correo)
create table if not exists public.auth_otp (
  id           uuid primary key default gen_random_uuid(),
  cedula       text not null,
  user_id      uuid references public.users(id) on delete cascade,
  email        citext not null,
  code_hash    text not null,                 -- SHA-256 del OTP; nunca se guarda en claro
  intentos     int not null default 0,
  max_intentos int not null default 5,
  expira_en    timestamptz not null,
  consumido_en timestamptz,
  ip           inet,
  user_agent   text,
  created_at   timestamptz not null default now()
);

comment on table public.auth_otp is
  'OTP numérico enviado al correo del usuario. Solo se almacena el hash del código.';

-- ---------------------------------------------------------------------
-- 4. ÍNDICES
-- ---------------------------------------------------------------------
create index if not exists idx_users_rol            on public.users (rol) where activo;
create index if not exists idx_users_jefe           on public.users (jefe_id);
create index if not exists idx_users_email          on public.users (email);

create index if not exists idx_requests_user        on public.requests (user_id, created_at desc);
create index if not exists idx_requests_estado      on public.requests (estado);
create index if not exists idx_requests_jefe        on public.requests (jefe_id) where estado = 'pendiente_jefe';
create index if not exists idx_requests_fechas      on public.requests (fecha_inicio, fecha_fin);
create index if not exists idx_requests_qr          on public.requests (qr_hash) where qr_hash is not null;
create index if not exists idx_requests_jefe_token  on public.requests (jefe_token);
create index if not exists idx_requests_rrhh_token  on public.requests (rrhh_token);

create index if not exists idx_access_logs_fecha    on public.access_logs (created_at desc);
create index if not exists idx_access_logs_user     on public.access_logs (user_id, created_at desc);

create index if not exists idx_audit_logs_fecha     on public.audit_logs (created_at desc);
create index if not exists idx_audit_logs_user      on public.audit_logs (user_id, created_at desc);

create index if not exists idx_visitors_cedula      on public.visitors (cedula);
create index if not exists idx_visitors_dentro      on public.visitors (ingreso_en desc) where salida_en is null;

create index if not exists idx_auth_otp_cedula      on public.auth_otp (cedula, created_at desc);
create index if not exists idx_auth_otp_vigente     on public.auth_otp (expira_en) where consumido_en is null;

create index if not exists idx_vac_mov_user         on public.vacation_movements (user_id, created_at desc);

-- ---------------------------------------------------------------------
-- 5. TRIGGERS
-- ---------------------------------------------------------------------

-- 5.1 updated_at
drop trigger if exists set_updated_at on public.users;
create trigger set_updated_at before update on public.users
  for each row execute function public.tg_set_updated_at();

drop trigger if exists set_updated_at on public.requests;
create trigger set_updated_at before update on public.requests
  for each row execute function public.tg_set_updated_at();

drop trigger if exists set_updated_at on public.visitors;
create trigger set_updated_at before update on public.visitors
  for each row execute function public.tg_set_updated_at();

-- 5.2 Cálculo de días, saldo y bandera de adelanto al INSERT
create or replace function public.tg_requests_before_insert()
returns trigger
language plpgsql
as $$
declare
  v_saldo numeric(6,2);
  v_jefe  uuid;
begin
  select u.dias_vacaciones, u.jefe_id into v_saldo, v_jefe
  from public.users u where u.id = new.user_id;

  if v_saldo is null then
    raise exception 'Usuario % no existe o está inactivo', new.user_id;
  end if;

  new.dias_solicitados   := public.calcular_dias(new.tipo, new.fecha_inicio, new.fecha_fin);
  new.saldo_al_solicitar := v_saldo;
  new.jefe_id            := coalesce(new.jefe_id, v_jefe);
  new.es_adelanto        := (new.tipo = 'vacacion' and new.dias_solicitados > v_saldo);
  new.estado             := 'pendiente_jefe';

  if new.dias_solicitados <= 0 then
    raise exception 'El rango de fechas no genera días computables (feriados/fin de semana).';
  end if;

  return new;
end;
$$;

drop trigger if exists requests_before_insert on public.requests;
create trigger requests_before_insert before insert on public.requests
  for each row execute function public.tg_requests_before_insert();

-- 5.3 Transiciones de estado válidas + emisión de QR + débito de saldo
create or replace function public.tg_requests_before_update()
returns trigger
language plpgsql
as $$
declare
  v_saldo_previo numeric(6,2);
  v_saldo_nuevo  numeric(6,2);
begin
  -- Recalcular si cambian las fechas mientras aún está pendiente del jefe
  if (new.fecha_inicio, new.fecha_fin, new.tipo) is distinct from (old.fecha_inicio, old.fecha_fin, old.tipo) then
    if old.estado <> 'pendiente_jefe' then
      raise exception 'No se pueden modificar las fechas de una solicitud en estado %', old.estado;
    end if;
    new.dias_solicitados := public.calcular_dias(new.tipo, new.fecha_inicio, new.fecha_fin);
  end if;

  if new.estado is distinct from old.estado then
    -- Máquina de estados del flujo secuencial
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

    -- Aprobación final: se emite el QR y se descuenta el saldo de vacaciones
    if new.estado = 'aprobado' then
      new.rrhh_aprobado_en := coalesce(new.rrhh_aprobado_en, now());
      new.qr_hash          := coalesce(new.qr_hash, gen_random_uuid());
      new.qr_emitido_en    := coalesce(new.qr_emitido_en, now());
      new.qr_expira_en     := coalesce(new.qr_expira_en, (new.fecha_fin + 1)::timestamptz);

      if new.tipo = 'vacacion' then
        select dias_vacaciones into v_saldo_previo from public.users where id = new.user_id for update;
        v_saldo_nuevo := v_saldo_previo - new.dias_solicitados;

        update public.users set dias_vacaciones = v_saldo_nuevo where id = new.user_id;

        insert into public.vacation_movements
          (user_id, request_id, dias, saldo_previo, saldo_nuevo, motivo, created_by)
        values
          (new.user_id, new.id, -new.dias_solicitados, v_saldo_previo, v_saldo_nuevo,
           case when new.es_adelanto then 'Consumo de vacaciones (días adelantados)'
                else 'Consumo de vacaciones aprobadas' end,
           new.rrhh_aprobado_por);
      end if;
    end if;

    -- Cancelación de una solicitud ya aprobada: se devuelve el saldo
    if new.estado = 'cancelado' and old.estado = 'aprobado' and new.tipo = 'vacacion' then
      select dias_vacaciones into v_saldo_previo from public.users where id = new.user_id for update;
      v_saldo_nuevo := v_saldo_previo + new.dias_solicitados;

      update public.users set dias_vacaciones = v_saldo_nuevo where id = new.user_id;

      insert into public.vacation_movements
        (user_id, request_id, dias, saldo_previo, saldo_nuevo, motivo)
      values
        (new.user_id, new.id, new.dias_solicitados, v_saldo_previo, v_saldo_nuevo,
         'Reversa por cancelación de solicitud');
    end if;
  end if;

  return new;
end;
$$;

drop trigger if exists requests_before_update on public.requests;
create trigger requests_before_update before update on public.requests
  for each row execute function public.tg_requests_before_update();

-- 5.4 Auditoría automática de cambios de estado
create or replace function public.tg_requests_audit()
returns trigger
language plpgsql
as $$
begin
  if tg_op = 'INSERT' then
    insert into public.audit_logs (user_id, accion, entidad, entidad_id, detalle)
    values (new.user_id, 'request_creada', 'requests', new.id::text,
            jsonb_build_object('tipo', new.tipo, 'dias', new.dias_solicitados,
                               'inicio', new.fecha_inicio, 'fin', new.fecha_fin,
                               'es_adelanto', new.es_adelanto));
  elsif tg_op = 'UPDATE' and new.estado is distinct from old.estado then
    insert into public.audit_logs (user_id, accion, entidad, entidad_id, detalle)
    values (new.user_id, 'request_estado_cambiado', 'requests', new.id::text,
            jsonb_build_object('de', old.estado, 'a', new.estado,
                               'motivo_rechazo', new.motivo_rechazo));
  end if;
  return null;
end;
$$;

drop trigger if exists requests_audit on public.requests;
create trigger requests_audit after insert or update on public.requests
  for each row execute function public.tg_requests_audit();

-- ---------------------------------------------------------------------
-- 6. HELPERS DE SESIÓN + ROW LEVEL SECURITY
-- ---------------------------------------------------------------------

-- SECURITY DEFINER para evitar recursión de políticas sobre public.users
create or replace function public.current_user_id()
returns uuid
language sql
stable
security definer
set search_path = public, auth
as $$
  select u.id from public.users u where u.auth_user_id = auth.uid() limit 1;
$$;

create or replace function public.current_user_role()
returns public.user_role
language sql
stable
security definer
set search_path = public, auth
as $$
  select u.rol from public.users u where u.auth_user_id = auth.uid() limit 1;
$$;

create or replace function public.is_rrhh_o_admin()
returns boolean
language sql
stable
as $$ select public.current_user_role() in ('rrhh', 'admin'); $$;

create or replace function public.is_guardia()
returns boolean
language sql
stable
as $$ select public.current_user_role() in ('guardia', 'rrhh', 'admin'); $$;

alter table public.users              enable row level security;
alter table public.requests           enable row level security;
alter table public.access_logs        enable row level security;
alter table public.visitors           enable row level security;
alter table public.audit_logs         enable row level security;
alter table public.auth_otp           enable row level security;
alter table public.vacation_movements enable row level security;
alter table public.feriados           enable row level security;

-- 6.1 users
drop policy if exists users_select on public.users;
create policy users_select on public.users
  for select to authenticated
  using (
    auth_user_id = auth.uid()                       -- su propio perfil
    or jefe_id = public.current_user_id()           -- su equipo
    or public.is_rrhh_o_admin()
  );

drop policy if exists users_update_self on public.users;
create policy users_update_self on public.users
  for update to authenticated
  using (auth_user_id = auth.uid())
  with check (auth_user_id = auth.uid());

drop policy if exists users_admin_all on public.users;
create policy users_admin_all on public.users
  for all to authenticated
  using (public.is_rrhh_o_admin())
  with check (public.is_rrhh_o_admin());

-- 6.2 requests
drop policy if exists requests_select on public.requests;
create policy requests_select on public.requests
  for select to authenticated
  using (
    user_id = public.current_user_id()
    or jefe_id = public.current_user_id()
    or public.is_rrhh_o_admin()
    or (public.is_guardia() and estado = 'aprobado')   -- garita ve solo lo aprobado
  );

drop policy if exists requests_insert_propia on public.requests;
create policy requests_insert_propia on public.requests
  for insert to authenticated
  with check (user_id = public.current_user_id());

drop policy if exists requests_update_flujo on public.requests;
create policy requests_update_flujo on public.requests
  for update to authenticated
  using (
    (user_id = public.current_user_id() and estado = 'pendiente_jefe')  -- editar/cancelar la propia
    or (jefe_id = public.current_user_id() and estado = 'pendiente_jefe')
    or public.is_rrhh_o_admin()
  )
  with check (
    user_id = public.current_user_id()
    or jefe_id = public.current_user_id()
    or public.is_rrhh_o_admin()
  );

-- 6.3 access_logs — la garita registra; el empleado solo ve lo suyo
drop policy if exists access_logs_select on public.access_logs;
create policy access_logs_select on public.access_logs
  for select to authenticated
  using (user_id = public.current_user_id() or public.is_guardia());

drop policy if exists access_logs_insert on public.access_logs;
create policy access_logs_insert on public.access_logs
  for insert to authenticated
  with check (public.is_guardia());

-- 6.4 visitors — gestionados por garita/RRHH
drop policy if exists visitors_rw on public.visitors;
create policy visitors_rw on public.visitors
  for all to authenticated
  using (public.is_guardia())
  with check (public.is_guardia());

-- 6.5 vacation_movements
drop policy if exists vac_mov_select on public.vacation_movements;
create policy vac_mov_select on public.vacation_movements
  for select to authenticated
  using (user_id = public.current_user_id() or public.is_rrhh_o_admin());

-- 6.6 audit_logs — solo lectura para admin/RRHH (la escritura va por service_role)
drop policy if exists audit_logs_select on public.audit_logs;
create policy audit_logs_select on public.audit_logs
  for select to authenticated
  using (public.is_rrhh_o_admin());

-- 6.7 feriados — lectura para todos los autenticados
drop policy if exists feriados_select on public.feriados;
create policy feriados_select on public.feriados
  for select to authenticated using (true);

drop policy if exists feriados_admin on public.feriados;
create policy feriados_admin on public.feriados
  for all to authenticated
  using (public.is_rrhh_o_admin())
  with check (public.is_rrhh_o_admin());

-- 6.8 auth_otp — SIN políticas: solo accesible con service_role (backend FastAPI)

-- Privilegios base (RLS decide la fila; esto decide la tabla)
grant usage on schema public to anon, authenticated;
grant select on public.users, public.requests, public.feriados,
                public.access_logs, public.visitors, public.vacation_movements,
                public.audit_logs to authenticated;
grant insert, update on public.requests to authenticated;
grant insert, update on public.visitors to authenticated;
grant insert on public.access_logs to authenticated;
grant update on public.users to authenticated;
grant usage, select on all sequences in schema public to authenticated;
revoke all on public.auth_otp from anon, authenticated;

-- ---------------------------------------------------------------------
-- 7. VISTAS DE GARITA + REALTIME
-- ---------------------------------------------------------------------

-- Vista con datos mínimos del personal con permiso/vacación vigente.
-- security_invoker = off (default): la vista filtra por rol y no expone columnas sensibles.
create or replace view public.v_garita_actividad as
select
  r.id              as request_id,
  r.qr_hash,
  r.tipo,
  r.estado,
  r.fecha_inicio,
  r.fecha_fin,
  r.hora_inicio,
  r.hora_fin,
  r.qr_usado_en,
  u.id              as user_id,
  u.cedula,
  u.nombre,
  u.departamento,
  u.cargo,
  (current_date between r.fecha_inicio and r.fecha_fin) as vigente_hoy
from public.requests r
join public.users u on u.id = r.user_id
where r.estado in ('pendiente_jefe', 'pendiente_rrhh', 'aprobado')
  and r.fecha_fin >= current_date - 1
  and public.is_guardia();

grant select on public.v_garita_actividad to authenticated;

-- Visitantes actualmente dentro de la planta
create or replace view public.v_visitantes_dentro as
select v.id, v.cedula, v.nombre, v.empresa, v.motivo_visita,
       v.a_quien_visita_texto, v.ingreso_en
from public.visitors v
where v.salida_en is null
  and public.is_guardia();

grant select on public.v_visitantes_dentro to authenticated;

-- Publicación Realtime para el dashboard de garita
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    begin
      alter publication supabase_realtime add table public.requests;
    exception when duplicate_object then null; end;
    begin
      alter publication supabase_realtime add table public.access_logs;
    exception when duplicate_object then null; end;
    begin
      alter publication supabase_realtime add table public.visitors;
    exception when duplicate_object then null; end;
  end if;
end$$;

-- Realtime necesita la fila completa en UPDATE/DELETE
alter table public.requests    replica identity full;
alter table public.access_logs replica identity full;
alter table public.visitors    replica identity full;
