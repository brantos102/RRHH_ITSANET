-- ---------------------------------------------------------------------------
-- 0027 · Qué se muestra en la pantalla principal, y quién lo decide.
--
-- El panel del colaborador se fue llenando de bloques —saldo, antigüedad,
-- fines de semana, calendario del equipo, firma, logros, solicitudes— y todos
-- se muestran siempre a todo el mundo. No todas las empresas quieren lo
-- mismo en la primera pantalla: hay quien no usa firma electrónica, quien no
-- quiere el calendario del equipo a la vista de todos, y quien necesita
-- poner un aviso arriba durante una semana.
--
-- Hasta ahora eso se cambiaba tocando el HTML. Un sistema oficial no se
-- administra editando archivos: se administra desde una pantalla, deja
-- constancia de quién cambió qué y se puede deshacer.
--
-- TRES REGLAS QUE EL MÓDULO NO DEJA ROMPER:
--
--   1. Hay bloques que no se pueden ocultar. El saldo, los botones para
--      pedir y la lista de solicitudes son la razón por la que alguien entra.
--      Un administrador que los apague por error deja a 350 personas con una
--      pantalla en blanco y sin forma de pedir vacaciones. La base lo
--      rechaza; no depende de que la pantalla se acuerde de impedirlo.
--
--   2. Ocultar un bloque no borra nada. Es una decisión de presentación: el
--      dato sigue estando, se sigue calculando y se sigue pudiendo consultar
--      por su propia pantalla. Apagar «Ausencias del equipo» no cancela
--      ninguna ausencia.
--
--   3. Si esta configuración no se puede leer, el panel se muestra entero.
--      Una falla en lo accesorio no puede dejar sin panel a nadie. Eso se
--      resuelve en el frontend, pero se decide aquí y por eso se dice aquí.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. Los bloques
--
-- La clave la escribe el frontend en `data-bloque`. Es el contrato entre
-- esta tabla y el HTML: si se renombra aquí, deja de encontrarse allá.
-- =========================================================================

create table if not exists public.panel_bloques (
  clave          text primary key,
  titulo         text not null,
  -- Para el administrador, no para el colaborador: qué es este bloque y qué
  -- se pierde de vista al apagarlo. Sin esto, la pantalla de configuración
  -- es una lista de interruptores sin nombre.
  descripcion    text not null,
  visible        boolean not null default true,
  orden          smallint not null,
  -- Vacío significa «todos los roles». Es lo más común y así no hay que
  -- enumerar los cinco cada vez.
  roles          public.user_role[] not null default '{}',
  -- Un bloque esencial se puede reordenar, pero no apagar.
  esencial       boolean not null default false,
  -- Solo lo usa el bloque de aviso: el texto que el administrador escribe.
  cuerpo         text,
  actualizado_en timestamptz,
  actualizado_por uuid references public.users (id) on delete set null,
  constraint panel_esencial_siempre_visible
    check (not (esencial and not visible)),
  constraint panel_orden_valido check (orden between 0 and 999)
);

comment on table public.panel_bloques is
  'Qué bloques se ven en la pantalla principal del colaborador, en qué orden y para qué roles. Ocultar un bloque no borra ningún dato.';

create index if not exists panel_bloques_orden_idx
  on public.panel_bloques (visible, orden);

alter table public.panel_bloques enable row level security;
drop policy if exists panel_bloques_lectura on public.panel_bloques;
-- Todos pueden leer la configuración de su propia pantalla. No hay nada
-- personal aquí: son nombres de bloques.
create policy panel_bloques_lectura on public.panel_bloques
  for select to authenticated using (true);

-- =========================================================================
-- B. El inventario inicial
--
-- Es exactamente lo que el panel muestra hoy, en el orden en que hoy se ve.
-- Instalar esta migración no cambia ni una pantalla: solo hace configurable
-- lo que ya estaba. Que la primera versión no cambie nada es a propósito;
-- así, si algo se ve distinto después, la causa es un cambio que alguien
-- hizo a conciencia y no la migración.
--
-- `on conflict do nothing`: al reaplicarla no se pisa lo que el
-- administrador haya configurado.
-- =========================================================================

insert into public.panel_bloques (clave, titulo, descripcion, orden, esencial, roles) values
  ('anuncio', 'Aviso de la empresa',
   'Un mensaje que usted escribe y aparece arriba de todo. Sirve para comunicados cortos: cierre por feriado, plazo para pedir vacaciones, cambio de horario. Vacío, no se muestra.',
   5, false, '{}'),
  ('alertas', 'Avisos del sistema',
   'Los que genera el sistema: días por vencer, solicitudes por corregir, datos por confirmar. Son de cada persona y no todos los ven.',
   10, false, '{}'),
  ('saldo', 'Días disponibles',
   'La cifra grande de vacaciones con su explicación. Es la razón por la que la mayoría entra al sistema.',
   20, true, '{}'),
  ('antiguedad', 'Antigüedad',
   'Años y meses en la empresa, y la fecha de ingreso.',
   30, false, '{}'),
  ('fines_semana', 'Fines de semana obligatorios',
   'Cuántos fines de semana completos le faltan por consumir en su período de vacaciones.',
   40, false, '{}'),
  ('acciones', 'Botones para solicitar',
   'Solicitar vacaciones y solicitar permiso. Sin esto nadie puede pedir nada desde el panel.',
   50, true, '{}'),
  ('calendario', 'Ausencias del equipo',
   'El calendario de quién está fuera y cuándo. Útil para no dejar el puesto descubierto; puede reservarlo a jefatura si prefiere que no lo vea todo el personal.',
   60, false, '{}'),
  ('firma', 'Mi firma electrónica',
   'Registrar o cambiar la firma con la que se firman las solicitudes. Si la empresa no usa firma, apáguelo.',
   70, false, '{}'),
  ('logros', 'Mis logros',
   'Reconocimientos del colaborador. Se muestra solo a quien tiene alguno.',
   80, false, '{}'),
  ('solicitudes', 'Mis solicitudes',
   'El historial propio con su estado. Es donde la persona sigue lo que pidió.',
   90, true, '{}')
on conflict (clave) do nothing;

-- =========================================================================
-- C. Cambiarlo
--
-- Una sola función y no un UPDATE suelto: así el rechazo de apagar un bloque
-- esencial dice por qué en palabras, y el cambio queda fechado y firmado.
-- =========================================================================

create or replace function public.panel_configurar(
  p_clave   text,
  p_por     uuid,
  p_visible boolean default null,
  p_orden   smallint default null,
  p_roles   public.user_role[] default null,
  p_cuerpo  text default null
) returns public.panel_bloques
language plpgsql
security definer
set search_path = public
as $pc$
declare
  v_bloque public.panel_bloques;
begin
  select * into v_bloque from public.panel_bloques where clave = p_clave;
  if not found then
    raise exception 'No existe el bloque «%» en la pantalla principal', p_clave;
  end if;

  if p_visible is false and v_bloque.esencial then
    raise exception '«%» no se puede ocultar: es lo que la gente viene a ver. '
                    'Puede moverlo de sitio, no apagarlo.', v_bloque.titulo;
  end if;

  update public.panel_bloques
     set visible         = coalesce(p_visible, visible),
         orden           = coalesce(p_orden, orden),
         roles           = coalesce(p_roles, roles),
         -- El cuerpo se limpia a cadena vacía para poder borrarlo: un
         -- coalesce puro dejaría el aviso viejo colgado para siempre.
         cuerpo          = case when p_cuerpo is null then cuerpo
                                else nullif(btrim(p_cuerpo), '') end,
         actualizado_en  = now(),
         actualizado_por = p_por
   where clave = p_clave
   returning * into v_bloque;

  return v_bloque;
end;
$pc$;

comment on function public.panel_configurar(text, uuid, boolean, smallint, public.user_role[], text) is
  'Cambia un bloque de la pantalla principal. Rechaza ocultar los esenciales.';

-- =========================================================================
-- D. Lo que le toca ver a cada quien
--
-- El frontend no debe decidir esto: si le mandamos la lista entera con un
-- «no mires estos», basta con abrir las herramientas del navegador para ver
-- lo que se quiso esconder. Se filtra aquí y viaja ya filtrado.
-- =========================================================================

create or replace function public.panel_de(p_user_id uuid)
returns table (
  clave  text,
  titulo text,
  orden  smallint,
  cuerpo text
)
language sql
stable
security definer
set search_path = public
as $pd$
  select b.clave, b.titulo, b.orden, b.cuerpo
    from public.panel_bloques b
    join public.users u on u.id = p_user_id
   where b.visible
     and (cardinality(b.roles) = 0 or u.rol = any (b.roles))
     -- Un aviso sin texto no es un aviso: es un recuadro vacío.
     and (b.clave <> 'anuncio' or nullif(btrim(coalesce(b.cuerpo, '')), '') is not null)
   order by b.orden, b.clave;
$pd$;

comment on function public.panel_de(uuid) is
  'Los bloques que esta persona debe ver en su pantalla principal, ya filtrados por rol.';

-- =========================================================================
-- E. Para la pantalla del administrador
-- =========================================================================

drop view if exists public.v_panel_configuracion;
create view public.v_panel_configuracion as
  select b.clave, b.titulo, b.descripcion, b.visible, b.orden, b.esencial,
         b.roles, b.cuerpo, b.actualizado_en,
         u.nombre as actualizado_por_nombre,
         cardinality(b.roles) = 0 as para_todos
    from public.panel_bloques b
    left join public.users u on u.id = b.actualizado_por
   order by b.orden, b.clave;

comment on view public.v_panel_configuracion is
  'Los bloques de la pantalla principal con quién los cambió por última vez.';
