-- ---------------------------------------------------------------------------
-- 0029 · Que nadie se quede sin forma de entrar.
--
-- El acceso es por código de un solo uso enviado al correo. En la migración
-- 0022 se borraron las 225 direcciones inventadas —`@pendiente.itsanet.local`,
-- que no existen y donde nunca llegó nada— porque un correo falso es peor que
-- ninguno. Fue lo correcto, y abrió un agujero que hay que cerrar aquí.
--
-- Quien no tiene correo entra por «primer ingreso»: prueba su identidad con
-- la fecha de nacimiento y la de ingreso, y declara su correo. Ese camino lo
-- abre `puede_completar_ficha`, que exigía además `not ficha_completa`.
--
-- LA COMBINACIÓN QUE ENCIERRA A UNA PERSONA: sin correo y con la ficha dada
-- por completa. No puede recibir el código porque no hay dónde enviarlo, y no
-- puede hacer el primer ingreso porque el sistema cree que ya lo hizo. No es
-- hipotético: basta que Talento Humano borre un correo equivocado de alguien
-- que ya entró una vez.
--
-- Y el encierro es SILENCIOSO. La pantalla de acceso responde lo mismo a una
-- cédula sin correo que a una que no existe —a propósito, para no filtrar
-- quién trabaja aquí—, así que la persona teclea su cédula, le dicen que
-- revise su correo, y no llega nada. Nunca. Sin un mensaje que lo explique.
--
-- La regla pasa a ser la que debió ser desde el principio: SI NO HAY CORREO,
-- EL PRIMER INGRESO ESTÁ ABIERTO. El correo es la única llave, y quien no
-- tiene llave tiene que poder pedir una.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. El primer ingreso, abierto a quien no tiene correo
--
-- Sigue sin filtrar nada: responde falso tanto si la cédula no existe como
-- si ya tiene correo, y la cédula en Ecuador es casi pública.
-- =========================================================================

create or replace function public.puede_completar_ficha(p_cedula text)
returns boolean
language sql
stable
security definer
set search_path = public
as $pcf$
  -- Devuelve booleano y nada más: no filtra si la cédula existe cuando la
  -- respuesta es falsa. La cédula es casi pública en Ecuador y esta función
  -- responde sin autenticación.
  select exists (
    select 1 from public.users
     where cedula = p_cedula and activo
       and (
         -- Sin correo no hay dónde mandar el código: el primer ingreso es su
         -- único camino, tenga la ficha por completa o no.
         email is null
         -- Y el caso de siempre: tiene correo provisional y ficha pendiente.
         or (correo_pendiente and not ficha_completa)
       )
  );
$pcf$;

comment on function public.puede_completar_ficha(text) is
  'Si esta cédula debe pasar por el primer ingreso. Verdadero siempre que la persona no tenga correo: sin correo no hay forma de recibir el código.';

-- =========================================================================
-- B. Quién sigue sin poder entrar
--
-- Para que la respuesta a «Fulano no puede entrar» sea una consulta y no una
-- investigación. Sin nombres ni correos de por medio: esta vista la mira
-- Talento Humano, no el público.
-- =========================================================================

drop view if exists public.v_sin_entrada;
create view public.v_sin_entrada as
select u.id as user_id, u.cedula, u.nombre, u.departamento, u.ciudad,
       u.email is null                as sin_correo,
       u.fecha_nacimiento is null     as sin_fecha_nacimiento,
       u.fecha_ingreso is null        as sin_fecha_ingreso,
       u.ficha_completa,
       u.correo_pendiente,
       case
         when u.fecha_nacimiento is null and u.fecha_ingreso is null
           then 'Faltan la fecha de nacimiento y la de ingreso: no puede probar su identidad'
         when u.fecha_nacimiento is null
           then 'Falta la fecha de nacimiento: no puede probar su identidad'
         when u.fecha_ingreso is null
           then 'Falta la fecha de ingreso: no puede probar su identidad'
         else 'Sin correo, pero puede entrar por primer ingreso'
       end as motivo,
       -- Lo que hay que hacer para desatascarlo, dicho en una línea.
       case
         when u.fecha_nacimiento is null or u.fecha_ingreso is null
           then 'Complete la fecha que falta en su ficha, o registre su correo desde Colaboradores'
         else 'Nada: dígale que use «Es mi primer ingreso» en la pantalla de acceso'
       end as que_hacer
  from public.users u
 where u.activo and u.email is null
 order by (u.fecha_nacimiento is null or u.fecha_ingreso is null) desc, u.nombre;

comment on view public.v_sin_entrada is
  'Personas activas sin correo registrado, y si les queda o no un camino de entrada. Herramienta de Talento Humano para responder «Fulano no puede entrar» sin investigar.';

grant select on public.v_sin_entrada to authenticated;
