-- ---------------------------------------------------------------------------
-- 0040 · Cómo terminó la relación laboral.
--
-- Hasta ahora una baja era `activo = false` y una fecha. Eso basta para que
-- la persona deje de entrar al sistema, y no basta para nada más: la causa
-- de la terminación decide qué se liquida y qué no, y es lo primero que
-- pregunta cualquiera que revise el expediente —una auditoría, el
-- Ministerio del Trabajo, o el propio ex colaborador que reclama—.
--
-- Las causas son las del Código del Trabajo del Ecuador. No se inventa
-- ninguna: cada una cita el artículo que la sustenta, porque de eso depende
-- lo que corresponde pagar.
--
-- Las vacaciones no gozadas se pagan SIEMPRE, cualquiera sea la causa
-- (Art. 76). Eso no cambia aquí; se recuerda en el comentario porque es la
-- confusión más común al dar una baja por despido.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

do $$
begin
  if not exists (select 1 from pg_type where typname = 'motivo_salida') then
    create type public.motivo_salida as enum (
      'renuncia',                 -- Art. 169 núm. 2 · voluntaria del trabajador
      'despido_intempestivo',     -- Art. 188 · indemnización por despido
      'visto_bueno_empleador',    -- Art. 172 · causas imputables al trabajador
      'visto_bueno_trabajador',   -- Art. 173 · causas imputables al empleador
      'desahucio',                -- Art. 184 · aviso de terminación
      'fin_de_contrato',          -- Art. 169 núm. 3 · plazo o obra concluida
      'mutuo_acuerdo',            -- Art. 169 núm. 2
      'jubilacion',               -- Art. 188 y siguientes
      'fallecimiento',            -- Art. 169 núm. 1
      'otro'
    );
  end if;
end$$;

alter table public.users
  add column if not exists motivo_salida public.motivo_salida,
  add column if not exists detalle_salida text,
  add column if not exists salida_registrada_por uuid references public.users(id),
  add column if not exists salida_registrada_en timestamptz;

comment on column public.users.motivo_salida is
  'Causa de terminación según el Código del Trabajo. Las vacaciones no gozadas se pagan en todos los casos (Art. 76).';
comment on column public.users.detalle_salida is
  'Lo que no cabe en la causa: el número de acta, la fecha del visto bueno, el detalle del acuerdo.';

-- Una baja sin causa deja el expediente sin lo primero que se pregunta.
-- NOT VALID: las bajas ya registradas no se tocan.
alter table public.users drop constraint if exists users_salida_con_motivo;
alter table public.users
  add constraint users_salida_con_motivo
  check (activo or fecha_salida is null or motivo_salida is not null) not valid;


-- =========================================================================
-- Dar de baja, en una sola operación y con constancia
-- =========================================================================

create or replace function public.dar_de_baja(
  p_persona uuid,
  p_fecha   date,
  p_motivo  public.motivo_salida,
  p_detalle text,
  p_actor   uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_persona   public.users%rowtype;
  v_a_cargo   integer;
  v_pendientes integer;
  v_saldo     numeric;
begin
  select * into v_persona from public.users where id = p_persona;
  if not found then
    raise exception 'No se encontró a esa persona.';
  end if;
  if p_persona = p_actor then
    raise exception 'No puede darse de baja usted mismo. Pídaselo a otro administrador.';
  end if;
  if p_motivo is null then
    raise exception 'Indique cómo terminó la relación laboral: es lo primero que se pregunta al revisar un expediente.';
  end if;
  if p_fecha > current_date + 1 then
    raise exception 'La fecha de salida no puede ser futura.';
  end if;

  -- Lo que queda abierto a su nombre. No se impide la baja —la persona ya
  -- se fue y el expediente tiene que reflejarlo—, pero se devuelve para que
  -- Talento Humano lo resuelva en vez de descubrirlo semanas después.
  select count(*) into v_a_cargo
    from public.users s where s.jefe_id = p_persona and s.activo;
  select count(*) into v_pendientes
    from public.requests r
   where r.user_id = p_persona and r.estado in ('pendiente_jefe', 'pendiente_rrhh');
  select coalesce(sum(dias_saldo), 0) into v_saldo
    from public.vacation_periods where user_id = p_persona and not caducado;

  update public.users
     set activo = false,
         fecha_salida = p_fecha,
         motivo_salida = p_motivo,
         detalle_salida = nullif(btrim(coalesce(p_detalle, '')), ''),
         salida_registrada_por = p_actor,
         salida_registrada_en = now()
   where id = p_persona;

  return jsonb_build_object(
    'id', p_persona,
    'nombre', v_persona.nombre,
    'motivo', p_motivo,
    'fecha_salida', p_fecha,
    'personas_a_cargo', v_a_cargo,
    'solicitudes_pendientes', v_pendientes,
    'dias_por_liquidar', round(v_saldo, 2),
    'mensaje', format(
      '%s queda dado de baja el %s. Las vacaciones no gozadas se pagan (Art. 76): %s día(s) por liquidar.',
      v_persona.nombre, to_char(p_fecha, 'DD/MM/YYYY'), round(v_saldo, 2)));
end;
$$;

comment on function public.dar_de_baja(uuid, date, public.motivo_salida, text, uuid) is
  'Da de baja con causa y devuelve lo que queda abierto a su nombre: gente a cargo, solicitudes en trámite y días por liquidar.';


drop view if exists public.v_salidas;
create view public.v_salidas as
select u.id, u.cedula, u.nombre, u.cargo, u.departamento,
       u.fecha_ingreso, u.fecha_salida,
       u.motivo_salida::text as motivo,
       u.detalle_salida,
       q.nombre as registrada_por,
       u.salida_registrada_en,
       public.anios_cumplidos(u.fecha_ingreso) as anios_servicio,
       (select coalesce(sum(p.dias_saldo), 0) from public.vacation_periods p
         where p.user_id = u.id and not p.caducado) as dias_por_liquidar
  from public.users u
  left join public.users q on q.id = u.salida_registrada_por
 where not u.activo and u.fecha_salida is not null
 order by u.fecha_salida desc;

comment on view public.v_salidas is
  'Quiénes salieron, cuándo, por qué y con cuántos días por liquidar (Art. 76).';

grant select on public.v_salidas to authenticated;
