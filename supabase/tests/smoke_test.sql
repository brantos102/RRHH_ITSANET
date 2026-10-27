-- =====================================================================
--  SMOKE TEST 1 — Reglas de vacaciones, permisos, QR y garita
--
--  Requiere las migraciones 0001 y 0002 aplicadas.
--
--  Se ejecuta de una sola vez, en cualquier sesión. Las sentencias son
--  cortas e independientes: si el editor corta el pegado, el error señala
--  la sección exacta y puede reanudarse desde ahí (las secciones están
--  numeradas y el esquema `smoke` conserva el estado entre ejecuciones).
--  Crea datos con correos @smoke.test y los borra en la sección final.
-- =====================================================================

-- ---------------------------------------------------------------------
-- UTILIDADES  (se crean aquí mismo: el editor de Supabase no conserva
-- objetos temporales entre ejecuciones, así que van en un esquema real)
-- ---------------------------------------------------------------------
drop schema if exists smoke cascade;
create schema smoke;

create table smoke.res (
  n serial primary key, caso text, esperado text, obtenido text, ok boolean
);

create table smoke.ctx (clave text primary key, valor text);

create function smoke.chk(p_caso text, p_esperado text, p_obtenido text)
returns void language sql as $f$
  insert into smoke.res (caso, esperado, obtenido, ok)
  values (p_caso, p_esperado, p_obtenido, p_esperado is not distinct from p_obtenido);
$f$;

create function smoke.pon(p_clave text, p_valor text)
returns void language sql as $f$
  insert into smoke.ctx values (p_clave, p_valor)
  on conflict (clave) do update set valor = excluded.valor;
$f$;

create function smoke.dame(p_clave text)
returns text language sql stable as $f$
  select valor from smoke.ctx where clave = p_clave;
$f$;

create function smoke.uid(p_clave text)
returns uuid language sql stable as $f$
  select valor::uuid from smoke.ctx where clave = p_clave;
$f$;

create function smoke.fecha(p_clave text)
returns date language sql stable as $f$
  select valor::date from smoke.ctx where clave = p_clave;
$f$;

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
select smoke.chk('A1. Cédula válida',                 'true',  public.es_cedula_valida('0926687856')::text);
select smoke.chk('A2. Dígito verificador incorrecto', 'false', public.es_cedula_valida('0926687857')::text);
select smoke.chk('A3. Solo 9 dígitos',                'false', public.es_cedula_valida('092668785')::text);
select smoke.chk('A4. Provincia inexistente (99)',    'false', public.es_cedula_valida('9926687856')::text);
select smoke.chk('A5. Tercer dígito > 5',             'false', public.es_cedula_valida('0976687856')::text);
select smoke.chk('A6. Contiene letras',               'false', public.es_cedula_valida('09A6687856')::text);
select smoke.chk('A7. Valor nulo',                    'false', coalesce(public.es_cedula_valida(null)::text, 'false'));

-- ---------------------------------------------------------------------
-- B. Días de vacaciones por antigüedad (Art. 69 CT)
-- ---------------------------------------------------------------------
select smoke.chk('B1. Año 1 de servicio = 15 días',       '15', public.dias_por_antiguedad(1)::text);
select smoke.chk('B2. Año 5 de servicio = 15 días',       '15', public.dias_por_antiguedad(5)::text);
select smoke.chk('B3. Año 6 de servicio = 16 días',       '16', public.dias_por_antiguedad(6)::text);
select smoke.chk('B4. Año 7 de servicio = 17 días',       '17', public.dias_por_antiguedad(7)::text);
select smoke.chk('B5. Año 10 de servicio = 20 días',      '20', public.dias_por_antiguedad(10)::text);
select smoke.chk('B6. Año 20 de servicio = 30 (tope)',    '30', public.dias_por_antiguedad(20)::text);
select smoke.chk('B7. Año 30 respeta el tope de 30',      '30', public.dias_por_antiguedad(30)::text);

-- ---------------------------------------------------------------------
-- C. Cálculo de días (regla Ecuador) con un feriado de prueba
-- ---------------------------------------------------------------------
select smoke.pon('lun', (date_trunc('week', date '2099-07-07')::date)::text);

insert into public.feriados (fecha, nombre)
values (smoke.fecha('lun') + 2, 'SMOKE feriado');

select smoke.chk('C1. Permiso lun-vie sin feriado = 5 hábiles', '5',
  public.calcular_dias('permiso',  smoke.fecha('lun') + 7, smoke.fecha('lun') + 11)::text);

select smoke.chk('C2. Vacación lun-dom sin feriado = 7 calendario', '7',
  public.calcular_dias('vacacion', smoke.fecha('lun') + 7, smoke.fecha('lun') + 13)::text);

select smoke.chk('C3. Permiso lun-vie con feriado = 4', '4',
  public.calcular_dias('permiso',  smoke.fecha('lun'), smoke.fecha('lun') + 4)::text);

select smoke.chk('C4. Vacación lun-dom con feriado = 6', '6',
  public.calcular_dias('vacacion', smoke.fecha('lun'), smoke.fecha('lun') + 6)::text);

select smoke.chk('C5. Fecha fin anterior al inicio = 0', '0',
  public.calcular_dias('vacacion', smoke.fecha('lun') + 5, smoke.fecha('lun'))::text);

-- ---------------------------------------------------------------------
-- D. Períodos anuales del empleado
-- ---------------------------------------------------------------------
insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
values ('1700000001', 'SMOKE Empleado', 'empleado@smoke.test', 'empleado',
        (current_date - make_interval(years => 7))::date);

select smoke.pon('uid', (select id::text from public.users where email = 'empleado@smoke.test'));
select public.generar_periodos_vacaciones(smoke.uid('uid'));
select public.caducar_periodos_vencidos();

select smoke.chk('D1. Período 5 asigna 15 días', '15.00',
  (select dias_asignados::text from public.vacation_periods
    where user_id = smoke.uid('uid') and periodo = 5));

select smoke.chk('D2. Período 6 asigna 16 días', '16.00',
  (select dias_asignados::text from public.vacation_periods
    where user_id = smoke.uid('uid') and periodo = 6));

select smoke.chk('D3. Período 7 asigna 17 días', '17.00',
  (select dias_asignados::text from public.vacation_periods
    where user_id = smoke.uid('uid') and periodo = 7));

select smoke.chk('D4. Existe período en curso no devengado', '1',
  (select count(*)::text from public.vacation_periods
    where user_id = smoke.uid('uid') and periodo = 8 and not devengado));

select smoke.chk('D5. Períodos de más de 3 años caducados', 'true',
  (select (count(*) >= 3)::text from public.vacation_periods
    where user_id = smoke.uid('uid') and caducado));

select smoke.chk('D6. Saldo = suma de períodos vigentes (15+16+17)', '48.00',
  (select dias_vacaciones::text from public.users where id = smoke.uid('uid')));

select public.cargar_saldo_inicial(smoke.uid('uid'), 12.5, 0);

select smoke.chk('D7. cargar_saldo_inicial cuadra el saldo', '12.50',
  (select dias_vacaciones::text from public.users where id = smoke.uid('uid')));

-- ---------------------------------------------------------------------
-- E. Regla de los 2 fines de semana obligatorios
-- ---------------------------------------------------------------------
select smoke.chk('E1. Fin de semana completo en lun-dom', '1',
  public.fines_de_semana_completos(smoke.fecha('lun') + 7, smoke.fecha('lun') + 13)::text);

select smoke.chk('E2. Ninguno en lun-vie', '0',
  public.fines_de_semana_completos(smoke.fecha('lun') + 7, smoke.fecha('lun') + 11)::text);

select smoke.chk('E3. Sábado suelto no cuenta', '0',
  public.fines_de_semana_completos(smoke.fecha('lun') + 7, smoke.fecha('lun') + 12)::text);

select smoke.chk('E4. Dos semanas = 2 fines de semana', '2',
  public.fines_de_semana_completos(smoke.fecha('lun') + 7, smoke.fecha('lun') + 20)::text);

select smoke.chk('E5. Fines de semana pendientes del empleado', '2',
  public.fines_semana_pendientes(smoke.uid('uid'))::text);

do $$
declare v_bloq boolean := false; v_msg text := '';
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (smoke.uid('uid'), 'vacacion', smoke.fecha('lun') + 7, smoke.fecha('lun') + 11,
            'SMOKE termina viernes');
  exception when raise_exception then
    v_bloq := true;
    get stacked diagnostics v_msg = message_text;
  end;
  perform smoke.chk('E6. Vacación que termina viernes se bloquea', 'true', v_bloq::text);
  perform smoke.chk('E7. El error sugiere incluir sábado y domingo', 'true',
                      (v_msg like '%sábado y domingo%')::text);
end $$;

do $$
declare v_bloq boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (smoke.uid('uid'), 'vacacion', smoke.fecha('lun') + 7, smoke.fecha('lun') + 10,
            'SMOKE empieza lunes');
  exception when raise_exception then v_bloq := true;
  end;
  perform smoke.chk('E8. Vacación que empieza lunes se bloquea', 'true', v_bloq::text);
end $$;

do $$
declare v_ok boolean := true; v_id uuid;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (smoke.uid('uid'), 'vacacion', smoke.fecha('lun') + 8, smoke.fecha('lun') + 10,
            'SMOKE martes a jueves')
    returning id into v_id;
    delete from public.requests where id = v_id;
  exception when raise_exception then v_ok := false;
  end;
  perform smoke.chk('E9. Vacación martes-jueves se permite', 'true', v_ok::text);
end $$;

insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
values (smoke.uid('uid'), 'vacacion', smoke.fecha('lun') + 7, smoke.fecha('lun') + 13,
        'SMOKE incluye fin de semana');

select smoke.pon('req', (select id::text from public.requests
                            where user_id = smoke.uid('uid') order by created_at desc limit 1));

select smoke.chk('E10. Rango lun-dom se acepta', 'true',
  (smoke.dame('req') is not null)::text);

select smoke.chk('E11. Registra 1 fin de semana completo', '1',
  (select fines_semana::text from public.requests where id = smoke.uid('req')));

select smoke.chk('E12. Días calculados = 7 (calendario)', '7.00',
  (select dias_solicitados::text from public.requests where id = smoke.uid('req')));

select smoke.pon('prev', public.previsualizar_solicitud(
  smoke.uid('uid'), 'vacacion', smoke.fecha('lun') + 21, smoke.fecha('lun') + 25, null)::text);

select smoke.chk('E13. Previsualización marca inválido el viernes', 'false',
  (smoke.dame('prev')::jsonb)->>'valido');

select smoke.chk('E14. Previsualización sugiere domingo como fin',
  (smoke.fecha('lun') + 27)::text,
  (smoke.dame('prev')::jsonb)->'rango_sugerido'->>'fin');

-- ---------------------------------------------------------------------
-- F. Flujo de aprobación, QR y consumo por períodos
-- ---------------------------------------------------------------------
do $$
declare v_bloq boolean := false;
begin
  begin
    update public.requests set estado = 'aprobado' where id = smoke.uid('req');
  exception when raise_exception then v_bloq := true;
  end;
  perform smoke.chk('F1. No se puede saltar la aprobación del jefe', 'true', v_bloq::text);
end $$;

update public.requests set estado = 'pendiente_rrhh' where id = smoke.uid('req');
update public.requests set estado = 'aprobado'       where id = smoke.uid('req');

select smoke.chk('F2. Estado final tras aprobar RRHH', 'aprobado',
  (select estado::text from public.requests where id = smoke.uid('req')));

select smoke.chk('F3. Se emite el código QR', 'true',
  (select (qr_hash is not null)::text from public.requests where id = smoke.uid('req')));

select smoke.chk('F4. Saldo descontado (12.5 - 7)', '5.50',
  (select dias_vacaciones::text from public.users where id = smoke.uid('uid')));

select smoke.chk('F5. Se acredita el fin de semana consumido', '1',
  (select fines_semana_consumidos::text from public.vacation_periods
    where user_id = smoke.uid('uid') and not caducado order by periodo limit 1));

select smoke.chk('F6. Queda 1 fin de semana obligatorio', '1',
  public.fines_semana_pendientes(smoke.uid('uid'))::text);

do $$
declare v_bloq boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (smoke.uid('uid'), 'vacacion', smoke.fecha('lun') + 35, smoke.fecha('lun') + 39,
            'SMOKE segundo viernes');
  exception when raise_exception then v_bloq := true;
  end;
  perform smoke.chk('F7. Con 1 fin de semana pendiente sigue bloqueando', 'true', v_bloq::text);
end $$;

update public.requests set estado = 'cancelado' where id = smoke.uid('req');

select smoke.chk('F8. Saldo devuelto al cancelar (5.5 + 7)', '12.50',
  (select dias_vacaciones::text from public.users where id = smoke.uid('uid')));

select smoke.chk('F9. Fin de semana devuelto', '2',
  public.fines_semana_pendientes(smoke.uid('uid'))::text);

-- ---------------------------------------------------------------------
-- G. Descripción y justificación
-- ---------------------------------------------------------------------
update public.vacation_periods set fines_semana_consumidos = 2
 where user_id = smoke.uid('uid') and not caducado;

do $$
declare v boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (smoke.uid('uid'), 'vacacion', smoke.fecha('lun') + 42, smoke.fecha('lun') + 46,
            repeat('x', 201));
  exception when check_violation then v := true;
  end;
  perform smoke.chk('G1. Descripción de 201 caracteres se rechaza', 'true', v::text);
end $$;

do $$
declare v boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (smoke.uid('uid'), 'vacacion', smoke.fecha('lun') + 42, smoke.fecha('lun') + 46, null);
  exception when check_violation then v := true;
  end;
  perform smoke.chk('G2. Descripción obligatoria', 'true', v::text);
end $$;

do $$
declare v boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
    values (smoke.uid('uid'), 'vacacion', smoke.fecha('lun') + 42, smoke.fecha('lun') + 90,
            'SMOKE excede saldo sin justificar');
  exception when check_violation then v := true;
  end;
  perform smoke.chk('G3. Excede saldo sin justificación se bloquea', 'true', v::text);
end $$;

do $$
declare v_ad boolean; v_id uuid;
begin
  insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion, justificacion)
  values (smoke.uid('uid'), 'vacacion', smoke.fecha('lun') + 42, smoke.fecha('lun') + 90,
          'SMOKE excede saldo', 'Días adelantados por viaje familiar programado con anticipación.')
  returning id, es_adelanto into v_id, v_ad;
  delete from public.requests where id = v_id;
  perform smoke.chk('G4. Con justificación se acepta como adelanto', 'true', v_ad::text);
end $$;

-- ---------------------------------------------------------------------
-- H. Permisos categorizados
-- ---------------------------------------------------------------------
select smoke.chk('H1. Catálogo de permisos cargado', 'true',
  (select (count(*) >= 16)::text from public.permission_types where activo));

do $$
declare v boolean := false;
begin
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion, justificacion)
    values (smoke.uid('uid'), 'permiso', smoke.fecha('lun') + 42, smoke.fecha('lun') + 42,
            'SMOKE sin categoría', 'Justificación suficiente aquí.');
  exception when check_violation or raise_exception then v := true;
  end;
  perform smoke.chk('H2. Permiso sin categoría se rechaza', 'true', v::text);
end $$;

do $$
declare v boolean := false; v_pt smallint;
begin
  select id into v_pt from public.permission_types where codigo = 'cita_medica';
  begin
    insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin, descripcion)
    values (smoke.uid('uid'), 'permiso', v_pt, smoke.fecha('lun') + 42, smoke.fecha('lun') + 42,
            'SMOKE cita sin justificar');
  exception when raise_exception then v := true;
  end;
  perform smoke.chk('H3. Cita médica exige justificación', 'true', v::text);
end $$;

do $$
declare v boolean := false; v_pt smallint;
begin
  select id into v_pt from public.permission_types where codigo = 'cita_medica';
  begin
    insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                                 descripcion, justificacion)
    values (smoke.uid('uid'), 'permiso', v_pt, smoke.fecha('lun') + 42, smoke.fecha('lun') + 46,
            'SMOKE excede días', 'Control médico programado en el hospital.');
  exception when raise_exception then v := true;
  end;
  perform smoke.chk('H4. Cita médica respeta el máximo de 1 día', 'true', v::text);
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
    values (smoke.uid('uid'), 'permiso', v_pt, smoke.fecha('lun') + 42, smoke.fecha('lun') + 42,
            '08:00', '12:00', 'SMOKE cita médica',
            'Control médico programado en el hospital del IESS.');
    execute 'set constraints all immediate';
  exception when raise_exception then
    v := true;
    execute 'set constraints all deferred';
  end;
  perform smoke.chk('I1. Permiso médico sin respaldo se rechaza', 'true', v::text);
end $$;

insert into public.signatures (user_id, tipo, contenido, hash_sha256)
values (smoke.uid('uid'), 'dibujada', 'data:image/svg+xml;base64,U01PS0U=',
        encode(digest('SMOKE firma', 'sha256'), 'hex'));

select smoke.pon('sig', (select id::text from public.signatures
                            where user_id = smoke.uid('uid') and activa));

select smoke.chk('I2. Firma registrada y activa', '1',
  (select count(*)::text from public.signatures where user_id = smoke.uid('uid') and activa));

do $$
declare v boolean := false;
begin
  begin
    insert into public.signatures (user_id, tipo, contenido, hash_sha256)
    values (smoke.uid('uid'), 'dibujada', 'data:image/svg+xml;base64,T1RSQQ==', 'otro_hash');
  exception when unique_violation then v := true;
  end;
  perform smoke.chk('I3. Solo una firma activa por usuario', 'true', v::text);
end $$;

do $$
declare v_ok boolean := true; v_pt smallint; v_id uuid;
begin
  select id into v_pt from public.permission_types where codigo = 'cita_medica';
  begin
    insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                                 hora_inicio, hora_fin, descripcion, justificacion)
    values (smoke.uid('uid'), 'permiso', v_pt, smoke.fecha('lun') + 42, smoke.fecha('lun') + 42,
            '08:00', '12:00', 'SMOKE cita médica',
            'Control médico programado en el hospital del IESS.')
    returning id into v_id;

    insert into public.request_attachments
      (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes, subido_por)
    values (v_id, 'solicitudes/' || v_id || '/cita.pdf', 'cita.pdf', 'application/pdf',
            20480, smoke.uid('uid'));

    insert into public.request_signatures (request_id, user_id, rol_firma, signature_id, hash_sha256)
    values (v_id, smoke.uid('uid'), 'solicitante', smoke.uid('sig'),
            encode(digest('SMOKE firma', 'sha256'), 'hex'));

    execute 'set constraints all immediate';
    execute 'set constraints all deferred';
    perform smoke.pon('req_med', v_id::text);
  exception when raise_exception then
    v_ok := false;
    execute 'set constraints all deferred';
  end;
  perform smoke.chk('I4. Permiso médico con adjunto y firma se acepta', 'true', v_ok::text);
end $$;

select smoke.chk('I5. Horas calculadas del permiso (08:00-12:00)', '4.00',
  (select horas_solicitadas::text from public.requests where id = smoke.uid('req_med')));

do $$
declare v boolean := false;
begin
  begin
    insert into public.request_attachments
      (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes)
    values (smoke.uid('req_med'), 'x/y.exe', 'virus.exe', 'application/x-msdownload', 1024);
  exception when check_violation then v := true;
  end;
  perform smoke.chk('I6. Adjunto con tipo no permitido se rechaza', 'true', v::text);
end $$;

do $$
declare v boolean := false;
begin
  begin
    insert into public.request_attachments
      (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes)
    values (smoke.uid('req_med'), 'x/y.pdf', 'enorme.pdf', 'application/pdf', 20971520);
  exception when check_violation then v := true;
  end;
  perform smoke.chk('I7. Adjunto mayor a 10 MB se rechaza', 'true', v::text);
end $$;

-- ---------------------------------------------------------------------
-- J. Permisos que descuentan (o no) vacaciones
-- ---------------------------------------------------------------------
do $$
declare v_pt smallint; v_id uuid; v_antes numeric;
begin
  select dias_vacaciones into v_antes from public.users where id = smoke.uid('uid');
  select id into v_pt from public.permission_types where codigo = 'permiso_personal';

  insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                               descripcion, justificacion)
  values (smoke.uid('uid'), 'permiso', v_pt, smoke.fecha('lun') + 49, smoke.fecha('lun') + 50,
          'SMOKE asunto personal', 'Trámite personal impostergable en la ciudad.')
  returning id into v_id;

  insert into public.request_signatures (request_id, user_id, rol_firma, signature_id, hash_sha256)
  values (v_id, smoke.uid('uid'), 'solicitante', smoke.uid('sig'),
          encode(digest('SMOKE firma', 'sha256'), 'hex'));

  update public.requests set estado = 'pendiente_rrhh' where id = v_id;
  update public.requests set estado = 'aprobado'       where id = v_id;

  perform smoke.chk('J1. Permiso personal descuenta vacaciones', (v_antes - 2)::text,
    (select dias_vacaciones::text from public.users where id = smoke.uid('uid')));
end $$;

do $$
declare v_pt smallint; v_id uuid; v_antes numeric;
begin
  select dias_vacaciones into v_antes from public.users where id = smoke.uid('uid');
  select id into v_pt from public.permission_types where codigo = 'caso_fortuito';

  insert into public.requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                               descripcion, justificacion)
  values (smoke.uid('uid'), 'permiso', v_pt, smoke.fecha('lun') + 56, smoke.fecha('lun') + 56,
          'SMOKE caso fortuito', 'Cierre de vía por deslizamiento de tierra.')
  returning id into v_id;

  insert into public.request_signatures (request_id, user_id, rol_firma, signature_id, hash_sha256)
  values (v_id, smoke.uid('uid'), 'solicitante', smoke.uid('sig'),
          encode(digest('SMOKE firma', 'sha256'), 'hex'));

  update public.requests set estado = 'pendiente_rrhh' where id = v_id;
  update public.requests set estado = 'aprobado'       where id = v_id;

  perform smoke.chk('J2. Caso fortuito NO descuenta vacaciones', v_antes::text,
    (select dias_vacaciones::text from public.users where id = smoke.uid('uid')));
end $$;

-- ---------------------------------------------------------------------
-- K. Trazabilidad y garita
-- ---------------------------------------------------------------------
select smoke.chk('K1. audit_logs registra la creación', '1',
  (select count(*)::text from public.audit_logs
    where entidad = 'requests' and entidad_id = smoke.dame('req') and accion = 'request_creada'));

select smoke.chk('K2. audit_logs registra los 3 cambios de estado', '3',
  (select count(*)::text from public.audit_logs
    where entidad = 'requests' and entidad_id = smoke.dame('req')
      and accion = 'request_estado_cambiado'));

insert into public.visitors (cedula, nombre, empresa, motivo_visita, a_quien_visita_texto)
values ('0900000001', 'SMOKE Visitante', 'ACME', 'SMOKE entrega de equipos', 'Bodega');

select smoke.pon('visit', (select id::text from public.visitors
                              where motivo_visita like 'SMOKE%' limit 1));

insert into public.access_logs (visitor_id, cedula, tipo_acceso, ip, observacion)
values (smoke.uid('visit'), '0900000001', 'ingreso_visita', '10.0.0.5'::inet, 'SMOKE ingreso');

insert into public.access_logs (user_id, cedula, tipo_acceso, ip, observacion)
values (smoke.uid('uid'), '1700000001', 'salida_empleado', '10.0.0.5'::inet, 'SMOKE salida');

select smoke.chk('K3. Garita registra accesos de empleado y visita', '2',
  (select count(*)::text from public.access_logs where observacion like 'SMOKE%'));

select smoke.chk('K4. Visitante queda marcado como dentro', '1',
  (select count(*)::text from public.visitors
    where id = smoke.uid('visit') and salida_en is null));

do $$
declare v boolean := false;
begin
  begin
    insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
    values ('1234567890', 'SMOKE Inválido', 'invalido@smoke.test', 'empleado', current_date);
  exception when check_violation then v := true;
  end;
  perform smoke.chk('K5. CHECK rechaza cédula inválida en users', 'true', v::text);
end $$;

-- ---------------------------------------------------------------------
-- Z. Limpieza y resultados
-- ---------------------------------------------------------------------
delete from public.access_logs where observacion like 'SMOKE%';
delete from public.audit_logs  where entidad = 'requests' and entidad_id in
  (select id::text from public.requests where user_id = smoke.uid('uid'));
delete from public.visitors    where motivo_visita like 'SMOKE%';
delete from public.users       where email like '%@smoke.test';
delete from public.feriados    where nombre = 'SMOKE feriado';

-- Resultados (dejar como última sentencia: el editor muestra solo la última)
select case when ok then '✅' else '❌' end as r, caso, esperado, obtenido
from smoke.res order by n;

-- Cuando termine de revisarlos, puede eliminar las utilidades con:
--   drop schema smoke cascade;
