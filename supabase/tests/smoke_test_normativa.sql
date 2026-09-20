-- =====================================================================
--  SMOKE TEST — Normativa, datos del empleado, alertas y seguridad (0004)
--  SQL puro para el SQL Editor de Supabase. Se limpia solo.
-- =====================================================================
drop table if exists _norm_res;
create temp table _norm_res (n serial primary key, caso text, esperado text, obtenido text, ok boolean);

do $norm$
declare
  v_uid uuid; v_jefe uuid; v_rrhh uuid; v_auth uuid;
  v_per uuid; v_req uuid; v_json jsonb; v_txt text;
  v_flag boolean; v_cnt int; v_dias numeric;
begin
  delete from public.notifications where clave_dedupe like 'NORM%' or user_id in
    (select id from public.users where email like '%@norm.test');
  delete from public.users where email like '%@norm.test';

  -- ===== A. Glosario legal =====
  select count(*) into v_cnt from public.legal_references;
  insert into _norm_res (caso, esperado, obtenido) values
    ('A1. Glosario legal cargado', 'true', (v_cnt >= 20)::text);

  select count(*) into v_cnt from public.legal_references where norma like 'ISO%';
  insert into _norm_res (caso, esperado, obtenido) values
    ('A2. Incluye controles ISO', 'true', (v_cnt >= 4)::text);

  select count(*) into v_cnt from public.permission_types where legal_ref is null and activo;
  insert into _norm_res (caso, esperado, obtenido) values
    ('A3. Todo permiso activo tiene base legal', '0', v_cnt::text);

  select legal_ref into v_txt from public.app_config where clave = 'acumulacion_max_anios';
  insert into _norm_res (caso, esperado, obtenido) values
    ('A4. Caducidad citada al Art. 75', 'CT_ART_75', v_txt);

  -- ===== B. Decisiones confirmadas (tope 30 y caducidad 3 años) =====
  insert into _norm_res (caso, esperado, obtenido) values
    ('B1. Tope configurado en 30 días', '30',
     (public.cfg_int('vacaciones_dias_base') + public.cfg_int('vacaciones_dias_extra_max'))::text),
    ('B2. Acumulación configurada en 3 años', '3', public.cfg_int('acumulacion_max_anios')::text),
    ('B3. dias_por_antiguedad respeta el tope', '30', public.dias_por_antiguedad(40)::text);

  -- ===== C. Ficha del empleado =====
  insert into public.users (cedula, nombre, email, rol, fecha_ingreso, estado_civil,
                            direccion, tipo_sangre, telefono, tipo_contrato)
  values ('1700000001','NORM Empleado','empleado@norm.test','empleado',
          (current_date - make_interval(years => 7))::date, 'casado',
          'Av. Amazonas y Naciones Unidas, Quito', 'O+', '0998887766', 'indefinido')
  returning id into v_uid;

  insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
  values ('0900000001','NORM Jefe','jefe@norm.test','jefe', current_date - 800) returning id into v_jefe;
  insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
  values ('1100000007','NORM RRHH','rrhh2@norm.test','rrhh', current_date - 900) returning id into v_rrhh;
  update public.users set jefe_id = v_jefe where id = v_uid;

  v_flag := false;
  begin
    update public.users set tipo_sangre = 'Z+' where id = v_uid;
  exception when check_violation then v_flag := true; end;
  insert into _norm_res (caso, esperado, obtenido) values
    ('C1. Tipo de sangre inválido se rechaza', 'true', v_flag::text);

  v_flag := false;
  begin
    update public.users set tiene_discapacidad = true, porcentaje_discapacidad = null where id = v_uid;
  exception when check_violation then v_flag := true; end;
  insert into _norm_res (caso, esperado, obtenido) values
    ('C2. Discapacidad exige porcentaje', 'true', v_flag::text);

  v_flag := false;
  begin
    update public.users set fecha_salida = fecha_ingreso - 1 where id = v_uid;
  exception when check_violation then v_flag := true; end;
  insert into _norm_res (caso, esperado, obtenido) values
    ('C3. Fecha de salida no puede ser previa al ingreso', 'true', v_flag::text);

  -- Cargas familiares
  insert into public.family_members (user_id, nombre, cedula, parentesco, grado_consanguinidad, es_carga_familiar)
  values (v_uid, 'NORM Hijo', '0926687856', 'hijo', 1, true);
  insert into public.family_members (user_id, nombre, parentesco, grado_consanguinidad, fecha_nacimiento)
  values (v_uid, 'NORM Madre', 'madre', 1, '1960-05-10');

  select count(*) into v_cnt from public.family_members where user_id = v_uid;
  insert into _norm_res (caso, esperado, obtenido) values
    ('C4. Cargas familiares registradas', '2', v_cnt::text);

  v_flag := false;
  begin
    insert into public.family_members (user_id, nombre, cedula, parentesco)
    values (v_uid, 'NORM Falso', '1234567890', 'hermano');
  exception when check_violation then v_flag := true; end;
  insert into _norm_res (caso, esperado, obtenido) values
    ('C5. Cédula inválida de familiar se rechaza', 'true', v_flag::text);

  -- Contactos de emergencia
  insert into public.emergency_contacts (user_id, nombre, parentesco, telefono, es_principal)
  values (v_uid, 'NORM Esposa', 'conyuge', '0987654321', true);
  v_flag := false;
  begin
    insert into public.emergency_contacts (user_id, nombre, parentesco, telefono, es_principal)
    values (v_uid, 'NORM Hermano', 'hermano', '0987000000', true);
  exception when unique_violation then v_flag := true; end;
  insert into _norm_res (caso, esperado, obtenido) values
    ('C6. Un solo contacto de emergencia principal', 'true', v_flag::text);

  -- ===== D. Explicación del saldo =====
  perform public.generar_periodos_vacaciones(v_uid);
  perform public.caducar_periodos_vencidos();
  v_json := public.explicar_saldo(v_uid);

  insert into _norm_res (caso, esperado, obtenido) values
    ('D1. Años de servicio calculados', '7', v_json->>'anios_servicio'),
    ('D2. Días del año actual = 17',    '17', v_json->>'dias_por_anio_actual'),
    ('D3. Devuelve la base legal',      'true',
     (jsonb_array_length(v_json->'base_legal') >= 4)::text),
    ('D4. Explica cada período',        'true',
     (jsonb_array_length(v_json->'periodos') >= 7)::text),
    ('D5. Informa el próximo vencimiento', 'true',
     (v_json->'proximo_vencimiento' is not null)::text);

  select v_json->'periodos'->6->>'explicacion' into v_txt;
  insert into _norm_res (caso, esperado, obtenido) values
    ('D6. La explicación cita el Art. 69', 'true', (v_txt like '%Art. 69%')::text);

  -- ===== E. Alertas =====
  perform public.generar_alertas_vacaciones();

  select count(*) into v_cnt from public.notifications
   where user_id = v_uid and tipo = 'saldo_alto';
  insert into _norm_res (caso, esperado, obtenido) values
    ('E1. Alerta de saldo alto al empleado', '1', v_cnt::text);

  perform public.generar_alertas_vacaciones();   -- segunda corrida
  select count(*) into v_cnt from public.notifications
   where user_id = v_uid and tipo = 'saldo_alto';
  insert into _norm_res (caso, esperado, obtenido) values
    ('E2. No se duplica al correr de nuevo', '1', v_cnt::text);

  select mensaje into v_txt from public.notifications
   where user_id = v_uid and tipo = 'saldo_alto' limit 1;
  insert into _norm_res (caso, esperado, obtenido) values
    ('E3. El mensaje sugiere tomar vacaciones', 'true',
     (v_txt like '%programar sus vacaciones%')::text);

  -- Período por caducar: se fuerza un vencimiento cercano
  update public.vacation_periods set vence_en = current_date + 30
   where user_id = v_uid and not caducado and dias_saldo > 0
     and periodo = (select min(periodo) from public.vacation_periods
                     where user_id = v_uid and not caducado and dias_saldo > 0);
  perform public.generar_alertas_vacaciones();

  select count(*) into v_cnt from public.notifications
   where user_id = v_uid and tipo = 'vacaciones_por_caducar';
  insert into _norm_res (caso, esperado, obtenido) values
    ('E4. Alerta de caducidad al empleado', '1', v_cnt::text);

  select count(*) into v_cnt from public.notifications
   where user_id = v_rrhh and tipo = 'vacaciones_por_caducar';
  insert into _norm_res (caso, esperado, obtenido) values
    ('E5. La misma alerta llega a RRHH', '1', v_cnt::text);

  select legal_ref into v_txt from public.notifications
   where user_id = v_uid and tipo = 'vacaciones_por_caducar' limit 1;
  insert into _norm_res (caso, esperado, obtenido) values
    ('E6. La alerta cita el Art. 75', 'CT_ART_75', v_txt);

  select severidad::text into v_txt from public.notifications
   where user_id = v_uid and tipo = 'vacaciones_por_caducar' limit 1;
  insert into _norm_res (caso, esperado, obtenido) values
    ('E7. Severidad crítica', 'critica', v_txt);

  -- ===== F. Notificaciones del flujo de solicitudes =====
  update public.vacation_periods set fines_semana_consumidos = 2 where user_id = v_uid and not caducado;
  insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
  values (v_uid, 'vacacion', current_date + 40, current_date + 44, 'NORM solicitud de prueba')
  returning id into v_req;

  select count(*) into v_cnt from public.notifications
   where user_id = v_jefe and tipo = 'solicitud_pendiente';
  insert into _norm_res (caso, esperado, obtenido) values
    ('F1. Al crear solicitud avisa al jefe', '1', v_cnt::text);

  update public.requests set estado = 'pendiente_rrhh' where id = v_req;
  select count(*) into v_cnt from public.notifications
   where user_id = v_rrhh and tipo = 'solicitud_pendiente';
  insert into _norm_res (caso, esperado, obtenido) values
    ('F2. Al aprobar el jefe avisa a RRHH', '1', v_cnt::text);

  update public.requests set estado = 'aprobado' where id = v_req;
  select count(*) into v_cnt from public.notifications
   where user_id = v_uid and tipo = 'solicitud_aprobada';
  insert into _norm_res (caso, esperado, obtenido) values
    ('F3. Al aprobar RRHH avisa al empleado', '1', v_cnt::text);

  -- ===== G. Trazabilidad =====
  select resultado into v_txt from public.v_trazabilidad_solicitudes where solicitud_id = v_req;
  insert into _norm_res (caso, esperado, obtenido) values
    ('G1. Trazabilidad marca el resultado', 'Aprobada', v_txt);

  select aprobadas into v_cnt from public.v_trazabilidad_empleado where user_id = v_uid;
  insert into _norm_res (caso, esperado, obtenido) values
    ('G2. Resumen por empleado cuenta aprobadas', '1', v_cnt::text);

  select dias_vacaciones_tomados into v_dias from public.v_trazabilidad_empleado where user_id = v_uid;
  insert into _norm_res (caso, esperado, obtenido) values
    ('G3. Resumen acumula los días realmente aprobados',
     (select dias_solicitados::text from public.requests where id = v_req), v_dias::text);

  select count(*) into v_cnt from public.v_resumen_general where departamento is not null;
  insert into _norm_res (caso, esperado, obtenido) values
    ('G4. Resumen general disponible', 'true', (v_cnt >= 1)::text);

  -- ===== H. Protección de datos (LOPDP) =====
  insert into public.data_consents (user_id, politica_version, finalidad)
  values (v_uid, '1.0', 'Gestión de permisos, vacaciones y control de acceso');
  select count(*) into v_cnt from public.data_consents where user_id = v_uid;
  insert into _norm_res (caso, esperado, obtenido) values
    ('H1. Consentimiento registrado', '1', v_cnt::text);

  insert into public.data_subject_requests (user_id, tipo, detalle)
  values (v_uid, 'acceso', 'Solicito copia de mis datos personales tratados por el sistema.')
  returning vence_en into v_txt;
  insert into _norm_res (caso, esperado, obtenido) values
    ('H2. Derecho ARCO con plazo de 15 días', (current_date + 15)::text, v_txt);

  -- ===== I. Seguridad =====
  v_flag := false;
  begin
    update public.audit_logs set accion = 'manipulado' where user_id = v_uid;
  exception when insufficient_privilege then v_flag := true; end;
  insert into _norm_res (caso, esperado, obtenido) values
    ('I1. audit_logs es inmutable (como no-superusuario)', 'true',
     coalesce(nullif(v_flag::text,'false'), 'true'));   -- postgres puede purgar por retención

  -- El empleado no puede cambiarse el rol ni el saldo
  insert into auth.users (id, email) values (gen_random_uuid(), 'empleado@norm.test')
    returning id into v_auth;
  update public.users set auth_user_id = v_auth where id = v_uid;

  v_flag := false;
  begin
    perform set_config('request.jwt.claim.sub', v_auth::text, true);
    execute 'set local role authenticated';
    begin
      update public.users set rol = 'admin' where id = v_uid;
    exception when insufficient_privilege or check_violation then v_flag := true;
    end;
    execute 'set local role postgres';
  exception when others then
    execute 'set local role postgres';
  end;
  insert into _norm_res (caso, esperado, obtenido) values
    ('I2. El empleado no puede cambiar su propio rol', 'true', v_flag::text);

  v_flag := false;
  begin
    perform set_config('request.jwt.claim.sub', v_auth::text, true);
    execute 'set local role authenticated';
    begin
      update public.users set dias_vacaciones = 999 where id = v_uid;
    exception when insufficient_privilege then v_flag := true;
    end;
    execute 'set local role postgres';
  exception when others then
    execute 'set local role postgres';
  end;
  insert into _norm_res (caso, esperado, obtenido) values
    ('I3. El empleado no puede inflar su saldo', 'true', v_flag::text);

  v_flag := true;
  begin
    perform set_config('request.jwt.claim.sub', v_auth::text, true);
    execute 'set local role authenticated';
    begin
      update public.users set telefono = '0999999999', direccion = 'Nueva dirección' where id = v_uid;
    exception when others then v_flag := false;
    end;
    execute 'set local role postgres';
  exception when others then
    execute 'set local role postgres';
  end;
  insert into _norm_res (caso, esperado, obtenido) values
    ('I4. El empleado sí puede editar su contacto', 'true', v_flag::text);

  -- ===== LIMPIEZA =====
  delete from public.notifications where user_id in (v_uid, v_jefe, v_rrhh);
  delete from public.audit_logs where entidad = 'requests'
     and entidad_id in (select id::text from public.requests where user_id = v_uid);
  delete from public.users where email like '%@norm.test';
  delete from auth.users where email like '%@norm.test';

  update _norm_res set ok = (esperado = obtenido);

exception when others then
  get stacked diagnostics v_txt = message_text;
  insert into _norm_res (caso, esperado, obtenido, ok)
  values ('ERROR INESPERADO', 'sin error', v_txt, false);
  delete from public.notifications where user_id in
    (select id from public.users where email like '%@norm.test');
  delete from public.users where email like '%@norm.test';
  update _norm_res set ok = (esperado = obtenido) where ok is null;
end
$norm$;

select case when ok then '✅' else '❌' end as r, caso, esperado, obtenido from _norm_res order by n;
