-- ---------------------------------------------------------------------------
-- 0035 · Ver lo que hay que depurar, sin abrir DBeaver.
--
-- La carga inicial dejó cosas que hay que revisar a mano, y revisarlas
-- escribiendo SQL contra la planilla real no es razonable como rutina.
--
-- LO QUE DESTAPÓ ESTA VISTA AL PROBARLA: las cuentas de prueba que se crearon
-- al arrancar el sistema —`admin@itsanet.test`, `rrhh@itsanet.test`,
-- `jefereal@itsanet.test`— no quedaron sueltas. Quedaron pegadas a personas
-- REALES de la planilla, que hoy cargan con un correo que no existe y con un
-- rol que probablemente no les corresponde. Una de ellas figura como jefe de
-- setenta y cuatro personas.
--
-- Eso tiene dos consecuencias, y ninguna se ve desde la pantalla:
--
--   · Esas personas no pueden recibir su código de acceso, porque el correo
--     no lleva a ninguna parte.
--   · Tienen permisos de administración, de Talento Humano o de garita sin
--     que nadie lo haya decidido.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. Cuentas que huelen a prueba
--
-- Por el correo, que es la marca que dejaron: el dominio `itsanet.test` no
-- existe y nunca existió. Se listan con su rol y con cuánta gente tienen a
-- cargo, porque eso es lo que decide si se corrige o se borra.
-- =========================================================================

drop view if exists public.v_cuentas_de_prueba;
create view public.v_cuentas_de_prueba as
select u.id as user_id, u.cedula, u.nombre, u.email, u.rol, u.cargo,
       u.departamento, u.fecha_ingreso, u.activo,
       (select count(*) from public.users s where s.jefe_id = u.id and s.activo) as a_cargo,
       (select count(*) from public.requests r where r.user_id = u.id)           as solicitudes,
       (select count(*) from public.vacaciones_historicas h where h.user_id = u.id) as historicas,
       -- Lo que hay que hacer con cada una, dicho en una línea. Una persona
       -- con historial y solicitudes es real: se le corrige el correo. Una
       -- sin nada es la cuenta de prueba de verdad y se puede desactivar.
       case
         when (select count(*) from public.vacaciones_historicas h where h.user_id = u.id) > 0
           or (select count(*) from public.requests r where r.user_id = u.id) > 0
           then 'Persona real con correo de prueba: corríjale el correo y revise su rol'
         when (select count(*) from public.users s where s.jefe_id = u.id and s.activo) > 0
           then 'Tiene gente a cargo: reasígnela antes de tocar esta cuenta'
         else 'Sin actividad: probablemente es una cuenta de prueba y se puede desactivar'
       end as que_hacer
  from public.users u
 -- Por el dominio de primer nivel `.test`, que la RFC 2606 reserva
 -- justamente para esto y que nunca resuelve a ningún servidor. Es más
 -- fiable que enumerar dominios: cubre `itsanet.test`, `api.test` y
 -- cualquiera que alguien invente mañana con la misma idea.
 where u.email::text like '%.test'
    or u.email::text like '%.invalid'
    or u.email::text like '%@ejemplo.%'
 order by u.rol, u.nombre;

comment on view public.v_cuentas_de_prueba is
  'Cuentas con correo de dominio de prueba. Dice de cada una si es una persona real a la que hay que corregirle el correo o una cuenta que se puede desactivar.';

grant select on public.v_cuentas_de_prueba to authenticated;

-- =========================================================================
-- B. Fichas incompletas
--
-- Solo lo que impide que el sistema funcione, no todo lo que falta. Un
-- teléfono en blanco no rompe nada; un empleado sin jefe deja sus solicitudes
-- sin quien las autorice.
-- =========================================================================

drop view if exists public.v_fichas_incompletas;
create view public.v_fichas_incompletas as
select u.id as user_id, u.cedula, u.nombre, u.departamento, u.cargo, u.rol,
       u.email is null                                    as sin_correo,
       u.cargo is null or btrim(u.cargo) = ''             as sin_cargo,
       u.departamento is null or btrim(u.departamento) = '' as sin_departamento,
       u.fecha_nacimiento is null                         as sin_nacimiento,
       u.telefono is null or btrim(u.telefono) = ''       as sin_telefono,
       u.jefe_id is null and u.rol = 'empleado'           as sin_jefe,
       -- Lo grave arriba: sin jefe no se puede autorizar nada, y sin correo
       -- ni fecha de nacimiento la persona no tiene forma de entrar.
       case
         when u.jefe_id is null and u.rol = 'empleado'
           then 'Sin jefe: sus solicitudes no le llegan a nadie'
         when u.email is null and u.fecha_nacimiento is null
           then 'No puede entrar: sin correo y sin fecha de nacimiento para el primer ingreso'
         when u.cargo is null or btrim(u.cargo) = ''
           then 'Sin cargo registrado'
         else 'Faltan datos de contacto'
       end                                                as lo_principal,
       (case when u.email is null then 1 else 0 end
        + case when u.cargo is null or btrim(u.cargo) = '' then 1 else 0 end
        + case when u.departamento is null or btrim(u.departamento) = '' then 1 else 0 end
        + case when u.fecha_nacimiento is null then 1 else 0 end
        + case when u.telefono is null or btrim(u.telefono) = '' then 1 else 0 end
        + case when u.jefe_id is null and u.rol = 'empleado' then 1 else 0 end) as huecos
  from public.users u
 where u.activo
   and (u.email is null
        or u.cargo is null or btrim(u.cargo) = ''
        or u.departamento is null or btrim(u.departamento) = ''
        or u.fecha_nacimiento is null
        or u.telefono is null or btrim(u.telefono) = ''
        or (u.jefe_id is null and u.rol = 'empleado'))
 order by (u.jefe_id is null and u.rol = 'empleado') desc, u.nombre;

comment on view public.v_fichas_incompletas is
  'Personas activas a las que les falta algo, ordenadas por gravedad: primero lo que impide autorizar o entrar.';

grant select on public.v_fichas_incompletas to authenticated;

-- =========================================================================
-- C. La jerarquía
--
-- Quién manda sobre quién, y dónde está rota. Una jefatura sin nadie a cargo
-- no es un error, pero conviene verla: suele ser un rol que se puso para
-- probar y quedó.
-- =========================================================================

drop view if exists public.v_jerarquia;
create view public.v_jerarquia as
select u.id as user_id, u.cedula, u.nombre, u.rol, u.cargo, u.departamento,
       j.id as jefe_id, j.nombre as jefe_nombre, j.activo as jefe_activo,
       (select count(*) from public.users s where s.jefe_id = u.id and s.activo) as a_cargo,
       case
         when u.jefe_id = u.id                          then 'Es su propio jefe'
         when j.id is not null and not j.activo         then 'Su jefe está inactivo'
         when u.jefe_id is null and u.rol = 'empleado'  then 'Sin jefe asignado'
         when u.rol in ('jefe', 'rrhh', 'admin')
          and (select count(*) from public.users s where s.jefe_id = u.id and s.activo) = 0
                                                        then 'Tiene rol de mando y nadie a cargo'
         else null
       end as problema
  from public.users u
  left join public.users j on j.id = u.jefe_id
 where u.activo;

comment on view public.v_jerarquia is
  'Quién reporta a quién. `problema` señala lo que hay que revisar; en nulo, la fila está bien.';

grant select on public.v_jerarquia to authenticated;
