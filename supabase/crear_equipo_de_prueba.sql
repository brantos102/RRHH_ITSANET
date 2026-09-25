-- =====================================================================
--  EQUIPO DE PRUEBA (opcional)
--
--  Crea un jefe, un empleado y un guardia para recorrer el flujo completo
--  usted solo: solicitar → aprobar como jefe → aprobar como RRHH →
--  validar el QR como guardia.
--
--  Si tiene varios correos (o usa alias tipo usted+jefe@empresa.com),
--  cámbielos abajo para recibir todos los códigos en su bandeja.
-- =====================================================================

do $$
declare
  -- ┌──────────────────────────────────────────────────────────────┐
  -- │  CAMBIE LOS CORREOS por los suyos o por alias reales         │
  -- └──────────────────────────────────────────────────────────────┘
  v_correo_jefe     text := 'usted+jefe@itsanet.com.ec';
  v_correo_empleado text := 'usted+empleado@itsanet.com.ec';
  v_correo_guardia  text := 'usted+guardia@itsanet.com.ec';

  v_jefe uuid; v_empleado uuid; v_guardia uuid;
begin
  -- Cédulas válidas reservadas para las pruebas
  insert into public.users (cedula, nombre, email, rol, cargo, departamento, fecha_ingreso)
  values ('1710034065', 'Jefe de Prueba', v_correo_jefe, 'jefe',
          'Jefe de Operaciones', 'Operaciones', current_date - interval '9 years')
  on conflict (cedula) do update set email = excluded.email, rol = 'jefe', activo = true
  returning id into v_jefe;

  insert into public.users (cedula, nombre, email, rol, cargo, departamento, jefe_id, fecha_ingreso)
  values ('0926687856', 'Empleado de Prueba', v_correo_empleado, 'empleado',
          'Asistente Administrativo', 'Operaciones', v_jefe, current_date - interval '7 years')
  on conflict (cedula) do update
    set email = excluded.email, rol = 'empleado', jefe_id = excluded.jefe_id, activo = true
  returning id into v_empleado;

  insert into public.users (cedula, nombre, email, rol, cargo, departamento, fecha_ingreso)
  values ('1713175071', 'Guardia de Prueba', v_correo_guardia, 'guardia',
          'Guardia de Seguridad', 'Seguridad', current_date - interval '4 years')
  on conflict (cedula) do update set email = excluded.email, rol = 'guardia', activo = true
  returning id into v_guardia;

  -- Períodos y un saldo cómodo para probar sin tropezar con los límites
  perform public.generar_periodos_vacaciones(v_jefe);
  perform public.generar_periodos_vacaciones(v_guardia);
  perform public.cargar_saldo_inicial(v_empleado, 20, 2);
  perform public.cargar_saldo_inicial(v_jefe, 20, 2);

  raise notice 'Equipo de prueba listo:';
  raise notice '  Jefe      1710034065 → %', v_correo_jefe;
  raise notice '  Empleado  0926687856 → %', v_correo_empleado;
  raise notice '  Guardia   1713175071 → %', v_correo_guardia;
end $$;

select cedula, nombre, rol::text as rol, email, dias_vacaciones as saldo
from public.users where activo order by rol::text, nombre;
