-- ---------------------------------------------------------------------------
-- 0021 · El Art. 75 dice otra cosa, y el control que sí corresponde.
--
-- El sistema tenía guardado este texto como Art. 75 del Código del Trabajo:
--
--   «Si el trabajador no hubiere gozado de las vacaciones podrá acumularlas
--    hasta por tres años consecutivos, a fin de gozarlas en el cuarto año.
--    Si no las gozare, PERDERÁ EL DERECHO sobre las acumuladas de más de
--    tres años.»
--
-- La segunda frase no está en la ley. El artículo dice:
--
--   «El trabajador podrá no hacer uso de las vacaciones hasta por tres años
--    consecutivos, a fin de acumularlas en el cuarto año.»
--
-- Y lo que pasa con las no gozadas lo dice el Art. 76, que el sistema ni
-- siquiera tenía:
--
--   «Si el trabajador no hubiere gozado de las vacaciones tendrá derecho al
--    equivalente de las remuneraciones que correspondan al tiempo de las no
--    gozadas, sin recargo.»
--
-- Es decir: las vacaciones no gozadas SE PAGAN. No se pierden. Y no podrían
-- perderse, porque el Art. 326 núm. 2 de la Constitución declara los
-- derechos laborales irrenunciables e intangibles.
--
-- De esa frase inventada salía todo lo demás: la fecha de vencimiento que
-- nadie entendía, los 9.554 días marcados como perdidos en la nómina y las
-- alertas de severidad crítica anunciando pérdidas que no iban a ocurrir.
-- Citar mal un artículo en un sistema oficial no es un detalle de
-- redacción: es la justificación de un comportamiento.
--
-- Ahora bien, el plazo de tres años del Art. 75 SÍ tiene consecuencias, y
-- son dos:
--
--   1. Es el límite de lo que el trabajador puede acumular por decisión
--      propia. Pasado ese punto, corresponde que la empresa programe las
--      vacaciones —el Art. 73 le da esa facultad al empleador—, no que se
--      queden acumulando indefinidamente.
--   2. Cada día no gozado es dinero que la empresa debe (Art. 76). Un saldo
--      que crece es un pasivo que crece.
--
-- Eso es lo que esta migración pone en su lugar: en vez de extinguir días,
-- avisa y mide.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A0. El aviso cambia de naturaleza, y necesita nombre propio
--
-- `vacaciones_por_caducar` describía algo que no ocurre. El aviso nuevo no
-- habla de una pérdida sino de una acumulación que hay que resolver, así
-- que no es el mismo aviso con otro texto: es otro aviso.
--
-- El valor viejo se deja en el enumerado a propósito. Quitarlo obligaría a
-- reescribir la bitácora, y la bitácora registra lo que pasó, no lo que
-- habría sido correcto que pasara.
-- =========================================================================

alter type public.notification_kind add value if not exists 'vacaciones_acumuladas';

-- =========================================================================
-- A. El texto correcto, y los artículos que faltaban
-- =========================================================================

update public.legal_references
   set titulo = 'Acumulación de vacaciones',
       texto  = 'El trabajador podrá no hacer uso de las vacaciones hasta por '
                'tres años consecutivos, a fin de acumularlas en el cuarto año.'
 where codigo = 'CT_ART_75';

insert into public.legal_references (codigo, norma, articulo, titulo, texto, categoria, orden)
values
  ('CT_ART_76', 'Código del Trabajo del Ecuador', 'Art. 76',
   'Compensación por vacaciones no gozadas',
   'Si el trabajador no hubiere gozado de las vacaciones tendrá derecho al '
   'equivalente de las remuneraciones que correspondan al tiempo de las no '
   'gozadas, sin recargo. La liquidación se efectuará en la forma prevista '
   'en el artículo 71 de este Código.',
   'vacaciones', 76),
  ('CONST_ART_326_2', 'Constitución de la República del Ecuador', 'Art. 326 núm. 2',
   'Irrenunciabilidad de los derechos laborales',
   'Los derechos laborales son irrenunciables e intangibles. Será nula toda '
   'estipulación en contrario.',
   'laboral', 77)
on conflict (codigo) do update
  set titulo = excluded.titulo, texto = excluded.texto,
      categoria = excluded.categoria, orden = excluded.orden;

-- =========================================================================
-- B. El control que sí corresponde: avisar, no extinguir
--
-- Tres períodos cumplidos sin gozar es el punto en que el Art. 75 se agota
-- como decisión del trabajador. A partir de ahí le toca a la empresa
-- programar las vacaciones (Art. 73). El sistema lo señala; no decide por
-- nadie ni borra nada.
-- =========================================================================

insert into public.app_config (clave, valor, descripcion) values
  ('acumulacion_aviso_periodos', '3',
   'Períodos cumplidos sin gozar a partir de los cuales Talento Humano debe '
   'programar las vacaciones (Art. 75 del Código del Trabajo).')
on conflict (clave) do nothing;

update public.app_config set legal_ref = 'CT_ART_75'
 where clave = 'acumulacion_aviso_periodos';

create or replace view public.v_acumulacion_excesiva as
select u.id as user_id, u.cedula, u.nombre, u.cargo, u.departamento, u.ciudad,
       coalesce(u.region, 'sierra') as region,
       u.fecha_ingreso,
       public.anios_cumplidos(u.fecha_ingreso) as anios,
       j.nombre as jefe,
       u.dias_vacaciones as saldo,
       -- Períodos cumplidos que todavía tienen días sin gozar. Es la cuenta
       -- que importa: no cuántos días hay, sino cuántos años arrastra.
       count(p.id) filter (where p.devengado and p.dias_saldo > 0) as periodos_sin_gozar,
       sum(p.dias_saldo) filter (where p.devengado and p.dias_saldo > 0) as dias_de_anios_cumplidos,
       min(p.fecha_hasta) filter (where p.devengado and p.dias_saldo > 0)
         as desde_cuando_arrastra
  from public.users u
  left join public.vacation_periods p on p.user_id = u.id
  left join public.users j on j.id = u.jefe_id
 where u.activo
 group by u.id, u.cedula, u.nombre, u.cargo, u.departamento, u.ciudad,
          u.region, u.fecha_ingreso, j.nombre, u.dias_vacaciones
having count(p.id) filter (where p.devengado and p.dias_saldo > 0)
       >= public.cfg_int('acumulacion_aviso_periodos')
 order by count(p.id) filter (where p.devengado and p.dias_saldo > 0) desc,
          sum(p.dias_saldo) filter (where p.devengado and p.dias_saldo > 0) desc;

grant select on public.v_acumulacion_excesiva to authenticated;

comment on view public.v_acumulacion_excesiva is
  'Quiénes arrastran tres o más años de vacaciones sin gozar. El Art. 75 agota ahí la decisión del trabajador: de ahí en adelante corresponde que la empresa programe (Art. 73). No se extingue nada.';

-- =========================================================================
-- C. Lo que la empresa debe: el pasivo del Art. 76
--
-- Cada día no gozado es dinero. La hoja de Talento Humano ya lleva pestañas
-- de PASIVOS; esto da la misma cuenta desde el sistema, sin teclear.
--
-- No se guarda sueldo alguno aquí: el valor se calcula fuera, con la
-- nómina. Lo que el sistema aporta es la cuenta de días, que es su trabajo.
-- =========================================================================

create or replace view public.v_pasivo_vacaciones as
select coalesce(u.departamento, 'SIN ÁREA') as departamento,
       coalesce(u.ciudad, 'SIN CIUDAD')     as ciudad,
       count(*)                              as personas,
       sum(u.dias_vacaciones)                as dias_por_pagar,
       sum(u.dias_vacaciones) filter (where u.dias_vacaciones > 30)
         as dias_de_quienes_pasan_de_30,
       round(avg(u.dias_vacaciones), 2)      as promedio_por_persona,
       max(u.dias_vacaciones)                as el_mas_alto
  from public.users u
 where u.activo and u.dias_vacaciones > 0
 group by 1, 2
 order by 4 desc;

grant select on public.v_pasivo_vacaciones to authenticated;

comment on view public.v_pasivo_vacaciones is
  'Días no gozados por área y ciudad. Cada uno es una obligación de pago (Art. 76 del Código del Trabajo), no un número administrativo.';

-- =========================================================================
-- D. La alerta cambia de sentido: de «va a perder» a «hay que programar»
--
-- Es la misma función de alertas; lo que cambia es el bloque (b), que antes
-- anunciaba una pérdida y ahora señala una acumulación que toca resolver.
-- =========================================================================

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

  -- (b) Acumulación que ya toca resolver
  --
  -- Antes este bloque anunciaba una pérdida: «Perderá 2,83 días el
  -- 07/02/2029», en rojo, citando un Art. 75 que no dice eso. Ahora dice lo
  -- que sí corresponde: esta persona arrastra tres o más años sin gozar, el
  -- Art. 75 agota ahí lo que ella puede decidir por su cuenta, y programar
  -- las vacaciones pasa a ser cosa de la empresa (Art. 73). Nadie pierde
  -- nada: lo no gozado se paga (Art. 76).
  for r in
    select a.user_id, a.nombre, a.periodos_sin_gozar, a.dias_de_anios_cumplidos,
           a.desde_cuando_arrastra
      from public.v_acumulacion_excesiva a
  loop
    v_clave := 'acumulacion:' || r.user_id || ':' || to_char(current_date, 'YYYY-MM');
    insert into public.notifications
      (user_id, tipo, severidad, titulo, mensaje, legal_ref, entidad, entidad_id, clave_dedupe, accion_url)
    values (r.user_id, 'vacaciones_acumuladas', 'advertencia',
      format('Tiene %s días de años ya cumplidos sin gozar', r.dias_de_anios_cumplidos),
      format('Arrastra %s período(s) anual(es) sin tomar vacaciones, el más '
          || 'antiguo desde el %s. El Art. 75 del Código del Trabajo permite '
          || 'acumular hasta tres años para gozarlos en el cuarto; a partir de '
          || 'ahí corresponde que Talento Humano programe sus vacaciones. '
          || 'Ningún día se pierde: lo no gozado se paga (Art. 76).',
          r.periodos_sin_gozar, to_char(r.desde_cuando_arrastra, 'DD/MM/YYYY')),
      'CT_ART_75', 'users', r.user_id::text, v_clave, '/dashboard.html#vacaciones')
    on conflict (clave_dedupe) do nothing;
    if found then v_por_cad := v_por_cad + 1; end if;

    -- Copia para Talento Humano: es quien tiene que programar.
    for v_rrhh in select id from public.users where rol in ('rrhh','admin') and activo loop
      insert into public.notifications
        (user_id, tipo, severidad, titulo, mensaje, legal_ref, entidad, entidad_id, clave_dedupe, accion_url)
      values (v_rrhh.id, 'vacaciones_acumuladas', 'advertencia',
        format('%s arrastra %s años de vacaciones sin gozar', r.nombre, r.periodos_sin_gozar),
        format('%s tiene %s días de períodos ya cumplidos, el más antiguo desde '
            || 'el %s. Pasado el tercer año el Art. 75 deja de amparar la '
            || 'acumulación por decisión del trabajador y el Art. 73 le da a la '
            || 'empresa la facultad de señalar el período. Cada día pendiente '
            || 'es además una obligación de pago (Art. 76).',
            r.nombre, r.dias_de_anios_cumplidos,
            to_char(r.desde_cuando_arrastra, 'DD/MM/YYYY')),
        'CT_ART_75', 'users', r.user_id::text,
        v_clave || ':rrhh:' || v_rrhh.id, '/colaboradores.html')
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

-- Los avisos viejos —los que anunciaban una pérdida— se retiran. Dejarlos
-- sería sostener en la campana de cada persona una cita mal hecha de la ley.
delete from public.notifications where tipo = 'vacaciones_por_caducar';
