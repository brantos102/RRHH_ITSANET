-- ---------------------------------------------------------------------------
-- 0037 · El departamento de Talento Humano, y fuera la firma dibujada.
--
-- DOS COSAS, y las dos venían de lo mismo: el sistema sabía quién tiene rol
-- de Talento Humano, pero no tenía un «departamento de Talento Humano».
--
-- A. EL CORREO DEL DEPARTAMENTO
--
--    Los avisos iban solo a los buzones personales de quienes tienen el rol.
--    Eso falla de una forma concreta y silenciosa: la persona sale de
--    vacaciones, cambia de puesto o se va de la empresa, y las solicitudes
--    siguen llegando a un buzón que nadie abre. Nadie se entera, porque un
--    correo que no se lee no produce ningún error.
--
--    Ahora existe un correo del departamento —uno por región— que recibe
--    TODO en copia. Los buzones personales siguen recibiendo: esto suma un
--    destinatario, no reemplaza a ninguno.
--
-- B. LA FIRMA DIBUJADA, FUERA
--
--    Se pedía dibujar la firma con el mouse para «firmar» la solicitud. No
--    aporta nada que no aporte ya el acceso con cédula y código de un solo
--    uso al correo institucional —que es más fuerte, porque exige poseer el
--    correo—, y en cambio frenaba al operario en el último paso con una
--    casilla en rojo: «aún no registra su firma».
--
--    Ningún tipo de permiso la exigía. Se retira la obligación, el bloque de
--    la pantalla y el parámetro; los datos ya registrados no se tocan.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A1. El correo del departamento, por región
-- =========================================================================

insert into public.app_config (clave, valor, descripcion) values
  ('rrhh_correo_sierra', '',
   'Correo del departamento de Talento Humano en la Sierra (Quito). Recibe copia de todo lo que se dirige al departamento. En blanco, solo reciben los buzones personales.'),
  ('rrhh_correo_costa', '',
   'Correo del departamento de Talento Humano en la Costa (Guayaquil). Recibe copia de todo lo que se dirige al departamento. En blanco, solo reciben los buzones personales.')
on conflict (clave) do nothing;


create or replace function public.cfg_texto(p_clave text)
returns text
language sql
stable
security definer
set search_path = public
as $$
  select nullif(btrim(valor), '') from public.app_config where clave = p_clave;
$$;

comment on function public.cfg_texto(text) is
  'El valor de un parámetro como texto; nulo si está vacío o no existe.';


create or replace function public.rrhh_correo_de_region(p_region text)
returns text
language sql
stable
security definer
set search_path = public
as $$
  select public.cfg_texto(
    case when coalesce(p_region, 'sierra') = 'costa'
         then 'rrhh_correo_costa' else 'rrhh_correo_sierra' end);
$$;

comment on function public.rrhh_correo_de_region(text) is
  'El buzón del departamento en esa región, o nulo si todavía no se ha configurado.';


-- =========================================================================
-- A2. Quiénes son el departamento
--
-- Separado del rol a propósito. El rol dice qué puede hacer alguien; esta
-- vista dice a quién le llega el trabajo. Casi siempre coinciden, pero el
-- administrador del sistema tiene rol de admin sin ser de Talento Humano, y
-- recibir todas las solicitudes del país no le sirve a nadie.
-- =========================================================================

drop view if exists public.v_talento_humano;
create view public.v_talento_humano as
select u.id,
       u.nombre,
       u.email,
       u.rol::text                                   as rol,
       u.cargo,
       coalesce(u.region, 'sierra')                  as region,
       r.nombre                                      as region_nombre,
       r.sede,
       u.activo,
       (u.email is not null
        and not u.correo_pendiente
        and u.email not like '%.test'
        and u.email not like '%.invalid')            as puede_recibir,
       (select count(*) from public.requests q
         where q.estado = 'pendiente_rrhh'
           and coalesce(q.region, 'sierra') = coalesce(u.region, 'sierra')) as esperando_en_su_region
  from public.users u
  left join public.regiones r on r.codigo = coalesce(u.region, 'sierra')
 where u.rol in ('rrhh', 'admin')
 order by coalesce(u.region, 'sierra'), u.nombre;

comment on view public.v_talento_humano is
  'El departamento: quién lo integra, en qué región y si puede recibir los avisos.';

grant select on public.v_talento_humano to authenticated;


-- =========================================================================
-- A3. Alta y baja de un integrante
--
-- La baja importa tanto como el alta: alguien que deja Talento Humano y
-- conserva el rol sigue viendo expedientes de toda su región. Es el tipo de
-- permiso que nadie revisa hasta que hay un problema.
-- =========================================================================

create or replace function public.rrhh_integrar(
  p_persona uuid, p_region text, p_actor uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_persona public.users%rowtype;
  v_region  text := coalesce(nullif(btrim(p_region), ''), 'sierra');
begin
  select * into v_persona from public.users where id = p_persona;
  if not found then
    raise exception 'No se encontró a esa persona.';
  end if;
  if not v_persona.activo then
    raise exception 'La ficha de % está inactiva: primero reactívela.', v_persona.nombre;
  end if;
  if not exists (select 1 from public.regiones where codigo = v_region) then
    raise exception 'La región «%» no existe.', v_region;
  end if;

  if v_persona.rol = 'admin' then
    -- Bajar a un administrador a rrhh le quitaría atribuciones sin avisar.
    update public.users set region = v_region where id = p_persona;
    return jsonb_build_object(
      'id', p_persona, 'nombre', v_persona.nombre, 'cambio', true, 'rol', 'admin',
      'mensaje', format('%s es administrador del sistema y ya ve todo. Se le asignó la región %s.',
                        v_persona.nombre, v_region));
  end if;

  update public.users set rol = 'rrhh', region = v_region where id = p_persona;

  return jsonb_build_object(
    'id', p_persona, 'nombre', v_persona.nombre, 'cambio', v_persona.rol <> 'rrhh',
    'rol', 'rrhh', 'region', v_region,
    'mensaje', format('%s integra Talento Humano en la región %s.', v_persona.nombre, v_region));
end;
$$;

comment on function public.rrhh_integrar(uuid, text, uuid) is
  'Suma a alguien al departamento, en una región. Un administrador conserva su rol.';


create or replace function public.rrhh_retirar(
  p_persona uuid, p_rol_destino public.user_role, p_actor uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_persona public.users%rowtype;
  v_quedan  integer;
  v_destino public.user_role := coalesce(p_rol_destino, 'empleado');
begin
  select * into v_persona from public.users where id = p_persona;
  if not found then
    raise exception 'No se encontró a esa persona.';
  end if;
  if p_persona = p_actor then
    raise exception 'No puede retirarse usted mismo del departamento. Pídaselo a otro administrador.';
  end if;
  if v_destino in ('rrhh', 'admin') then
    raise exception 'El rol de destino seguiría viendo los expedientes: eso no retira a nadie.';
  end if;

  -- Dejar una región sin nadie significa que sus solicitudes no le llegan a
  -- ninguna persona. El correo del departamento no basta: alguien tiene que
  -- poder entrar y resolverlas.
  select count(*) into v_quedan
    from public.v_talento_humano
   where region = coalesce(v_persona.region, 'sierra')
     and id <> p_persona
     and activo;

  if v_quedan = 0 then
    raise exception
      'Es la única persona de Talento Humano en la región %. Integre a alguien más antes de retirarla, o sus solicitudes no le llegarán a nadie.',
      coalesce(v_persona.region, 'sierra');
  end if;

  update public.users set rol = v_destino where id = p_persona;

  return jsonb_build_object(
    'id', p_persona, 'nombre', v_persona.nombre,
    'rol_anterior', v_persona.rol, 'rol_nuevo', v_destino,
    'quedan_en_la_region', v_quedan,
    'mensaje', format('%s deja Talento Humano. Quedan %s persona(s) en la región %s.',
                      v_persona.nombre, v_quedan, coalesce(v_persona.region, 'sierra')));
end;
$$;

comment on function public.rrhh_retirar(uuid, public.user_role, uuid) is
  'Retira a alguien del departamento. Nunca deja una región sin nadie que resuelva.';


-- =========================================================================
-- B. Fuera la firma dibujada
-- =========================================================================

-- Ningún tipo la exigía ya; esto lo deja escrito y no reversible por olvido.
update public.permission_types set requiere_firma = false where requiere_firma;

-- El bloque de la pantalla principal: ya no existe en la interfaz, así que
-- dejarlo configurable sería ofrecer encender algo que no se dibuja.
delete from public.panel_bloques where clave = 'firma';

-- El parámetro, con su descripción corregida: queda como constancia de que
-- se retiró a propósito, no como un interruptor que alguien pueda volver a
-- subir esperando que haga algo.
update public.app_config
   set valor = 'false',
       descripcion = 'RETIRADO. La firma dibujada se quitó del sistema: el acceso con '
                     'cédula y código de un solo uso al correo institucional identifica '
                     'mejor a quien solicita. Este parámetro ya no tiene efecto.'
 where clave = 'firma_obligatoria';

grant execute on function public.cfg_texto(text) to authenticated;
grant execute on function public.rrhh_correo_de_region(text) to authenticated;
