-- =====================================================================
--  SEED — Feriados Ecuador + usuarios de prueba
--  Ejecutar DESPUÉS de la migración 0001.
-- =====================================================================

-- Feriados nacionales Ecuador (necesarios para el cálculo de días)
insert into public.feriados (fecha, nombre) values
  ('2026-01-01', 'Año Nuevo'),
  ('2026-02-16', 'Carnaval'),
  ('2026-02-17', 'Carnaval'),
  ('2026-04-03', 'Viernes Santo'),
  ('2026-05-01', 'Día del Trabajo'),
  ('2026-05-24', 'Batalla de Pichincha'),
  ('2026-08-10', 'Primer Grito de Independencia'),
  ('2026-10-09', 'Independencia de Guayaquil'),
  ('2026-11-02', 'Día de los Difuntos'),
  ('2026-11-03', 'Independencia de Cuenca'),
  ('2026-12-25', 'Navidad'),
  ('2027-01-01', 'Año Nuevo'),
  ('2027-02-08', 'Carnaval'),
  ('2027-02-09', 'Carnaval'),
  ('2027-03-26', 'Viernes Santo'),
  ('2027-05-01', 'Día del Trabajo'),
  ('2027-05-24', 'Batalla de Pichincha'),
  ('2027-08-10', 'Primer Grito de Independencia'),
  ('2027-10-09', 'Independencia de Guayaquil'),
  ('2027-11-02', 'Día de los Difuntos'),
  ('2027-11-03', 'Independencia de Cuenca'),
  ('2027-12-25', 'Navidad')
on conflict (fecha) do nothing;

-- Usuarios de prueba (cédulas válidas según módulo 10).
-- Cambia los correos por los reales antes de probar el envío de OTP.
-- El saldo NO se escribe a mano: se deriva de los períodos anuales (migración 0002).
with rrhh as (
  insert into public.users (cedula, nombre, email, telefono, rol, cargo, departamento, fecha_ingreso)
  values ('0703886002', 'María Vera', 'rrhh@itsanet.test', '0999000001', 'rrhh', 'Analista de RRHH', 'Talento Humano', '2019-03-01')
  on conflict (cedula) do update set nombre = excluded.nombre
  returning id
), jefe as (
  insert into public.users (cedula, nombre, email, telefono, rol, cargo, departamento, fecha_ingreso)
  values ('1710034065', 'Carlos Moreno', 'jefe@itsanet.test', '0999000002', 'jefe', 'Jefe de Operaciones', 'Operaciones', '2017-06-15')
  on conflict (cedula) do update set nombre = excluded.nombre
  returning id
)
insert into public.users (cedula, nombre, email, telefono, rol, cargo, departamento, jefe_id, fecha_ingreso, logros)
select * from (
  select '0926687856'::text, 'Ana Suárez', 'empleado@itsanet.test'::citext, '0999000003', 'empleado'::public.user_role,
         'Asistente Administrativo', 'Operaciones', (select id from jefe), '2021-09-01'::date,
         '[{"titulo":"Empleado del mes","fecha":"2026-05-31","detalle":"Marzo 2026"}]'::jsonb
  union all
  select '1713175071', 'Luis Pinto', 'guardia@itsanet.test', '0999000004', 'guardia',
         'Guardia de Seguridad', 'Seguridad', null, '2022-01-10', '[]'::jsonb
  union all
  select '0602910945', 'Admin Sistema', 'admin@itsanet.test', '0999000005', 'admin',
         'Administrador', 'TI', null, '2016-01-04', '[]'::jsonb
) as t(cedula, nombre, email, telefono, rol, cargo, departamento, jefe_id, fecha_ingreso, logros)
on conflict (cedula) do nothing;

-- Generar los períodos anuales de vacaciones y caducar los acumulados de más de 3 años
select public.generar_periodos_vacaciones(id) from public.users;
select public.caducar_periodos_vencidos();

-- Saldos "reales" de demostración (así se migrarán los 250 empleados desde la planilla).
-- El tercer parámetro son los fines de semana obligatorios que ya consumió este período.
select public.cargar_saldo_inicial(id, 12.5, 1) from public.users where cedula = '0926687856';
select public.cargar_saldo_inicial(id, 18,   0) from public.users where cedula = '1710034065';
select public.cargar_saldo_inicial(id, 22,   2) from public.users where cedula = '0703886002';
select public.cargar_saldo_inicial(id, 10,   0) from public.users where cedula = '1713175071';
select public.cargar_saldo_inicial(id, 15,   0) from public.users where cedula = '0602910945';
