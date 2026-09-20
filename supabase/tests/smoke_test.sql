-- =====================================================================
--  SMOKE TEST 1 — Reglas de vacaciones, permisos, QR y garita
--
--  REQUISITO: ejecutar antes `_helpers.sql` en la MISMA pestaña del editor.
--
--  Sentencias cortas e independientes: si el editor corta el pegado, el
--  error indica en qué sección ocurrió y se puede reanudar desde ahí.
--  Crea datos con correos @smoke.test y los borra en la sección final.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. Limpieza de corridas anteriores
-- ---------------------------------------------------------------------
delete from public.access_logs where observacion like 'SMOKE%';
delete from public.visitors     where motivo_visita like 'SMOKE%';
delete from public.users        where email like '%@smoke.test';
delete from public.feriados     where nombre = 'SMOKE feriado';

-- ---------------------------------------------------------------------
-- A. Validación de cédula ecuatoriana (módulo 10)
-- ---------------------------------------------------------------------
select pg_temp.chk('A1. Cédula válida',                 'true',  public.es_cedula_valida('0926687856')::text);
select pg_temp.chk('A2. Dígito verificador incorrecto', 'false', public.es_cedula_valida('0926687857')::text);
select pg_temp.chk('A3. Solo 9 dígitos',                'false', public.es_cedula_valida('092668785')::text);
select pg_temp.chk('A4. Provincia inexistente (99)',    'false', public.es_cedula_valida('9926687856')::text);
select pg_temp.chk('A5. Tercer dígito > 5',             'false', public.es_cedula_valida('0976687856')::text);
select pg_temp.chk('A6. Contiene letras',               'false', public.es_cedula_valida('09A6687856')::text);
select pg_temp.chk('A7. Valor nulo',                    'false', coalesce(public.es_cedula_valida(null)::text, 'false'));

-- ---------------------------------------------------------------------
-- B. Días de vacaciones por antigüedad (Art. 69 CT)
-- ---------------------------------------------------------------------
select pg_temp.chk('B1. Año 1 de servicio = 15 días',       '15', public.dias_por_antiguedad(1)::text);
select pg_temp.chk('B2. Año 5 de servicio = 15 días',       '15', public.dias_por_antiguedad(5)::text);
select pg_temp.chk('B3. Año 6 de servicio = 16 días',       '16', public.dias_por_antiguedad(6)::text);
select pg_temp.chk('B4. Año 7 de servicio = 17 días',       '17', public.dias_por_antiguedad(7)::text);
select pg_temp.chk('B5. Año 10 de servicio = 20 días',      '20', public.dias_por_antiguedad(10)::text);
select pg_temp.chk('B6. Año 20 de servicio = 30 (tope)',    '30', public.dias_por_antiguedad(20)::text);
select pg_temp.chk('B7. Año 30 respeta el tope de 30',      '30', public.dias_por_antiguedad(30)::text);

-- ---------------------------------------------------------------------
-- C. Cálculo de días (regla Ecuador) con un feriado de prueba
-- ---------------------------------------------------------------------
select pg_temp.pon('lun', (date_trunc('week', date '2099-07-07')::date)::text);

insert into public.feriados (fecha, nombre)
values (pg_temp.fecha('lun') + 2, 'SMOKE feriado');

select pg_temp.chk('C1. Permiso lun-vie sin feriado = 5 hábiles', '5',
  public.calcular_dias('permiso',  pg_temp.fecha('lun') + 7, pg_temp.fecha('lun') + 11)::text);

select pg_temp.chk('C2. Vacación lun-dom sin feriado = 7 calendario', '7',
  public.calcular_dias('vacacion', pg_temp.fecha('lun') + 7, pg_temp.fecha('lun') + 13)::text);

select pg_temp.chk('C3. Permiso lun-vie con feriado = 4', '4',
  public.calcular_dias('permiso',  pg_temp.fecha('lun'), pg_temp.fecha('lun') + 4)::text);

select pg_temp.chk('C4. Vacación lun-dom con feriado = 6', '6',
  public.calcular_dias('vacacion', pg_temp.fecha('lun'), pg_temp.fecha('lun') + 6)::text);

select pg_temp.chk('C5. Fecha fin anterior al inicio = 0', '0',
  public.calcular_dias('vacacion', pg_temp.fecha('lun') + 5, pg_temp.fecha('lun'))::text);

-- ---------------------------------------------------------------------
-- D. Períodos anuales del empleado
-- ---------------------------------------------------------------------
insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
values ('1700000001', 'SMOKE Empleado', 'empleado@smoke.test', 'empleado',
        (current_date - make_interval(years => 7))::date);

select pg_temp.pon('uid', (select id::text from public.users where email = 'empleado@smoke.test'));
select public.generar_periodos_vacaciones(pg_temp.uid('uid'));
select public.caducar_periodos_vencidos();

select pg_temp.chk('D1. Período 5 asigna 15 días', '15.00',
  (select dias_asignados::text from public.vacation_periods
    where user_id = pg_temp.uid('uid') and periodo = 5));

select pg_temp.chk('D2. Período 6 asigna 16 días', '16.00',
  (select dias_asignados::text from public.vacation_periods
    where user_id = pg_temp.uid('uid') and periodo = 6));

select pg_temp.chk('D3. Período 7 asigna 17 días', '17.00',
  (select dias_asignados::text from public.vacation_periods
    where user_id = pg_temp.uid('uid') and periodo = 7));

select pg_temp.chk('D4. Existe período en curso no devengado', '1',
  (select count(*)::text from public.vacation_periods
    where user_id = pg_temp.uid('uid') and periodo = 8 and not devengado));

select pg_temp.chk('D5. Períodos de más de 3 años caducados', 'true',
  (select (count(*) >= 3)::text from public.vacation_periods
    where user_id = pg_temp.uid('uid') and caducado));

select pg_temp.chk('D6. Saldo = suma de períodos vigentes (15+16+17)', '48.00',
  (select dias_vacaciones::text from public.users where id = pg_temp.uid('uid')));

select public.cargar_saldo_inicial(pg_temp.uid('uid'), 12.5, 0);

select pg_temp.chk('D7. cargar_saldo_inicial cuadra el saldo', '12.50',
  (select dias_vacaciones::text from public.users where id = pg_temp.uid('uid')));

-- ---------------------------------------------------------------------
-- E. Regla de los 2 fines de semana obligatorios
-- ---------------------------------------------------------------------
select pg_temp.chk('E1. Fin de semana completo en lun-dom', '1',
  public.fines_de_semana_completos(pg_temp.fecha('lun') + 7, pg_temp.fecha('lun') + 13)::text);

select pg_temp.chk('E2. Ninguno en lun-vie', '0',
  public.fines_de_semana_completos(pg_temp.fecha('lun') + 7, pg_temp.fecha('lun') + 11)::text);

select pg_temp.chk('E3. Sábado suelto no cuenta', '0',
  public.fines_de_semana_completos(pg_temp.fecha('lun') + 7, pg_temp.fecha('lun') + 12)::text);

select pg_temp.chk('E4. Dos semanas = 2 fines de semana', '2',
  public.fines_de_semana_completos(pg_temp.fecha('lun') + 7, pg_temp.fecha('lun') + 20)::text);

select pg_temp.chk('E5. Fines de semana pendientes del empleado', '2',
  public.fines_semana_pendientes(pg_temp.uid('uid'))::text);

do $$
declare v_bloq boolean := false; v_msg text := '';
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (pg_temp.uid('uid'), 'vacacion', pg_temp.fecha('lun') + 7, pg_temp.fecha('lun') + 11,
            'SMOKE termina viernes');
  exception when raise_exception then
    v_bloq := true;
    get stacked diagnostics v_msg = message_text;
  end;
  perform pg_temp.chk('E6. Vacación que termina viernes se bloquea', 'true', v_bloq::text);
  perform pg_temp.chk('E7. El error sugiere incluir sábado y domingo', 'true',
                      (v_msg like '%sábado y domingo%')::text);
end $$;

do $$
declare v_bloq boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (pg_temp.uid('uid'), 'vacacion', pg_temp.fecha('lun') + 7, pg_temp.fecha('lun') + 10,
            'SMOKE empieza lunes');
  exception when raise_exception then v_bloq := true;
  end;
  perform pg_temp.chk('E8. Vacación que empieza lunes se bloquea', 'true', v_bloq::text);
end $$;

do $$
declare v_ok boolean := true; v_id uuid;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (pg_temp.uid('uid'), 'vacacion', pg_temp.fecha('lun') + 8, pg_temp.fecha('lun') + 10,
            'SMOKE martes a jueves')
    returning id into v_id;
    delete from public.requests where id = v_id;
  exception when raise_exception then v_ok := false;
  end;
  perform pg_temp.chk('E9. Vacación martes-jueves se permite', 'true', v_ok::text);
end $$;

insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
values (pg_temp.uid('uid'), 'vacacion', pg_temp.fecha('lun') + 7, pg_temp.fecha('lun') + 13,
        'SMOKE incluye fin de semana');

select pg_temp.pon('req', (select id::text from public.requests
                            where user_id = pg_temp.uid('uid') order by created_at desc limit 1));

select pg_temp.chk('E10. Rango lun-dom se acepta', 'true',
  (pg_temp.dame('req') is not null)::text);

select pg_temp.chk('E11. Registra 1 fin de semana completo', '1',
  (select fines_semana::text from public.requests where id = pg_temp.uid('req')));

select pg_temp.chk('E12. Días calculados = 7 (calendario)', '7.00',
  (select dias_solicitados::text from public.requests where id = pg_temp.uid('req')));

select pg_temp.pon('prev', public.previsualizar_solicitud(
  pg_temp.uid('uid'), 'vacacion', pg_temp.fecha('lun') + 21, pg_temp.fecha('lun') + 25, null)::text);

select pg_temp.chk('E13. Previsualización marca inválido el viernes', 'false',
  (pg_temp.dame('prev')::jsonb)->>'valido');

select pg_temp.chk('E14. Previsualización sugiere domingo como fin',
  (pg_temp.fecha('lun') + 27)::text,
  (pg_temp.dame('prev')::jsonb)->'rango_sugerido'->>'fin');

-- ---------------------------------------------------------------------
-- F. Flujo de aprobación, QR y consumo por períodos
-- ---------------------------------------------------------------------
do $$
declare v_bloq boolean := false;
begin
  begin
    update public.requests set estado = 'aprobado' where id = pg_temp.uid('req');
  exception when raise_exception then v_bloq := true;
  end;
  perform pg_temp.chk('F1. No se puede saltar la aprobación del jefe', 'true', v_bloq::text);
end $$;

update public.requests set estado = 'pendiente_rrhh' where id = pg_temp.uid('req');
update public.requests set estado = 'aprobado'       where id = pg_temp.uid('req');

select pg_temp.chk('F2. Estado final tras aprobar RRHH', 'aprobado',
  (select estado::text from public.requests where id = pg_temp.uid('req')));

select pg_temp.chk('F3. Se emite el código QR', 'true',
  (select (qr_hash is not null)::text from public.requests where id = pg_temp.uid('req')));

select pg_temp.chk('F4. Saldo descontado (12.5 - 7)', '5.50',
  (select dias_vacaciones::text from public.users where id = pg_temp.uid('uid')));

select pg_temp.chk('F5. Se acredita el fin de semana consumido', '1',
  (select fines_semana_consumidos::text from public.vacation_periods
    where user_id = pg_temp.uid('uid') and not caducado order by periodo limit 1));

select pg_temp.chk('F6. Queda 1 fin de semana obligatorio', '1',
  public.fines_semana_pendientes(pg_temp.uid('uid'))::text);

do $$
declare v_bloq boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (pg_temp.uid('uid'), 'vacacion', pg_temp.fecha('lun') + 35, pg_temp.fecha('lun') + 39,
            'SMOKE segundo viernes');
  exception when raise_exception then v_bloq := true;
  end;
  perform pg_temp.chk('F7. Con 1 fin de semana pendiente sigue bloqueando', 'true', v_bloq::text);
end $$;

update public.requests set estado = 'cancelado' where id = pg_temp.uid('req');

select pg_temp.chk('F8. Saldo devuelto al cancelar (5.5 + 7)', '12.50',
  (select dias_vacaciones::text from public.users where id = pg_temp.uid('uid')));

select pg_temp.chk('F9. Fin de semana devuelto', '2',
  public.fines_semana_pendientes(pg_temp.uid('uid'))::text);

-- ---------------------------------------------------------------------
-- G. Descripción y justificación
-- ---------------------------------------------------------------------
update public.vacation_periods set fines_semana_consumidos = 2
 where user_id = pg_temp.uid('uid') and not caducado;

do $$
declare v boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (pg_temp.uid('uid'), 'vacacion', pg_temp.fecha('lun') + 42, pg_temp.fecha('lun') + 46,
            repeat('x', 201));
  exception when check_violation then v := true;
  end;
  perform pg_temp.chk('G1. Descripción de 201 caracteres se rechaza', 'true', v::text);
end $$;

do $$
declare v boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (pg_temp.uid('uid'), 'vacacion', pg_temp.fecha('lun') + 42, pg_temp.fecha('lun') + 46, null);
  exception when check_violation then v := true;
  end;
  perform pg_temp.chk('G2. Descripción obligatoria', 'true', v::text);
end $$;

do $$
declare v boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (pg_temp.uid('uid'), 'vacacion', pg_temp.fecha('lun') + 42, pg_temp.fecha('lun') + 90,
            'SMOKE excede saldo sin justificar');
  exception when check_violation then v := true;
  end;
  perform pg_temp.chk('G3. Excede saldo sin justificación se bloquea', 'true', v::text);
end $$;

do $$
declare v_ad boolean; v_id uuid;
begin
  insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion, justificacion)
  values (pg_temp.uid('uid'), 'vacacion', pg_temp.fecha('lun') + 42, pg_temp.fecha('lun') + 90,
          'SMOKE excede saldo', 'Días adelantados por viaje familiar programado con anticipación.')
  returning id, es_adelanto into v_id, v_ad;
  delete from public.requests where id = v_id;
  perform pg_temp.chk('G4. Con justificación se acepta como adelanto', 'true', v_ad::text);
end $$;

-- ---------------------------------------------------------------------
-- H. Permisos categorizados
-- ---------------------------------------------------------------------
select pg_temp.chk('H1. Catálogo de permisos cargado', 'true',
  (select (count(*) >= 16)::text from public.permission_types where activo));

do $$
declare v boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion, justificacion)
    values (pg_temp.uid('uid'), 'permiso', pg_temp.fecha('lun') + 42, pg_temp.fecha('lun') + 42,
            'SMOKE sin categoría', 'Justificación suficiente aquí.');
  exception when check_violation or raise_exception then v := true;
  end;
  perform pg_temp.chk('H2. Permiso sin categoría se rechaza', 'true', v::text);
end $$;

do $$
declare v boolean := false; v_pt smallint;
begin
  select id into v_pt from public.permission_types where codigo = 'cita_medica';
  begin
    insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin, descripcion)
    values (pg_temp.uid('uid'), 'permiso', v_pt, pg_temp.fecha('lun') + 42, pg_temp.fecha('lun') + 42,
            'SMOKE cita sin justificar');
  exception when raise_exception then v := true;
  end;
  perform pg_temp.chk('H3. Cita médica exige justificación', 'true', v::text);
end $$;

do $$
declare v boolean := false; v_pt smallint;
begin
  select id into v_pt from public.permission_types where codigo = 'cita_medica';
  begin
    insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                                 descripcion, justificacion)
    values (pg_temp.uid('uid'), 'permiso', v_pt, pg_temp.fecha('lun') + 42, pg_temp.fecha('lun') + 46,
            'SMOKE excede días', 'Control médico programado en el hospital.');
  exception when raise_exception then v := true;
  end;
  perform pg_temp.chk('H4. Cita médica respeta el máximo de 1 día', 'true', v::text);
end $$;

-- ---------------------------------------------------------------------
-- I. Adjuntos y firma electrónica (validación diferida al confirmar)
-- ---------------------------------------------------------------------
do $$
declare v boolean := false; v_pt smallint;
begin
  select id into v_pt from public.permission_types where codigo = 'cita_medica';
  begin
    insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                                 hora_inicio, hora_fin, descripcion, justificacion)
    values (pg_temp.uid('uid'), 'permiso', v_pt, pg_temp.fecha('lun') + 42, pg_temp.fecha('lun') + 42,
            '08:00', '12:00', 'SMOKE cita médica',
            'Control médico programado en el hospital del IESS.');
    execute 'set constraints all immediate';
  exception when raise_exception then
    v := true;
    execute 'set constraints all deferred';
  end;
  perform pg_temp.chk('I1. Permiso médico sin respaldo se rechaza', 'true', v::text);
end $$;

insert into public.signatures (user_id, tipo, contenido, hash_sha256)
values (pg_temp.uid('uid'), 'dibujada', 'data:image/svg+xml;base64,U01PS0U=',
        encode(digest('SMOKE firma', 'sha256'), 'hex'));

select pg_temp.pon('sig', (select id::text from public.signatures
                            where user_id = pg_temp.uid('uid') and activa));

select pg_temp.chk('I2. Firma registrada y activa', '1',
  (select count(*)::text from public.signatures where user_id = pg_temp.uid('uid') and activa));

do $$
declare v boolean := false;
begin
  begin
    insert into public.signatures (user_id, tipo, contenido, hash_sha256)
    values (pg_temp.uid('uid'), 'dibujada', 'data:image/svg+xml;base64,T1RSQQ==', 'otro_hash');
  exception when unique_violation then v := true;
  end;
  perform pg_temp.chk('I3. Solo una firma activa por usuario', 'true', v::text);
end $$;

do $$
declare v_ok boolean := true; v_pt smallint; v_id uuid;
begin
  select id into v_pt from public.permission_types where codigo = 'cita_medica';
  begin
    insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                                 hora_inicio, hora_fin, descripcion, justificacion)
    values (pg_temp.uid('uid'), 'permiso', v_pt, pg_temp.fecha('lun') + 42, pg_temp.fecha('lun') + 42,
            '08:00', '12:00', 'SMOKE cita médica',
            'Control médico programado en el hospital del IESS.')
    returning id into v_id;

    insert into public.request_attachments
      (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes, subido_por)
    values (v_id, 'solicitudes/' || v_id || '/cita.pdf', 'cita.pdf', 'application/pdf',
            20480, pg_temp.uid('uid'));

    insert into public.request_signatures (request_id, user_id, rol_firma, signature_id, hash_sha256)
    values (v_id, pg_temp.uid('uid'), 'solicitante', pg_temp.uid('sig'),
            encode(digest('SMOKE firma', 'sha256'), 'hex'));

    execute 'set constraints all immediate';
    execute 'set constraints all deferred';
    perform pg_temp.pon('req_med', v_id::text);
  exception when raise_exception then
    v_ok := false;
    execute 'set constraints all deferred';
  end;
  perform pg_temp.chk('I4. Permiso médico con adjunto y firma se acepta', 'true', v_ok::text);
end $$;

select pg_temp.chk('I5. Horas calculadas del permiso (08:00-12:00)', '4.00',
  (select horas_solicitadas::text from public.requests where id = pg_temp.uid('req_med')));

do $$
declare v boolean := false;
begin
  begin
    insert into public.request_attachments
      (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes)
    values (pg_temp.uid('req_med'), 'x/y.exe', 'virus.exe', 'application/x-msdownload', 1024);
  exception when check_violation then v := true;
  end;
  perform pg_temp.chk('I6. Adjunto con tipo no permitido se rechaza', 'true', v::text);
end $$;

do $$
declare v boolean := false;
begin
  begin
    insert into public.request_attachments
      (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes)
    values (pg_temp.uid('req_med'), 'x/y.pdf', 'enorme.pdf', 'application/pdf', 20971520);
  exception when check_violation then v := true;
  end;
  perform pg_temp.chk('I7. Adjunto mayor a 10 MB se rechaza', 'true', v::text);
end $$;

-- ---------------------------------------------------------------------
-- J. Permisos que descuentan (o no) vacaciones
-- ---------------------------------------------------------------------
do $$
declare v_pt smallint; v_id uuid; v_antes numeric;
begin
  select dias_vacaciones into v_antes from public.users where id = pg_temp.uid('uid');
  select id into v_pt from public.permission_types where codigo = 'permiso_personal';

  insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                               descripcion, justificacion)
  values (pg_temp.uid('uid'), 'permiso', v_pt, pg_temp.fecha('lun') + 49, pg_temp.fecha('lun') + 50,
          'SMOKE asunto personal', 'Trámite personal impostergable en la ciudad.')
  returning id into v_id;

  insert into public.request_signatures (request_id, user_id, rol_firma, signature_id, hash_sha256)
  values (v_id, pg_temp.uid('uid'), 'solicitante', pg_temp.uid('sig'),
          encode(digest('SMOKE firma', 'sha256'), 'hex'));

  update public.requests set estado = 'pendiente_rrhh' where id = v_id;
  update public.requests set estado = 'aprobado'       where id = v_id;

  perform pg_temp.chk('J1. Permiso personal descuenta vacaciones', (v_antes - 2)::text,
    (select dias_vacaciones::text from public.users where id = pg_temp.uid('uid')));
end $$;

do $$
declare v_pt smallint; v_id uuid; v_antes numeric;
begin
  select dias_vacaciones into v_antes from public.users where id = pg_temp.uid('uid');
  select id into v_pt from public.permission_types where codigo = 'caso_fortuito';

  insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                               descripcion, justificacion)
  values (pg_temp.uid('uid'), 'permiso', v_pt, pg_temp.fecha('lun') + 56, pg_temp.fecha('lun') + 56,
          'SMOKE caso fortuito', 'Cierre de vía por deslizamiento de tierra.')
  returning id into v_id;

  insert into public.request_signatures (request_id, user_id, rol_firma, signature_id, hash_sha256)
  values (v_id, pg_temp.uid('uid'), 'solicitante', pg_temp.uid('sig'),
          encode(digest('SMOKE firma', 'sha256'), 'hex'));

  update public.requests set estado = 'pendiente_rrhh' where id = v_id;
  update public.requests set estado = 'aprobado'       where id = v_id;

  perform pg_temp.chk('J2. Caso fortuito NO descuenta vacaciones', v_antes::text,
    (select dias_vacaciones::text from public.users where id = pg_temp.uid('uid')));
end $$;

-- ---------------------------------------------------------------------
-- K. Trazabilidad y garita
-- ---------------------------------------------------------------------
select pg_temp.chk('K1. audit_logs registra la creación', '1',
  (select count(*)::text from public.audit_logs
    where entidad = 'requests' and entidad_id = pg_temp.dame('req') and accion = 'request_creada'));

select pg_temp.chk('K2. audit_logs registra los 3 cambios de estado', '3',
  (select count(*)::text from public.audit_logs
    where entidad = 'requests' and entidad_id = pg_temp.dame('req')
      and accion = 'request_estado_cambiado'));

insert into public.visitors (cedula, nombre, empresa, motivo_visita, a_quien_visita_texto)
values ('0900000001', 'SMOKE Visitante', 'ACME', 'SMOKE entrega de equipos', 'Bodega');

select pg_temp.pon('visit', (select id::text from public.visitors
                              where motivo_visita like 'SMOKE%' limit 1));

insert into public.access_logs (visitor_id, cedula, tipo_acceso, ip, observacion)
values (pg_temp.uid('visit'), '0900000001', 'ingreso_visita', '10.0.0.5'::inet, 'SMOKE ingreso');

insert into public.access_logs (user_id, cedula, tipo_acceso, ip, observacion)
values (pg_temp.uid('uid'), '1700000001', 'salida_empleado', '10.0.0.5'::inet, 'SMOKE salida');

select pg_temp.chk('K3. Garita registra accesos de empleado y visita', '2',
  (select count(*)::text from public.access_logs where observacion like 'SMOKE%'));

select pg_temp.chk('K4. Visitante queda marcado como dentro', '1',
  (select count(*)::text from public.visitors
    where id = pg_temp.uid('visit') and salida_en is null));

do $$
declare v boolean := false;
begin
  begin
    insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
    values ('1234567890', 'SMOKE Inválido', 'invalido@smoke.test', 'empleado', current_date);
  exception when check_violation then v := true;
  end;
  perform pg_temp.chk('K5. CHECK rechaza cédula inválida en users', 'true', v::text);
end $$;

-- ---------------------------------------------------------------------
-- Z. Limpieza y resultados
-- ---------------------------------------------------------------------
delete from public.access_logs where observacion like 'SMOKE%';
delete from public.audit_logs  where entidad = 'requests' and entidad_id in
  (select id::text from public.requests where user_id = pg_temp.uid('uid'));
delete from public.visitors    where motivo_visita like 'SMOKE%';
delete from public.users       where email like '%@smoke.test';
delete from public.feriados    where nombre = 'SMOKE feriado';

select case when ok then '✅' else '❌' end as r, caso, esperado, obtenido
from _res order by n;
