-- ---------------------------------------------------------------------------
-- 0030 · Los lineamientos los escribe Talento Humano, y buscar sin tildes.
--
-- DOS COSAS QUE ESTABAN EN EL CÓDIGO Y NO DEBÍAN.
--
-- La primera: el recuadro «Antes de enviar, tenga presente» que ve quien pide
-- vacaciones o un permiso estaba escrito dentro del HTML. Son reglas internas
-- de la empresa —cuántos días de anticipación, si el período se toma entero—
-- y cambian por una circular, no por una versión del sistema. Quien las
-- decide es Talento Humano, así que quien las escribe también.
--
-- La segunda: buscar «Suarez» no encontraba a «Suárez». Con trescientas
-- cincuenta personas y una tilde de por medio, un buscador que exige escribir
-- el acento no lo usa nadie.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. Texto comparable, sin tildes
--
-- Con `translate` y no con la extensión `unaccent`: esta va en la misma
-- migración que todo lo demás y no depende de que el administrador de la
-- base habilite nada. Cubre lo que hay en nombres ecuatorianos.
-- =========================================================================

create or replace function public.sin_tildes(p_texto text)
returns text
language sql
immutable
parallel safe
as $st$
  select translate(
    coalesce(p_texto, ''),
    'áàäâãÁÀÄÂÃéèëêÉÈËÊíìïîÍÌÏÎóòöôõÓÒÖÔÕúùüûÚÙÜÛñÑçÇ',
    'aaaaaAAAAAeeeeEEEEiiiiIIIIoooooOOOOOuuuuUUUUnNcC');
$st$;

comment on function public.sin_tildes(text) is
  'El mismo texto sin tildes ni diéresis, para buscar «Suarez» y encontrar «Suárez».';

-- Para que la búsqueda por nombre no recorra la planilla entera en cada
-- tecla. Es funcional y sobre la expresión exacta que usa el buscador.
create index if not exists users_nombre_sin_tildes_idx
  on public.users (public.sin_tildes(nombre) text_pattern_ops);

-- =========================================================================
-- B. Los lineamientos de la empresa
--
-- Una tabla y no un parámetro de configuración con el texto dentro: son
-- varias líneas, cada una se enciende y se apaga por separado, y cada una
-- corresponde a un tipo de solicitud distinto.
-- =========================================================================

create table if not exists public.lineamientos_solicitud (
  id             bigint generated always as identity primary key,
  -- A qué formulario pertenece: 'vacacion', 'permiso' o 'ambos'.
  ambito         text not null default 'ambos'
                   check (ambito in ('vacacion', 'permiso', 'ambos')),
  texto          text not null check (length(btrim(texto)) between 5 and 400),
  orden          smallint not null default 100,
  activo         boolean not null default true,
  actualizado_en timestamptz,
  actualizado_por uuid references public.users (id) on delete set null
);

comment on table public.lineamientos_solicitud is
  'Las reglas internas que ve quien va a pedir vacaciones o un permiso. Las escribe Talento Humano: cambian por circular, no por versión del sistema.';

create index if not exists lineamientos_orden_idx
  on public.lineamientos_solicitud (ambito, activo, orden);

alter table public.lineamientos_solicitud enable row level security;
drop policy if exists lineamientos_lectura on public.lineamientos_solicitud;
create policy lineamientos_lectura on public.lineamientos_solicitud
  for select to authenticated using (true);

-- El texto que estaba escrito en el HTML, tal cual. Instalar esto no cambia
-- ni una palabra de lo que el colaborador lee hoy; solo lo saca del código.
insert into public.lineamientos_solicitud (ambito, texto, orden)
select * from (values
  ('vacacion', 'Se proponen 15 días, que es el período completo. La regla es tomarlo entero.', 10),
  ('vacacion', 'Se comunican con 10 días de anticipación, para que su jefe organice la cobertura.', 20),
  ('vacacion', 'Registrar una fecha no significa que estén aprobadas: deciden su jefe y Talento Humano.', 30),
  ('vacacion', 'Los días son calendario: incluyen los fines de semana que caigan dentro.', 40),
  ('vacacion', 'Para un asunto personal de un día, corresponde un permiso, no vacaciones.', 50),
  ('permiso',  'Registrar el permiso no significa que esté aprobado: deciden su jefe y Talento Humano.', 10),
  ('permiso',  'Si el permiso exige respaldo —un certificado médico, por ejemplo—, adjúntelo al pedirlo.', 20)
) as nuevos(ambito, texto, orden)
where not exists (select 1 from public.lineamientos_solicitud);

-- =========================================================================
-- C. Escribirlos
--
-- Una función y no un UPDATE suelto: deja el cambio fechado y firmado, que
-- es lo que permite responder «esto lo cambió quién y cuándo» cuando un
-- colaborador discute una regla.
-- =========================================================================

create or replace function public.lineamiento_guardar(
  p_id     bigint,
  p_por    uuid,
  p_texto  text default null,
  p_ambito text default null,
  p_orden  smallint default null,
  p_activo boolean default null
) returns public.lineamientos_solicitud
language plpgsql
security definer
set search_path = public
as $lg$
declare
  v_fila public.lineamientos_solicitud;
begin
  if p_id is null then
    if p_texto is null or length(btrim(p_texto)) < 5 then
      raise exception 'Escriba el lineamiento: al menos cinco caracteres';
    end if;
    insert into public.lineamientos_solicitud
        (ambito, texto, orden, actualizado_en, actualizado_por)
    values (coalesce(p_ambito, 'ambos'), btrim(p_texto), coalesce(p_orden, 100::smallint),
            now(), p_por)
    returning * into v_fila;
    return v_fila;
  end if;

  update public.lineamientos_solicitud
     set texto           = coalesce(nullif(btrim(p_texto), ''), texto),
         ambito          = coalesce(p_ambito, ambito),
         orden           = coalesce(p_orden, orden),
         activo          = coalesce(p_activo, activo),
         actualizado_en  = now(),
         actualizado_por = p_por
   where id = p_id
   returning * into v_fila;

  if not found then
    raise exception 'Ese lineamiento ya no existe';
  end if;
  return v_fila;
end;
$lg$;

comment on function public.lineamiento_guardar(bigint, uuid, text, text, smallint, boolean) is
  'Crea o cambia un lineamiento. Con identificador nulo, crea.';

drop view if exists public.v_lineamientos;
create view public.v_lineamientos as
  select l.id, l.ambito, l.texto, l.orden, l.activo, l.actualizado_en,
         u.nombre as actualizado_por_nombre
    from public.lineamientos_solicitud l
    left join public.users u on u.id = l.actualizado_por
   order by l.ambito, l.orden, l.id;

grant select on public.v_lineamientos to authenticated;
