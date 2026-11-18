-- ---------------------------------------------------------------------------
-- 0012 · Talento Humano por región, y la firma electrónica deja de ser
--        obligatoria.
--
-- Dos cambios que vienen de cómo trabaja la empresa de verdad:
--
-- 1. Talento Humano no es una persona: es un equipo repartido entre Quito y
--    Guayaquil. Una solicitud de Quito la resuelve mejor quien conoce a esa
--    gente y tiene sus papeles a mano. Se enruta por región y el aviso va al
--    grupo, no a un buzón concreto; cualquier miembro de esa región puede
--    resolverla, de modo que nadie queda esperando a que vuelva de almorzar.
--
-- 2. La firma dibujada era obligatoria en los 22 subtipos. Entrar al sistema
--    ya exige un código enviado al correo institucional: la identidad está
--    confirmada antes de abrir el formulario. Pedir además un garabato con
--    el mouse no agrega prueba y sí fricción. Queda como opción.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. Regiones de atención
-- =========================================================================

create table if not exists public.regiones (
  codigo      text primary key,
  nombre      text not null,
  sede        text not null,
  descripcion text,
  activo      boolean not null default true
);

comment on table public.regiones is
  'Zonas de atención de Talento Humano. Cada solicitud se resuelve en la suya.';

insert into public.regiones (codigo, nombre, sede, descripcion) values
  ('sierra', 'Sierra y Oriente', 'Quito',
   'Pichincha y el resto de la Sierra, más la Amazonía, atendidas desde Quito.'),
  ('costa',  'Costa e Insular',  'Guayaquil',
   'Guayas y el resto de la Costa, más Galápagos, atendidas desde Guayaquil.')
on conflict (codigo) do update
  set nombre = excluded.nombre, sede = excluded.sede,
      descripcion = excluded.descripcion;

-- Mapa de ciudades. Se deja como tabla y no como lista en el código para
-- que Talento Humano pueda agregar una ciudad nueva sin esperar un despliegue.
create table if not exists public.ciudades_region (
  ciudad  text primary key,
  region  text not null references public.regiones(codigo)
);

insert into public.ciudades_region (ciudad, region) values
  -- Sierra
  ('QUITO','sierra'), ('AMBATO','sierra'), ('CUENCA','sierra'), ('LOJA','sierra'),
  ('RIOBAMBA','sierra'), ('IBARRA','sierra'), ('LATACUNGA','sierra'),
  ('TULCAN','sierra'), ('AZOGUES','sierra'), ('GUARANDA','sierra'),
  ('CAYAMBE','sierra'), ('OTAVALO','sierra'), ('SANGOLQUI','sierra'),
  ('MACHACHI','sierra'), ('ALAUSI','sierra'), ('SALCEDO','sierra'),
  ('PELILEO','sierra'), ('PILLARO','sierra'), ('CAÑAR','sierra'),
  -- Oriente, atendido desde Quito
  ('TENA','sierra'), ('PUYO','sierra'), ('MACAS','sierra'), ('ZAMORA','sierra'),
  ('NUEVA LOJA','sierra'), ('LAGO AGRIO','sierra'), ('COCA','sierra'),
  ('EL COCA','sierra'), ('SUCUA','sierra'),
  -- Costa
  ('GUAYAQUIL','costa'), ('MACHALA','costa'), ('PORTOVIEJO','costa'),
  ('MANTA','costa'), ('ESMERALDAS','costa'), ('BABAHOYO','costa'),
  ('QUEVEDO','costa'), ('MILAGRO','costa'), ('DURAN','costa'),
  ('DAULE','costa'), ('SAMBORONDON','costa'), ('SALINAS','costa'),
  ('SANTA ELENA','costa'), ('LA LIBERTAD','costa'), ('PLAYAS','costa'),
  ('SANTO DOMINGO','costa'), ('CHONE','costa'), ('JIPIJAPA','costa'),
  ('VENTANAS','costa'), ('EL TRIUNFO','costa'), ('NARANJAL','costa'),
  ('PASAJE','costa'), ('HUAQUILLAS','costa'), ('BAHIA DE CARAQUEZ','costa'),
  -- Insular, atendido desde Guayaquil
  ('PUERTO AYORA','costa'), ('PUERTO BAQUERIZO MORENO','costa'), ('GALAPAGOS','costa')
on conflict (ciudad) do update set region = excluded.region;

alter table public.regiones enable row level security;
alter table public.ciudades_region enable row level security;

drop policy if exists regiones_lectura on public.regiones;
create policy regiones_lectura on public.regiones
  for select to authenticated using (true);

drop policy if exists ciudades_region_lectura on public.ciudades_region;
create policy ciudades_region_lectura on public.ciudades_region
  for select to authenticated using (true);

grant select on public.regiones, public.ciudades_region to authenticated;

-- =========================================================================
-- B. Cada persona y cada solicitud saben a qué región pertenecen
-- =========================================================================

-- Pequeño auxiliar: quitar tildes sin depender de la extensión `unaccent`,
-- que en Supabase no siempre está habilitada.
create or replace function public.unaccent_simple(p_texto text)
returns text
language sql
immutable
as $ua$
  select translate(coalesce(p_texto, ''),
                   'áéíóúÁÉÍÓÚàèìòùÀÈÌÒÙäëïöüÄËÏÖÜñÑ',
                   'aeiouAEIOUaeiouAEIOUaeiouAEIOUnN');
$ua$;

create or replace function public.region_de_ciudad(p_ciudad text)
returns text
language sql
stable
as $reg$
  -- Si la ciudad no está en el mapa, se atiende desde Quito: es la sede
  -- administrativa. Mejor que dejar la solicitud sin destinatario.
  select coalesce(
    (select c.region from public.ciudades_region c
      where c.ciudad = upper(unaccent_simple(btrim(coalesce(p_ciudad, ''))))),
    'sierra');
$reg$;

alter table public.users
  add column if not exists region text references public.regiones(codigo);

comment on column public.users.region is
  'Región que atiende sus solicitudes. Se deduce de la ciudad; Talento Humano puede fijarla a mano.';

create index if not exists users_region_rol_idx on public.users (region, rol) where activo;

-- Se completa la región de quien ya está cargado.
update public.users
   set region = public.region_de_ciudad(ciudad)
 where region is null;

-- Y se mantiene al día cuando cambia la ciudad.
create or replace function public.tg_users_region()
returns trigger
language plpgsql
as $tgr$
begin
  if new.region is null or new.ciudad is distinct from old.ciudad then
    new.region := public.region_de_ciudad(new.ciudad);
  end if;
  return new;
end;
$tgr$;

drop trigger if exists users_region on public.users;
create trigger users_region
  before insert or update of ciudad, region on public.users
  for each row execute function public.tg_users_region();

-- La solicitud guarda su región al nacer: si la persona se traslada después,
-- la solicitud sigue en manos de quien la venía atendiendo.
alter table public.requests add column if not exists region text;

create index if not exists requests_region_estado_idx
  on public.requests (region, estado);

create or replace function public.tg_requests_region()
returns trigger
language plpgsql
as $tgrr$
begin
  if new.region is null then
    select coalesce(u.region, public.region_de_ciudad(u.ciudad))
      into new.region
      from public.users u where u.id = new.user_id;
  end if;
  return new;
end;
$tgrr$;

drop trigger if exists requests_region on public.requests;
create trigger requests_region
  before insert on public.requests
  for each row execute function public.tg_requests_region();

update public.requests r
   set region = coalesce(u.region, 'sierra')
  from public.users u
 where u.id = r.user_id and r.region is null;

-- =========================================================================
-- C. La firma electrónica deja de ser obligatoria
--
-- Para entrar hay que recibir un código en el correo institucional: la
-- identidad ya está probada cuando se abre el formulario. Exigir además un
-- trazo con el mouse no aporta prueba y sí fricción —y en un teléfono, con
-- el dedo, bastante—. La columna se conserva: si algún día un permiso
-- concreto la amerita, Talento Humano la activa desde Administración.
-- =========================================================================

update public.permission_types set requiere_firma = false where requiere_firma;

comment on column public.permission_types.requiere_firma is
  'Exigir firma dibujada. Falso por omisión: el acceso por código al correo ya acredita la identidad. Talento Humano puede activarlo para un subtipo concreto.';

insert into public.app_config (clave, valor, descripcion) values
  ('firma_obligatoria', 'false',
   'Si es verdadero, toda solicitud exige la firma dibujada además del acceso por código')
on conflict (clave) do update set descripcion = excluded.descripcion;

-- =========================================================================
-- D. Quién atiende cada solicitud
-- =========================================================================

create or replace view public.v_rrhh_por_region as
select u.id, u.nombre, u.email, u.cedula, u.cargo, u.ciudad,
       coalesce(u.region, 'sierra') as region,
       r.nombre as region_nombre, r.sede
  from public.users u
  join public.regiones r on r.codigo = coalesce(u.region, 'sierra')
 where u.activo and u.rol in ('rrhh', 'admin') and not u.correo_pendiente;

comment on view public.v_rrhh_por_region is
  'Personal de Talento Humano que puede resolver solicitudes de cada región. El aviso va al grupo: cualquiera de ellos puede decidir.';

grant select on public.v_rrhh_por_region to authenticated;

create or replace function public.rrhh_de_region(p_region text)
returns setof public.v_rrhh_por_region
language sql
stable
as $rr$
  -- Si la región no tiene a nadie —vacaciones, una sede nueva— responde
  -- todo el equipo: es preferible que llegue de más a que no llegue.
  select * from public.v_rrhh_por_region
   where region = coalesce(p_region, 'sierra')
  union all
  select * from public.v_rrhh_por_region
   where not exists (select 1 from public.v_rrhh_por_region
                      where region = coalesce(p_region, 'sierra'));
$rr$;
