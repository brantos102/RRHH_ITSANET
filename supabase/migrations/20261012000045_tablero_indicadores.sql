-- ---------------------------------------------------------------------------
-- 0045 · El tablero de indicadores, por bloques que se encienden y se apagan.
--
-- La pantalla principal del colaborador ya era configurable por bloques
-- (`panel_bloques`). Esto es lo mismo para quien dirige: cuántos están fuera
-- hoy, cuánta gente activa hay, cómo crece la plantilla por área. Cada
-- indicador es un bloque que Administración y Talento Humano encienden,
-- apagan, reordenan y ajustan sin tocar código.
--
-- POR QUÉ UNA TABLA Y NO UNA PANTALLA FIJA. Un tablero fijo envejece en tres
-- semanas: sirve para la reunión en la que se pidió y después estorba. Lo que
-- cambia no es el cálculo sino qué interesa mirar, y eso lo decide quien
-- dirige, no quien programa.
--
-- POR QUÉ LOS NÚMEROS SE CALCULAN Y NO SE GUARDAN. Un tablero con cifras
-- guardadas miente en cuanto alguien aprueba una solicitud. Se calculan al
-- pedirlos, contra las mismas vistas de las que sale todo lo demás: si el
-- tablero y el informe de la misma semana no coinciden, uno de los dos
-- está mal y nadie sabe cuál.
--
-- LO QUE NO LLEVA: NINGÚN NOMBRE. Son agregados. «Cuántos están de
-- vacaciones» es un número; quién, es el calendario del equipo, que ya tiene
-- sus propios permisos. Un tablero que enseña nombres a quien no le toca es
-- una fuga de datos con buena presentación (LOPDP, Art. 10: minimización).
--
-- Los ajustes de cada bloque viajan en `ajustes` porque cada indicador
-- necesita los suyos —el umbral de días, cuántos meses de historia— y una
-- columna por parámetro sería una migración por cada idea nueva.
-- ---------------------------------------------------------------------------

create table if not exists public.tablero_bloques (
  clave           text primary key,
  titulo          text not null,
  descripcion     text not null,
  -- Qué contesta este número, en una frase. Va en la pantalla, bajo la
  -- cifra: un indicador que hay que ir a preguntar qué mide no se usa.
  pregunta        text not null,
  visible         boolean not null default true,
  orden           smallint not null,
  roles           user_role[] not null default '{}',
  ajustes         jsonb not null default '{}'::jsonb,
  actualizado_en  timestamptz,
  actualizado_por uuid references public.users(id) on delete set null,
  constraint tablero_orden_valido check (orden >= 0 and orden <= 999)
);

comment on table public.tablero_bloques is
  'Qué indicadores se ven en el tablero, en qué orden y con qué ajustes. Los números se calculan al pedirlos.';

create index if not exists tablero_bloques_orden_idx on public.tablero_bloques (visible, orden);

alter table public.tablero_bloques enable row level security;

do $$
begin
  if not exists (select 1 from pg_policies
                 where tablename = 'tablero_bloques' and policyname = 'tablero_lectura') then
    create policy tablero_lectura on public.tablero_bloques for select
      to authenticated using (public.is_rrhh_o_admin());
  end if;
  if not exists (select 1 from pg_policies
                 where tablename = 'tablero_bloques' and policyname = 'tablero_admin') then
    create policy tablero_admin on public.tablero_bloques for all
      to authenticated using (public.is_rrhh_o_admin()) with check (public.is_rrhh_o_admin());
  end if;
end $$;

-- --------------------------------------------------------- los que vienen
insert into public.tablero_bloques (clave, titulo, descripcion, pregunta, orden, ajustes) values
  ('ausentes_hoy', 'Fuera hoy',
   'Cuántas personas están hoy de vacaciones o con permiso aprobado. Es el número que decide si el turno se cubre.',
   '¿Cuánta gente falta hoy?', 10, '{}'),
  ('activos', 'Colaboradores activos',
   'La plantilla viva, con las altas y las bajas del año para saber si crece o se encoge.',
   '¿Cuántos somos?', 20, '{"meses": 12}'),
  ('por_aprobar', 'Solicitudes por resolver',
   'Lo que está esperando una decisión, y cuánto lleva esperando. Una solicitud sin resolver es alguien que no sabe si puede viajar.',
   '¿Qué está trabado?', 30, '{"dias_alerta": 3}'),
  ('sin_jefe', 'Sin jefe asignado',
   'Personas cuyo expediente no dice de quién dependen. Sus solicitudes no tienen a quién ir, y hay que resolverlas a mano.',
   '¿A quién le falta jefe?', 40, '{}'),
  ('pasivo', 'Días acumulados sin gozar',
   'Los días de vacaciones que la empresa debe. No caducan: el Art. 76 dice que se pagan, así que son dinero comprometido.',
   '¿Cuánto debemos en vacaciones?', 50, '{"umbral_persona": 30}'),
  ('crecimiento', 'Altas y bajas por mes',
   'Cómo se mueve la plantilla mes a mes. Sirve para ver si una bodega rota gente más rápido que las demás.',
   '¿Cómo cambia la plantilla?', 60, '{"meses": 12}'),
  ('por_area', 'Reparto por área',
   'Cuánta gente hay en cada departamento y cuántos días debe cada uno. Ordenado por lo que más pesa.',
   '¿Dónde está la gente?', 70, '{"cuantas": 10}'),
  ('expedientes', 'Expedientes incompletos',
   'Sin correo real, sin jefe o con el saldo descuadrado. Cada uno es un trámite que un día se va a trabar.',
   '¿Qué falta por completar?', 80, '{}'),
  ('papeles', 'Papeles sin imprimir',
   'Documentos emitidos que nadie imprimió todavía. Sin la copia firmada en el expediente, la solicitud consta registrada pero no verificada.',
   '¿Qué falta firmar?', 90, '{}')
on conflict (clave) do nothing;

-- ---------------------------------------------------------- los nueve cálculos
-- Una función por indicador sería más limpia de leer y más lenta de usar: el
-- tablero los pide todos juntos y nueve viajes a la base para pintar una
-- pantalla se notan. Van en una, con un `case` por bloque, y solo se calcula
-- lo que está encendido: apagar un bloque lo quita de la pantalla Y deja de
-- costarlo.
create or replace function public.tablero_indicadores(p_claves text[] default null)
returns table (clave text, datos jsonb)
language plpgsql
stable
security definer
set search_path = public
as $tab$
declare
  b record;
  v_ajustes jsonb;
begin
  for b in
    select t.clave, t.ajustes from public.tablero_bloques t
     where t.visible and (p_claves is null or t.clave = any(p_claves))
     order by t.orden
  loop
    v_ajustes := b.ajustes;
    clave := b.clave;

    if b.clave = 'ausentes_hoy' then
      select jsonb_build_object(
        'cifra', count(*),
        'detalle', jsonb_build_object(
          'vacaciones', count(*) filter (where r.tipo = 'vacacion'),
          'permisos',   count(*) filter (where r.tipo <> 'vacacion'),
          'de', (select count(*) from public.users where activo)))
        into datos
      from public.requests r
      where r.estado = 'aprobado'
        and current_date between r.fecha_inicio and r.fecha_fin;

    elsif b.clave = 'activos' then
      select jsonb_build_object(
        'cifra', count(*) filter (where u.activo),
        'detalle', jsonb_build_object(
          'altas',  count(*) filter (where u.fecha_ingreso >= v_desde),
          'bajas',  count(*) filter (where u.fecha_salida is not null and u.fecha_salida >= v_desde),
          'meses',  coalesce((v_ajustes->>'meses')::int, 12)))
        into datos
      from public.users u,
           lateral (select (current_date - make_interval(
                      months => coalesce((v_ajustes->>'meses')::int, 12)))::date as v_desde) d;

    elsif b.clave = 'por_aprobar' then
      select jsonb_build_object(
        'cifra', count(*),
        'detalle', jsonb_build_object(
          'con_jefe',  count(*) filter (where r.estado = 'pendiente_jefe' and r.jefe_id is not null),
          'sin_jefe',  count(*) filter (where r.estado = 'pendiente_jefe' and r.jefe_id is null),
          'en_rrhh',   count(*) filter (where r.estado = 'pendiente_rrhh'),
          'atrasadas', count(*) filter (
            where r.created_at < now() - make_interval(
              days => coalesce((v_ajustes->>'dias_alerta')::int, 3))),
          'dias_alerta', coalesce((v_ajustes->>'dias_alerta')::int, 3),
          'la_mas_vieja', (select max(current_date - r2.created_at::date)
                             from public.requests r2
                            where r2.estado in ('pendiente_jefe','pendiente_rrhh'))))
        into datos
      from public.requests r
      where r.estado in ('pendiente_jefe', 'pendiente_rrhh');

    elsif b.clave = 'sin_jefe' then
      select jsonb_build_object(
        'cifra', count(*),
        'detalle', jsonb_build_object(
          'de', (select count(*) from public.users where activo),
          'con_solicitudes_abiertas', (
            select count(*) from public.requests r
             join public.users u2 on u2.id = r.user_id
            where u2.jefe_id is null and u2.activo
              and r.estado in ('pendiente_jefe','pendiente_rrhh'))))
        into datos
      from public.users u where u.activo and u.jefe_id is null;

    elsif b.clave = 'pasivo' then
      select jsonb_build_object(
        'cifra', round(coalesce(sum(u.dias_vacaciones), 0), 0),
        'detalle', jsonb_build_object(
          'personas', count(*) filter (where u.dias_vacaciones > 0),
          'promedio', round(coalesce(avg(u.dias_vacaciones) filter (where u.dias_vacaciones > 0), 0), 2),
          'pasan_del_umbral', count(*) filter (
            where u.dias_vacaciones > coalesce((v_ajustes->>'umbral_persona')::numeric, 30)),
          'umbral', coalesce((v_ajustes->>'umbral_persona')::numeric, 30),
          'el_mas_alto', round(coalesce(max(u.dias_vacaciones), 0), 0)))
        into datos
      from public.users u where u.activo;

    elsif b.clave = 'crecimiento' then
      select jsonb_build_object(
        'cifra', coalesce(sum(m.altas) - sum(m.bajas), 0),
        'detalle', jsonb_build_object(
          'meses', coalesce(jsonb_agg(jsonb_build_object(
                     'mes', to_char(m.mes, 'YYYY-MM'),
                     'altas', m.altas, 'bajas', m.bajas) order by m.mes), '[]'::jsonb)))
        into datos
      from (
        select date_trunc('month', s.mes)::date as mes,
               (select count(*) from public.users u
                 where date_trunc('month', u.fecha_ingreso) = s.mes) as altas,
               (select count(*) from public.users u
                 where u.fecha_salida is not null
                   and date_trunc('month', u.fecha_salida) = s.mes) as bajas
          from generate_series(
                 date_trunc('month', current_date - make_interval(
                   months => coalesce((v_ajustes->>'meses')::int, 12) - 1)),
                 date_trunc('month', current_date), interval '1 month') as s(mes)
      ) m;

    elsif b.clave = 'por_area' then
      select jsonb_build_object(
        'cifra', count(distinct coalesce(u.departamento, '(sin área)')),
        'detalle', jsonb_build_object(
          'areas', coalesce((
            select jsonb_agg(jsonb_build_object(
                     'area', x.area, 'personas', x.personas, 'dias', x.dias)
                   order by x.personas desc)
              from (
                select coalesce(u2.departamento, '(sin área)') as area,
                       count(*) as personas,
                       round(coalesce(sum(u2.dias_vacaciones), 0), 0) as dias
                  from public.users u2 where u2.activo
                 group by 1
                 order by count(*) desc
                 limit coalesce((v_ajustes->>'cuantas')::int, 10)) x), '[]'::jsonb)))
        into datos
      from public.users u where u.activo;

    elsif b.clave = 'expedientes' then
      select jsonb_build_object(
        'cifra', count(*) filter (
          where u.correo_pendiente or u.jefe_id is null or not coalesce(u.ficha_completa, false)),
        'detalle', jsonb_build_object(
          'sin_correo', count(*) filter (where u.correo_pendiente),
          'sin_jefe',   count(*) filter (where u.jefe_id is null),
          'ficha_incompleta', count(*) filter (where not coalesce(u.ficha_completa, false)),
          'de', count(*)))
        into datos
      from public.users u where u.activo;

    elsif b.clave = 'papeles' then
      select jsonb_build_object(
        'cifra', count(*) filter (where i.impresiones = 0),
        'detalle', jsonb_build_object(
          'trazabilidad', count(*) filter (where i.impresiones = 0 and i.tipo = 'trazabilidad'),
          'solicitud',    count(*) filter (where i.impresiones = 0 and i.tipo = 'solicitud'),
          'emitidos',     count(*)))
        into datos
      from public.informes_firmados i;

    else
      -- Un bloque en la tabla sin cálculo aquí: se dice, no se calla. Un
      -- hueco silencioso en un tablero se lee como un cero.
      datos := jsonb_build_object('cifra', null, 'error', 'Este indicador todavía no se calcula.');
    end if;

    return next;
  end loop;
end;
$tab$;

comment on function public.tablero_indicadores(text[]) is
  'Los indicadores encendidos, calculados al momento. Solo agregados: ningún nombre.';
