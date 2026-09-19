-- =====================================================================
--  SMOKE TEST — Reglas de negocio del esquema
--
--  SQL puro: se pega y ejecuta tal cual en el SQL Editor de Supabase
--  (no usa meta-comandos de psql como \set o \pset).
--
--  * Crea sus propios datos de prueba (cédulas 1700000001 / 0900000001,
--    correos @smoke.test) y los BORRA al terminar.
--  * No depende de seed.sql ni toca datos reales.
--  * Al final muestra una tabla con el resultado de cada caso.
-- =====================================================================

drop table if exists _smoke_resultados;
create temp table _smoke_resultados (
  n        serial primary key,
  caso     text,
  esperado text,
  obtenido text,
  ok       boolean
);

do $smoke$
declare
  v_user_id    uuid;
  v_req_ok     uuid;
  v_req_excede uuid;
  v_visit_id   uuid;
  v_lun        date;
  v_feriado    date;
  v_estado     public.request_status;
  v_dias       numeric;
  v_adelanto   boolean;
  v_saldo      numeric;
  v_qr         uuid;
  v_bloqueado  boolean;
  v_txt        text;
  v_cnt        int;

begin
  ---------------------------------------------------------------------
  -- Limpieza previa (por si una corrida anterior quedó a medias)
  ---------------------------------------------------------------------
  delete from public.access_logs where observacion like 'SMOKE%';
  delete from public.visitors     where cedula = '0900000001' and motivo_visita like 'SMOKE%';
  delete from public.users        where email like '%@smoke.test';
  delete from public.feriados     where nombre = 'SMOKE feriado';

  ---------------------------------------------------------------------
  -- 1. Validación de cédula ecuatoriana (módulo 10)
  ---------------------------------------------------------------------
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('1. Cédula válida',                'true',  public.es_cedula_valida('0926687856')::text),
    ('2. Dígito verificador incorrecto','false', public.es_cedula_valida('0926687857')::text),
    ('3. Solo 9 dígitos',               'false', public.es_cedula_valida('092668785')::text),
    ('4. Provincia inexistente (99)',   'false', public.es_cedula_valida('9926687856')::text),
    ('5. Tercer dígito > 5',            'false', public.es_cedula_valida('0976687856')::text),
    ('6. Contiene letras',              'false', public.es_cedula_valida('09A6687856')::text),
    ('7. Valor nulo',                   'false', coalesce(public.es_cedula_valida(null)::text,'false'));

  ---------------------------------------------------------------------
  -- 2. Cálculo de días (regla Ecuador) con un feriado de prueba
  ---------------------------------------------------------------------
  v_lun     := date_trunc('week', date '2099-07-07')::date;  -- lunes
  v_feriado := v_lun + 2;                                    -- miércoles feriado
  insert into public.feriados (fecha, nombre) values (v_feriado, 'SMOKE feriado');

  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('8. Permiso lun-vie sin feriado = 5 días hábiles',
     '5', public.calcular_dias('permiso',  v_lun + 7, v_lun + 11)::text),
    ('9. Vacación lun-dom sin feriado = 7 días calendario',
     '7', public.calcular_dias('vacacion', v_lun + 7, v_lun + 13)::text),
    ('10. Permiso lun-vie con feriado = 4',
     '4', public.calcular_dias('permiso',  v_lun, v_lun + 4)::text),
    ('11. Vacación lun-dom con feriado = 6',
     '6', public.calcular_dias('vacacion', v_lun, v_lun + 6)::text),
    ('12. Fecha fin anterior a inicio = 0',
     '0', public.calcular_dias('vacacion', v_lun + 5, v_lun)::text);

  ---------------------------------------------------------------------
  -- 3. Usuario de prueba (saldo 12.5 días)
  ---------------------------------------------------------------------
  insert into public.users (cedula, nombre, email, rol, dias_vacaciones, fecha_ingreso)
  values ('1700000001', 'SMOKE Empleado', 'empleado@smoke.test', 'empleado', 12.5, '2021-01-04')
  returning id into v_user_id;

  ---------------------------------------------------------------------
  -- 4. Solicitud dentro del saldo
  ---------------------------------------------------------------------
  insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, motivo)
  values (v_user_id, 'vacacion', v_lun + 7, v_lun + 11, 'SMOKE dentro de saldo')
  returning id, estado, dias_solicitados, es_adelanto
    into v_req_ok, v_estado, v_dias, v_adelanto;

  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('13. Estado inicial de la solicitud', 'pendiente_jefe', v_estado::text),
    ('14. Días calculados por el trigger', '5.00',           v_dias::text),
    ('15. No se marca como adelanto',      'false',          v_adelanto::text);

  ---------------------------------------------------------------------
  -- 5. Excede el saldo SIN justificación -> debe bloquearse
  ---------------------------------------------------------------------
  v_bloqueado := false;
  begin
    insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, motivo)
    values (v_user_id, 'vacacion', v_lun + 30, v_lun + 59, 'SMOKE sin justificar');
  exception when check_violation then
    v_bloqueado := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('16. Excede saldo sin justificación se bloquea', 'true', v_bloqueado::text);

  ---------------------------------------------------------------------
  -- 6. Excede el saldo CON justificación -> se acepta como adelanto
  ---------------------------------------------------------------------
  insert into public.requests (user_id, tipo, fecha_inicio, fecha_fin, motivo, justificacion)
  values (v_user_id, 'vacacion', v_lun + 30, v_lun + 59, 'SMOKE con justificación',
          'Días adelantados por viaje familiar programado con anticipación.')
  returning id, es_adelanto into v_req_excede, v_adelanto;

  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('17. Excede saldo con justificación se acepta', 'true', (v_req_excede is not null)::text),
    ('18. Se marca como días adelantados',           'true', v_adelanto::text);

  ---------------------------------------------------------------------
  -- 7. No se puede saltar la aprobación del jefe
  ---------------------------------------------------------------------
  v_bloqueado := false;
  begin
    update public.requests set estado = 'aprobado' where id = v_req_ok;
  exception when raise_exception then
    v_bloqueado := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('19. Transición pendiente_jefe -> aprobado bloqueada', 'true', v_bloqueado::text);

  ---------------------------------------------------------------------
  -- 8. Flujo completo: jefe -> RRHH -> QR + débito de saldo
  ---------------------------------------------------------------------
  update public.requests set estado = 'pendiente_rrhh' where id = v_req_ok;
  update public.requests set estado = 'aprobado'       where id = v_req_ok;

  select estado, qr_hash, qr_emitido_en is not null
    into v_estado, v_qr, v_bloqueado
  from public.requests where id = v_req_ok;

  select dias_vacaciones into v_saldo from public.users where id = v_user_id;

  select count(*) into v_cnt
  from public.vacation_movements where request_id = v_req_ok and dias = -5;

  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('20. Estado final tras aprobar RRHH',        'aprobado', v_estado::text),
    ('21. Se emite el código QR',                 'true',     (v_qr is not null)::text),
    ('22. Se registra la fecha de emisión del QR','true',     v_bloqueado::text),
    ('23. Saldo descontado (12.5 - 5)',           '7.50',     v_saldo::text),
    ('24. Movimiento de saldo registrado',        '1',        v_cnt::text);

  ---------------------------------------------------------------------
  -- 9. Cancelar una solicitud aprobada devuelve los días
  ---------------------------------------------------------------------
  update public.requests set estado = 'cancelado' where id = v_req_ok;
  select dias_vacaciones into v_saldo from public.users where id = v_user_id;

  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('25. Saldo devuelto tras cancelar (7.5 + 5)', '12.50', v_saldo::text);

  ---------------------------------------------------------------------
  -- 10. Trazabilidad: auditoría automática de solicitudes
  ---------------------------------------------------------------------
  select count(*) into v_cnt
  from public.audit_logs
  where entidad = 'requests' and entidad_id = v_req_ok::text and accion = 'request_creada';
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('26. audit_logs registra la creación', '1', v_cnt::text);

  select count(*) into v_cnt
  from public.audit_logs
  where entidad = 'requests' and entidad_id = v_req_ok::text and accion = 'request_estado_cambiado';
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('27. audit_logs registra los 3 cambios de estado', '3', v_cnt::text);

  ---------------------------------------------------------------------
  -- 11. Garita: visitante + bitácora de acceso
  ---------------------------------------------------------------------
  insert into public.visitors (cedula, nombre, empresa, motivo_visita, a_quien_visita_texto)
  values ('0900000001', 'SMOKE Visitante', 'ACME', 'SMOKE entrega de equipos', 'Bodega')
  returning id into v_visit_id;

  insert into public.access_logs (visitor_id, cedula, tipo_acceso, ip, observacion)
  values (v_visit_id, '0900000001', 'ingreso_visita', '10.0.0.5'::inet, 'SMOKE ingreso');

  insert into public.access_logs (user_id, cedula, tipo_acceso, ip, observacion)
  values (v_user_id, '1700000001', 'salida_empleado', '10.0.0.5'::inet, 'SMOKE salida');

  select count(*) into v_cnt from public.access_logs where observacion like 'SMOKE%';
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('28. Garita registra accesos de empleado y visita', '2', v_cnt::text);

  select count(*) into v_cnt from public.visitors
   where id = v_visit_id and salida_en is null;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('29. Visitante queda marcado como "dentro"', '1', v_cnt::text);

  ---------------------------------------------------------------------
  -- 12. Cédula inválida rechazada por el CHECK de users
  ---------------------------------------------------------------------
  v_bloqueado := false;
  begin
    insert into public.users (cedula, nombre, email, rol, fecha_ingreso)
    values ('1234567890', 'SMOKE Inválido', 'invalido@smoke.test', 'empleado', '2021-01-04');
  exception when check_violation then
    v_bloqueado := true;
  end;
  insert into _smoke_resultados (caso, esperado, obtenido) values
    ('30. CHECK rechaza cédula inválida en users', 'true', v_bloqueado::text);

  ---------------------------------------------------------------------
  -- LIMPIEZA: se borra todo lo creado por la prueba
  ---------------------------------------------------------------------
  delete from public.access_logs where observacion like 'SMOKE%';
  delete from public.audit_logs  where entidad = 'requests'
     and entidad_id in (v_req_ok::text, v_req_excede::text);
  delete from public.visitors    where id = v_visit_id;
  delete from public.users       where id = v_user_id;   -- cascada: requests y movimientos
  delete from public.feriados    where nombre = 'SMOKE feriado';

  update _smoke_resultados set ok = (esperado = obtenido);

exception when others then
  -- Si algo explota, se deja constancia y se limpia igual
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

-- ===== RESULTADOS =====
select
  case when ok then '✅' else '❌' end as r,
  caso, esperado, obtenido
from _smoke_resultados
order by n;
