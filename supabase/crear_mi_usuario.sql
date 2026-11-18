-- =====================================================================
--  CREAR SU USUARIO PARA PROBAR
--
--  EDITE los valores de abajo con su cédula y su correo REAL, y ejecute
--  esto en el SQL Editor de Supabase. Sin esto no podrá iniciar sesión:
--  el sistema solo deja entrar a quien esté registrado.
--
--  La cédula debe ser una cédula ecuatoriana válida (la base la verifica
--  con el algoritmo módulo 10). El correo es donde llegará su código.
-- =====================================================================

do $$
declare
  -- ┌──────────────────────────────────────────────────────────────┐
  -- │  CAMBIE ESTOS CUATRO VALORES                                 │
  -- └──────────────────────────────────────────────────────────────┘
  v_cedula        text := '1712345675';
  v_nombre        text := 'Nombre Apellido';
  v_email         text := 'usted@itsanet.com.ec';
  v_fecha_ingreso date := '2018-03-01';        -- afecta cuántos días le tocan

  v_id uuid;
begin
  if not public.es_cedula_valida(v_cedula) then
    -- Se calcula el dígito que debería llevar: casi siempre el error es ese
    raise exception 'La cédula % no es válida. Si los primeros nueve dígitos son correctos, el último debería ser %.',
      v_cedula,
      (select (10 - (sum(case when i %% 2 = 1
                              then case when substring(v_cedula from i for 1)::int * 2 > 9
                                        then substring(v_cedula from i for 1)::int * 2 - 9
                                        else substring(v_cedula from i for 1)::int * 2 end
                              else substring(v_cedula from i for 1)::int end) %% 10)) %% 10
         from generate_series(1, 9) as i);
  end if;

  insert into public.users (cedula, nombre, email, rol, cargo, departamento, fecha_ingreso)
  values (v_cedula, v_nombre, v_email, 'admin', 'Administrador del sistema', 'TI', v_fecha_ingreso)
  on conflict (cedula) do update
    set nombre = excluded.nombre,
        email  = excluded.email,
        rol    = 'admin',
        activo = true
  returning id into v_id;

  -- Genera sus períodos de vacaciones según la fecha de ingreso
  perform public.generar_periodos_vacaciones(v_id);
  perform public.caducar_periodos_vencidos();

  raise notice 'Listo. Ingrese con la cédula % — el código llegará a %', v_cedula, v_email;
  raise notice 'Saldo calculado: % días', (select dias_vacaciones from public.users where id = v_id);
end $$;

-- Comprobación
select cedula, nombre, email, rol::text as rol, fecha_ingreso,
       public.anios_cumplidos(fecha_ingreso) as anios_servicio,
       dias_vacaciones as saldo
from public.users
where activo
order by case rol when 'admin' then 1 when 'rrhh' then 2 else 3 end, nombre;
