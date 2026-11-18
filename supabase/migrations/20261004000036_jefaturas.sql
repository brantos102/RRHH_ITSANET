-- ---------------------------------------------------------------------------
-- 0036 · Agregar y quitar jefaturas sin dejar gente colgando.
--
-- Hasta ahora una jefatura se creaba y se deshacía cambiando el rol en la
-- pantalla de usuarios: un UPDATE suelto sobre `users.rol`. Crear así está
-- bien; deshacer así, no. Quitarle el rol de jefe a alguien que tiene gente
-- a cargo deja tres cosas rotas y ninguna se ve:
--
--   · Sus colaboradores siguen apuntando a él en `users.jefe_id`, pero él ya
--     no tiene permiso para aprobarles nada.
--   · Las solicitudes que estaban esperando su visto bueno se quedan ahí,
--     dirigidas a alguien que ya no puede resolverlas.
--   · El colaborador no ve ningún error. Pide vacaciones, y su pedido no le
--     llega a nadie.
--
-- En la planilla real esto no es hipotético: hay una jefatura con setenta y
-- cuatro personas a cargo y otra con cincuenta. Quitar una de esas dos con un
-- clic dejaría a ciento veinticuatro personas sin a quién pedirle permiso.
--
-- Así que aquí la baja de una jefatura es una sola operación con un
-- destinatario obligatorio: a quién pasan las personas y los pendientes.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. Alta de una jefatura
--
-- Es lo simple: alguien pasa a tener gente a cargo. No se toca nada más —ni
-- su ficha, ni su jefe, ni su saldo—, solo el rol con el que entra.
-- =========================================================================

create or replace function public.jefatura_crear(p_persona uuid, p_actor uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_persona public.users%rowtype;
begin
  select * into v_persona from public.users where id = p_persona;
  if not found then
    raise exception 'No se encontró a esa persona.';
  end if;
  if not v_persona.activo then
    raise exception 'La ficha de % está inactiva: primero reactívela.', v_persona.nombre;
  end if;

  -- Talento Humano y administración ya aprueban por su rol. Convertirlos en
  -- «jefe» les quitaría atribuciones en vez de dárselas.
  if v_persona.rol in ('rrhh', 'admin') then
    return jsonb_build_object(
      'id', p_persona, 'nombre', v_persona.nombre, 'cambio', false,
      'mensaje', format('%s ya aprueba por su rol de %s. No hace falta nombrarlo jefe.',
                        v_persona.nombre, v_persona.rol));
  end if;

  if v_persona.rol = 'jefe' then
    return jsonb_build_object(
      'id', p_persona, 'nombre', v_persona.nombre, 'cambio', false,
      'mensaje', format('%s ya es jefatura.', v_persona.nombre));
  end if;

  update public.users set rol = 'jefe' where id = p_persona;

  return jsonb_build_object(
    'id', p_persona, 'nombre', v_persona.nombre, 'cambio', true,
    'rol_anterior', v_persona.rol,
    'mensaje', format('%s queda como jefatura. Asígnele su gente desde la ficha de cada uno.',
                      v_persona.nombre));
end;
$$;

comment on function public.jefatura_crear(uuid, uuid) is
  'Nombra jefatura a una persona. No mueve a nadie: asignar quién le reporta es otro paso.';


-- =========================================================================
-- B. Baja de una jefatura
--
-- `p_nuevo_jefe` es obligatorio cuando hay gente a cargo. No hay forma de
-- llamar a esto y dejar a alguien sin jefe: o no había nadie, o se dice a
-- quién pasa.
--
-- El orden importa. Primero se mueve la gente y los pendientes, y solo
-- después se le cambia el rol: si algo falla, la transacción entera se
-- deshace y la jefatura sigue en pie con su gente.
-- =========================================================================

create or replace function public.jefatura_quitar(
  p_jefe        uuid,
  p_nuevo_jefe  uuid,
  p_rol_destino public.user_role,
  p_actor       uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_jefe    public.users%rowtype;
  v_nuevo   public.users%rowtype;
  v_a_cargo integer;
  v_movidos integer := 0;
  v_pendientes integer := 0;
begin
  select * into v_jefe from public.users where id = p_jefe;
  if not found then
    raise exception 'No se encontró a esa persona.';
  end if;

  if p_jefe = p_actor then
    raise exception 'No puede quitarse su propia jefatura. Pídaselo a otro administrador.';
  end if;

  if coalesce(p_rol_destino, 'empleado') = 'jefe' then
    raise exception 'El rol de destino no puede seguir siendo jefe: eso no quita nada.';
  end if;

  select count(*) into v_a_cargo
    from public.users s where s.jefe_id = p_jefe and s.activo;

  if v_a_cargo > 0 and p_nuevo_jefe is null then
    raise exception
      '% tiene % persona(s) a cargo. Indique a qué jefatura pasan antes de quitarle el mando.',
      v_jefe.nombre, v_a_cargo;
  end if;

  if p_nuevo_jefe is not null then
    if p_nuevo_jefe = p_jefe then
      raise exception 'La jefatura de destino no puede ser la misma que se está quitando.';
    end if;
    select * into v_nuevo from public.users where id = p_nuevo_jefe;
    if not found or not v_nuevo.activo then
      raise exception 'La jefatura de destino no existe o está inactiva.';
    end if;
    if v_nuevo.rol not in ('jefe', 'rrhh', 'admin') then
      raise exception '% no puede recibir gente a cargo: no es jefatura.', v_nuevo.nombre;
    end if;

    -- Si el receptor le reportaba a quien pierde el mando, no puede quedar
    -- reportándose a sí mismo: hereda el jefe que tenía su antiguo superior.
    if v_nuevo.jefe_id = p_jefe then
      update public.users
         set jefe_id = case when v_jefe.jefe_id = p_nuevo_jefe then null else v_jefe.jefe_id end
       where id = p_nuevo_jefe;
    end if;

    update public.users set jefe_id = p_nuevo_jefe
     where jefe_id = p_jefe and id <> p_nuevo_jefe;
    get diagnostics v_movidos = row_count;

    -- Lo que estaba esperando su firma pasa con la gente. Sin esto el
    -- colaborador ve su solicitud «pendiente del jefe» para siempre.
    update public.requests set jefe_id = p_nuevo_jefe
     where jefe_id = p_jefe and estado = 'pendiente_jefe';
    get diagnostics v_pendientes = row_count;
  end if;

  update public.users set rol = coalesce(p_rol_destino, 'empleado') where id = p_jefe;

  return jsonb_build_object(
    'id', p_jefe,
    'nombre', v_jefe.nombre,
    'rol_anterior', v_jefe.rol,
    'rol_nuevo', coalesce(p_rol_destino, 'empleado'),
    'nuevo_jefe', p_nuevo_jefe,
    'nuevo_jefe_nombre', v_nuevo.nombre,
    'personas_movidas', v_movidos,
    'solicitudes_movidas', v_pendientes,
    'mensaje', case
      when p_nuevo_jefe is null then
        format('%s deja de ser jefatura. No tenía gente a cargo.', v_jefe.nombre)
      else
        format('%s deja de ser jefatura. %s persona(s) y %s solicitud(es) pendiente(s) pasaron a %s.',
               v_jefe.nombre, v_movidos, v_pendientes, v_nuevo.nombre)
    end);
end;
$$;

comment on function public.jefatura_quitar(uuid, uuid, public.user_role, uuid) is
  'Quita el mando y traslada en el mismo movimiento a su gente y a sus solicitudes pendientes.';


-- =========================================================================
-- C. La lista con la que se decide
--
-- Cuánta gente tiene cada uno, cuánto le está esperando y si puede entrar al
-- sistema. Sin cédula ni correo de terceros: para decidir una jefatura no
-- hace falta (LOPDP, Art. 10).
-- =========================================================================

drop view if exists public.v_jefaturas_admin;
create view public.v_jefaturas_admin as
select u.id,
       u.nombre,
       u.rol::text                         as rol,
       u.cargo,
       u.departamento,
       coalesce(u.region, 'sierra')        as region,
       (select count(*) from public.users s
         where s.jefe_id = u.id and s.activo)                     as a_cargo,
       (select count(*) from public.requests r
         where r.jefe_id = u.id and r.estado = 'pendiente_jefe')  as esperando,
       (u.email is not null and u.email not like '%.test'
                            and u.email not like '%.invalid')     as puede_entrar,
       j.nombre                            as reporta_a
  from public.users u
  left join public.users j on j.id = u.jefe_id
 where u.activo
   and (u.rol in ('jefe', 'rrhh', 'admin')
        or exists (select 1 from public.users s where s.jefe_id = u.id and s.activo))
 order by u.nombre;

comment on view public.v_jefaturas_admin is
  'Las jefaturas vigentes con su carga: gente a cargo, pendientes por firmar y si puede entrar.';

grant select on public.v_jefaturas_admin to authenticated;
