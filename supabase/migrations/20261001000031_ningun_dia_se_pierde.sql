-- ---------------------------------------------------------------------------
-- 0031 · La alerta de saldo alto dejaba de decir que los días se pierden.
--
-- La migración 0021 corrigió el texto del Art. 75 y reescribió el aviso de
-- acumulación excesiva. Se le pasó el otro: el aviso de saldo alto —el que
-- llega a quien más días tiene, que es justo el que no debe leer una
-- amenaza falsa— seguía diciendo:
--
--     «los días de períodos más antiguos se pierden si no los goza a tiempo»
--
-- Eso no está en el Código del Trabajo. El Art. 75 permite acumular hasta
-- tres años; el Art. 76 dice que lo no gozado SE PAGA, y el Art. 326
-- núm. 2 de la Constitución dice que los derechos laborales son
-- irrenunciables. Un sistema de la empresa que le dice a un trabajador que
-- va a perder días que la ley le reconoce no es un error de redacción:
-- empuja a decisiones equivocadas y lo hace desde la voz de la empresa.
--
-- Se reemplaza el texto y se corrigen los avisos ya enviados que lo
-- repiten: dejar en la bandeja de alguien un mensaje que se sabe falso es
-- lo mismo que haberlo escrito hoy.
--
-- La función se reescribe desde su definición vigente, cambiando solo esas
-- líneas. Copiarla de una migración anterior habría deshecho los arreglos
-- que vinieron después.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

create or replace function public.generar_alertas_vacaciones()
returns table (tipo text, generadas integer)
language plpgsql
security definer
set search_path = public
as $gav$
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
  -- (a) Saldo acumulado alto: conviene programarlas, no porque se pierdan
  --     —no se pierden— sino porque acumular años sin descansar es justo lo
  --     que el Art. 75 no quiere, y porque quince días se organizan con
  --     tiempo o no se organizan.
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
      format('Su saldo acumulado es de %s días. Ningún día se pierde: el Art. 75 permite '
          || 'acumular hasta tres años y lo que no llegue a gozar se le paga (Art. 76). '
          || 'Aun así conviene programarlas con su jefe inmediato: son días de descanso, '
          || 'no un ahorro.', r.dias_vacaciones),
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
$gav$;

comment on function public.generar_alertas_vacaciones() is
  'Genera los avisos de vacaciones. Ninguno afirma que los días se pierdan: el Art. 75 permite acumular y el Art. 76 manda pagar lo no gozado.';

-- Los avisos ya enviados que repiten la afirmación falsa. Se corrigen en
-- vez de borrarlos: la persona recuerda haber recibido algo sobre sus días
-- acumulados, y que desaparezca sin más es otra forma de confundirla.
update public.notifications
   set mensaje = regexp_replace(
         mensaje,
         'El Código del Trabajo permite acumular hasta tres años; los días de períodos más antiguos se pierden si no los goza a tiempo\.',
         'Ningún día se pierde: el Art. 75 permite acumular hasta tres años y lo que no llegue a gozar se le paga (Art. 76).')
 where tipo = 'saldo_alto'
   and mensaje like '%se pierden si no los goza a tiempo%';
