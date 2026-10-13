-- ---------------------------------------------------------------------------
-- 0008 · Lineamientos de vacaciones de ITSANET, tabla de antigüedad,
--        permisos por horas y subtipo de respaldo por pilar.
--
-- Fuentes: los dos comunicados internos («Proyección de vacaciones» y
-- «Lineamientos para la solicitud de vacaciones») y la tabla de días por
-- años laborados. Se cargan como datos consultables, no como comentarios:
-- el sistema tiene que poder mostrarle al colaborador la regla que le
-- están aplicando, igual que hace con los artículos del Código del Trabajo.
--
-- Idempotente. Cada sentencia es independiente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. Tabla de antigüedad de la empresa
--
-- Publicada por Talento Humano: por años laborados, cuántos días se gozan,
-- cuántos son laborables y cuántos no laborables (fines de semana) van
-- incluidos. Confirma algo que conviene tener explícito: los días de
-- vacaciones son CALENDARIO, con los fines de semana dentro.
-- =========================================================================

create table if not exists public.antiguedad_referencia (
  anios_desde      smallint primary key,
  anios_hasta      smallint,
  dias_gozar       smallint not null,
  dias_laborables  smallint not null,
  dias_no_laborables smallint not null,
  nota             text,
  constraint antiguedad_suma_coherente
    check (dias_laborables + dias_no_laborables = dias_gozar)
);

comment on table public.antiguedad_referencia is
  'Tabla oficial de ITSANET: días de vacaciones por años laborados, con el desglose entre laborables y no laborables. Los días son calendario.';

insert into public.antiguedad_referencia
  (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables) values
  (1,  5,  15, 11, 4),
  (6,  6,  16, 12, 4),
  (7,  7,  17, 13, 4),
  (8,  8,  18, 14, 4),
  (9,  9,  19, 15, 4),
  (10, 10, 20, 15, 5),
  (11, 11, 21, 15, 6),
  (12, 12, 22, 16, 6),
  (13, 13, 23, 17, 6),
  (14, 14, 24, 18, 6),
  (15, 15, 25, 19, 6),
  (16, 16, 26, 20, 6),
  (17, 17, 27, 20, 7),
  (18, 18, 28, 20, 8),
  (19, 19, 29, 21, 8),
  (20, null, 30, 22, 8)
on conflict (anios_desde) do update
  set anios_hasta = excluded.anios_hasta,
      dias_gozar = excluded.dias_gozar,
      dias_laborables = excluded.dias_laborables,
      dias_no_laborables = excluded.dias_no_laborables;

alter table public.antiguedad_referencia enable row level security;

drop policy if exists antiguedad_referencia_lectura on public.antiguedad_referencia;
create policy antiguedad_referencia_lectura on public.antiguedad_referencia
  for select to authenticated using (true);

grant select on public.antiguedad_referencia to authenticated;

create or replace view public.v_antiguedad_referencia as
select anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables,
       case when anios_hasta is null then anios_desde::text || ' años o más'
            when anios_hasta = anios_desde then anios_desde::text || ' años'
            else anios_desde::text || '-' || anios_hasta::text || ' años'
       end as rango
  from public.antiguedad_referencia
 order by anios_desde;

grant select on public.v_antiguedad_referencia to authenticated;

-- =========================================================================
-- B. Lineamientos internos de ITSANET
--
-- Van en `legal_references` junto a los artículos del Código del Trabajo:
-- al colaborador le da igual si la regla viene de la ley o de la empresa,
-- lo que necesita es saber por qué le responden lo que le responden. La
-- categoría distingue el origen.
-- =========================================================================

insert into public.legal_references (codigo, norma, articulo, titulo, texto, categoria, orden) values
  ('ITSANET_ANTICIPACION', 'Lineamientos internos ITSANET', 'Lineamiento 1',
   'Anticipación mínima',
   'Las vacaciones deberán ser comunicadas con mínimo 10 días de anticipación, para que la jefatura pueda organizar la cobertura del puesto.',
   'vacaciones', 300),

  ('ITSANET_APROBACION', 'Lineamientos internos ITSANET', 'Lineamiento 2',
   'Aprobación previa',
   'Toda vacación debe ser planificada y aprobada previamente por la jefatura inmediata y Talento Humano. Registrar una fecha no significa que las vacaciones estén aprobadas.',
   'vacaciones', 310),

  ('ITSANET_DISPONIBILIDAD', 'Lineamientos internos ITSANET', 'Lineamiento 3',
   'Disponibilidad de días',
   'Antes de confirmar las vacaciones se debe consultar con Talento Humano la disponibilidad de días del colaborador.',
   'vacaciones', 320),

  ('ITSANET_ANULACION', 'Lineamientos internos ITSANET', 'Lineamiento 4',
   'Anulación o modificación',
   'Las vacaciones aprobadas podrán ser modificadas o anuladas únicamente por una necesidad operativa debidamente justificada y previa coordinación con Talento Humano.',
   'vacaciones', 330),

  ('ITSANET_ASUNTOS_PERSONALES', 'Lineamientos internos ITSANET', 'Lineamiento 5',
   'Asuntos personales',
   'Los asuntos personales no se registran como vacaciones sino como permiso. Para esos casos corresponde gestionar el permiso respectivo.',
   'permisos', 340),

  ('ITSANET_PROYECCION', 'Lineamientos internos ITSANET', 'Comunicado de proyección',
   'Las fechas proyectadas son tentativas',
   'Las fechas registradas en la proyección son tentativas y están sujetas a revisión y confirmación según las necesidades de la compañía. La programación considera la operación y demanda del servicio, la disponibilidad de reemplazos, la continuidad de las operaciones y las necesidades de cada área.',
   'vacaciones', 350),

  ('ITSANET_BLOQUE', 'Lineamientos internos ITSANET', 'Política de bloques',
   'Las vacaciones se toman en bloques',
   'La regla general es tomar el período completo que corresponde por antigüedad. El bloque mínimo aceptado es de 7 días seguidos. Solicitar menos es una excepción que exige justificación documentada y la autoriza Talento Humano antes que la jefatura.',
   'vacaciones', 360),

  ('ITSANET_ADELANTO', 'Lineamientos internos ITSANET', 'Política de adelanto',
   'Adelanto de días no devengados',
   'Quien no tenga días disponibles puede solicitar un adelanto, pero ese camino lo autoriza primero Talento Humano: implica comprometer días que aún no se han generado.',
   'vacaciones', 370)
on conflict (codigo) do update
  set norma = excluded.norma, articulo = excluded.articulo,
      titulo = excluded.titulo, texto = excluded.texto,
      categoria = excluded.categoria, orden = excluded.orden;

-- Parámetros que el administrador puede ajustar sin tocar código.
insert into public.app_config (clave, valor, descripcion) values
  ('vacaciones_anticipacion_dias', '10',
   'Días de anticipación mínimos para solicitar vacaciones (Lineamiento 1)')
on conflict (clave) do update set descripcion = excluded.descripcion;

insert into public.app_config (clave, valor, descripcion) values
  ('vacaciones_bloque_sugerido', '15',
   'Días que se proponen por omisión al solicitar vacaciones: el período completo')
on conflict (clave) do update set descripcion = excluded.descripcion;

-- =========================================================================
-- C. Un subtipo de respaldo en cada pilar
--
-- Ninguna lista de categorías cubre la realidad. Sin una salida, quien
-- tiene un motivo legítimo que no encaja termina eligiendo mal el subtipo
-- —y el dato queda sucio para siempre— o no pidiendo el permiso. «Otros»
-- exige descripción detallada y respaldo, de modo que quien decide tenga
-- con qué, y permite a Talento Humano detectar categorías que faltan.
-- =========================================================================

insert into public.permission_types
  (codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion,
   remunerado, legal_ref, orden)
values
  ('otro_salud', 'Otro motivo de salud',
   'Atención de salud que no encaja en los anteriores', true, true, true, 'CT_ART_42_9', 90),
  ('otro_personal', 'Otro asunto personal',
   'Obligación o trámite que no encaja en los anteriores', true, true, true, 'CT_ART_42_29', 190)
on conflict (codigo) do nothing;

update public.permission_types t set category_id = c.id
  from public.permission_categories c
 where c.codigo = 'cita_medica' and t.codigo = 'otro_salud';

update public.permission_types t set category_id = c.id
  from public.permission_categories c
 where c.codigo = 'permiso_personal' and t.codigo = 'otro_personal';

update public.permission_types set
  guia_ejemplo = 'Ej.: Debo someterme a un examen de laboratorio en ayunas en el laboratorio de la av. Shyris. Me presento a las 07:00 y calculo estar en la oficina a las 10:00. No encontré una categoría que lo describa.',
  guia_adjuntos = 'Adjunte la orden médica, el turno o el documento que respalde la atención. Al ser un motivo fuera de las categorías, el respaldo pesa más.'
where codigo = 'otro_salud';

update public.permission_types set
  guia_ejemplo = 'Ej.: Debo asistir a la lectura de un testamento en la notaría tercera de la av. Amazonas el martes 12 a las 09:00. Es la única fecha fijada por el notario y calculo 3 horas.',
  guia_adjuntos = 'Adjunte la convocatoria, la notificación o el documento que respalde el compromiso. Al ser un motivo fuera de las categorías, el respaldo pesa más.'
where codigo = 'otro_personal';

-- «Otra calamidad doméstica» ya existía desde la migración anterior y cumple
-- el mismo papel en su pilar. Se ordena al final, como los otros dos.
update public.permission_types set orden = 39 where codigo = 'calamidad_domestica';

-- =========================================================================
-- D. Permisos por horas dentro de un mismo día
--
-- Es el caso más frecuente y el que peor estaba resuelto: una cita médica
-- a las 13:00 no es «un día de permiso», son tres horas. Se marca qué
-- subtipos admiten esa modalidad para que el formulario la ofrezca, y se
-- guarda cuánto tiempo conviene reservar antes y después de la cita.
-- =========================================================================

alter table public.permission_types
  add column if not exists admite_horas boolean not null default false;
alter table public.permission_types
  add column if not exists horas_antes numeric(3,1) not null default 1;
alter table public.permission_types
  add column if not exists horas_despues numeric(3,1) not null default 2;

comment on column public.permission_types.admite_horas is
  'El permiso puede pedirse por horas dentro de un mismo día, no solo por días completos.';
comment on column public.permission_types.horas_antes is
  'Horas que se sugiere reservar antes de la hora del compromiso (traslado, espera).';

-- Lo que razonablemente se resuelve en horas.
update public.permission_types set admite_horas = true
 where codigo in ('cita_medica', 'acompanamiento_medico', 'donacion_sangre',
                  'cuidado_discapacidad', 'lactancia', 'citacion_judicial',
                  'tramite_gobierno', 'sufragio', 'estudios', 'permiso_personal',
                  'otro_salud', 'otro_personal', 'emergencia_medica');

-- Lo que por su naturaleza ocupa el día o más: reposo, licencias, duelo.
update public.permission_types set admite_horas = false
 where codigo in ('enfermedad', 'maternidad', 'paternidad', 'fallecimiento_familiar',
                  'enfermedad_familiar', 'siniestro_domicilio', 'caso_fortuito',
                  'matrimonio', 'calamidad_domestica');

-- Un trámite en una entidad pública rara vez toma menos de media jornada.
update public.permission_types set horas_antes = 1, horas_despues = 3
 where codigo in ('tramite_gobierno', 'citacion_judicial');

-- Donar sangre exige reposo posterior.
update public.permission_types set horas_antes = 0.5, horas_despues = 3
 where codigo = 'donacion_sangre';

-- =========================================================================
-- E. Anticipación y adelanto de días no devengados
--
-- Lineamiento 1: mínimo 10 días de anticipación, para que la jefatura
-- alcance a organizar la cobertura. No es un capricho administrativo: es
-- lo que permite que el reemplazo exista.
--
-- Y el adelanto —pedir días que todavía no se generan— sigue el mismo
-- camino que la excepción al bloque mínimo: lo autoriza Talento Humano
-- antes que la jefatura, porque compromete días que aún no existen.
-- =========================================================================

create or replace function public.tg_requests_ruta_aprobacion()
returns trigger
language plpgsql
as $ruta$
declare
  v_minimo       numeric;
  v_anticipacion integer;
  v_calendario   integer;
  v_dias_aviso   integer;
begin
  new.ruta_aprobacion := 'estandar';

  if new.tipo = 'vacacion' then
    select coalesce(nullif(valor, '')::numeric, 0) into v_minimo
      from public.app_config where clave = 'vacaciones_bloque_minimo';

    select coalesce(nullif(valor, '')::integer, 0) into v_anticipacion
      from public.app_config where clave = 'vacaciones_anticipacion_dias';

    -- El mínimo se mide en días de AUSENCIA, no en los que se descuentan
    -- del saldo. Un feriado dentro del rango no acorta el descanso: la
    -- persona igual está fuera. Medirlo contra `dias_solicitados` —que
    -- excluye feriados— hacía imposible tomar la semana de Navidad.
    v_calendario := (new.fecha_fin - new.fecha_inicio) + 1;
    v_dias_aviso := new.fecha_inicio - current_date;

    if coalesce(v_anticipacion, 0) > 0 and v_dias_aviso < v_anticipacion
       and not new.bloque_menor_justificado then
      raise exception
        'Las vacaciones se comunican con % días de anticipación y usted avisa con % (Lineamiento 1 de Talento Humano). Su jefe necesita ese tiempo para organizar quién cubre el puesto. Si el caso no admite espera, márquelo como excepción y explíquelo.',
        v_anticipacion, greatest(v_dias_aviso, 0)
        using errcode = 'P0001', hint = 'anticipacion|' || v_anticipacion::text;
    end if;

    if coalesce(v_minimo, 0) > 0 and v_calendario < v_minimo then
      if not new.bloque_menor_justificado then
        raise exception
          'Las vacaciones se toman en bloques de al menos % días seguidos y usted pidió %. Si su caso lo amerita, márquelo como excepción, explique el motivo y adjunte el respaldo: la autoriza Talento Humano, no su jefe.',
          v_minimo, v_calendario
          using errcode = 'P0001', hint = 'bloque_minimo|' || v_minimo::text;
      end if;

      if length(btrim(coalesce(new.justificacion, ''))) < 30 then
        raise exception
          'Para tomar menos de % días debe justificarlo por escrito, con al menos 30 caracteres: quien autoriza la excepción necesita entender por qué se aparta de la política.',
          v_minimo;
      end if;
    end if;

    -- Apartarse de la política y comprometer días que no existen son las
    -- dos decisiones que no le corresponden a la jefatura inmediata.
    if new.bloque_menor_justificado or new.es_adelanto then
      new.ruta_aprobacion := 'rrhh_primero';
      new.estado := 'pendiente_rrhh';
    end if;
  else
    new.bloque_menor_justificado := false;
  end if;

  return new;
end;
$ruta$;

-- El catálogo que consume el formulario incorpora la modalidad por horas.
drop view if exists public.v_catalogo_permisos;

create view public.v_catalogo_permisos as
select c.id          as categoria_id,
       c.codigo      as categoria_codigo,
       c.nombre      as categoria_nombre,
       c.descripcion as categoria_descripcion,
       c.ayuda       as categoria_ayuda,
       c.orden       as categoria_orden,
       t.id          as tipo_id,
       t.codigo      as tipo_codigo,
       t.nombre      as tipo_nombre,
       t.descripcion as tipo_descripcion,
       t.requiere_adjunto,
       t.requiere_justificacion,
       t.remunerado,
       t.descuenta_vacaciones,
       t.max_dias,
       t.max_horas,
       t.legal_ref,
       t.guia_ejemplo,
       t.guia_adjuntos,
       t.admite_horas,
       t.horas_antes,
       t.horas_despues,
       t.orden       as tipo_orden
  from public.permission_categories c
  join public.permission_types t on t.category_id = c.id
 where c.activo and t.activo;

grant select on public.v_catalogo_permisos to authenticated;


-- =========================================================================
-- F. Corrección: la previsualización fallaba al armar ciertos avisos
--
-- `text[] || 'literal'` es ambiguo: sin tipo, PostgreSQL resuelve el
-- operador como «arreglo || arreglo» e intenta convertir la cadena en un
-- arreglo. «malformed array literal». Solo ocurría en los avisos escritos
-- como literal —los que usan format() devuelven text y funcionaban—, de
-- modo que el fallo aparecía únicamente en ciertos permisos: el que exige
-- firma, el que se descuenta de vacaciones y el de rango sin días.
-- Se añade el tipo explícito.
-- =========================================================================

CREATE OR REPLACE FUNCTION public.previsualizar_solicitud(p_user_id uuid, p_tipo request_type, p_inicio date, p_fin date, p_permission_type_id smallint DEFAULT NULL::smallint)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
AS $function$
declare
  v_dias      numeric;
  v_saldo     numeric;
  v_fds       int;
  v_fds_pend  int;
  v_pt        public.permission_types%rowtype;
  v_sug       date[];
  v_avisos    text[] := '{}';
  v_ok        boolean := true;
  v_desglose  jsonb;
begin
  select dias_vacaciones into v_saldo from public.users where id = p_user_id;
  v_dias     := public.calcular_dias(p_tipo, p_inicio, p_fin);
  v_fds      := public.fines_de_semana_completos(p_inicio, p_fin);
  v_fds_pend := public.fines_semana_pendientes(p_user_id);
  v_sug      := array[p_inicio, p_fin];
  v_desglose := public.desglose_dias(p_tipo, p_inicio, p_fin);

  if v_dias <= 0 then
    v_ok := false;
    v_avisos := v_avisos || 'El rango seleccionado no genera días computables.'::text;
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
      v_avisos := v_avisos || 'Debe seleccionar un tipo de permiso válido.'::text;
    else
      if v_pt.requiere_adjunto then
        v_avisos := v_avisos || format('El permiso "%s" exige adjuntar respaldo.', v_pt.nombre);
      end if;
      if v_pt.requiere_firma then
        v_avisos := v_avisos || 'Debe firmar electrónicamente la solicitud.'::text;
      end if;
      if v_pt.max_dias is not null and v_dias > v_pt.max_dias then
        v_ok := false;
        v_avisos := v_avisos || format('Máximo %s día(s) para este permiso.', v_pt.max_dias);
      end if;
      if v_pt.descuenta_vacaciones then
        v_avisos := v_avisos || 'Este permiso se descuenta de su saldo de vacaciones.'::text;
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
    'avisos',                 to_jsonb(v_avisos),
    'desglose',               v_desglose
  );
end;
$function$
