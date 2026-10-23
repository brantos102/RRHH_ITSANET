-- ---------------------------------------------------------------------------
-- 0002 · Las reglas que la base sostiene por su cuenta.
--
-- En PostgreSQL estas reglas eran restricciones CHECK. MySQL no las admite
-- tal cual, por dos motivos distintos:
--
--   1. Un CHECK no puede llamar a una función propia, y la validación de la
--      cédula ecuatoriana es una (algoritmo de módulo 10).
--   2. Un CHECK no puede usar una columna que tenga acción de clave foránea
--      (ON DELETE SET NULL): error 3823. Es el caso de «el jefe no puede ser
--      uno mismo», «el reemplazo no puede ser el solicitante», «una
--      reemisión lleva autorización completa» y «todo acceso de garita
--      identifica a alguien».
--
-- Van como disparadores que responden EXACTAMENTE igual que un CHECK
-- violado —el mismo número de error, 3819, y el mismo texto con el nombre
-- de la restricción—, para que la aplicación las trate igual que a las
-- demás y el mensaje al usuario salga del mismo sitio.
--
-- Los disparadores de cascada de claves foráneas NO disparan disparadores
-- en MySQL. No afecta aquí: un ON DELETE SET NULL deja la columna en nulo,
-- y las cuatro reglas se cumplen siempre con nulo.
--
-- LA VARIABLE @migrando. Dos reglas eran «NOT VALID» en PostgreSQL: valen
-- para lo nuevo, no para lo histórico (permisos antiguos sin justificación,
-- bajas antiguas sin motivo). El traslado de datos fija @migrando = 1 para
-- poder cargar esa historia tal como está. La aplicación nunca la fija.
--
-- Idempotente: cada objeto se borra antes de crearse.
-- ---------------------------------------------------------------------------

-- Folios con formato (TRZ-2026-00001). MySQL no tiene secuencias: una tabla
-- con un contador por nombre, que se incrementa de forma atómica con
-- UPDATE ... SET valor = LAST_INSERT_ID(valor + 1).
CREATE TABLE IF NOT EXISTS secuencias (
  nombre VARCHAR(60) NOT NULL PRIMARY KEY,
  valor  BIGINT NOT NULL DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Contadores para folios con formato. MySQL no tiene secuencias.';

INSERT IGNORE INTO secuencias (nombre, valor) VALUES ('informes_firmados_folio', 0);

DELIMITER $$

-- ---------------------------------------------------- cédula ecuatoriana
-- Misma lógica que app/cedula.py y que la función de PostgreSQL: provincia
-- 01 a 24 o 30, tercer dígito menor que 6, dígito verificador de módulo 10.
DROP FUNCTION IF EXISTS es_cedula_valida $$
CREATE FUNCTION es_cedula_valida(p_cedula VARCHAR(20))
RETURNS BOOLEAN
DETERMINISTIC
NO SQL
BEGIN
  DECLARE v_provincia INT;
  DECLARE v_suma INT DEFAULT 0;
  DECLARE v_digito INT;
  DECLARE i INT DEFAULT 1;

  IF p_cedula IS NULL OR NOT REGEXP_LIKE(p_cedula, '^[0-9]{10}$') THEN
    RETURN FALSE;
  END IF;

  SET v_provincia = CAST(SUBSTRING(p_cedula, 1, 2) AS UNSIGNED);
  IF NOT ((v_provincia BETWEEN 1 AND 24) OR v_provincia = 30) THEN
    RETURN FALSE;
  END IF;
  IF CAST(SUBSTRING(p_cedula, 3, 1) AS UNSIGNED) > 5 THEN
    RETURN FALSE;
  END IF;

  WHILE i <= 9 DO
    SET v_digito = CAST(SUBSTRING(p_cedula, i, 1) AS UNSIGNED);
    IF i % 2 = 1 THEN                       -- posiciones impares: coeficiente 2
      SET v_digito = v_digito * 2;
      IF v_digito > 9 THEN
        SET v_digito = v_digito - 9;
      END IF;
    END IF;
    SET v_suma = v_suma + v_digito;
    SET i = i + 1;
  END WHILE;

  RETURN ((10 - (v_suma % 10)) % 10) = CAST(SUBSTRING(p_cedula, 10, 1) AS UNSIGNED);
END $$

-- ------------------------------------------------------------------ users
DROP TRIGGER IF EXISTS users_bi_reglas $$
CREATE TRIGGER users_bi_reglas BEFORE INSERT ON users FOR EACH ROW
BEGIN
  IF NOT es_cedula_valida(NEW.cedula) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''users_cedula_valida'' is violated.';
  END IF;
  IF NEW.jefe_id IS NOT NULL AND NEW.jefe_id = NEW.id THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''users_no_es_su_propio_jefe'' is violated.';
  END IF;
  IF COALESCE(@migrando, 0) = 0
     AND NOT NEW.activo AND NEW.fecha_salida IS NOT NULL AND NEW.motivo_salida IS NULL THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''users_salida_con_motivo'' is violated.';
  END IF;
  -- La región se deduce de la ciudad. Antes lo hacía un disparador de
  -- PostgreSQL; aquí también, para que valga escriba quien escriba.
  --
  -- La condición imita exactamente a la original. En PostgreSQL, al
  -- insertar, OLD es nulo y «NEW.ciudad IS DISTINCT FROM OLD.ciudad» es
  -- verdadero siempre que haya ciudad: la región se deduce de la ciudad
  -- AUNQUE el alta traiga una región escrita. Como `ciudad` vale 'Quito' por
  -- omisión, en la práctica la región de un alta sale siempre de la ciudad.
  IF NEW.region IS NULL OR NEW.ciudad IS NOT NULL THEN
    SET NEW.region = COALESCE(
      (SELECT c.region FROM ciudades_region c
        WHERE c.ciudad = TRIM(COALESCE(NEW.ciudad, '')) LIMIT 1),
      'sierra');
  END IF;
END $$

DROP TRIGGER IF EXISTS users_bu_reglas $$
CREATE TRIGGER users_bu_reglas BEFORE UPDATE ON users FOR EACH ROW
BEGIN
  IF NOT es_cedula_valida(NEW.cedula) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''users_cedula_valida'' is violated.';
  END IF;
  IF NEW.jefe_id IS NOT NULL AND NEW.jefe_id = NEW.id THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''users_no_es_su_propio_jefe'' is violated.';
  END IF;
  IF COALESCE(@migrando, 0) = 0
     AND NOT NEW.activo AND NEW.fecha_salida IS NOT NULL AND NEW.motivo_salida IS NULL THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''users_salida_con_motivo'' is violated.';
  END IF;
  -- Si cambió la ciudad, cambia la región. La comparación con <=> trata
  -- los nulos como iguales, que es lo que hacía IS DISTINCT FROM.
  IF NEW.region IS NULL OR NOT (NEW.ciudad <=> OLD.ciudad) THEN
    SET NEW.region = COALESCE(
      (SELECT c.region FROM ciudades_region c
        WHERE c.ciudad = TRIM(COALESCE(NEW.ciudad, '')) LIMIT 1),
      'sierra');
  END IF;
END $$

-- ------------------------------------------- cédulas en las demás tablas
DROP TRIGGER IF EXISTS visitors_bi_cedula $$
CREATE TRIGGER visitors_bi_cedula BEFORE INSERT ON visitors FOR EACH ROW
BEGIN
  IF NOT es_cedula_valida(NEW.cedula) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''visitors_cedula_valida'' is violated.';
  END IF;
END $$

DROP TRIGGER IF EXISTS visitors_bu_cedula $$
CREATE TRIGGER visitors_bu_cedula BEFORE UPDATE ON visitors FOR EACH ROW
BEGIN
  IF NOT es_cedula_valida(NEW.cedula) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''visitors_cedula_valida'' is violated.';
  END IF;
END $$

DROP TRIGGER IF EXISTS personal_temporal_bi_cedula $$
CREATE TRIGGER personal_temporal_bi_cedula BEFORE INSERT ON personal_temporal FOR EACH ROW
BEGIN
  IF NOT es_cedula_valida(NEW.cedula) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''temporal_cedula_valida'' is violated.';
  END IF;
END $$

DROP TRIGGER IF EXISTS personal_temporal_bu_cedula $$
CREATE TRIGGER personal_temporal_bu_cedula BEFORE UPDATE ON personal_temporal FOR EACH ROW
BEGIN
  IF NOT es_cedula_valida(NEW.cedula) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''temporal_cedula_valida'' is violated.';
  END IF;
END $$

DROP TRIGGER IF EXISTS family_members_bi_cedula $$
CREATE TRIGGER family_members_bi_cedula BEFORE INSERT ON family_members FOR EACH ROW
BEGIN
  IF NEW.cedula IS NOT NULL AND NOT es_cedula_valida(NEW.cedula) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''family_cedula_valida'' is violated.';
  END IF;
END $$

DROP TRIGGER IF EXISTS family_members_bu_cedula $$
CREATE TRIGGER family_members_bu_cedula BEFORE UPDATE ON family_members FOR EACH ROW
BEGIN
  IF NEW.cedula IS NOT NULL AND NOT es_cedula_valida(NEW.cedula) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''family_cedula_valida'' is violated.';
  END IF;
END $$

-- -------------------------------------------------------------- solicitudes
-- Solo las dos reglas que eran CHECK. Toda la lógica de negocio de las
-- solicitudes —días, saldo, ruta, estados, notificaciones— está en Python.
DROP TRIGGER IF EXISTS requests_bi_reglas $$
CREATE TRIGGER requests_bi_reglas BEFORE INSERT ON requests FOR EACH ROW
BEGIN
  IF NEW.reemplazo_id IS NOT NULL AND NEW.reemplazo_id = NEW.user_id THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''requests_reemplazo_distinto'' is violated.';
  END IF;
  IF COALESCE(@migrando, 0) = 0 AND NEW.tipo = 'permiso'
     AND (NEW.justificacion IS NULL OR CHAR_LENGTH(TRIM(NEW.justificacion)) < 10) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''requests_permiso_justificado'' is violated.';
  END IF;
END $$

DROP TRIGGER IF EXISTS requests_bu_reglas $$
CREATE TRIGGER requests_bu_reglas BEFORE UPDATE ON requests FOR EACH ROW
BEGIN
  IF NEW.reemplazo_id IS NOT NULL AND NEW.reemplazo_id = NEW.user_id THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''requests_reemplazo_distinto'' is violated.';
  END IF;
  IF COALESCE(@migrando, 0) = 0 AND NEW.tipo = 'permiso'
     AND (NEW.justificacion IS NULL OR CHAR_LENGTH(TRIM(NEW.justificacion)) < 10) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''requests_permiso_justificado'' is violated.';
  END IF;
END $$

-- ------------------------------------------------------- papeles firmados
DROP TRIGGER IF EXISTS informes_firmados_bi_reglas $$
CREATE TRIGGER informes_firmados_bi_reglas BEFORE INSERT ON informes_firmados FOR EACH ROW
BEGIN
  IF NOT ((NEW.autorizado_por IS NULL AND NEW.autorizado_en IS NULL)
          OR (NEW.autorizado_por IS NOT NULL AND NEW.autorizado_en IS NOT NULL
              AND COALESCE(TRIM(NEW.autorizacion_motivo), '') <> '')) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''informe_autorizacion_completa'' is violated.';
  END IF;
END $$

DROP TRIGGER IF EXISTS informes_firmados_bu_reglas $$
CREATE TRIGGER informes_firmados_bu_reglas BEFORE UPDATE ON informes_firmados FOR EACH ROW
BEGIN
  IF NOT ((NEW.autorizado_por IS NULL AND NEW.autorizado_en IS NULL)
          OR (NEW.autorizado_por IS NOT NULL AND NEW.autorizado_en IS NOT NULL
              AND COALESCE(TRIM(NEW.autorizacion_motivo), '') <> '')) THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''informe_autorizacion_completa'' is violated.';
  END IF;
END $$

-- ------------------------------------------------------------- bitácoras
-- Nadie modifica ni borra un registro de auditoría. La protección real es
-- de permisos —el usuario del backend no tiene UPDATE ni DELETE sobre estas
-- tablas—; este disparador es la segunda barrera. La depuración por
-- retención la ejecuta el administrador fijando @retencion = 'autorizada'.
DROP TRIGGER IF EXISTS access_logs_bi_identifica $$
CREATE TRIGGER access_logs_bi_identifica BEFORE INSERT ON access_logs FOR EACH ROW
BEGIN
  IF NOT (NEW.user_id IS NOT NULL OR NEW.visitor_id IS NOT NULL
          OR NEW.cedula IS NOT NULL OR NEW.tipo_acceso = 'acceso_denegado') THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''access_logs_identifica_persona'' is violated.';
  END IF;
END $$

DROP TRIGGER IF EXISTS access_logs_bu_inmutable $$
CREATE TRIGGER access_logs_bu_inmutable BEFORE UPDATE ON access_logs FOR EACH ROW
BEGIN
  IF COALESCE(@retencion, '') <> 'autorizada' THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 1142,
      MESSAGE_TEXT = 'Las bitácoras son inmutables: no se pueden modificar ni eliminar registros de auditoría.';
  END IF;
END $$

DROP TRIGGER IF EXISTS access_logs_bd_inmutable $$
CREATE TRIGGER access_logs_bd_inmutable BEFORE DELETE ON access_logs FOR EACH ROW
BEGIN
  IF COALESCE(@retencion, '') <> 'autorizada' THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 1142,
      MESSAGE_TEXT = 'Las bitácoras son inmutables: no se pueden modificar ni eliminar registros de auditoría.';
  END IF;
END $$

DROP TRIGGER IF EXISTS audit_logs_bu_inmutable $$
CREATE TRIGGER audit_logs_bu_inmutable BEFORE UPDATE ON audit_logs FOR EACH ROW
BEGIN
  IF COALESCE(@retencion, '') <> 'autorizada' THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 1142,
      MESSAGE_TEXT = 'Las bitácoras son inmutables: no se pueden modificar ni eliminar registros de auditoría.';
  END IF;
END $$

DROP TRIGGER IF EXISTS audit_logs_bd_inmutable $$
CREATE TRIGGER audit_logs_bd_inmutable BEFORE DELETE ON audit_logs FOR EACH ROW
BEGIN
  IF COALESCE(@retencion, '') <> 'autorizada' THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 1142,
      MESSAGE_TEXT = 'Las bitácoras son inmutables: no se pueden modificar ni eliminar registros de auditoría.';
  END IF;
END $$

-- -------------------------------------------- períodos de vacaciones
-- Un período ya devengado y consumido entero tiene sus fines de semana
-- cumplidos: no se puede deber un fin de semana de un período que ya no
-- tiene días.
DROP TRIGGER IF EXISTS vacation_periods_bi_fds $$
CREATE TRIGGER vacation_periods_bi_fds BEFORE INSERT ON vacation_periods FOR EACH ROW
BEGIN
  IF NEW.devengado AND NEW.dias_consumidos >= NEW.dias_asignados
     AND NEW.dias_asignados > 0
     AND NEW.fines_semana_consumidos < NEW.fines_semana_obligatorios THEN
    SET NEW.fines_semana_consumidos = NEW.fines_semana_obligatorios;
  END IF;
END $$

DROP TRIGGER IF EXISTS vacation_periods_bu_fds $$
CREATE TRIGGER vacation_periods_bu_fds BEFORE UPDATE ON vacation_periods FOR EACH ROW
BEGIN
  IF NEW.devengado AND NEW.dias_consumidos >= NEW.dias_asignados
     AND NEW.dias_asignados > 0
     AND NEW.fines_semana_consumidos < NEW.fines_semana_obligatorios THEN
    SET NEW.fines_semana_consumidos = NEW.fines_semana_obligatorios;
  END IF;
END $$

-- El saldo que muestra la ficha es la suma de los períodos vigentes. Es un
-- dato derivado: se recalcula ante cualquier cambio en los períodos, venga
-- de la aplicación, del traslado o de una carga.
DROP TRIGGER IF EXISTS vacation_periods_ai_saldo $$
CREATE TRIGGER vacation_periods_ai_saldo AFTER INSERT ON vacation_periods FOR EACH ROW
BEGIN
  UPDATE users SET dias_vacaciones = (
    SELECT COALESCE(SUM(p.dias_saldo), 0) FROM vacation_periods p
     WHERE p.user_id = NEW.user_id AND NOT p.caducado)
   WHERE id = NEW.user_id;
END $$

DROP TRIGGER IF EXISTS vacation_periods_au_saldo $$
CREATE TRIGGER vacation_periods_au_saldo AFTER UPDATE ON vacation_periods FOR EACH ROW
BEGIN
  UPDATE users SET dias_vacaciones = (
    SELECT COALESCE(SUM(p.dias_saldo), 0) FROM vacation_periods p
     WHERE p.user_id = NEW.user_id AND NOT p.caducado)
   WHERE id = NEW.user_id;
  IF NOT (NEW.user_id <=> OLD.user_id) THEN
    UPDATE users SET dias_vacaciones = (
      SELECT COALESCE(SUM(p.dias_saldo), 0) FROM vacation_periods p
       WHERE p.user_id = OLD.user_id AND NOT p.caducado)
     WHERE id = OLD.user_id;
  END IF;
END $$

DROP TRIGGER IF EXISTS vacation_periods_ad_saldo $$
CREATE TRIGGER vacation_periods_ad_saldo AFTER DELETE ON vacation_periods FOR EACH ROW
BEGIN
  UPDATE users SET dias_vacaciones = (
    SELECT COALESCE(SUM(p.dias_saldo), 0) FROM vacation_periods p
     WHERE p.user_id = OLD.user_id AND NOT p.caducado)
   WHERE id = OLD.user_id;
END $$

-- -------------------------------------------------------------- mensajes
-- Un mensaje nuevo reabre la conversación y la sube en la bandeja.
DROP TRIGGER IF EXISTS mensajes_ai_tocar $$
CREATE TRIGGER mensajes_ai_tocar AFTER INSERT ON mensajes FOR EACH ROW
BEGIN
  UPDATE conversaciones
     SET updated_at = CURRENT_TIMESTAMP(6),
         estado = CASE WHEN estado = 'cerrada' THEN 'abierta' ELSE estado END
   WHERE id = NEW.conversacion_id;
END $$

DELIMITER ;
