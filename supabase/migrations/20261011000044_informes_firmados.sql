-- ---------------------------------------------------------------------------
-- 0044 · Los dos papeles que el colaborador firma y lleva a Talento Humano.
--
-- Son dos documentos distintos y se emiten con reglas distintas. Mezclarlos
-- sería el error:
--
--   TRAZABILIDAD — el historial completo de vacaciones de la persona. Se
--   emite UNA SOLA VEZ, la primera vez que solicita vacaciones desde el
--   sistema. La firma y la presenta en Talento Humano: es el acta de que
--   ambas partes están de acuerdo en el punto de partida. No se vuelve a
--   emitir salvo que un administrador o Talento Humano lo autoricen, y eso
--   se configura.
--
--   SOLICITUD — solo lo pedido en esa sesión. Se emite SIEMPRE, con cada
--   solicitud de vacaciones. Se firma y se presenta físicamente, y eso es lo
--   que confirma que quien pidió es la persona y no un tercero que entró con
--   su sesión.
--
-- POR QUÉ SE GUARDA UNA FOTO Y NO SOLO LA FECHA. Un papel firmado dice algo
-- concreto: «a esta fecha, usted ha gozado estos períodos». Si dentro de un
-- año Talento Humano corrige un registro de 2019, el papel firmado no
-- cambia, y el sistema tiene que poder reimprimir EXACTAMENTE lo que se
-- firmó, no lo que hoy diría. Por eso cada emisión guarda su contenido en
-- `datos`. Sin eso, reimprimir sería falsificar.
--
-- LO QUE NO SE HACE AQUÍ. Ningún dato personal sale de la base: el documento
-- se arma al pedirlo y se imprime desde el navegador. No se generan archivos
-- en disco ni se envían por correo (LOPDP, Art. 10: minimización).
-- ---------------------------------------------------------------------------

do $$
begin
  if not exists (select 1 from pg_type where typname = 'tipo_informe_firmado') then
    create type public.tipo_informe_firmado as enum ('trazabilidad', 'solicitud');
  end if;
end $$;

create table if not exists public.informes_firmados (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references public.users(id) on delete cascade,
  tipo            public.tipo_informe_firmado not null,
  -- Solo para el informe de solicitud: a qué solicitud corresponde.
  request_id      uuid references public.requests(id) on delete cascade,
  folio           text not null unique,

  -- La autorización, cuando hizo falta. Nula en la primera emisión
  -- automática: esa no la autoriza nadie porque es la que inaugura el
  -- expediente.
  autorizado_por  uuid references public.users(id) on delete set null,
  autorizado_en   timestamptz,
  autorizacion_motivo text,

  emitido_en      timestamptz not null default now(),
  -- Quién lo generó. Nulo cuando lo generó el propio sistema al registrarse
  -- la primera solicitud de vacaciones.
  emitido_por     uuid references public.users(id) on delete set null,

  -- La foto de lo que decía el papel. Ver la cabecera.
  datos           jsonb not null,

  impresiones     integer not null default 0,
  ultima_impresion timestamptz,

  constraint informe_solicitud_con_solicitud check (
    (tipo = 'solicitud' and request_id is not null) or
    (tipo = 'trazabilidad' and request_id is null)),
  constraint informe_autorizacion_completa check (
    (autorizado_por is null and autorizado_en is null) or
    (autorizado_por is not null and autorizado_en is not null
     and coalesce(btrim(autorizacion_motivo), '') <> ''))
);

comment on table public.informes_firmados is
  'Cada papel que el colaborador firma y presenta en Talento Humano, con la foto de lo que decía.';
comment on column public.informes_firmados.datos is
  'El contenido tal como se emitió. Reimprimir con los datos de hoy sería falsificar lo que se firmó.';

-- LA REGLA DE LA EMISIÓN ÚNICA, EN LA BASE. Un índice parcial: puede haber
-- un solo informe de trazabilidad por persona SIN autorización. Las
-- reemisiones autorizadas son filas aparte y no choca ninguna. Así la regla
-- no depende de que todas las rutas se acuerden de comprobarla.
create unique index if not exists idx_trazabilidad_una_sola_vez
  on public.informes_firmados (user_id)
  where tipo = 'trazabilidad' and autorizado_por is null;

create index if not exists idx_informes_firmados_persona
  on public.informes_firmados (user_id, tipo, emitido_en desc);
create index if not exists idx_informes_firmados_solicitud
  on public.informes_firmados (request_id) where request_id is not null;

alter table public.informes_firmados enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies
                 where tablename = 'informes_firmados' and policyname = 'informes_propios') then
    create policy informes_propios on public.informes_firmados for select
      to authenticated using (user_id = auth.uid() or public.is_rrhh_o_admin());
  end if;
  if not exists (select 1 from pg_policies
                 where tablename = 'informes_firmados' and policyname = 'informes_rrhh') then
    create policy informes_rrhh on public.informes_firmados for all
      to authenticated using (public.is_rrhh_o_admin()) with check (public.is_rrhh_o_admin());
  end if;
end $$;

-- --------------------------------------------------------------- parámetros
insert into public.app_config (clave, valor, descripcion) values
  ('trazabilidad_reemision', 'autorizada',
   'Qué pasa cuando el colaborador vuelve a pedir su informe de trazabilidad. '
   '«autorizada»: hace falta que un administrador o Talento Humano lo autoricen, '
   'dejando el motivo. «libre»: lo puede reimprimir cuando quiera. '
   'El papel ya firmado nunca cambia: una reemisión es un documento nuevo con su propio folio.'),
  ('empresa_razon_social', 'ITSANET S.A.',
   'Razón social que encabeza los documentos que el colaborador firma.'),
  ('empresa_ruc', '',
   'RUC que se imprime en los documentos. En blanco, no se imprime la línea.'),
  ('empresa_ciudad', 'Quito',
   'Ciudad que se imprime al pie de los documentos, antes de la fecha.')
on conflict (clave) do nothing;
-- ---------------------------------------------------- la foto de cada papel
-- Las dos funciones que arman el contenido. Van en la base y no en el
-- backend porque el contenido se guarda al emitir: el papel firmado tiene
-- que poder reimprimirse igual dentro de tres años.

create or replace function public.datos_informe_trazabilidad(p_user_id uuid)
returns jsonb
language sql
stable
set search_path = public
as $$
  select jsonb_build_object(
    'empresa', jsonb_build_object(
      'razon_social', public.cfg_texto('empresa_razon_social'),
      'ruc',          public.cfg_texto('empresa_ruc'),
      'ciudad',       public.cfg_texto('empresa_ciudad')),
    'colaborador', jsonb_build_object(
      'nombre', u.nombre, 'cedula', u.cedula, 'cargo', u.cargo,
      'departamento', u.departamento, 'bodega', u.bodega,
      'centro_costo', u.centro_costo, 'fecha_ingreso', u.fecha_ingreso,
      'anios_servicio', public.anios_cumplidos(u.fecha_ingreso),
      'jefe', (select j.nombre from public.users j where j.id = u.jefe_id)),
    'saldo', jsonb_build_object(
      'dias_disponibles', u.dias_vacaciones,
      'dias_por_periodo_en_curso',
        public.dias_por_antiguedad(greatest(public.anios_cumplidos(u.fecha_ingreso), 0) + 1)),
    'gozadas', coalesce((
      select jsonb_agg(jsonb_build_object(
               'fecha_inicio', h.fecha_inicio, 'fecha_fin', h.fecha_fin,
               'dias', h.dias,
               'observacion', case h.procedencia
                 when 'historico' then coalesce(h.detalle, 'Registro del archivo de Talento Humano')
                 else coalesce(h.detalle, 'Tramitada por el sistema') || ' · folio ' || h.folio
               end)
             order by h.fecha_inicio)
        from public.v_historial_vacaciones h where h.user_id = p_user_id), '[]'::jsonb),
    'totales', (
      select jsonb_build_object(
               'veces', count(*),
               'dias', coalesce(sum(h.dias), 0),
               'desde_la_hoja', count(*) filter (where h.procedencia = 'historico'),
               'en_el_sistema', count(*) filter (where h.procedencia <> 'historico'))
        from public.v_historial_vacaciones h where h.user_id = p_user_id)
  )
  from public.users u where u.id = p_user_id
$$;

comment on function public.datos_informe_trazabilidad(uuid) is
  'El historial completo de vacaciones, como se imprime para firmar.';

create or replace function public.datos_informe_solicitud(p_request_id uuid)
returns jsonb
language sql
stable
set search_path = public
as $$
  select jsonb_build_object(
    'empresa', jsonb_build_object(
      'razon_social', public.cfg_texto('empresa_razon_social'),
      'ruc',          public.cfg_texto('empresa_ruc'),
      'ciudad',       public.cfg_texto('empresa_ciudad')),
    'colaborador', jsonb_build_object(
      'nombre', u.nombre, 'cedula', u.cedula, 'cargo', u.cargo,
      'departamento', u.departamento, 'bodega', u.bodega,
      'centro_costo', u.centro_costo, 'fecha_ingreso', u.fecha_ingreso,
      'jefe', j.nombre),
    'solicitud', jsonb_build_object(
      'folio', r.folio,
      'solicitada_en', r.created_at,
      'fecha_inicio', r.fecha_inicio,
      'fecha_fin', r.fecha_fin,
      'dias', r.dias_solicitados,
      -- El día en que se reincorpora: el siguiente al último de vacaciones.
      'reintegro', r.fecha_fin + 1,
      'clase', case when r.es_adelanto then 'Adelantadas' else 'Ordinarias' end,
      'estado', r.estado::text,
      'aprobada', r.estado = 'aprobado',
      'saldo_al_solicitar', r.saldo_al_solicitar,
      'descripcion', r.descripcion,
      'reemplazo', (select x.nombre from public.users x where x.id = r.reemplazo_id)),
    'aprobaciones', jsonb_build_object(
      'jefe', jsonb_build_object(
        'nombre', (select a.nombre from public.users a where a.id = r.jefe_aprobado_por),
        'cuando', r.jefe_aprobado_en),
      'rrhh', jsonb_build_object(
        'nombre', (select a.nombre from public.users a where a.id = r.rrhh_aprobado_por),
        'cuando', r.rrhh_aprobado_en)))
  from public.requests r
  join public.users u on u.id = r.user_id
  left join public.users j on j.id = r.jefe_id
  where r.id = p_request_id
$$;

comment on function public.datos_informe_solicitud(uuid) is
  'Lo pedido en esa sesión, como se imprime para firmar y presentar en Talento Humano.';

-- ------------------------------------------------------------------- folios
-- Un folio que se pueda decir por teléfono y que diga qué documento es.
create sequence if not exists public.informes_firmados_folio_seq;

create or replace function public.folio_informe(p_tipo public.tipo_informe_firmado)
returns text
language sql
volatile
set search_path = public
as $$
  select case p_tipo when 'trazabilidad' then 'TRZ-' else 'SOL-' end
         || to_char(current_date, 'YYYY') || '-'
         || lpad(nextval('public.informes_firmados_folio_seq')::text, 5, '0')
$$;

-- ------------------------------------------------------- emitir y reimprimir
create or replace function public.informe_trazabilidad_asegurar(
  p_user_id uuid, p_emitido_por uuid default null)
returns public.informes_firmados
language plpgsql
security definer
set search_path = public
as $$
declare
  v_fila public.informes_firmados;
begin
  -- El que ya existe manda. Si hay una reemisión autorizada sin usar, esa es
  -- la vigente; si no, la primera emisión.
  select * into v_fila from public.informes_firmados
   where user_id = p_user_id and tipo = 'trazabilidad'
   order by emitido_en desc limit 1;

  if v_fila.id is not null then
    return v_fila;
  end if;

  insert into public.informes_firmados (user_id, tipo, folio, emitido_por, datos)
  values (p_user_id, 'trazabilidad', public.folio_informe('trazabilidad'),
          p_emitido_por, public.datos_informe_trazabilidad(p_user_id))
  returning * into v_fila;
  return v_fila;
end;
$$;

comment on function public.informe_trazabilidad_asegurar(uuid, uuid) is
  'Devuelve el informe de trazabilidad de la persona; lo crea solo si no tiene ninguno.';

create or replace function public.informe_trazabilidad_reemitir(
  p_user_id uuid, p_autoriza uuid, p_motivo text)
returns public.informes_firmados
language plpgsql
security definer
set search_path = public
as $$
declare
  v_fila public.informes_firmados;
begin
  if coalesce(btrim(p_motivo), '') = '' then
    raise exception 'Una reemisión necesita motivo: queda como constancia de quién la autorizó y por qué.';
  end if;
  if not exists (select 1 from public.informes_firmados
                  where user_id = p_user_id and tipo = 'trazabilidad') then
    raise exception 'Esa persona no tiene todavía un informe de trazabilidad que reemitir.';
  end if;

  -- El papel ya firmado NO se toca. Una reemisión es un documento nuevo, con
  -- su propio folio y su propia foto de los datos de hoy, y con el nombre de
  -- quien la autorizó impreso en él.
  insert into public.informes_firmados (
    user_id, tipo, folio, autorizado_por, autorizado_en, autorizacion_motivo,
    emitido_por, datos)
  values (p_user_id, 'trazabilidad', public.folio_informe('trazabilidad'),
          p_autoriza, now(), btrim(p_motivo), p_autoriza,
          public.datos_informe_trazabilidad(p_user_id))
  returning * into v_fila;
  return v_fila;
end;
$$;

comment on function public.informe_trazabilidad_reemitir(uuid, uuid, text) is
  'Reemisión autorizada: documento nuevo con folio nuevo. El anterior sigue siendo válido.';

create or replace function public.informe_solicitud_asegurar(
  p_request_id uuid, p_emitido_por uuid default null)
returns public.informes_firmados
language plpgsql
security definer
set search_path = public
as $$
declare
  v_fila public.informes_firmados;
  v_user uuid;
  v_tipo request_type;
begin
  select user_id, tipo into v_user, v_tipo
  from public.requests where id = p_request_id;
  if v_user is null then
    raise exception 'Esa solicitud no existe.';
  end if;
  if v_tipo <> 'vacacion' then
    raise exception 'Este informe es de vacaciones; esa solicitud es de otro tipo.';
  end if;

  select * into v_fila from public.informes_firmados
   where request_id = p_request_id and tipo = 'solicitud' limit 1;

  if v_fila.id is not null then
    -- Se reimprime con lo que diga HOY: a diferencia del de trazabilidad,
    -- este papel acompaña una solicitud que todavía puede aprobarse o
    -- rechazarse, y un formulario que dijera «pendiente» cuando ya está
    -- aprobado no serviría de nada en el mostrador.
    update public.informes_firmados
       set datos = public.datos_informe_solicitud(p_request_id)
     where id = v_fila.id
    returning * into v_fila;
    return v_fila;
  end if;

  insert into public.informes_firmados (
    user_id, tipo, request_id, folio, emitido_por, datos)
  values (v_user, 'solicitud', p_request_id, public.folio_informe('solicitud'),
          p_emitido_por, public.datos_informe_solicitud(p_request_id))
  returning * into v_fila;
  return v_fila;
end;
$$;

comment on function public.informe_solicitud_asegurar(uuid, uuid) is
  'El formulario de esa solicitud. Uno por solicitud; al reimprimirlo se actualiza al estado de hoy.';

create or replace function public.informe_impreso(p_id uuid)
returns void
language sql
security definer
set search_path = public
as $$
  update public.informes_firmados
     set impresiones = impresiones + 1, ultima_impresion = now()
   where id = p_id
$$;

-- ---------------------------------------------- la primera vez, sin pedirlo
-- «Se genera la primera vez que el usuario solicita vacaciones desde la
-- aplicación.» Va en un disparador y no en la ruta de la API para que valga
-- por cualquier camino: la carga masiva, una corrección de Talento Humano o
-- una ruta que se escriba el año que viene.
create or replace function public.tg_requests_informe_trazabilidad()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.tipo = 'vacacion' then
    perform public.informe_trazabilidad_asegurar(new.user_id);
    perform public.informe_solicitud_asegurar(new.id);
  end if;
  return null;
end;
$$;

drop trigger if exists trg_requests_informe_trazabilidad on public.requests;
create trigger trg_requests_informe_trazabilidad
  after insert on public.requests
  for each row execute function public.tg_requests_informe_trazabilidad();

comment on function public.tg_requests_informe_trazabilidad() is
  'Al registrarse una solicitud de vacaciones: el informe de trazabilidad si no lo tenía, y el de la solicitud siempre.';

-- ----------------------------------------------------- lo que ve el mostrador
create or replace view public.v_informes_firmados as
select i.id, i.user_id, u.cedula, u.nombre, u.departamento, u.region,
       i.tipo::text as tipo, i.request_id, r.folio as solicitud_folio,
       i.folio, i.emitido_en, i.impresiones, i.ultima_impresion,
       e.nombre as emitido_por,
       a.nombre as autorizado_por, i.autorizado_en, i.autorizacion_motivo,
       i.autorizado_por is not null as es_reemision,
       -- El vigente de cada tipo: el último emitido. Los anteriores siguen
       -- siendo documentos válidos —están firmados— pero no son el actual.
       i.emitido_en = max(i.emitido_en) over (partition by i.user_id, i.tipo)
         as es_el_vigente
  from public.informes_firmados i
  join public.users u on u.id = i.user_id
  left join public.users e on e.id = i.emitido_por
  left join public.users a on a.id = i.autorizado_por
  left join public.requests r on r.id = i.request_id;

comment on view public.v_informes_firmados is
  'Los papeles emitidos, con quién los emitió y cuántas veces se imprimieron.';

-- --------------------------------------------- el bloque del panel
-- Sin esta fila el panel esconde el bloque: lo que no está configurado no se
-- muestra, y esa regla es deliberada —un bloque fantasma que nadie puede
-- apagar es peor que uno que falta—. Queda como esencial: si un administrador
-- lo apagara, el colaborador no tendría de dónde imprimir el papel que la
-- empresa le exige firmar.
insert into public.panel_bloques (clave, titulo, descripcion, visible, orden, esencial) values
  ('papeles', 'Documentos para firmar',
   'Los dos papeles de vacaciones que se imprimen, se firman a mano y se presentan en '
   'Talento Humano. Solo aparece a quien tenga alguno emitido.',
   true, 85, true)
on conflict (clave) do nothing;
