-- ---------------------------------------------------------------------------
-- 0042 · La base legal se muestra, se resume o se calla. Lo decide la empresa.
--
-- Hoy el panel del colaborador imprime el texto literal de cuatro artículos
-- del Código del Trabajo. Dos de ellos —el 75 y el 76— son los que terminan
-- en discusión en el mostrador de Talento Humano:
--
--   Art. 75  permite ACUMULAR hasta tres años. Leído solo, se entiende como
--            una invitación a no tomar vacaciones.
--   Art. 76  dice que lo no gozado SE PAGA. Leído solo, se entiende como un
--            derecho a cobrar en lugar de descansar, cuando en realidad opera
--            sobre la liquidación y no a pedido del trabajador.
--
-- El sistema no puede resolver esa discusión, pero sí puede dejar de
-- provocarla. Y hay una salida mejor que el interruptor de encendido y
-- apagado: TRES MODOS por artículo.
--
--   completo  el texto literal de la norma, como hasta hoy.
--   resumen   una línea en lenguaje llano que Talento Humano redacta y
--             sostiene. El artículo se sigue citando: cambia la explicación,
--             no el derecho.
--   oculto    no aparece en el panel del colaborador.
--
-- POR QUÉ NO SE OCULTA NADA POR OMISIÓN. Los derechos laborales son
-- irrenunciables (Constitución, Art. 326 núm. 2). Un sistema de la empresa
-- que esconde el artículo que favorece al trabajador no elimina el derecho:
-- elimina la prueba de que la empresa lo informó, y eso la deja peor parada
-- que la discusión que quería evitar. Así que esta migración NO cambia lo que
-- hoy se ve: los tres modos quedan disponibles y todos los artículos siguen
-- en «completo». Quien decide es Talento Humano, desde Configuración, con el
-- cambio quedando en la bitácora.
--
-- Lo que sí se deja preparado es el resumen de los cuatro artículos del
-- panel, redactado para que no haga falta escribirlo en la reunión.
--
-- LA CONSECUENCIA OPERATIVA NO SE OCULTA NUNCA. «Tres días vencen el 30 de
-- junio» se sigue diciendo aunque el Art. 75 esté oculto: lo que se puede
-- callar es la cita de la norma, no el hecho que la persona necesita para
-- actuar. Por eso la cita viaja ahora como un dato aparte y la pantalla la
-- añade solo si está permitida, en vez de llevarla escrita en el código.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

alter table public.legal_references
  add column if not exists visibilidad      text,
  add column if not exists resumen          text,
  add column if not exists visibilidad_en   timestamptz,
  add column if not exists visibilidad_por  uuid references public.users(id) on delete set null;

update public.legal_references set visibilidad = 'completo' where visibilidad is null;

alter table public.legal_references
  alter column visibilidad set default 'completo',
  alter column visibilidad set not null;

do $$
begin
  if not exists (select 1 from pg_constraint where conname = 'legal_visibilidad_valida') then
    alter table public.legal_references
      add constraint legal_visibilidad_valida
      check (visibilidad in ('completo','resumen','oculto'));
  end if;
  -- Elegir «resumen» sin haberlo escrito dejaría el artículo en blanco, que
  -- es peor que cualquiera de los tres modos.
  if not exists (select 1 from pg_constraint where conname = 'legal_resumen_si_resume') then
    alter table public.legal_references
      add constraint legal_resumen_si_resume
      check (visibilidad <> 'resumen' or coalesce(btrim(resumen), '') <> '');
  end if;
end $$;

comment on column public.legal_references.visibilidad is
  'completo = texto literal; resumen = la línea llana de resumen; oculto = no se muestra al colaborador.';
comment on column public.legal_references.resumen is
  'Explicación en lenguaje llano que Talento Humano sostiene. Obligatoria para usar el modo resumen.';

-- ------------------------------------------------- los resúmenes de los cuatro
-- Redactados para decir la verdad completa en una línea: el derecho y su
-- límite juntos, que es exactamente lo que falta cuando se cita el artículo
-- suelto y empieza la discusión.
update public.legal_references set resumen =
  'Le corresponden quince días de descanso por cada año cumplido. Desde el sexto año se suma un día por año, hasta treinta días en total.'
 where codigo = 'CT_ART_69' and resumen is null;

update public.legal_references set resumen =
  'Si un año no alcanza a tomar sus vacaciones, no las pierde: puede acumularlas hasta tres años. Pasado ese plazo la empresa está obligada a programarlas, y por eso Talento Humano puede fijarle las fechas.'
 where codigo = 'CT_ART_75' and resumen is null;

update public.legal_references set resumen =
  'Las vacaciones que no llegó a tomar no se pierden: se pagan al liquidar la relación de trabajo. No son dinero que se pueda pedir en lugar del descanso mientras sigue trabajando.'
 where codigo = 'CT_ART_76' and resumen is null;

update public.legal_references set resumen =
  'Las fechas se acuerdan con su jefe inmediato dentro del año siguiente al que generó el derecho. La empresa puede ajustarlas por necesidad del servicio.'
 where codigo = 'CT_ART_73' and resumen is null;

update public.legal_references set resumen =
  'La empresa puede postergar sus vacaciones por necesidad del servicio, pero no puede dejarlas sin fecha: queda obligada a concederlas.'
 where codigo = 'CT_ART_74' and resumen is null;

-- ------------------------------------------------------------ qué ve el panel
-- Una sola función responde «¿qué artículos, y con qué texto?» para que
-- ninguna pantalla vuelva a decidirlo por su cuenta.
create or replace function public.base_legal_visible(p_codigos text[])
returns table (codigo text, norma text, articulo text, titulo text,
               texto text, modo text)
language sql
stable
set search_path = public
as $$
  select l.codigo, l.norma, l.articulo, l.titulo,
         case when l.visibilidad = 'resumen' then l.resumen else l.texto end,
         l.visibilidad
    from public.legal_references l
   where l.codigo = any(p_codigos)
     and l.visibilidad <> 'oculto'
   order by l.orden
$$;

comment on function public.base_legal_visible(text[]) is
  'Los artículos que el colaborador puede ver, con el texto que corresponde a su modo. Los ocultos no salen.';

-- ------------------------------------------- se puede citar el artículo o no
create or replace function public.puede_citar(p_codigo text)
returns boolean
language sql
stable
set search_path = public
as $$
  select coalesce((select l.visibilidad <> 'oculto'
                     from public.legal_references l where l.codigo = p_codigo), true)
$$;

comment on function public.puede_citar(text) is
  'Falso solo si el artículo está oculto. La consecuencia operativa se dice siempre; lo que se calla es la cita.';

-- --------------------------------------- el panel pregunta, ya no decide solo
-- Se reemplaza explicar_saldo_base DESDE SU DEFINICIÓN VIVA (la que dejó la
-- 0041), cambiando solo cuatro cosas: de dónde sale la base legal, las dos
-- citas que estaban escritas dentro del texto de cada período, y un campo
-- nuevo «citar» para que la pantalla no las lleve escritas tampoco.
CREATE OR REPLACE FUNCTION public.explicar_saldo_base(p_user_id uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
declare
  v_u        record;
  v_anios    int;
  v_periodos jsonb;
  v_legal    jsonb;
  v_prox     record;
  -- La cita del artículo se resuelve una vez y se pega donde hace falta. Si
  -- Talento Humano ocultó el artículo, queda en blanco: el hecho se sigue
  -- diciendo, la cita no.
  v_cita_69  text;
  v_cita_75  text;
begin
  select id, nombre, fecha_ingreso, dias_vacaciones into v_u
  from public.users where id = p_user_id;

  if v_u.id is null then
    return jsonb_build_object('error', 'Usuario no encontrado');
  end if;

  v_anios := public.anios_cumplidos(v_u.fecha_ingreso);
  v_cita_69 := case when public.puede_citar('CT_ART_69') then ' (Art. 69 CT)' else '' end;
  v_cita_75 := case when public.puede_citar('CT_ART_75') then ' (Art. 75 CT)' else '' end;

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
             when p.caducado then format('Caducó el %s por acumulación mayor a %s años%s.',
                                         to_char(p.vence_en,'DD/MM/YYYY'),
                                         public.cfg_int('acumulacion_max_anios'), v_cita_75)
             when p.periodo < public.cfg_int('vacaciones_anio_dia_extra')
               then format('Año %s de servicio: %s días base%s.',
                           p.periodo, p.dias_asignados, v_cita_69)
             else format('Año %s de servicio: %s días base + %s día(s) por antigüedad%s.',
                         p.periodo, public.cfg_int('vacaciones_dias_base'),
                         p.dias_asignados - public.cfg_int('vacaciones_dias_base'), v_cita_69)
           end)
         order by p.periodo)
    into v_periodos
  from public.vacation_periods p where p.user_id = p_user_id;

  select p.periodo, p.vence_en, p.dias_saldo into v_prox
  from public.vacation_periods p
  where p.user_id = p_user_id and not p.caducado and p.dias_saldo > 0
  order by p.vence_en limit 1;

  -- Antes se leía la tabla y se imprimía el texto literal. Ahora lo decide
  -- base_legal_visible: devuelve el resumen cuando el artículo está en modo
  -- resumen y no devuelve nada cuando está oculto.
  select jsonb_agg(jsonb_build_object(
           'codigo', b.codigo, 'norma', b.norma, 'articulo', b.articulo,
           'titulo', b.titulo, 'texto', b.texto, 'modo', b.modo))
    into v_legal
  from public.base_legal_visible(
         array['CT_ART_69','CT_ART_75','CT_ART_73','CT_ART_74']) b;

  return jsonb_build_object(
    'empleado',        v_u.nombre,
    'fecha_ingreso',   v_u.fecha_ingreso,
    'anios_servicio',  v_anios,
    'saldo_total',     v_u.dias_vacaciones,
    -- El PERÍODO EN CURSO, no los años ya cumplidos. Quien lleva 7 años
    -- cumplidos está cursando su período 8, y ese período vale 18 días, no
    -- 17. Se calculaba con los años cumplidos y la línea «a este año le
    -- tocan N días» quedaba un día por debajo de lo que el propio sistema
    -- asigna al cerrar el período. El saldo nunca estuvo mal —el año en
    -- curso devenga sobre la base de 15—; lo que estaba mal era lo que se
    -- le decía a la persona que va a recibir.
    'dias_por_anio_actual', public.dias_por_antiguedad(greatest(v_anios, 0) + 1),
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
    -- Para que la pantalla no lleve «(Art. 75)» escrito en el código.
    'citar',           jsonb_build_object('art_69', v_cita_69 <> '', 'art_75', v_cita_75 <> ''),
    'base_legal',      coalesce(v_legal, '[]'::jsonb)
  );
end;
$function$

;

-- ---------------------------------------- una sola puerta para el colaborador
-- Tres pantallas más citan artículos: el catálogo de tipos de permiso, las
-- notificaciones y el glosario. Si el interruptor solo funcionara en el panel
-- de saldo sería un adorno. Esta vista aplica el modo una vez y las tres se
-- cuelgan de ella; un artículo oculto simplemente no tiene fila, así que el
-- left join de cada consulta devuelve nulo y la pantalla ya sabe qué hacer
-- con eso. Las pantallas de administración siguen leyendo la tabla: quien
-- configura tiene que poder ver lo que está configurando.
create or replace view public.v_legal_colaborador as
select l.codigo, l.norma, l.articulo, l.titulo, l.categoria, l.orden,
       case when l.visibilidad = 'resumen' then l.resumen else l.texto end as texto,
       l.visibilidad as modo
  from public.legal_references l
 where l.visibilidad <> 'oculto';

comment on view public.v_legal_colaborador is
  'Los artículos tal como los puede leer el colaborador. Los ocultos no tienen fila.';

grant select on public.v_legal_colaborador to authenticated, anon;
