-- =====================================================================
--  SMOKE TEST 2 — Normativa, ficha del empleado, alertas y seguridad
--
--  Requiere las migraciones 0001 a 0004 aplicadas (0004 crea notifications).
--
--  Se ejecuta de una sola vez, en cualquier sesión. Las sentencias son
--  cortas e independientes: si el editor corta el pegado, el error señala
--  la sección exacta y puede reanudarse desde ahí (las secciones están
--  numeradas y el esquema `smoke` conserva el estado entre ejecuciones).
--  Crea datos con correos @norm.test y los borra en la sección final.
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
delete from public.notifications where user_id in
  (select id from public.users where email like '%@norm.test');
delete from public.users where email like '%@norm.test';

-- ---------------------------------------------------------------------
-- A. Glosario legal
-- ---------------------------------------------------------------------
select smoke.chk('A1. Glosario legal cargado', 'true',
  (select (count(*) >= 20)::text from public.legal_references));

select smoke.chk('A2. Incluye controles ISO', 'true',
  (select (count(*) >= 4)::text from public.legal_references where norma like 'ISO%'));

select smoke.chk('A3. Todo permiso activo tiene base legal', '0',
  (select count(*)::text from public.permission_types where legal_ref is null and activo));

select smoke.chk('A4. Caducidad citada al Art. 75', 'CT_ART_75',
  (select legal_ref from public.app_config where clave = 'acumulacion_max_anios'));

-- ---------------------------------------------------------------------
-- B. Decisiones confirmadas: tope de 30 días y acumulación de 3 años
-- ---------------------------------------------------------------------
select smoke.chk('B1. Tope configurado en 30 días', '30',
  (public.cfg_int('vacaciones_dias_base') + public.cfg_int('vacaciones_dias_extra_max'))::text);

select smoke.chk('B2. Acumulación configurada en 3 años', '3',
  public.cfg_int('acumulacion_max_anios')::text);

select smoke.chk('B3. dias_por_antiguedad respeta el tope', '30',
  public.dias_por_antiguedad(40)::text);

-- ---------------------------------------------------------------------
-- C. Ficha del empleado
-- ---------------------------------------------------------------------
insert into public.users (cedula, nombre, email, rol, fecha_ingreso, estado_civil,
                          direccion, tipo_sangre, telefono, tipo_contrato)
values ('1700000001', 'NORM Empleado', 'empleado@norm.test', 'empleado',
        (current_date - make_interval(years => 7))::date, 'casado',
        'Av. Amazonas y Naciones Unidas, Quito', 'O+', '0998887766', 'indefinido');

insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
values ('0900000001', 'NORM Jefe', 'jefe@norm.test', 'jefe', current_date - 800);

insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
values ('1100000007', 'NORM RRHH', 'rrhh2@norm.test', 'rrhh', current_date - 900);

select smoke.pon('uid',  (select id::text from public.users where email = 'empleado@norm.test'));
select smoke.pon('jefe', (select id::text from public.users where email = 'jefe@norm.test'));
select smoke.pon('rrhh', (select id::text from public.users where email = 'rrhh2@norm.test'));

update public.users set jefe_id = smoke.uid('jefe') where id = smoke.uid('uid');

do $$ declare v boolean := false; begin
  update public.users set tipo_sangre = 'Z+' where id = smoke.uid('uid');
exception when check_violation then v := true;
end $$;
select smoke.chk('C1. Tipo de sangre inválido se rechaza', 'true',
  (select (tipo_sangre = 'O+')::text from public.users where id = smoke.uid('uid')));

do $$ begin
  begin
    update public.users set tiene_discapacidad = true, porcentaje_discapacidad = null
     where id = smoke.uid('uid');
    perform smoke.chk('C2. Discapacidad exige porcentaje', 'true', 'false');
  exception when check_violation then
    perform smoke.chk('C2. Discapacidad exige porcentaje', 'true', 'true');
  end;
end $$;

do $$ begin
  begin
    update public.users set fecha_salida = fecha_ingreso - 1 where id = smoke.uid('uid');
    perform smoke.chk('C3. Fecha de salida posterior al ingreso', 'true', 'false');
  exception when check_violation then
    perform smoke.chk('C3. Fecha de salida posterior al ingreso', 'true', 'true');
  end;
end $$;

-- Cargas familiares (sustentan el Art. 42 núm. 30)
insert into public.family_members (user_id, nombre, cedula, parentesco, grado_consanguinidad, es_carga_familiar)
values (smoke.uid('uid'), 'NORM Hijo', '0926687856', 'hijo', 1, true);

insert into public.family_members (user_id, nombre, parentesco, grado_consanguinidad, fecha_nacimiento)
values (smoke.uid('uid'), 'NORM Madre', 'madre', 1, '1960-05-10');

select smoke.chk('C4. Cargas familiares registradas', '2',
  (select count(*)::text from public.family_members where user_id = smoke.uid('uid')));

do $$ begin
  begin
    insert into public.family_members (user_id, nombre, cedula, parentesco)
    values (smoke.uid('uid'), 'NORM Falso', '1234567890', 'hermano');
    perform smoke.chk('C5. Cédula inválida de familiar se rechaza', 'true', 'false');
  exception when check_violation then
    perform smoke.chk('C5. Cédula inválida de familiar se rechaza', 'true', 'true');
  end;
end $$;

insert into public.emergency_contacts (user_id, nombre, parentesco, telefono, es_principal)
values (smoke.uid('uid'), 'NORM Esposa', 'conyuge', '0987654321', true);

do $$ begin
  begin
    insert into public.emergency_contacts (user_id, nombre, parentesco, telefono, es_principal)
    values (smoke.uid('uid'), 'NORM Hermano', 'hermano', '0987000000', true);
    perform smoke.chk('C6. Un solo contacto de emergencia principal', 'true', 'false');
  exception when unique_violation then
    perform smoke.chk('C6. Un solo contacto de emergencia principal', 'true', 'true');
  end;
end $$;

-- ---------------------------------------------------------------------
-- D. Explicación del saldo
-- ---------------------------------------------------------------------
select public.generar_periodos_vacaciones(smoke.uid('uid'));
select public.caducar_periodos_vencidos();
select smoke.pon('saldo_json', public.explicar_saldo(smoke.uid('uid'))::text);

select smoke.chk('D1. Años de servicio calculados', '7',
  (smoke.dame('saldo_json')::jsonb)->>'anios_servicio');

select smoke.chk('D2. Días del año actual = 17', '17',
  (smoke.dame('saldo_json')::jsonb)->>'dias_por_anio_actual');

select smoke.chk('D3. Devuelve la base legal', 'true',
  (jsonb_array_length((smoke.dame('saldo_json')::jsonb)->'base_legal') >= 4)::text);

select smoke.chk('D4. Explica cada período', 'true',
  (jsonb_array_length((smoke.dame('saldo_json')::jsonb)->'periodos') >= 7)::text);

select smoke.chk('D5. Informa el próximo vencimiento', 'true',
  ((smoke.dame('saldo_json')::jsonb)->'proximo_vencimiento' is not null)::text);

select smoke.chk('D6. La explicación cita el Art. 69', 'true',
  (((smoke.dame('saldo_json')::jsonb)->'periodos'->6->>'explicacion') like '%Art. 69%')::text);

-- ---------------------------------------------------------------------
-- E. Alertas de vacaciones
-- ---------------------------------------------------------------------
select public.generar_alertas_vacaciones();

select smoke.chk('E1. Alerta de saldo alto al empleado', '1',
  (select count(*)::text from public.notifications
    where user_id = smoke.uid('uid') and tipo = 'saldo_alto'));

select public.generar_alertas_vacaciones();

select smoke.chk('E2. No se duplica al correr de nuevo', '1',
  (select count(*)::text from public.notifications
    where user_id = smoke.uid('uid') and tipo = 'saldo_alto'));

select smoke.chk('E3. El mensaje sugiere tomar vacaciones', 'true',
  (select (mensaje like '%programar sus vacaciones%')::text from public.notifications
    where user_id = smoke.uid('uid') and tipo = 'saldo_alto' limit 1));

-- Se fuerza un vencimiento cercano para disparar la alerta de caducidad
update public.vacation_periods set vence_en = current_date + 30
 where user_id = smoke.uid('uid') and not caducado and dias_saldo > 0
   and periodo = (select min(periodo) from public.vacation_periods
                   where user_id = smoke.uid('uid') and not caducado and dias_saldo > 0);

select public.generar_alertas_vacaciones();

select smoke.chk('E4. Alerta de caducidad al empleado', '1',
  (select count(*)::text from public.notifications
    where user_id = smoke.uid('uid') and tipo = 'vacaciones_por_caducar'));

select smoke.chk('E5. La misma alerta llega a RRHH', '1',
  (select count(*)::text from public.notifications
    where user_id = smoke.uid('rrhh') and tipo = 'vacaciones_por_caducar'));

select smoke.chk('E6. La alerta cita el Art. 75', 'CT_ART_75',
  (select legal_ref from public.notifications
    where user_id = smoke.uid('uid') and tipo = 'vacaciones_por_caducar' limit 1));

select smoke.chk('E7. Severidad crítica', 'critica',
  (select severidad::text from public.notifications
    where user_id = smoke.uid('uid') and tipo = 'vacaciones_por_caducar' limit 1));

-- ---------------------------------------------------------------------
-- F. Notificaciones del flujo de solicitudes
-- ---------------------------------------------------------------------
update public.vacation_periods set fines_semana_consumidos = 2
 where user_id = smoke.uid('uid') and not caducado;

insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion)
values (smoke.uid('uid'), 'vacacion', current_date + 40, current_date + 44,
        'NORM solicitud de prueba');

select smoke.pon('req', (select id::text from public.requests
                            where user_id = smoke.uid('uid') order by created_at desc limit 1));

select smoke.chk('F1. Al crear solicitud avisa al jefe', '1',
  (select count(*)::text from public.notifications
    where user_id = smoke.uid('jefe') and tipo = 'solicitud_pendiente'));

update public.requests set estado = 'pendiente_rrhh' where id = smoke.uid('req');

select smoke.chk('F2. Al aprobar el jefe avisa a RRHH', '1',
  (select count(*)::text from public.notifications
    where user_id = smoke.uid('rrhh') and tipo = 'solicitud_pendiente'));

update public.requests set estado = 'aprobado' where id = smoke.uid('req');

select smoke.chk('F3. Al aprobar RRHH avisa al empleado', '1',
  (select count(*)::text from public.notifications
    where user_id = smoke.uid('uid') and tipo = 'solicitud_aprobada'));

-- ---------------------------------------------------------------------
-- G. Trazabilidad
-- ---------------------------------------------------------------------
select smoke.chk('G1. Trazabilidad marca el resultado', 'Aprobada',
  (select resultado from public.v_trazabilidad_solicitudes where solicitud_id = smoke.uid('req')));

select smoke.chk('G2. Resumen por empleado cuenta aprobadas', '1',
  (select aprobadas::text from public.v_trazabilidad_empleado where user_id = smoke.uid('uid')));

select smoke.chk('G3. Resumen acumula los días realmente aprobados',
  (select dias_solicitados::text from public.requests where id = smoke.uid('req')),
  (select dias_vacaciones_tomados::text from public.v_trazabilidad_empleado
    where user_id = smoke.uid('uid')));

select smoke.chk('G4. Resumen general disponible', 'true',
  (select (count(*) >= 1)::text from public.v_resumen_general));

-- ---------------------------------------------------------------------
-- H. Protección de datos (LOPDP)
-- ---------------------------------------------------------------------
insert into public.data_consents (user_id, politica_version, finalidad)
values (smoke.uid('uid'), '1.0', 'Gestión de permisos, vacaciones y control de acceso');

select smoke.chk('H1. Consentimiento registrado', '1',
  (select count(*)::text from public.data_consents where user_id = smoke.uid('uid')));

insert into public.data_subject_requests (user_id, tipo, detalle)
values (smoke.uid('uid'), 'acceso', 'Solicito copia de mis datos personales.');

select smoke.chk('H2. Derecho ARCO con plazo de 15 días', (current_date + 15)::text,
  (select vence_en::text from public.data_subject_requests where user_id = smoke.uid('uid')));

-- ---------------------------------------------------------------------
-- I. Seguridad: el empleado no puede escalar privilegios
-- ---------------------------------------------------------------------
insert into auth.users (id, email) values (gen_random_uuid(), 'empleado@norm.test');
update public.users set auth_user_id =
  (select id from auth.users where email = 'empleado@norm.test')
 where id = smoke.uid('uid');

-- Nota: el resultado se registra DESPUÉS de restaurar el rol, porque como
-- `authenticated` no se puede escribir en la tabla temporal de resultados.
do $$
declare
  v_auth text := (select auth_user_id::text from public.users where id = smoke.uid('uid'));
  v_uid  uuid := smoke.uid('uid');
  v_rol  boolean := false;
  v_sal  boolean := false;
  v_tel  boolean := true;
begin
  perform set_config('request.jwt.claim.sub', v_auth, true);
  execute 'set local role authenticated';

  begin
    update public.users set rol = 'admin' where id = v_uid;
  exception when others then v_rol := true;
  end;

  begin
    update public.users set dias_vacaciones = 999 where id = v_uid;
  exception when others then v_sal := true;
  end;

  begin
    update public.users set telefono = '0999999999' where id = v_uid;
  exception when others then v_tel := false;
  end;

  execute 'set local role none';

  perform smoke.chk('I1. El empleado no puede cambiar su rol',        'true', v_rol::text);
  perform smoke.chk('I2. El empleado no puede inflar su saldo',       'true', v_sal::text);
  perform smoke.chk('I3. El empleado sí puede editar su contacto',    'true', v_tel::text);
end $$;

do $$
declare v_ok boolean := false;
begin
  execute 'set local role authenticated';
  begin
    update public.audit_logs set accion = 'manipulado'
     where entidad_id in (select id::text from public.requests where user_id = smoke.uid('uid'));
  exception when others then v_ok := true;
  end;
  execute 'set local role none';
  perform smoke.chk('I4. Las bitácoras son inmutables', 'true', v_ok::text);
end $$;

-- ---------------------------------------------------------------------
-- Z. Limpieza y resultados
-- ---------------------------------------------------------------------
delete from public.notifications where user_id in
  (select id from public.users where email like '%@norm.test');
delete from public.audit_logs where entidad = 'requests' and entidad_id in
  (select id::text from public.requests where user_id = smoke.uid('uid'));
delete from public.users where email like '%@norm.test';
delete from auth.users where email like '%@norm.test';

-- Resultados (dejar como última sentencia: el editor muestra solo la última)
select case when ok then '✅' else '❌' end as r, caso, esperado, obtenido
from smoke.res order by n;

-- Cuando termine de revisarlos, puede eliminar las utilidades con:
--   drop schema smoke cascade;
