-- ---------------------------------------------------------------------------
-- 0028 · El devengo del año en curso, como lo calcula Talento Humano.
--
-- El sistema y la hoja daban cifras distintas para la misma persona. Para
-- Espinosa Pascal: la hoja 83,75 días devengados y el sistema 84,33. La
-- diferencia no es un redondeo ni un error de captura, y conviene decir
-- exactamente dónde está porque de ahí sale la decisión.
--
-- LOS DOS CÁLCULOS COINCIDEN EXACTAMENTE EN CADA ANIVERSARIO. Difieren solo
-- dentro del año en marcha, y solo para quien lleva más de cinco años:
--
--   La hoja acumula 1,25 días por mes —quince partido para doce— todo el
--   año, y suma los días adicionales del Art. 69 enteros, el día en que la
--   persona cumple el año.
--
--   El sistema prorrateaba también los días adicionales: a quien ya tenía
--   derecho a 27 días anuales le acumulaba 27/12 = 2,25 por mes.
--
-- En la planilla: 283 personas con menos de cinco años tenían CERO
-- diferencia, y 68 con cinco o más iban de 0 a 11 días por encima de la
-- hoja, 187,42 días en total.
--
-- POR QUÉ SE ADOPTA EL DE LA HOJA. El Art. 69 concede el día adicional a
-- quien «hubiere prestado servicios por más de cinco años»: el derecho nace
-- al cumplir el año, no se va ganando dentro de él. Prorratearlo mostraba a
-- mitad de año una fracción de un día que la persona todavía no ha
-- adquirido. No quitaba nada a nadie —iba por delante del derecho, no por
-- detrás—, pero la cifra que ve el colaborador debe ser la que le pueden
-- confirmar en Talento Humano, y la que Talento Humano lleva es esta.
--
-- EL SALDO NO SE MUEVE. Esto cambia cómo se calcula lo devengado del año en
-- curso, no lo ya devengado de años cumplidos ni lo gozado. Los períodos
-- cerrados siguen valiendo `dias_por_antiguedad`, con sus días adicionales
-- completos.
--
-- Queda un parámetro para volver atrás sin otra migración, por si la empresa
-- decide adoptar el prorrateo: `vacaciones_extra_prorrateado`.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

insert into public.app_config (clave, valor, descripcion)
values ('vacaciones_extra_prorrateado', 'false',
        'Si los días adicionales por antigüedad (Art. 69) se acumulan mes a mes dentro del año en curso. En falso —como lo lleva Talento Humano— el año en curso acumula solo la parte base (1,25 días al mes) y los adicionales se conceden enteros al cumplir el año.')
on conflict (clave) do nothing;

-- Un ayudante propio y no `cfg_int`: el parámetro es un sí o un no, y
-- leerlo como entero convertiría cualquier cosa que no sea número en un
-- error de ejecución en medio del cálculo del saldo. Ante la duda, falso:
-- el cálculo que la empresa ya lleva.
create or replace function public.cfg_bool(p_clave text)
returns boolean
language sql
stable
as $cb$
  select coalesce((select lower(btrim(valor)) = 'true'
                     from public.app_config where clave = p_clave), false);
$cb$;

comment on function public.cfg_bool(text) is
  'Un parámetro de configuración leído como sí o no. Si falta o trae otra cosa, falso.';

-- =========================================================================
-- El devengo del período en curso
--
-- Se conserva todo lo demás de la función original: el acotado a doce meses
-- para que un período vencido sin renovar no acumule de más, y el redondeo
-- a dos decimales.
-- =========================================================================

create or replace function public.dias_devengados_en_curso(
  p_ingreso date,
  p_periodo int
) returns numeric
language sql
stable
as $ddc$
  -- Meses completos transcurridos dentro del período en curso, por la parte
  -- diaria que corresponde. Se acota a doce para que un período vencido sin
  -- renovar no acumule de más.
  --
  -- La parte diaria es la base —1,25 al mes— y no el tope del período, que
  -- incluiría los días adicionales del Art. 69. Esos se conceden enteros al
  -- cumplir el año, que es cuando nace el derecho, y así lo lleva Talento
  -- Humano en su hoja desde hace años.
  select round(
    case when public.cfg_bool('vacaciones_extra_prorrateado')
         then public.dias_por_antiguedad(p_periodo)
         else public.cfg_int('vacaciones_dias_base')::numeric
    end *
    least(
      greatest(
        (extract(year  from age(current_date, (p_ingreso + make_interval(years => p_periodo - 1))::date)) * 12
         + extract(month from age(current_date, (p_ingreso + make_interval(years => p_periodo - 1))::date))),
        0),
      12) / 12.0,
    2)::numeric;
$ddc$;

comment on function public.dias_devengados_en_curso(date, int) is
  'Días acumulados dentro del año de vacaciones en marcha, a razón de 1,25 al mes (Art. 69, quince días partidos para doce). Los días adicionales por antigüedad no se prorratean: se conceden enteros al cumplir el año.';

-- =========================================================================
-- Para poder cotejarlo con la hoja, persona por persona
--
-- Sin una vista así, «el sistema dice otra cosa» es una discusión sin
-- pruebas. Con ella, cada cifra se explica con los meses y la fórmula que
-- la produjeron.
-- =========================================================================

drop view if exists public.v_devengo_cotejo;
create view public.v_devengo_cotejo as
with base as (
  select u.id as user_id, u.cedula, u.nombre, u.departamento, u.fecha_ingreso,
         public.anios_cumplidos(u.fecha_ingreso)     as anios_cumplidos,
         public.anios_cumplidos(u.fecha_ingreso) + 1 as periodo_en_curso
    from public.users u
   where u.activo
)
select b.*,
       least(greatest(
         extract(year  from age(current_date, (b.fecha_ingreso + make_interval(years => b.periodo_en_curso - 1))::date)) * 12
       + extract(month from age(current_date, (b.fecha_ingreso + make_interval(years => b.periodo_en_curso - 1))::date)), 0), 12)::int
         as meses_del_periodo,
       public.dias_por_antiguedad(b.periodo_en_curso) as tope_anual_del_periodo,
       public.dias_devengados_en_curso(b.fecha_ingreso, b.periodo_en_curso) as devengado_hoja,
       round(public.dias_por_antiguedad(b.periodo_en_curso) *
             least(greatest(
               extract(year  from age(current_date, (b.fecha_ingreso + make_interval(years => b.periodo_en_curso - 1))::date)) * 12
             + extract(month from age(current_date, (b.fecha_ingreso + make_interval(years => b.periodo_en_curso - 1))::date)), 0), 12) / 12.0, 2)
         as devengado_prorrateado,
       (select coalesce(sum(p.dias_asignados), 0) from public.vacation_periods p
         where p.user_id = b.user_id and p.devengado and not p.caducado) as devengado_de_anios_cumplidos
  from base b;

comment on view public.v_devengo_cotejo is
  'Los dos cálculos del año en curso, lado a lado, con los meses que los producen. Para cotejar con la hoja de Talento Humano.';

grant select on public.v_devengo_cotejo to authenticated;
