-- =====================================================================
--  SMOKE TEST — Reglas de negocio (migraciones 0001 + 0002)
--
--  SQL puro: se pega y ejecuta tal cual en el SQL Editor de Supabase.
--  Crea sus propios datos (@smoke.test) y los BORRA al terminar.
--  Devuelve una tabla con ✅/❌ por caso.
-- =====================================================================

drop table if exists _smoke_resultados;
create temp table _smoke_resultados (
  n serial primary key, caso text, esperado text, obtenido text, ok boolean
);

do $smoke$
declare
  v_uid       uuid;
  v_req       uuid;
  v_req2      uuid;
  v_visit     uuid;
  v_sig       uuid;
  v_pt_medica smallint;
  v_pt_person smallint;
  v_pt_caso   smallint;
  v_lun       date;
  v_ingreso   date;
  v_estado    public.request_status;
  v_dias      numeric;
  v_saldo     numeric;
  v_qr        uuid;
  v_flag      boolean;
  v_json      jsonb;
  v_txt       text;
  v_cnt       int;
begin
  ---------------------------------------------------------------------
  -- Limpieza previa
  ---------------------------------------------------------------------
  delete from public.access_logs where observacion like 'SMOKE%';
  delete from public.visitors     where cedula = '0900000001' and motivo_visita like 'SMOKE%';
  delete from public.users        where email like '%@smoke.test';
  delete from public.feriados     where nombre = 'SMOKE feriado';

  select id into v_pt_medica from public.permission_types where codigo = 'cita_medica';
  select id into v_pt_person from public.permission_types where codigo = 'permiso_personal';
  select id into v_pt_caso   from public.permission_types where codigo = 'caso_fortuito';

  -- ===================================================================
  -- BLOQUE A — Validación de cédula ecuatoriana (módulo 10)
  -- ===================================================================
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('A1. Cédula válida',                 'true',  public.es_cedula_valida('0926687856')::text),
    ('A2. Dígito verificador incorrecto', 'false', public.es_cedula_valida('0926687857')::text),
    ('A3. Solo 9 dígitos',                'false', public.es_cedula_valida('092668785')::text),
    ('A4. Provincia inexistente (99)',    'false', public.es_cedula_valida('9926687856')::text),
    ('A5. Tercer dígito > 5',             'false', public.es_cedula_valida('0976687856')::text),
    ('A6. Contiene letras',               'false', public.es_cedula_valida('09A6687856')::text),
    ('A7. Valor nulo',                    'false', coalesce(public.es_cedula_valida(null)::text,'false'));

  -- ===================================================================
  -- BLOQUE B — Días de vacaciones por antigüedad (Art. 69 CT)
  -- ===================================================================
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('B1. Año 1 de servicio = 15 días',  '15', public.dias_por_antiguedad(1)::text),
    ('B2. Año 5 de servicio = 15 días',  '15', public.dias_por_antiguedad(5)::text),
    ('B3. Año 6 de servicio = 16 días',  '16', public.dias_por_antiguedad(6)::text),
    ('B4. Año 7 de servicio = 17 días',  '17', public.dias_por_antiguedad(7)::text),
    ('B5. Año 10 de servicio = 20 días', '20', public.dias_por_antiguedad(10)::text),
    ('B6. Año 20 de servicio = 30 días (tope)', '30', public.dias_por_antiguedad(20)::text),
    ('B7. Año 30 respeta el tope de 30', '30', public.dias_por_antiguedad(30)::text);

  -- ===================================================================
  -- BLOQUE C — Cálculo de días (regla Ecuador) con feriado de prueba
  -- ===================================================================
  v_lun := date_trunc('week', date '2099-07-07')::date;          -- lunes
  insert into public.feriados (fecha, nombre) values (v_lun + 2, 'SMOKE feriado');

  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('C1. Permiso lun-vie sin feriado = 5 hábiles',
     '5', public.calcular_dias('permiso',  v_lun + 7, v_lun + 11)::text),
    ('C2. Vacación lun-dom sin feriado = 7 calendario',
     '7', public.calcular_dias('vacacion', v_lun + 7, v_lun + 13)::text),
    ('C3. Permiso lun-vie con feriado = 4',
     '4', public.calcular_dias('permiso',  v_lun, v_lun + 4)::text),
    ('C4. Vacación lun-dom con feriado = 6',
     '6', public.calcular_dias('vacacion', v_lun, v_lun + 6)::text),
    ('C5. Fecha fin anterior al inicio = 0',
     '0', public.calcular_dias('vacacion', v_lun + 5, v_lun)::text);

  -- ===================================================================
  -- BLOQUE D — Períodos anuales del empleado
  -- ===================================================================
  v_ingreso := (current_date - make_interval(years => 7))::date;
  insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
  values ('1700000001', 'SMOKE Empleado', 'empleado@smoke.test', 'empleado', v_ingreso)
  returning id into v_uid;

  perform public.generar_periodos_vacaciones(v_uid);
  perform public.caducar_periodos_vencidos();

  select dias_asignados into v_dias from public.vacation_periods where user_id = v_uid and periodo = 5;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('D1. Período 5 asigna 15 días', '15.00', v_dias::text);

  select dias_asignados into v_dias from public.vacation_periods where user_id = v_uid and periodo = 6;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('D2. Período 6 asigna 16 días', '16.00', v_dias::text);

  select dias_asignados into v_dias from public.vacation_periods where user_id = v_uid and periodo = 7;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('D3. Período 7 asigna 17 días', '17.00', v_dias::text);

  select count(*) into v_cnt from public.vacation_periods
   where user_id = v_uid and periodo = 8 and not devengado;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('D4. Existe período en curso no devengado', '1', v_cnt::text);

  select count(*) into v_cnt from public.vacation_periods where user_id = v_uid and caducado;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('D5. Períodos de más de 3 años caducados', 'true', (v_cnt >= 3)::text);

  select dias_vacaciones into v_saldo from public.users where id = v_uid;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('D6. Saldo = suma de períodos vigentes (15+16+17)', '48.00', v_saldo::text);

  -- Carga de saldo real (migración de los 250 empleados)
  perform public.cargar_saldo_inicial(v_uid, 12.5, 0);
  select dias_vacaciones into v_saldo from public.users where id = v_uid;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('D7. cargar_saldo_inicial cuadra el saldo', '12.50', v_saldo::text);

  -- ===================================================================
  -- BLOQUE E — Regla de los 2 fines de semana obligatorios
  -- ===================================================================
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('E1. Fines de semana completos en lun-dom',  '1', public.fines_de_semana_completos(v_lun+7, v_lun+13)::text),
    ('E2. Fines de semana completos en lun-vie',  '0', public.fines_de_semana_completos(v_lun+7, v_lun+11)::text),
    ('E3. Sábado suelto no cuenta como completo', '0', public.fines_de_semana_completos(v_lun+7, v_lun+12)::text),
    ('E4. Dos semanas completas = 2 fines de semana', '2', public.fines_de_semana_completos(v_lun+7, v_lun+20)::text),
    ('E5. Fines de semana pendientes del empleado', '2', public.fines_semana_pendientes(v_uid)::text);

  -- E6: solicitud que TERMINA VIERNES con fines de semana pendientes -> bloqueada
  v_flag := false;
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (v_uid, 'vacacion', v_lun + 7, v_lun + 11, 'SMOKE termina viernes');
  exception when raise_exception then
    v_flag := true;
    get stacked diagnostics v_txt = message_text;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('E6. Vacación que termina viernes se bloquea', 'true', v_flag::text),
    ('E7. El error sugiere incluir sábado y domingo', 'true',
     (v_txt like '%sábado y domingo%')::text);

  -- E8: solicitud que EMPIEZA LUNES sin fin de semana -> también bloqueada
  v_flag := false;
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (v_uid, 'vacacion', v_lun + 7, v_lun + 10, 'SMOKE empieza lunes');
  exception when raise_exception then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('E8. Vacación que empieza lunes se bloquea', 'true', v_flag::text);

  -- E9: martes a jueves no toca fin de semana -> permitida
  v_flag := true;
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (v_uid, 'vacacion', v_lun + 8, v_lun + 10, 'SMOKE martes a jueves')
    returning id into v_req2;
  exception when raise_exception then v_flag := false;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('E9. Vacación martes-jueves se permite', 'true', v_flag::text);
  delete from public.requests where id = v_req2;

  -- E10: el rango sugerido (lun a dom) sí se acepta
  insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
  values (v_uid, 'vacacion', v_lun + 7, v_lun + 13, 'SMOKE incluye fin de semana')
  returning id, dias_solicitados, fines_semana into v_req, v_dias, v_cnt;

  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('E10. Rango lun-dom se acepta',            'true', (v_req is not null)::text),
    ('E11. Registra 1 fin de semana completo',  '1',    v_cnt::text),
    ('E12. Días calculados = 7 (calendario)',   '7.00', v_dias::text);

  -- E13: previsualización devuelve el rango corregido
  v_json := public.previsualizar_solicitud(v_uid, 'vacacion', v_lun + 21, v_lun + 25, null);
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('E13. Previsualización marca inválido el viernes', 'false', (v_json->>'valido')),
    ('E14. Previsualización sugiere domingo como fin',
     (v_lun + 27)::text, (v_json->'rango_sugerido'->>'fin'));

  -- ===================================================================
  -- BLOQUE F — Flujo de aprobación, QR y consumo por períodos
  -- ===================================================================
  v_flag := false;
  begin
    update public.requests set estado = 'aprobado' where id = v_req;
  exception when raise_exception then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('F1. No se puede saltar la aprobación del jefe', 'true', v_flag::text);

  update public.requests set estado = 'pendiente_rrhh' where id = v_req;
  update public.requests set estado = 'aprobado'       where id = v_req;

  select estado, qr_hash into v_estado, v_qr from public.requests where id = v_req;
  select dias_vacaciones into v_saldo from public.users where id = v_uid;

  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('F2. Estado final tras aprobar RRHH', 'aprobado', v_estado::text),
    ('F3. Se emite el código QR',          'true',     (v_qr is not null)::text),
    ('F4. Saldo descontado (12.5 - 7)',    '5.50',     v_saldo::text);

  select fines_semana_consumidos into v_cnt
  from public.vacation_periods where user_id = v_uid and not caducado order by periodo limit 1;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('F5. Se acredita el fin de semana consumido', '1', v_cnt::text),
    ('F6. Quedan 1 fin de semana obligatorio',     '1', public.fines_semana_pendientes(v_uid)::text);

  -- F7: ahora que solo falta 1 fin de semana, sigue bloqueando el viernes
  v_flag := false;
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (v_uid, 'vacacion', v_lun + 35, v_lun + 39, 'SMOKE segundo viernes');
  exception when raise_exception then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('F7. Con 1 fin de semana pendiente sigue bloqueando', 'true', v_flag::text);

  -- Cancelación devuelve saldo y fin de semana
  update public.requests set estado = 'cancelado' where id = v_req;
  select dias_vacaciones into v_saldo from public.users where id = v_uid;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('F8. Saldo devuelto al cancelar (5.5 + 7)', '12.50', v_saldo::text),
    ('F9. Fin de semana devuelto',               '2',     public.fines_semana_pendientes(v_uid)::text);

  -- ===================================================================
  -- BLOQUE G — Descripción y justificación
  -- ===================================================================
  -- Forzamos 2 fines de semana ya consumidos para aislar estas reglas
  update public.vacation_periods set fines_semana_consumidos = 2
   where user_id = v_uid and not caducado;

  v_flag := false;
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (v_uid, 'vacacion', v_lun + 42, v_lun + 46, repeat('x', 201));
  exception when check_violation then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('G1. Descripción de 201 caracteres se rechaza', 'true', v_flag::text);

  v_flag := false;
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (v_uid, 'vacacion', v_lun + 42, v_lun + 46, null);
  exception when check_violation then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('G2. Descripción obligatoria', 'true', v_flag::text);

  v_flag := false;
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (v_uid, 'vacacion', v_lun + 42, v_lun + 90, 'SMOKE excede saldo sin justificar');
  exception when check_violation then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('G3. Excede saldo sin justificación se bloquea', 'true', v_flag::text);

  insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion, justificacion)
  values (v_uid, 'vacacion', v_lun + 42, v_lun + 90, 'SMOKE excede saldo',
          'Días adelantados por viaje familiar programado con anticipación.')
  returning id, es_adelanto into v_req2, v_flag;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('G4. Con justificación se acepta como adelanto', 'true', v_flag::text);
  delete from public.requests where id = v_req2;

  -- ===================================================================
  -- BLOQUE H — Permisos categorizados
  -- ===================================================================
  select count(*) into v_cnt from public.permission_types where activo;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('H1. Catálogo de permisos cargado', 'true', (v_cnt >= 16)::text);

  v_flag := false;
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion, justificacion)
    values (v_uid, 'permiso', v_lun + 42, v_lun + 42, 'SMOKE sin categoría', 'Justificación suficiente aquí.');
  exception when check_violation or raise_exception then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('H2. Permiso sin categoría se rechaza', 'true', v_flag::text);

  v_flag := false;
  begin
    insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin, descripcion)
    values (v_uid, 'permiso', v_pt_medica, v_lun + 42, v_lun + 42, 'SMOKE cita sin justificar');
  exception when raise_exception then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('H3. Cita médica exige justificación', 'true', v_flag::text);

  v_flag := false;
  begin
    insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin, descripcion, justificacion)
    values (v_uid, 'permiso', v_pt_medica, v_lun + 42, v_lun + 46, 'SMOKE excede días',
            'Control médico programado en el hospital.');
  exception when raise_exception then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('H4. Cita médica respeta el máximo de 1 día', 'true', v_flag::text);

  -- ===================================================================
  -- BLOQUE I — Adjuntos y firma electrónica (validación diferida)
  -- ===================================================================
  -- I1: cita médica sin adjunto ni firma -> rechazada al confirmar
  v_flag := false;
  begin
    insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                                 hora_inicio, hora_fin, descripcion, justificacion)
    values (v_uid, 'permiso', v_pt_medica, v_lun + 42, v_lun + 42, '08:00', '12:00',
            'SMOKE cita médica', 'Control médico programado en el hospital del IESS.');
    execute 'set constraints all immediate';
  exception when raise_exception then
    v_flag := true;
    execute 'set constraints all deferred';
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('I1. Permiso médico sin respaldo se rechaza', 'true', v_flag::text);

  -- Firma registrada del empleado
  insert into public.signatures (user_id, tipo, contenido, hash_sha256)
  values (v_uid, 'dibujada', 'data:image/svg+xml;base64,U01PS0U=',
          encode(digest('SMOKE firma', 'sha256'), 'hex'))
  returning id into v_sig;

  select count(*) into v_cnt from public.signatures where user_id = v_uid and activa;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('I2. Firma registrada y activa', '1', v_cnt::text);

  v_flag := false;
  begin
    insert into public.signatures (user_id, tipo, contenido, hash_sha256)
    values (v_uid, 'dibujada', 'data:image/svg+xml;base64,T1RSQQ==', 'otro_hash');
  exception when unique_violation then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('I3. Solo una firma activa por usuario', 'true', v_flag::text);

  -- I4: misma solicitud CON adjunto y firma -> aceptada
  v_flag := true;
  begin
    insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                                 hora_inicio, hora_fin, descripcion, justificacion)
    values (v_uid, 'permiso', v_pt_medica, v_lun + 42, v_lun + 42, '08:00', '12:00',
            'SMOKE cita médica', 'Control médico programado en el hospital del IESS.')
    returning id into v_req2;

    insert into public.request_attachments
      (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes, subido_por)
    values (v_req2, 'solicitudes/' || v_req2 || '/cita.pdf', 'cita.pdf', 'application/pdf', 20480, v_uid);

    insert into public.request_signatures (request_id, user_id, rol_firma, signature_id, hash_sha256)
    values (v_req2, v_uid, 'solicitante', v_sig, encode(digest('SMOKE firma', 'sha256'), 'hex'));

    execute 'set constraints all immediate';
    execute 'set constraints all deferred';
  exception when raise_exception then
    v_flag := false;
    execute 'set constraints all deferred';
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('I4. Permiso médico con adjunto y firma se acepta', 'true', v_flag::text);

  select horas_solicitadas into v_dias from public.requests where id = v_req2;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('I5. Horas calculadas del permiso (08:00-12:00)', '4.00', v_dias::text);

  v_flag := false;
  begin
    insert into public.request_attachments
      (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes)
    values (v_req2, 'x/y.exe', 'virus.exe', 'application/x-msdownload', 1024);
  exception when check_violation then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('I6. Adjunto con tipo no permitido se rechaza', 'true', v_flag::text);

  v_flag := false;
  begin
    insert into public.request_attachments
      (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes)
    values (v_req2, 'x/y.pdf', 'enorme.pdf', 'application/pdf', 20971520);
  exception when check_violation then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('I7. Adjunto mayor a 10 MB se rechaza', 'true', v_flag::text);

  -- ===================================================================
  -- BLOQUE J — Permiso con cargo a vacaciones
  -- ===================================================================
  select dias_vacaciones into v_saldo from public.users where id = v_uid;
  insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                               descripcion, justificacion)
  values (v_uid, 'permiso', v_pt_person, v_lun + 49, v_lun + 50,
          'SMOKE asunto personal', 'Trámite personal impostergable en la ciudad.')
  returning id into v_req2;

  insert into public.request_signatures (request_id, user_id, rol_firma, signature_id, hash_sha256)
  values (v_req2, v_uid, 'solicitante', v_sig, encode(digest('SMOKE firma', 'sha256'), 'hex'));

  update public.requests set estado = 'pendiente_rrhh' where id = v_req2;
  update public.requests set estado = 'aprobado'       where id = v_req2;

  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('J1. Permiso personal descuenta vacaciones', (v_saldo - 2)::text,
     (select dias_vacaciones::text from public.users where id = v_uid));

  -- Permiso que NO descuenta (caso fortuito)
  select dias_vacaciones into v_saldo from public.users where id = v_uid;
  insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                               descripcion, justificacion)
  values (v_uid, 'permiso', v_pt_caso, v_lun + 56, v_lun + 56,
          'SMOKE caso fortuito', 'Cierre de vía por deslizamiento de tierra.')
  returning id into v_req2;
  insert into public.request_signatures (request_id, user_id, rol_firma, signature_id, hash_sha256)
  values (v_req2, v_uid, 'solicitante', v_sig, encode(digest('SMOKE firma', 'sha256'), 'hex'));
  update public.requests set estado = 'pendiente_rrhh' where id = v_req2;
  update public.requests set estado = 'aprobado'       where id = v_req2;

  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('J2. Caso fortuito NO descuenta vacaciones', v_saldo::text,
     (select dias_vacaciones::text from public.users where id = v_uid));

  -- ===================================================================
  -- BLOQUE K — Trazabilidad y garita
  -- ===================================================================
  select count(*) into v_cnt from public.audit_logs
   where entidad = 'requests' and entidad_id = v_req::text and accion = 'request_creada';
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('K1. audit_logs registra la creación', '1', v_cnt::text);

  select count(*) into v_cnt from public.audit_logs
   where entidad = 'requests' and entidad_id = v_req::text and accion = 'request_estado_cambiado';
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('K2. audit_logs registra los 3 cambios de estado', '3', v_cnt::text);

  insert into public.visitors (cedula, nombre, empresa, motivo_visita, a_quien_visita_texto)
  values ('0900000001', 'SMOKE Visitante', 'ACME', 'SMOKE entrega de equipos', 'Bodega')
  returning id into v_visit;

  insert into public.access_logs (visitor_id, cedula, tipo_acceso, ip, observacion)
  values (v_visit, '0900000001', 'ingreso_visita', '10.0.0.5'::inet, 'SMOKE ingreso');
  insert into public.access_logs (user_id, cedula, tipo_acceso, ip, observacion)
  values (v_uid, '1700000001', 'salida_empleado', '10.0.0.5'::inet, 'SMOKE salida');

  select count(*) into v_cnt from public.access_logs where observacion like 'SMOKE%';
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('K3. Garita registra accesos de empleado y visita', '2', v_cnt::text);

  select count(*) into v_cnt from public.visitors where id = v_visit and salida_en is null;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('K4. Visitante queda marcado como dentro', '1', v_cnt::text);

  v_flag := false;
  begin
    insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
    values ('1234567890', 'SMOKE Inválido', 'invalido@smoke.test', 'empleado', current_date);
  exception when check_violation then v_flag := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('K5. CHECK rechaza cédula inválida en users', 'true', v_flag::text);

  ---------------------------------------------------------------------
  -- LIMPIEZA
  ---------------------------------------------------------------------
  delete from public.access_logs where observacion like 'SMOKE%';
  delete from public.audit_logs  where entidad = 'requests'
     and entidad_id in (select id::text from public.requests where user_id = v_uid);
  delete from public.visitors    where id = v_visit;
  delete from public.users       where id = v_uid;
  delete from public.feriados    where nombre = 'SMOKE feriado';

  update _smoke_resultados set ok = (esperado = obtenido);

exception when others then
  get stacked diagnostics v_txt = message_text;
  insert into _smoke_resultados (caso, esperado, obtenido, ok)
  values ('ERROR INESPERADO', 'sin error', v_txt, false);

  delete from public.access_logs where observacion like 'SMOKE%';
  delete from public.visitors    where cedula = '0900000001' and motivo_visita like 'SMOKE%';
  delete from public.users       where email like '%@smoke.test';
  delete from public.feriados    where nombre = 'SMOKE feriado';
  update _smoke_resultados set ok = (esperado = obtenido) where ok is null;
end
$smoke$;

select case when ok then '✅' else '❌' end as r, caso, esperado, obtenido
from _smoke_resultados order by n;
