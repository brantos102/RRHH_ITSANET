-- ---------------------------------------------------------------------------
-- 0033 · Los fines de semana obligatorios dejan de pedir lo imposible.
--
-- El Art. 69 dice que los quince días de vacaciones son calendario e incluyen
-- los no laborables, así que dentro de un período completo caen dos fines de
-- semana. El sistema lleva la cuenta para que nadie tome solo los laborables
-- y deje los sábados y domingos «para después», que es como una persona
-- termina debiendo cuatro días que ya descansó.
--
-- El contador arrancó en cero para todo el mundo, y ahí estaba el disparate:
-- 784 períodos GOZADOS POR COMPLETO seguían pidiendo dos fines de semana cada
-- uno. Son 1.568 avisos sobre días que la persona ya tomó, por aritmética:
-- quien gozó los quince días de un período tomó los dos fines de semana que
-- caen dentro; no hay otra forma de gastar quince días seguidos.
--
-- CUATRO SITUACIONES, Y SOLO UNA PIDE ALGO:
--
--   cumplido      El período se gozó entero. Los fines de semana se dan por
--                 tomados, sin que nadie confirme nada.
--   por_confirmar Se gozó una parte. Aquí sí cabe la duda de si los fines de
--                 semana estaban dentro, y solo Talento Humano puede
--                 resolverla.
--   sin_gozar     No se tomó ni un día. Mal puede deberse un fin de semana de
--                 unas vacaciones que no han empezado.
--   en_curso      El año todavía corre.
--
-- Pedir confirmación en las tres últimas es pedirle a alguien que declare
-- algo que no ha pasado. Un aviso que no se puede atender enseña a ignorar
-- los avisos.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. La situación de cada período
-- =========================================================================

create or replace function public.situacion_fines_semana(
  p_devengado  boolean,
  p_asignados  numeric,
  p_consumidos numeric
) returns text
language sql
immutable
as $sfs$
  select case
    when not p_devengado          then 'en_curso'
    when p_consumidos <= 0        then 'sin_gozar'
    when p_consumidos >= p_asignados then 'cumplido'
    else 'por_confirmar'
  end;
$sfs$;

comment on function public.situacion_fines_semana(boolean, numeric, numeric) is
  'En qué situación están los fines de semana obligatorios de un período. Solo «por_confirmar» pide algo a alguien.';

-- =========================================================================
-- B. Un período gozado por completo trae sus fines de semana dentro
--
-- No es una suposición: quince días seguidos contienen dos fines de semana
-- por calendario. Lo que se corrige es que el sistema lo pedía igual.
-- =========================================================================

create or replace function public.cerrar_fines_semana_si_completo()
returns trigger
language plpgsql
as $cfs$
begin
  if new.devengado
     and new.dias_consumidos >= new.dias_asignados
     and new.dias_asignados > 0
     and new.fines_semana_consumidos < new.fines_semana_obligatorios then
    new.fines_semana_consumidos := new.fines_semana_obligatorios;
  end if;
  return new;
end;
$cfs$;

drop trigger if exists periodos_fines_semana_completos on public.vacation_periods;
create trigger periodos_fines_semana_completos
  before insert or update on public.vacation_periods
  for each row execute function public.cerrar_fines_semana_si_completo();

-- La misma regla, aplicada a lo que ya estaba guardado.
update public.vacation_periods
   set fines_semana_consumidos = fines_semana_obligatorios
 where devengado
   and dias_asignados > 0
   and dias_consumidos >= dias_asignados
   and fines_semana_consumidos < fines_semana_obligatorios;

-- =========================================================================
-- C. Lo que queda pendiente de verdad
--
-- Antes contaba el primer período no caducado, cualquiera que fuese su
-- situación. Ahora cuenta solo lo que alguien puede resolver.
-- =========================================================================

create or replace function public.fines_semana_pendientes(p_user_id uuid)
returns integer
language sql
stable
as $fsp$
  select coalesce(sum(greatest(0, p.fines_semana_obligatorios - p.fines_semana_consumidos)), 0)::int
    from public.vacation_periods p
   where p.user_id = p_user_id
     and not p.caducado
     and public.situacion_fines_semana(p.devengado, p.dias_asignados, p.dias_consumidos)
         = 'por_confirmar';
$fsp$;

comment on function public.fines_semana_pendientes(uuid) is
  'Fines de semana obligatorios que alguien todavía puede confirmar: solo los de períodos gozados a medias. Un período completo los trae dentro y uno sin empezar no los puede deber.';

-- =========================================================================
-- D. Para verlo y para explicarlo
-- =========================================================================

drop view if exists public.v_fines_semana;
create view public.v_fines_semana as
select p.user_id, u.cedula, u.nombre, u.departamento,
       p.periodo, p.fecha_desde, p.fecha_hasta,
       p.dias_asignados, p.dias_consumidos, p.dias_saldo,
       p.fines_semana_obligatorios, p.fines_semana_consumidos,
       public.situacion_fines_semana(p.devengado, p.dias_asignados, p.dias_consumidos)
         as situacion,
       case public.situacion_fines_semana(p.devengado, p.dias_asignados, p.dias_consumidos)
         when 'cumplido'      then 'Gozó el período completo: los fines de semana van dentro'
         when 'sin_gozar'     then 'No ha tomado días de este período todavía'
         when 'en_curso'      then 'El año todavía corre'
         else 'Gozó una parte: Talento Humano confirma si los fines de semana estaban dentro'
       end as explicacion
  from public.vacation_periods p
  join public.users u on u.id = p.user_id
 where not p.caducado and u.activo;

comment on view public.v_fines_semana is
  'Los fines de semana obligatorios período a período, con la situación de cada uno y por qué.';

grant select on public.v_fines_semana to authenticated;
