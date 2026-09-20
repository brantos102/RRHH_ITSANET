-- =====================================================================
--  Migración 0004 — Normativa ecuatoriana, datos del empleado y alertas
--
--   1. Glosario legal (legal_references) + enlace desde config y permisos
--   2. Ficha completa del empleado (LOPDP: minimización y dato sensible)
--   3. Cargas familiares y contactos de emergencia
--   4. Alertas de vacaciones (saldo alto, por caducar, caducadas)
--   5. Trazabilidad general y por empleado
--   6. Protección de datos: consentimientos, derechos ARCO, retención
--   7. Endurecimiento de RLS (campos protegidos, auditoría inmutable)
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. GLOSARIO LEGAL
-- ---------------------------------------------------------------------
create table if not exists public.legal_references (
  codigo        text primary key,
  norma         text not null,
  articulo      text not null,
  titulo        text not null,
  texto         text not null,
  url_oficial   text,
  categoria     text not null default 'laboral',
  orden         int  not null default 100,
  created_at    timestamptz not null default now()
);

comment on table public.legal_references is
  'Glosario que el aplicativo muestra al empleado para explicar de dónde sale cada regla y cada resultado.';

insert into public.legal_references (codigo, norma, articulo, titulo, texto, categoria, orden) values
('CT_ART_69','Código del Trabajo del Ecuador','Art. 69','Vacaciones anuales',
 'Todo trabajador tendrá derecho a gozar anualmente de un período ininterrumpido de quince días de descanso, incluidos los días no laborables. Los trabajadores que hubieren prestado servicios por más de cinco años en la misma empresa tendrán derecho a gozar adicionalmente de un día de vacaciones por cada uno de los años excedentes o recibirán en dinero la remuneración correspondiente a los días excedentes. El trabajador podrá no hacer uso de las vacaciones hasta por tres años consecutivos, a fin de acumularlas en el cuarto año.',
 'vacaciones', 10),

('CT_ART_71','Código del Trabajo del Ecuador','Art. 71','Liquidación para pago de vacaciones',
 'La liquidación para el pago de vacaciones se hará en forma general y única, computando la veinticuatroava parte de lo percibido por el trabajador durante un año completo de trabajo.',
 'vacaciones', 20),

('CT_ART_73','Código del Trabajo del Ecuador','Art. 73','Fijación del período vacacional',
 'En el contrato se hará constar el período en que el trabajador comenzará a gozar de vacaciones. No habiendo contrato escrito o de no haberse establecido en él, el empleador señalará el período vacacional, lo que deberá constar en un cuadro que se exhibirá en un lugar visible.',
 'vacaciones', 30),

('CT_ART_74','Código del Trabajo del Ecuador','Art. 74','Postergación por el empleador',
 'Cuando se trate de labores técnicas o de confianza para las que sea difícil reemplazar al trabajador por corto tiempo, el empleador podrá negar la vacación en un año para acumularla necesariamente a la del año siguiente.',
 'vacaciones', 40),

('CT_ART_75','Código del Trabajo del Ecuador','Art. 75','Acumulación de vacaciones',
 'Si el trabajador no hubiere gozado de las vacaciones podrá acumularlas hasta por tres años consecutivos, a fin de gozarlas en el cuarto año. Si no las gozare, perderá el derecho sobre las acumuladas de más de tres años.',
 'vacaciones', 50),

('CT_ART_42_30','Código del Trabajo del Ecuador','Art. 42 núm. 30','Permiso por calamidad doméstica',
 'Es obligación del empleador conceder permiso o declarar en comisión de servicio hasta por un año, con sueldo, en casos de calamidad doméstica debidamente comprobada, y conceder tres días de licencia por fallecimiento del cónyuge o conviviente en unión de hecho o de sus parientes dentro del segundo grado de consanguinidad o afinidad.',
 'permisos', 60),

('CT_ART_42_9','Código del Trabajo del Ecuador','Art. 42 núm. 9','Atención médica y enfermedad',
 'Es obligación del empleador sujetarse al reglamento de seguridad e higiene y conceder al trabajador la atención médica necesaria, así como respetar los certificados médicos emitidos por el IESS.',
 'permisos', 70),

('CT_ART_152','Código del Trabajo del Ecuador','Art. 152','Licencia por maternidad y paternidad',
 'Toda mujer trabajadora tiene derecho a una licencia con remuneración de doce semanas por el nacimiento de su hija o hijo. El padre tiene derecho a licencia con remuneración por diez días por el nacimiento de su hija o hijo cuando el parto es normal, y por quince días en los casos de nacimientos múltiples o por cesárea.',
 'permisos', 80),

('CT_ART_155','Código del Trabajo del Ecuador','Art. 155','Jornada por lactancia',
 'Durante los doce meses posteriores al parto, la jornada de la madre lactante durará seis horas, de conformidad con la necesidad de la beneficiaria.',
 'permisos', 90),

('LOD_ART_49','Ley Orgánica de Discapacidades','Art. 49','Permiso por cuidado de persona con discapacidad',
 'La persona trabajadora que tenga bajo su responsabilidad a una persona con discapacidad severa tiene derecho a dos horas diarias de permiso para su cuidado, previa justificación.',
 'permisos', 100),

('LOD_ART_47','Ley Orgánica de Discapacidades','Art. 47','Inclusión laboral',
 'El empleador público o privado que cuente con un número mínimo de veinticinco trabajadores está obligado a contratar un mínimo de cuatro por ciento de personas con discapacidad.',
 'laboral', 110),

('COD_DEMOCRACIA','Código de la Democracia','Art. 11','Permiso para sufragar',
 'El ejercicio del derecho al voto es obligatorio. Los empleadores concederán el permiso necesario para que sus trabajadores acudan a sufragar sin descuento de su remuneración.',
 'permisos', 120),

('CT_ART_42_29','Código del Trabajo del Ecuador','Art. 42 núm. 29','Facilidades para estudios',
 'Es obligación del empleador suministrar cada año, en forma completamente gratuita, por lo menos un vestido adecuado para el trabajo y conceder a los trabajadores las facilidades necesarias para su instrucción y capacitación.',
 'permisos', 65),

('CT_ART_42','Código del Trabajo del Ecuador','Art. 42','Obligaciones del empleador',
 'Enumera las obligaciones del empleador, entre ellas conceder los permisos y licencias que la ley establece y facilitar al trabajador el cumplimiento de deberes legales ante entidades públicas.',
 'permisos', 66),

('COGEP_ART_53','Código Orgánico General de Procesos','Art. 53','Deber de comparecer',
 'Las personas citadas o notificadas por la autoridad judicial están obligadas a comparecer. El empleador concederá el permiso necesario para el cumplimiento de esta obligación.',
 'permisos', 115),

('LOS_ART_79','Ley Orgánica de Salud','Art. 79','Donación voluntaria de sangre',
 'La donación de sangre es un acto voluntario y solidario. Las instituciones públicas y privadas concederán a sus trabajadores el permiso necesario para donar sangre.',
 'permisos', 135),

('CC_ART_30','Código Civil del Ecuador','Art. 30','Caso fortuito o fuerza mayor',
 'Se llama fuerza mayor o caso fortuito el imprevisto a que no es posible resistir, como un naufragio, un terremoto, el apresamiento de enemigos, los actos de autoridad ejercidos por un funcionario público, etcétera.',
 'permisos', 155),

('POLITICA_INTERNA','Reglamento Interno de Trabajo','Política interna','Permiso por asunto personal',
 'Permiso discrecional otorgado por la empresa para asuntos personales del trabajador. No corresponde a una licencia legal obligatoria, por lo que se imputa al saldo de vacaciones conforme a la política interna aprobada por Talento Humano.',
 'permisos', 165),

('LOPDP_ART_4','Ley Orgánica de Protección de Datos Personales','Art. 4','Datos sensibles',
 'Se consideran datos sensibles aquellos relativos a salud, datos genéticos y biométricos, origen étnico, condición migratoria, orientación sexual, religión, filiación política y situación de discapacidad. Su tratamiento requiere consentimiento expreso y medidas de seguridad reforzadas.',
 'proteccion_datos', 200),

('LOPDP_ART_7','Ley Orgánica de Protección de Datos Personales','Art. 7','Consentimiento',
 'El tratamiento de datos personales requiere el consentimiento libre, específico, informado e inequívoco del titular, salvo las excepciones previstas en la ley, entre ellas el cumplimiento de una obligación legal o la ejecución de una relación contractual laboral.',
 'proteccion_datos', 210),

('LOPDP_ART_10','Ley Orgánica de Protección de Datos Personales','Art. 10','Principios',
 'El tratamiento de datos personales se rige por los principios de juridicidad, lealtad, transparencia, finalidad, pertinencia y minimización, proporcionalidad, confidencialidad, calidad y exactitud, conservación, seguridad de datos personales y responsabilidad proactiva y demostrada.',
 'proteccion_datos', 220),

('LOPDP_ART_12','Ley Orgánica de Protección de Datos Personales','Art. 12 al 16','Derechos del titular (ARCO)',
 'El titular tiene derecho de acceso, rectificación y actualización, eliminación, oposición, portabilidad, y a no ser objeto de decisiones automatizadas. El responsable debe atender la solicitud en un plazo máximo de quince días.',
 'proteccion_datos', 230),

('LOPDP_ART_37','Ley Orgánica de Protección de Datos Personales','Art. 37','Seguridad del tratamiento',
 'El responsable y el encargado aplicarán medidas técnicas y organizativas apropiadas, incluidas la seudonimización y el cifrado, la capacidad de garantizar confidencialidad, integridad, disponibilidad y resiliencia, y un proceso de verificación y evaluación regular de su eficacia.',
 'proteccion_datos', 240),

('ISO27001_A5_15','ISO/IEC 27001:2022','Anexo A 5.15','Control de acceso',
 'Se deben establecer y aplicar reglas de control de acceso físico y lógico a la información sobre la base de los requisitos del negocio y de seguridad de la información. En este sistema se implementa con Row Level Security por rol y con el principio de mínimo privilegio.',
 'iso', 300),

('ISO27001_A8_15','ISO/IEC 27001:2022','Anexo A 8.15','Registro de eventos (logging)',
 'Se deben producir, almacenar, proteger y analizar registros de actividades, excepciones, fallos y eventos relevantes para la seguridad. En este sistema corresponde a audit_logs y access_logs, protegidos contra modificación y borrado.',
 'iso', 310),

('ISO27001_A5_34','ISO/IEC 27001:2022','Anexo A 5.34','Privacidad y protección de datos personales',
 'La organización debe identificar y cumplir los requisitos relativos a la preservación de la privacidad y la protección de datos personales de acuerdo con la legislación aplicable.',
 'iso', 320),

('ISO9001_8_5_2','ISO 9001:2015','Cláusula 8.5.2','Identificación y trazabilidad',
 'Cuando la trazabilidad sea un requisito, la organización debe controlar la identificación única de las salidas y conservar la información documentada necesaria para permitir la trazabilidad. En este sistema, cada solicitud tiene identificador único, historial de estados, firmas y bitácora de accesos.',
 'iso', 330)
on conflict (codigo) do update set
  texto = excluded.texto, titulo = excluded.titulo, norma = excluded.norma;

-- Enlazar configuración y tipos de permiso con su base legal
alter table public.app_config       add column if not exists legal_ref text references public.legal_references(codigo);
alter table public.permission_types add column if not exists legal_ref text references public.legal_references(codigo);

update public.app_config set legal_ref = 'CT_ART_69' where clave in
  ('vacaciones_dias_base','vacaciones_anio_dia_extra','vacaciones_dias_extra_max');
update public.app_config set legal_ref = 'CT_ART_75' where clave = 'acumulacion_max_anios';

update public.permission_types set legal_ref = 'CT_ART_42_9'  where codigo in ('cita_medica','enfermedad');
update public.permission_types set legal_ref = 'CT_ART_42_30' where codigo in ('calamidad_domestica','fallecimiento_familiar','matrimonio');
update public.permission_types set legal_ref = 'CT_ART_152'   where codigo in ('maternidad','paternidad');
update public.permission_types set legal_ref = 'CT_ART_155'   where codigo = 'lactancia';
update public.permission_types set legal_ref = 'LOD_ART_49'   where codigo = 'cuidado_discapacidad';
update public.permission_types set legal_ref = 'COD_DEMOCRACIA' where codigo = 'sufragio';
update public.permission_types set legal_ref = 'CT_ART_42_29'    where codigo = 'estudios';
update public.permission_types set legal_ref = 'CT_ART_42'       where codigo = 'tramite_gobierno';
update public.permission_types set legal_ref = 'COGEP_ART_53'    where codigo = 'citacion_judicial';
update public.permission_types set legal_ref = 'LOS_ART_79'      where codigo = 'donacion_sangre';
update public.permission_types set legal_ref = 'CC_ART_30'       where codigo = 'caso_fortuito';
update public.permission_types set legal_ref = 'POLITICA_INTERNA' where codigo = 'permiso_personal';

-- Parámetros nuevos de alertas
insert into public.app_config (clave, valor, descripcion, legal_ref) values
  ('alerta_saldo_alto',        '30', 'Saldo acumulado a partir del cual se sugiere tomar vacaciones', 'CT_ART_75'),
  ('alerta_dias_por_caducar',  '90', 'Días de anticipación con que se avisa que un período va a caducar', 'CT_ART_75'),
  ('retencion_audit_logs_meses','84','Meses de conservación de la bitácora de auditoría (7 años)', 'LOPDP_ART_10'),
  ('retencion_access_logs_meses','24','Meses de conservación de la bitácora de garita', 'LOPDP_ART_10'),
  ('politica_privacidad_version','1.0','Versión vigente de la política de tratamiento de datos', 'LOPDP_ART_7')
on conflict (clave) do nothing;

-- ---------------------------------------------------------------------
-- 2. FICHA COMPLETA DEL EMPLEADO
--    LOPDP Art. 10 (minimización): solo lo que el sistema realmente usa
--    para resolver permisos, emergencias y obligaciones legales.
-- ---------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_type where typname = 'estado_civil') then
    create type public.estado_civil as enum
      ('soltero','casado','union_hecho','divorciado','viudo');
  end if;
  if not exists (select 1 from pg_type where typname = 'tipo_contrato') then
    create type public.tipo_contrato as enum
      ('indefinido','eventual','ocasional','temporada','obra_cierta','prueba','aprendizaje','pasantia');
  end if;
  if not exists (select 1 from pg_type where typname = 'parentesco') then
    create type public.parentesco as enum
      ('conyuge','conviviente','hijo','padre','madre','hermano','abuelo','nieto','suegro','cunado','otro');
  end if;
end$$;

alter table public.users
  add column if not exists fecha_nacimiento      date,
  add column if not exists estado_civil          public.estado_civil,
  add column if not exists direccion             text,
  add column if not exists ciudad                text default 'Quito',
  add column if not exists provincia             text default 'Pichincha',
  add column if not exists telefono_alternativo  text,
  add column if not exists tipo_contrato         public.tipo_contrato default 'indefinido',
  add column if not exists fecha_salida          date,
  add column if not exists tipo_sangre           text,
  add column if not exists iess_afiliado         boolean not null default true,
  -- Dato sensible (LOPDP Art. 4): acceso restringido y consentimiento expreso
  add column if not exists tiene_discapacidad    boolean not null default false,
  add column if not exists porcentaje_discapacidad int,
  add column if not exists carnet_conadis        text;

alter table public.users drop constraint if exists users_tipo_sangre_valido;
alter table public.users add constraint users_tipo_sangre_valido
  check (tipo_sangre is null or tipo_sangre in ('A+','A-','B+','B-','AB+','AB-','O+','O-'));

alter table public.users drop constraint if exists users_discapacidad_coherente;
alter table public.users add constraint users_discapacidad_coherente
  check (not tiene_discapacidad
         or (porcentaje_discapacidad is not null
             and porcentaje_discapacidad between 1 and 100));

alter table public.users drop constraint if exists users_salida_posterior_ingreso;
alter table public.users add constraint users_salida_posterior_ingreso
  check (fecha_salida is null or fecha_salida >= fecha_ingreso);

comment on column public.users.tiene_discapacidad is
  'Dato sensible (LOPDP Art. 4). Habilita permisos y beneficios de la Ley Orgánica de Discapacidades.';

-- 2.1 Cargas familiares — sustentan calamidad doméstica, fallecimiento
--     dentro del 2do grado, lactancia y cuidado de discapacidad.
create table if not exists public.family_members (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references public.users(id) on delete cascade,
  nombre             text not null,
  cedula             text,
  parentesco         public.parentesco not null,
  grado_consanguinidad int not null default 1 check (grado_consanguinidad between 1 and 4),
  fecha_nacimiento   date,
  es_carga_familiar  boolean not null default false,
  tiene_discapacidad boolean not null default false,
  porcentaje_discapacidad int,
  observacion        text,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  constraint family_cedula_valida check (cedula is null or public.es_cedula_valida(cedula))
);

comment on table public.family_members is
  'Cargas familiares y parientes. El grado de consanguinidad sustenta la licencia del Art. 42 núm. 30 (hasta 2do grado).';

create index if not exists idx_family_user on public.family_members (user_id);

drop trigger if exists set_updated_at on public.family_members;
create trigger set_updated_at before update on public.family_members
  for each row execute function public.tg_set_updated_at();

-- 2.2 Contactos de emergencia — los usa la garita y RRHH ante un incidente
create table if not exists public.emergency_contacts (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users(id) on delete cascade,
  nombre        text not null,
  parentesco    public.parentesco not null,
  telefono      text not null,
  telefono_alternativo text,
  direccion     text,
  es_principal  boolean not null default false,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create unique index if not exists idx_emergency_principal
  on public.emergency_contacts (user_id) where es_principal;
create index if not exists idx_emergency_user on public.emergency_contacts (user_id);

drop trigger if exists set_updated_at on public.emergency_contacts;
create trigger set_updated_at before update on public.emergency_contacts
  for each row execute function public.tg_set_updated_at();

-- ---------------------------------------------------------------------
-- 3. ALERTAS Y NOTIFICACIONES
-- ---------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_type where typname = 'notification_kind') then
    create type public.notification_kind as enum (
      'saldo_alto', 'vacaciones_por_caducar', 'periodo_caducado',
      'solicitud_pendiente', 'solicitud_aprobada', 'solicitud_rechazada',
      'documento_faltante', 'informativo'
    );
  end if;
  if not exists (select 1 from pg_type where typname = 'notification_level') then
    create type public.notification_level as enum ('info', 'advertencia', 'critica');
  end if;
end$$;

create table if not exists public.notifications (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references public.users(id) on delete cascade,
  tipo           public.notification_kind not null,
  severidad      public.notification_level not null default 'info',
  titulo         text not null,
  mensaje        text not null,
  legal_ref      text references public.legal_references(codigo),
  entidad        text,
  entidad_id     text,
  accion_url     text,
  clave_dedupe   text unique,      -- evita repetir la misma alerta cada día
  leida_en       timestamptz,
  email_enviado_en timestamptz,
  expira_en      timestamptz,
  created_at     timestamptz not null default now()
);

comment on column public.notifications.clave_dedupe is
  'Clave idempotente (usuario + tipo + período + mes) para que la tarea diaria no duplique alertas.';

create index if not exists idx_notif_user on public.notifications (user_id, created_at desc);
create index if not exists idx_notif_no_leidas on public.notifications (user_id) where leida_en is null;

-- 3.1 Generador de alertas de vacaciones
create or replace function public.generar_alertas_vacaciones()
returns TABLE(tipo text, generadas int)
language plpgsql
as $$
declare
  v_umbral     numeric := public.cfg_int('alerta_saldo_alto');
  v_anticip    int     := public.cfg_int('alerta_dias_por_caducar');
  v_saldo_alto int := 0;
  v_por_cad    int := 0;
  v_caducado   int := 0;
  r            record;
  v_rrhh       record;
  v_clave      text;
begin
  -- (a) Saldo acumulado alto: conviene tomar vacaciones antes de perderlas
  for r in
    select u.id, u.nombre, u.dias_vacaciones
    from public.users u
    where u.activo and u.dias_vacaciones >= v_umbral
  loop
    v_clave := 'saldo_alto:' || r.id || ':' || to_char(current_date, 'YYYY-MM');
    insert into public.notifications
      (user_id, tipo, severidad, titulo, mensaje, legal_ref, clave_dedupe, accion_url)
    values (r.id, 'saldo_alto', 'advertencia',
      format('Tiene %s días de vacaciones acumulados', r.dias_vacaciones),
      format('Su saldo acumulado es de %s días. El Código del Trabajo permite acumular hasta tres años; '
          || 'los días de períodos más antiguos se pierden si no los goza a tiempo. '
          || 'Le sugerimos programar sus vacaciones con su jefe inmediato.', r.dias_vacaciones),
      'CT_ART_75', v_clave, '/dashboard.html#vacaciones')
    on conflict (clave_dedupe) do nothing;
    if found then v_saldo_alto := v_saldo_alto + 1; end if;
  end loop;

  -- (b) Períodos próximos a caducar
  for r in
    select p.id, p.user_id, p.periodo, p.dias_saldo, p.vence_en, u.nombre
    from public.vacation_periods p
    join public.users u on u.id = p.user_id
    where not p.caducado and u.activo and p.dias_saldo > 0
      and p.vence_en between current_date and current_date + v_anticip
  loop
    v_clave := 'por_caducar:' || r.id || ':' || to_char(current_date, 'YYYY-MM');
    insert into public.notifications
      (user_id, tipo, severidad, titulo, mensaje, legal_ref, entidad, entidad_id, clave_dedupe, accion_url)
    values (r.user_id, 'vacaciones_por_caducar', 'critica',
      format('Perderá %s días el %s', r.dias_saldo, to_char(r.vence_en, 'DD/MM/YYYY')),
      format('Su período %s vence el %s y aún tiene %s días sin gozar. '
          || 'Según el Art. 75 del Código del Trabajo, las vacaciones acumuladas por más de tres años se pierden. '
          || 'Solicite sus vacaciones antes de esa fecha.',
          r.periodo, to_char(r.vence_en, 'DD/MM/YYYY'), r.dias_saldo),
      'CT_ART_75', 'vacation_periods', r.id::text, v_clave, '/dashboard.html#vacaciones')
    on conflict (clave_dedupe) do nothing;
    if found then v_por_cad := v_por_cad + 1; end if;

    -- Copia para RRHH y administradores
    for v_rrhh in select id from public.users where rol in ('rrhh','admin') and activo loop
      insert into public.notifications
        (user_id, tipo, severidad, titulo, mensaje, legal_ref, entidad, entidad_id, clave_dedupe, accion_url)
      values (v_rrhh.id, 'vacaciones_por_caducar', 'advertencia',
        format('%s perderá %s días el %s', r.nombre, r.dias_saldo, to_char(r.vence_en, 'DD/MM/YYYY')),
        format('El período %s de %s vence el %s con %s días sin gozar (Art. 75 CT). '
            || 'Coordine la programación de sus vacaciones.',
            r.periodo, r.nombre, to_char(r.vence_en, 'DD/MM/YYYY'), r.dias_saldo),
        'CT_ART_75', 'vacation_periods', r.id::text,
        v_clave || ':rrhh:' || v_rrhh.id, '/rrhh.html#alertas')
      on conflict (clave_dedupe) do nothing;
    end loop;
  end loop;

  -- (c) Períodos ya caducados en los últimos 30 días
  for r in
    select p.id, p.user_id, p.periodo, p.dias_saldo, p.vence_en, u.nombre
    from public.vacation_periods p
    join public.users u on u.id = p.user_id
    where p.caducado and u.activo and p.dias_saldo > 0
      and p.vence_en >= current_date - 30
  loop
    v_clave := 'caducado:' || r.id;
    insert into public.notifications
      (user_id, tipo, severidad, titulo, mensaje, legal_ref, entidad, entidad_id, clave_dedupe)
    values (r.user_id, 'periodo_caducado', 'critica',
      format('Caducaron %s días de vacaciones', r.dias_saldo),
      format('Su período %s venció el %s y los %s días no gozados caducaron conforme al Art. 75 '
          || 'del Código del Trabajo. Si considera que hubo un error, comuníquese con Talento Humano.',
          r.periodo, to_char(r.vence_en, 'DD/MM/YYYY'), r.dias_saldo),
      'CT_ART_75', 'vacation_periods', r.id::text, v_clave)
    on conflict (clave_dedupe) do nothing;
    if found then v_caducado := v_caducado + 1; end if;

    for v_rrhh in select id from public.users where rol in ('rrhh','admin') and activo loop
      insert into public.notifications
        (user_id, tipo, severidad, titulo, mensaje, legal_ref, entidad, entidad_id, clave_dedupe)
      values (v_rrhh.id, 'periodo_caducado', 'critica',
        format('%s perdió %s días caducados', r.nombre, r.dias_saldo),
        format('El período %s de %s venció el %s con %s días no gozados (Art. 75 CT).',
               r.periodo, r.nombre, to_char(r.vence_en, 'DD/MM/YYYY'), r.dias_saldo),
        'CT_ART_75', 'vacation_periods', r.id::text, v_clave || ':rrhh:' || v_rrhh.id)
      on conflict (clave_dedupe) do nothing;
    end loop;
  end loop;

  return query
    select 'saldo_alto'::text, v_saldo_alto
    union all select 'vacaciones_por_caducar', v_por_cad
    union all select 'periodo_caducado', v_caducado;
end;
$$;

comment on function public.generar_alertas_vacaciones is
  'Tarea diaria: avisa al empleado y a RRHH sobre saldo alto, días por caducar y días ya caducados.';

-- 3.2 Notificación automática al cambiar el estado de una solicitud
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
        'requests', new.id::text, '/aprobaciones.html');
    end if;

  elsif tg_op = 'UPDATE' and new.estado is distinct from old.estado then
    if new.estado = 'pendiente_rrhh' then
      for v_dest in select id from public.users where rol in ('rrhh','admin') and activo loop
        insert into public.notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
        values (v_dest, 'solicitud_pendiente', 'info',
          format('Solicitud de %s aprobada por el jefe', v_nombre),
          format('La solicitud de %s (%s al %s) espera la aprobación de Talento Humano.',
                 v_nombre, to_char(new.fecha_inicio,'DD/MM/YYYY'), to_char(new.fecha_fin,'DD/MM/YYYY')),
          'requests', new.id::text, '/rrhh.html');
      end loop;

    elsif new.estado = 'aprobado' then
      insert into public.notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      values (new.user_id, 'solicitud_aprobada', 'info',
        'Su solicitud fue aprobada',
        format('Su solicitud del %s al %s fue aprobada. Ya puede descargar su código QR de salida.',
               to_char(new.fecha_inicio,'DD/MM/YYYY'), to_char(new.fecha_fin,'DD/MM/YYYY')),
        'requests', new.id::text, '/dashboard.html#solicitudes');

    elsif new.estado = 'rechazado' then
      insert into public.notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      values (new.user_id, 'solicitud_rechazada', 'advertencia',
        'Su solicitud fue rechazada',
        format('Su solicitud del %s al %s fue rechazada. Motivo: %s',
               to_char(new.fecha_inicio,'DD/MM/YYYY'), to_char(new.fecha_fin,'DD/MM/YYYY'),
               coalesce(new.motivo_rechazo, 'no especificado')),
        'requests', new.id::text, '/dashboard.html#solicitudes');
    end if;
  end if;

  return null;
end;
$$;

drop trigger if exists requests_notificar on public.requests;
create trigger requests_notificar after insert or update on public.requests
  for each row execute function public.tg_requests_notificar();

-- ---------------------------------------------------------------------
-- 4. EXPLICACIÓN DEL SALDO (por qué el empleado tiene esos días)
-- ---------------------------------------------------------------------
create or replace function public.explicar_saldo(p_user_id uuid)
returns jsonb
language plpgsql
stable
as $$
declare
  v_u        record;
  v_anios    int;
  v_periodos jsonb;
  v_legal    jsonb;
  v_prox     record;
begin
  select id, nombre, fecha_ingreso, dias_vacaciones into v_u
  from public.users where id = p_user_id;

  if v_u.id is null then
    return jsonb_build_object('error', 'Usuario no encontrado');
  end if;

  v_anios := public.anios_cumplidos(v_u.fecha_ingreso);

  select jsonb_agg(jsonb_build_object(
           'periodo',      p.periodo,
           'desde',        p.fecha_desde,
           'hasta',        p.fecha_hasta,
           'asignados',    p.dias_asignados,
           'consumidos',   p.dias_consumidos,
           'saldo',        p.dias_saldo,
           'vence_en',     p.vence_en,
           'caducado',     p.caducado,
           'devengado',    p.devengado,
           'explicacion',  case
             when not p.devengado then 'Período en curso: aún no cumple el año de servicio.'
             when p.caducado then format('Caducó el %s por acumulación mayor a %s años (Art. 75 CT).',
                                         to_char(p.vence_en,'DD/MM/YYYY'), public.cfg_int('acumulacion_max_anios'))
             when p.periodo < public.cfg_int('vacaciones_anio_dia_extra')
               then format('Año %s de servicio: %s días base (Art. 69 CT).', p.periodo, p.dias_asignados)
             else format('Año %s de servicio: %s días base + %s día(s) por antigüedad (Art. 69 CT).',
                         p.periodo, public.cfg_int('vacaciones_dias_base'),
                         p.dias_asignados - public.cfg_int('vacaciones_dias_base'))
           end)
         order by p.periodo)
    into v_periodos
  from public.vacation_periods p where p.user_id = p_user_id;

  select p.periodo, p.vence_en, p.dias_saldo into v_prox
  from public.vacation_periods p
  where p.user_id = p_user_id and not p.caducado and p.dias_saldo > 0
  order by p.vence_en limit 1;

  select jsonb_agg(jsonb_build_object(
           'codigo', l.codigo, 'norma', l.norma, 'articulo', l.articulo,
           'titulo', l.titulo, 'texto', l.texto) order by l.orden)
    into v_legal
  from public.legal_references l
  where l.codigo in ('CT_ART_69','CT_ART_75','CT_ART_73','CT_ART_74');

  return jsonb_build_object(
    'empleado',        v_u.nombre,
    'fecha_ingreso',   v_u.fecha_ingreso,
    'anios_servicio',  v_anios,
    'saldo_total',     v_u.dias_vacaciones,
    'dias_por_anio_actual', public.dias_por_antiguedad(greatest(v_anios, 1)),
    'fines_semana_pendientes', public.fines_semana_pendientes(p_user_id),
    'regla_antiguedad', format(
      '%s días por año cumplido. Desde el año %s se suma 1 día por cada año de servicio, hasta un máximo de %s días adicionales (%s días en total).',
      public.cfg_int('vacaciones_dias_base'), public.cfg_int('vacaciones_anio_dia_extra'),
      public.cfg_int('vacaciones_dias_extra_max'),
      public.cfg_int('vacaciones_dias_base') + public.cfg_int('vacaciones_dias_extra_max')),
    'regla_fines_semana', format(
      'De los %s días del período, %s deben corresponder a %s fines de semana completos.',
      public.cfg_int('vacaciones_dias_base'), public.cfg_int('fines_semana_obligatorios') * 2,
      public.cfg_int('fines_semana_obligatorios')),
    'proximo_vencimiento', case when v_prox.periodo is null then null else jsonb_build_object(
      'periodo', v_prox.periodo, 'vence_en', v_prox.vence_en, 'dias_en_riesgo', v_prox.dias_saldo) end,
    'periodos',        coalesce(v_periodos, '[]'::jsonb),
    'base_legal',      coalesce(v_legal, '[]'::jsonb)
  );
end;
$$;

comment on function public.explicar_saldo is
  'Desglose del saldo con su explicación y los artículos que lo sustentan. Alimenta el dashboard del empleado.';

-- ---------------------------------------------------------------------
-- 5. TRAZABILIDAD (ISO 9001 cláusula 8.5.2)
-- ---------------------------------------------------------------------
drop view if exists public.v_trazabilidad_solicitudes;
create view public.v_trazabilidad_solicitudes as
select
  r.id                     as solicitud_id,
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
  r.estado,
  r.created_at             as fecha_solicitud,
  j.nombre                 as jefe,
  r.jefe_aprobado_en,
  h.nombre                 as aprobador_rrhh,
  r.rrhh_aprobado_en,
  x.nombre                 as rechazado_por,
  r.rechazado_en,
  r.motivo_rechazo,
  r.qr_emitido_en,
  r.qr_usado_en,
  (select count(*) from public.request_attachments a where a.request_id = r.id) as adjuntos,
  (select count(*) from public.request_signatures s where s.request_id = r.id)  as firmas,
  case r.estado
    when 'aprobado'  then 'Aprobada'
    when 'rechazado' then 'Rechazada'
    when 'cancelado' then 'Cancelada'
    else 'En trámite'
  end as resultado
from public.requests r
join public.users u on u.id = r.user_id
left join public.users j on j.id = r.jefe_id
left join public.users h on h.id = r.rrhh_aprobado_por
left join public.users x on x.id = r.rechazado_por
left join public.permission_types pt on pt.id = r.permission_type_id;

comment on view public.v_trazabilidad_solicitudes is
  'Trazabilidad completa: una fila por solicitud con su resultado, quién decidió y cuándo (ISO 9001 8.5.2).';

drop view if exists public.v_trazabilidad_empleado;
create view public.v_trazabilidad_empleado as
select
  u.id as user_id, u.cedula, u.nombre, u.departamento, u.fecha_ingreso,
  public.anios_cumplidos(u.fecha_ingreso) as anios_servicio,
  u.dias_vacaciones as saldo_actual,
  count(r.id)                                                    as solicitudes_totales,
  count(*) filter (where r.estado = 'aprobado')                  as aprobadas,
  count(*) filter (where r.estado = 'rechazado')                 as rechazadas,
  count(*) filter (where r.estado in ('pendiente_jefe','pendiente_rrhh')) as en_tramite,
  count(*) filter (where r.estado = 'cancelado')                 as canceladas,
  coalesce(sum(r.dias_solicitados) filter (where r.estado = 'aprobado' and r.tipo = 'vacacion'), 0) as dias_vacaciones_tomados,
  coalesce(sum(r.dias_solicitados) filter (where r.estado = 'aprobado' and r.tipo = 'permiso'), 0)  as dias_permiso_tomados,
  max(r.created_at)                                              as ultima_solicitud
from public.users u
left join public.requests r on r.user_id = u.id
where u.activo
group by u.id, u.cedula, u.nombre, u.departamento, u.fecha_ingreso, u.dias_vacaciones;

drop view if exists public.v_resumen_general;
create view public.v_resumen_general as
select
  coalesce(u.departamento, 'Sin departamento') as departamento,
  date_trunc('month', r.created_at)::date      as mes,
  r.tipo,
  count(*)                                      as solicitudes,
  count(*) filter (where r.estado = 'aprobado')  as aprobadas,
  count(*) filter (where r.estado = 'rechazado') as rechazadas,
  round(100.0 * count(*) filter (where r.estado = 'aprobado') / nullif(count(*), 0), 1) as porcentaje_aprobacion,
  sum(r.dias_solicitados) filter (where r.estado = 'aprobado') as dias_aprobados
from public.requests r
join public.users u on u.id = r.user_id
group by 1, 2, 3;

-- ---------------------------------------------------------------------
-- 6. PROTECCIÓN DE DATOS PERSONALES (LOPDP)
-- ---------------------------------------------------------------------
create table if not exists public.data_consents (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references public.users(id) on delete cascade,
  politica_version text not null,
  finalidad       text not null,
  otorgado        boolean not null default true,
  otorgado_en     timestamptz not null default now(),
  revocado_en     timestamptz,
  ip              inet,
  user_agent      text
);

comment on table public.data_consents is
  'Consentimiento informado del titular (LOPDP Art. 7). Se registra versión de política, finalidad, fecha e IP.';

create index if not exists idx_consents_user on public.data_consents (user_id, otorgado_en desc);

do $$
begin
  if not exists (select 1 from pg_type where typname = 'arco_kind') then
    create type public.arco_kind as enum
      ('acceso','rectificacion','eliminacion','oposicion','portabilidad','decision_automatizada');
  end if;
  if not exists (select 1 from pg_type where typname = 'arco_status') then
    create type public.arco_status as enum ('recibida','en_proceso','atendida','rechazada');
  end if;
end$$;

create table if not exists public.data_subject_requests (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references public.users(id) on delete cascade,
  tipo          public.arco_kind not null,
  detalle       text not null,
  estado        public.arco_status not null default 'recibida',
  respuesta     text,
  atendida_por  uuid references public.users(id) on delete set null,
  vence_en      date not null default (current_date + 15),   -- LOPDP: 15 días
  atendida_en   timestamptz,
  created_at    timestamptz not null default now()
);

comment on table public.data_subject_requests is
  'Ejercicio de derechos ARCO (LOPDP Art. 12-16). Plazo legal de atención: 15 días.';

-- 6.1 Retención: purga de bitácoras según el plazo configurado
create or replace function public.aplicar_retencion()
returns TABLE(tabla text, eliminados bigint)
language plpgsql
as $$
declare
  v_audit  int := public.cfg_int('retencion_audit_logs_meses');
  v_access int := public.cfg_int('retencion_access_logs_meses');
  n1 bigint; n2 bigint;
begin
  with d as (
    delete from public.audit_logs
     where created_at < now() - make_interval(months => v_audit) returning 1
  ) select count(*) into n1 from d;

  with d as (
    delete from public.access_logs
     where created_at < now() - make_interval(months => v_access) returning 1
  ) select count(*) into n2 from d;

  return query select 'audit_logs'::text, n1 union all select 'access_logs', n2;
end;
$$;

comment on function public.aplicar_retencion is
  'Purga bitácoras vencidas según app_config (principio de conservación, LOPDP Art. 10).';

-- ---------------------------------------------------------------------
-- 7. ENDURECIMIENTO DE SEGURIDAD
-- ---------------------------------------------------------------------

-- 7.1 El empleado solo puede editar sus datos de contacto.
--     Antes podía modificar cualquier columna de su fila, incluido su rol.
create or replace function public.tg_users_proteger_campos()
returns trigger
language plpgsql
as $$
begin
  if current_user in ('postgres', 'service_role', 'supabase_admin') then
    return new;
  end if;
  if public.current_user_role() in ('rrhh', 'admin') then
    return new;
  end if;

  if (new.rol, new.cedula, new.email, new.dias_vacaciones, new.fecha_ingreso,
      new.fecha_salida, new.jefe_id, new.activo, new.logros, new.tipo_contrato,
      new.tiene_discapacidad, new.porcentaje_discapacidad, new.carnet_conadis)
     is distinct from
     (old.rol, old.cedula, old.email, old.dias_vacaciones, old.fecha_ingreso,
      old.fecha_salida, old.jefe_id, old.activo, old.logros, old.tipo_contrato,
      old.tiene_discapacidad, old.porcentaje_discapacidad, old.carnet_conadis)
  then
    raise exception 'Solo Talento Humano puede modificar estos datos. Usted puede actualizar sus datos de contacto.'
      using errcode = 'insufficient_privilege';
  end if;

  return new;
end;
$$;

drop trigger if exists users_proteger_campos on public.users;
create trigger users_proteger_campos before update on public.users
  for each row execute function public.tg_users_proteger_campos();

-- 7.2 Bitácoras inmutables (ISO 27001 A.8.15): nadie las edita ni borra
create or replace function public.tg_log_inmutable()
returns trigger
language plpgsql
as $$
begin
  if current_user in ('postgres', 'supabase_admin') then
    return coalesce(new, old);   -- solo el mantenimiento programado (retención)
  end if;
  raise exception 'Las bitácoras son inmutables: no se pueden modificar ni eliminar registros de auditoría.'
    using errcode = 'insufficient_privilege';
end;
$$;

drop trigger if exists audit_logs_inmutable on public.audit_logs;
create trigger audit_logs_inmutable before update or delete on public.audit_logs
  for each row execute function public.tg_log_inmutable();

drop trigger if exists access_logs_inmutable on public.access_logs;
create trigger access_logs_inmutable before update or delete on public.access_logs
  for each row execute function public.tg_log_inmutable();

revoke update, delete on public.audit_logs  from authenticated, anon;
revoke update, delete on public.access_logs from authenticated, anon;

-- 7.3 RLS de las tablas nuevas
alter table public.legal_references       enable row level security;
alter table public.family_members         enable row level security;
alter table public.emergency_contacts     enable row level security;
alter table public.notifications          enable row level security;
alter table public.data_consents          enable row level security;
alter table public.data_subject_requests  enable row level security;

drop policy if exists legal_select on public.legal_references;
create policy legal_select on public.legal_references
  for select to authenticated using (true);
drop policy if exists legal_admin on public.legal_references;
create policy legal_admin on public.legal_references
  for all to authenticated using (public.is_rrhh_o_admin()) with check (public.is_rrhh_o_admin());

-- Cargas familiares: dato personal (y sensible si hay discapacidad).
-- El jefe NO las ve; solo el titular y Talento Humano.
drop policy if exists family_propias on public.family_members;
create policy family_propias on public.family_members
  for all to authenticated
  using (user_id = public.current_user_id() or public.is_rrhh_o_admin())
  with check (user_id = public.current_user_id() or public.is_rrhh_o_admin());

drop policy if exists emergency_propios on public.emergency_contacts;
create policy emergency_propios on public.emergency_contacts
  for all to authenticated
  using (user_id = public.current_user_id() or public.is_rrhh_o_admin())
  with check (user_id = public.current_user_id() or public.is_rrhh_o_admin());

drop policy if exists notif_propias on public.notifications;
create policy notif_propias on public.notifications
  for select to authenticated using (user_id = public.current_user_id());
drop policy if exists notif_marcar_leida on public.notifications;
create policy notif_marcar_leida on public.notifications
  for update to authenticated
  using (user_id = public.current_user_id()) with check (user_id = public.current_user_id());

drop policy if exists consents_propios on public.data_consents;
create policy consents_propios on public.data_consents
  for select to authenticated
  using (user_id = public.current_user_id() or public.is_rrhh_o_admin());
drop policy if exists consents_insert on public.data_consents;
create policy consents_insert on public.data_consents
  for insert to authenticated with check (user_id = public.current_user_id());

drop policy if exists arco_propias on public.data_subject_requests;
create policy arco_propias on public.data_subject_requests
  for select to authenticated
  using (user_id = public.current_user_id() or public.is_rrhh_o_admin());
drop policy if exists arco_insert on public.data_subject_requests;
create policy arco_insert on public.data_subject_requests
  for insert to authenticated with check (user_id = public.current_user_id());
drop policy if exists arco_atender on public.data_subject_requests;
create policy arco_atender on public.data_subject_requests
  for update to authenticated
  using (public.is_rrhh_o_admin()) with check (public.is_rrhh_o_admin());

grant select on public.legal_references, public.notifications, public.family_members,
                public.emergency_contacts, public.data_consents, public.data_subject_requests,
                public.v_trazabilidad_solicitudes, public.v_trazabilidad_empleado,
                public.v_resumen_general
  to authenticated;
grant insert, update, delete on public.family_members, public.emergency_contacts to authenticated;
grant insert on public.data_consents, public.data_subject_requests to authenticated;
grant update on public.notifications to authenticated;
grant usage, select on all sequences in schema public to authenticated;

-- 7.4 Realtime de notificaciones (campanita en vivo)
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    begin alter publication supabase_realtime add table public.notifications;
    exception when duplicate_object then null; end;
  end if;
end$$;
alter table public.notifications replica identity full;

-- ---------------------------------------------------------------------
-- 8. TAREAS PROGRAMADAS (pg_cron, si está disponible en el proyecto)
-- ---------------------------------------------------------------------
do $cron$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    perform cron.unschedule('rrhh-alertas-vacaciones') where exists
      (select 1 from cron.job where jobname = 'rrhh-alertas-vacaciones');
    perform cron.schedule('rrhh-alertas-vacaciones', '0 12 * * *',
      $job$ select public.caducar_periodos_vencidos(); select public.generar_alertas_vacaciones(); $job$);

    perform cron.unschedule('rrhh-retencion-bitacoras') where exists
      (select 1 from cron.job where jobname = 'rrhh-retencion-bitacoras');
    perform cron.schedule('rrhh-retencion-bitacoras', '0 6 1 * *',
      $job$ select public.aplicar_retencion(); $job$);

    raise notice 'Tareas programadas con pg_cron (alertas diarias 07:00 Ecuador, retención mensual).';
  else
    raise notice 'pg_cron no está habilitado: programe generar_alertas_vacaciones() y aplicar_retencion() desde el backend.';
  end if;
end
$cron$;
