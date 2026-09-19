\set ON_ERROR_STOP on
\pset pager off

-- ===== 1. Validación de cédula (módulo 10) =====
select 'cedula valida'        as caso, public.es_cedula_valida('0926687856') as esperado_t;
select 'digito verif malo'    as caso, public.es_cedula_valida('0926687857') as esperado_f;
select '9 digitos'            as caso, public.es_cedula_valida('092668785')  as esperado_f;
select 'provincia 99'         as caso, public.es_cedula_valida('9926687856') as esperado_f;
select 'tercer digito 7'      as caso, public.es_cedula_valida('0976687856') as esperado_f;
select 'con letras'           as caso, public.es_cedula_valida('09A6687856') as esperado_f;

-- ===== 2. Cálculo de días (regla Ecuador) =====
select 'permiso lun-vie (5 habiles)'      as caso, public.calcular_dias('permiso','2026-09-21','2026-09-25')  as dias;
select 'vacacion lun-dom (7 calendario)'  as caso, public.calcular_dias('vacacion','2026-09-21','2026-09-27') as dias;
select 'vacacion con feriado 09-oct (6)'  as caso, public.calcular_dias('vacacion','2026-10-05','2026-10-11') as dias;
select 'permiso con feriado 09-oct (4)'   as caso, public.calcular_dias('permiso','2026-10-05','2026-10-09')  as dias;

-- ===== 3. Alta de solicitud dentro del saldo =====
insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, motivo)
select id, 'vacacion', '2026-11-09', '2026-11-13', 'Viaje familiar' from public.users where cedula='0926687856';

select 'insert dentro de saldo' as caso, estado, dias_solicitados, saldo_al_solicitar, es_adelanto,
       jefe_id is not null as jefe_asignado
from public.requests order by created_at desc limit 1;

-- ===== 4. Excede saldo SIN justificación -> debe fallar =====
do $$
begin
  insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, motivo)
  select id, 'vacacion', '2026-12-01', '2026-12-31', 'Sin justificar' from public.users where cedula='0926687856';
  raise exception 'FALLO: se permitió exceder el saldo sin justificación';
exception when check_violation then
  raise notice 'OK: bloqueado por justificación obligatoria';
end$$;

-- ===== 5. Excede saldo CON justificación -> es_adelanto = true =====
insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, motivo, justificacion)
select id, 'vacacion', '2026-12-01', '2026-12-31', 'Fin de año',
       'Requiere días adelantados por viaje familiar programado con anticipación.'
from public.users where cedula='0926687856';
select 'excede saldo con justificacion' as caso, dias_solicitados, es_adelanto from public.requests
 where fecha_inicio='2026-12-01';

-- ===== 6. Transición inválida pendiente_jefe -> aprobado =====
do $$
declare v_id uuid;
begin
  select id into v_id from public.requests where fecha_inicio='2026-11-09';
  update public.requests set estado='aprobado' where id=v_id;
  raise exception 'FALLO: se permitió saltar la aprobación del jefe';
exception when raise_exception then
  if sqlerrm like 'FALLO%' then raise; end if;
  raise notice 'OK: transición inválida bloqueada (%)', sqlerrm;
end$$;

-- ===== 7. Flujo completo jefe -> RRHH -> QR + débito de saldo =====
update public.requests r set estado='pendiente_rrhh', jefe_aprobado_por=u.id
  from public.users u where u.cedula='1710034065' and r.fecha_inicio='2026-11-09';
update public.requests r set estado='aprobado', rrhh_aprobado_por=u.id
  from public.users u where u.cedula='0703886002' and r.fecha_inicio='2026-11-09';

select 'aprobacion final' as caso, estado, qr_hash is not null as qr_emitido,
       qr_emitido_en is not null as ts_qr, qr_expira_en::date as qr_expira
from public.requests where fecha_inicio='2026-11-09';

select 'saldo tras aprobar (12.5-5=7.5)' as caso, dias_vacaciones from public.users where cedula='0926687856';
select 'movimiento de saldo' as caso, dias, saldo_previo, saldo_nuevo, motivo from public.vacation_movements;

-- ===== 8. Cancelación de aprobada devuelve saldo =====
update public.requests set estado='cancelado' where fecha_inicio='2026-11-09';
select 'saldo tras cancelar (7.5+5=12.5)' as caso, dias_vacaciones from public.users where cedula='0926687856';

-- ===== 9. Trazabilidad =====
select 'audit_logs' as caso, accion, count(*) from public.audit_logs group by accion order by accion;

-- ===== 10. Garita: access_log + visitante =====
insert into public.visitors (cedula, nombre, empresa, motivo_visita, a_quien_visita_texto, registrado_por)
select '1713175071', 'Proveedor X', 'ACME', 'Entrega de equipos', 'Bodega', id
from public.users where cedula='1713175071';
insert into public.access_logs (visitor_id, cedula, tipo_acceso, guardia_id, ip)
select v.id, v.cedula, 'ingreso_visita', u.id, '10.0.0.5'::inet
from public.visitors v, public.users u where u.cedula='1713175071' limit 1;
select 'garita' as caso, (select count(*) from public.v_visitantes_dentro) as ignorado_sin_rol,
       (select count(*) from public.access_logs) as logs;
