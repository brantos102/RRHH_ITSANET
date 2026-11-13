-- ---------------------------------------------------------------------------
-- 0020 · La caducidad de vacaciones se apaga, y lo ya marcado se repara.
--
-- El sistema mostraba a cada colaborador una FECHA DE VENCIMIENTO de sus
-- vacaciones. A quien entró el 1 de junio de 2026 le decía «vence el 31 de
-- mayo de 2030». Esa fecha no existe en ninguna parte: la hoja con la que
-- Talento Humano lleva los saldos desde hace años no tiene columna de
-- caducidad, y la empresa nunca ha extinguido días a nadie.
--
-- La fecha salía de aplicar el Art. 75 del Código del Trabajo como si fuera
-- una obligación. No lo es: el artículo PERMITE acumular hasta tres años, no
-- manda extinguir lo que pase de ahí. Aplicarlo por omisión convirtió un
-- derecho del trabajador en un plazo en su contra.
--
-- Y no se quedó en la pantalla. En la copia de la nómina real había 559
-- períodos de 76 personas marcados como caducados, con 9.554 días anotados
-- como perdidos. Eso no es un defecto de presentación: es una afirmación del
-- sistema sobre un pasivo laboral de la empresa. Además, las alertas
-- generaban avisos de severidad crítica —«Perderá 2,83 días el
-- 07/02/2029»— sobre una pérdida que no iba a ocurrir.
--
-- Qué hace esta migración:
--
--   A. Agrega el interruptor `caducidad_activa`, apagado. La maquinaria
--      queda intacta para el día en que haga falta —un contrato de plazo
--      fijo es otra cosa y se trata aparte—, pero no actúa sola.
--   B. Con el interruptor apagado no se calcula ninguna fecha de
--      vencimiento, no se caduca nada y no se avisa de pérdidas.
--   C. Repara lo ya marcado SIN mover un solo saldo. Los períodos viejos que
--      figuran como caducados pasan a figurar como consumidos, que es lo que
--      de verdad ocurrió: esa gente tomó sus vacaciones durante quince años,
--      solo que el sistema no tiene el detalle de cuándo. La migración
--      compara los saldos antes y después y se aborta si alguno se movió.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. El interruptor
-- =========================================================================

insert into public.app_config (clave, valor, descripcion) values
  ('caducidad_activa', 'false',
   'Si los días no gozados se extinguen al cumplirse el plazo de acumulación. '
   'El Art. 75 del Código del Trabajo PERMITE acumular hasta tres años; no '
   'obliga a extinguir. ITSANET no extingue: apagado.')
on conflict (clave) do nothing;

update public.app_config set legal_ref = 'CT_ART_75' where clave = 'caducidad_activa';

create or replace function public.caducidad_activa()
returns boolean
language sql
stable
as $ca$
  -- Ante la duda, no. Si la clave falta o trae cualquier otra cosa, el
  -- sistema no extingue días de nadie.
  select coalesce((select lower(btrim(valor)) = 'true'
                     from public.app_config where clave = 'caducidad_activa'), false);
$ca$;

comment on function public.caducidad_activa() is
  'Si la extinción de días por acumulación está en vigor. Apagada por omisión: una fecha de vencimiento que no va a cumplirse es peor que ninguna.';

-- =========================================================================
-- B. Las funciones dejan de actuar solas
--
-- Cada una es la original de su migración, con el cambio mínimo. Se copian
-- enteras y no se parchean: una función se reemplaza completa o no se
-- reemplaza.
-- =========================================================================

-- Cada función es la VERSIÓN VIGENTE —la de la migración más reciente que
-- la define, que no siempre es la que la creó— con el cambio mínimo. El
-- primer intento copió `generar_periodos_vacaciones` de la 0002 sin ver
-- que la 0011 ya la había reemplazado, y eso devolvió el devengo mensual
-- a cero. Una función se reemplaza entera, y desde donde está vigente.

create or replace function public.generar_periodos_vacaciones(p_user_id uuid)
returns integer
language plpgsql
as $gen$
declare
  v_ingreso date;
  v_anios   int;
  v_fds     int := public.cfg_int('fines_semana_obligatorios');
  v_acum    int := public.cfg_int('acumulacion_max_anios');
  -- Apagada la caducidad no se calcula fecha de vencimiento alguna: una
  -- fecha que no va a cumplirse es peor que ninguna fecha.
  v_caduca  boolean := public.caducidad_activa();
  k         int;
  v_hasta   date;
  v_vence   date;
  v_creados int := 0;
  v_parcial numeric;
begin
  select fecha_ingreso into v_ingreso from public.users where id = p_user_id;
  if v_ingreso is null then
    raise exception 'Usuario % no existe', p_user_id;
  end if;

  v_anios := public.anios_cumplidos(v_ingreso);

  for k in 1..greatest(v_anios, 0) loop
    v_hasta := (v_ingreso + make_interval(years => k))::date - 1;
    v_vence := case when v_caduca then (v_hasta + make_interval(years => v_acum))::date end;
    insert into public.vacation_periods
      (user_id, periodo, fecha_desde, fecha_hasta, dias_asignados,
       fines_semana_obligatorios, devengado, vence_en, caducado)
    values
      (p_user_id, k, (v_ingreso + make_interval(years => k - 1))::date, v_hasta,
       public.dias_por_antiguedad(k), v_fds, true, v_vence,
       coalesce(v_vence < current_date, false))
    on conflict (user_id, periodo) do update
      set dias_asignados = excluded.dias_asignados,
          devengado      = true,
          vence_en       = excluded.vence_en
      where not public.vacation_periods.devengado;
    v_creados := v_creados + 1;
  end loop;

  k         := v_anios + 1;
  v_hasta   := (v_ingreso + make_interval(years => k))::date - 1;
  v_parcial := public.dias_devengados_en_curso(v_ingreso, k);

  insert into public.vacation_periods
    (user_id, periodo, fecha_desde, fecha_hasta, dias_asignados,
     fines_semana_obligatorios, devengado, vence_en)
  values
    (p_user_id, k, (v_ingreso + make_interval(years => k - 1))::date, v_hasta,
     v_parcial, v_fds, false,
     case when v_caduca then (v_hasta + make_interval(years => v_acum))::date end)
  on conflict (user_id, periodo) do update
    set dias_asignados = greatest(public.vacation_periods.dias_asignados, excluded.dias_asignados)
    where not public.vacation_periods.devengado;

  perform public.refrescar_saldo_vacaciones(p_user_id);
  return v_creados;
end;
$gen$;

create or replace function public.caducar_periodos_vencidos()
returns int
language plpgsql
as $$
declare v_n int;
begin
  -- Apagada: no se extingue nada. Marcar días como perdidos no es un
  -- detalle de presentación, es una afirmación sobre un pasivo laboral.
  if not public.caducidad_activa() then
    return 0;
  end if;
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

create or replace function public.caducar_periodos_de(p_user_id uuid)
returns integer
language plpgsql
as $cad$
declare v_n int;
begin
  -- Apagada: no se extingue nada. Marcar días como perdidos no es un
  -- detalle de presentación, es una afirmación sobre un pasivo laboral.
  if not public.caducidad_activa() then
    return 0;
  end if;
  with vencidos as (
    update public.vacation_periods
       set caducado = true
     where user_id = p_user_id
       and not caducado and vence_en < current_date and dias_saldo > 0
     returning 1
  )
  select count(*) into v_n from vencidos;

  perform public.refrescar_saldo_vacaciones(p_user_id);
  return v_n;
end;
$cad$;

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
      -- Sin caducidad no hay nada que perder, y avisar de una pérdida que no
      -- va a ocurrir es la peor clase de aviso: asusta, y además enseña a la
      -- gente a ignorar los avisos.
      and public.caducidad_activa()
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

-- =========================================================================
-- C. Reparar lo ya marcado, sin mover ningún saldo
--
-- Un período marcado «caducado» no suma al saldo. Uno consumido por
-- completo tampoco. Pasar de lo primero a lo segundo deja el saldo igual y
-- cambia lo único que estaba mal: lo que el sistema afirma que pasó con
-- esos días.
--
-- No se des-caducan y ya: eso devolvería al saldo días que la persona sí
-- gozó —a Quiroz Freire lo llevaría de 19,75 a 299,75— y sería un error
-- mucho peor que el que se está corrigiendo.
-- =========================================================================

do $reparar$
declare
  v_antes  numeric;
  v_despues numeric;
  v_periodos int;
  v_gente  int;
begin
  if public.caducidad_activa() then
    raise notice 'La caducidad está activa: no se repara nada.';
    return;
  end if;

  select coalesce(sum(dias_vacaciones), 0) into v_antes from public.users;

  select count(*), count(distinct user_id) into v_periodos, v_gente
    from public.vacation_periods where caducado;

  -- Lo que el sistema llamó «caducado» fue en realidad «gozado antes de que
  -- existiera este sistema». Se anota como tal.
  update public.vacation_periods
     set dias_consumidos = dias_asignados,
         caducado        = false,
         vence_en        = null
   where caducado;

  -- Y ninguna fecha de vencimiento sobrevive mientras el interruptor esté
  -- apagado, ni en los períodos vivos.
  update public.vacation_periods set vence_en = null where vence_en is not null;

  select coalesce(sum(dias_vacaciones), 0) into v_despues from public.users;

  if v_antes is distinct from v_despues then
    raise exception 'La reparación movió los saldos: antes % y después %. '
                    'No se aplica ningún cambio.', v_antes, v_despues;
  end if;

  if v_periodos > 0 then
    raise notice 'Reparados % períodos de % persona(s). Saldo total sin cambios: %.',
                 v_periodos, v_gente, v_despues;
  end if;
end;
$reparar$;

-- Los avisos de pérdida ya enviados sobre algo que no va a ocurrir se
-- retiran: dejarlos sería sostener el error en la campana de cada persona.
delete from public.notifications
 where tipo = 'vacaciones_por_caducar' and not public.caducidad_activa();

-- =========================================================================
-- D. Que se vea desde dónde
-- =========================================================================

create or replace view public.v_caducidad as
select public.caducidad_activa() as activa,
       public.cfg_int('acumulacion_max_anios') as anios_de_acumulacion,
       (select count(*) from public.vacation_periods where caducado) as periodos_caducados,
       (select count(*) from public.vacation_periods where vence_en is not null)
         as periodos_con_fecha_de_vencimiento;

grant select on public.v_caducidad to authenticated;

comment on view public.v_caducidad is
  'Si la extinción de días está en vigor y cuántos períodos la tienen anotada. Con la caducidad apagada, las dos cuentas deben ser cero.';

-- =========================================================================
-- E. El tope del saldo deja de estorbar
--
-- `users_dias_rango` limitaba el saldo a 365 días. Con la caducidad activa
-- nadie llegaba: los períodos viejos se extinguían por el camino. Apagada,
-- el tope se vuelve alcanzable, y de hecho hay una persona en la nómina
-- —diecinueve períodos desde 2008— cuyos días asignados suman 377,92.
--
-- Eso no significa que tenga 377 días disponibles: significa que su
-- historial de vacaciones tomadas todavía no está cargado. Pero durante la
-- carga inicial el sistema pasa por ese estado intermedio —primero crea los
-- períodos, después descuenta lo gozado—, y ahí el tope hacía fallar la
-- carga con un error de restricción que no le dice nada a nadie.
--
-- El tope sigue existiendo, porque sirve para detectar un disparate: un
-- saldo de cinco mil días es un error de carga, no un trabajador con mucha
-- antigüedad. Se sube a 1.200, que es una carrera de cuarenta años
-- devengando el máximo del Art. 69 (30 días al año) sin gozar uno solo:
-- imposible en la práctica, y suficiente para que el tope nunca se
-- interponga en un caso legítimo.
-- =========================================================================

alter table public.users drop constraint if exists users_dias_rango;
alter table public.users add constraint users_dias_rango
  check (dias_vacaciones >= -60 and dias_vacaciones <= 1200);

comment on constraint users_dias_rango on public.users is
  'Detector de disparates, no política: un saldo fuera de este rango es un error de carga. El mínimo admite el adelanto que autoriza Talento Humano.';
