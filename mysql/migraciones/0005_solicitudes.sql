-- ---------------------------------------------------------------------------
-- 0005 · La vida de una solicitud después de creada.
--
-- En PostgreSQL, once disparadores sobre `requests` sostenían las reglas.
-- Aquí se reparten según una limitación concreta de MySQL: el mensaje de
-- error de un disparador (SIGNAL) no puede pasar de 128 caracteres.
--
--   EN MYSQL, aquí:
--     · qué transiciones de estado valen, y que una solicitud aprobada no
--       cambie de fechas;
--     · los campos que se derivan del cambio: días recalculados, sellos de
--       fecha de cada etapa, el código QR al aprobar, la etapa del rechazo;
--     · descontar los días del saldo al aprobar y devolverlos al anular, EN
--       LA MISMA OPERACIÓN que el cambio de estado;
--     · la auditoría y las notificaciones de cada cambio.
--   Todo eso vale escriba quien escriba: la aplicación, el traslado de datos
--   o un administrador desde la consola. Los mensajes son cortos y caben.
--
--   EN PYTHON (servidor/app/reglas/solicitudes.py):
--     · las validaciones al CREAR —anticipación, bloque mínimo, solape,
--       saldo—, cuyos mensajes al usuario pasan de 200 caracteres y llevan
--       una pista para que la pantalla ofrezca la corrección;
--     · los requisitos que se comprueban al confirmar (el adjunto), porque
--       MySQL no tiene disparadores diferidos hasta el final de la
--       transacción.
--
-- POR QUÉ EL SALDO SE DESCUENTA AQUÍ Y NO EN PYTHON. Aprobar y descontar
-- tienen que ser una sola cosa: en PostgreSQL lo eran, porque el disparador
-- llamaba a consumir_vacaciones() dentro del mismo UPDATE. Si el descuento
-- viviera en Python, cualquier cambio de estado hecho por otro camino
-- dejaría una solicitud aprobada con el saldo intacto, y nadie lo notaría
-- hasta que la persona tomara los días dos veces.
--
-- LA VARIABLE @ajuste_en_curso. En PostgreSQL solo ajustar_ausencia() podía
-- cambiar las fechas de una solicitud ya aprobada, levantando un indicador
-- de transacción. Aquí es la variable de sesión @ajuste_en_curso, que la
-- función de Python levanta y BAJA siempre al terminar (las conexiones se
-- reutilizan: una variable olvidada viajaría a la petición siguiente).
--
-- Idempotente.
-- ---------------------------------------------------------------------------

DELIMITER $$

-- --------------------------------------------- descontar y devolver días
-- Se descuenta de los períodos más antiguos primero. Lo que no alcanza se
-- carga al período en curso, que queda en negativo: son días adelantados.
--
-- Sin cursor, a propósito. En MySQL un cursor puede no ver las
-- actualizaciones que el mismo bucle va haciendo sobre la tabla que recorre.
-- Cada vuelta vuelve a buscar el período más antiguo que todavía tiene
-- saldo, así que el resultado no depende de eso.
DROP PROCEDURE IF EXISTS consumir_vacaciones $$
CREATE PROCEDURE consumir_vacaciones(p_user_id CHAR(36), p_dias DECIMAL(6,2),
                                     p_request_id CHAR(36), p_fds INT, p_por CHAR(36))
MODIFIES SQL DATA
BEGIN
  DECLARE v_restante DECIMAL(6,2) DEFAULT p_dias;
  DECLARE v_toma DECIMAL(6,2);
  DECLARE v_id CHAR(36);
  DECLARE v_saldo DECIMAL(6,2);
  DECLARE v_saldo_prev DECIMAL(6,2);
  DECLARE v_ultimo CHAR(36);

  SELECT COALESCE(SUM(dias_saldo), 0) INTO v_saldo_prev
    FROM vacation_periods WHERE user_id = p_user_id AND NOT caducado;

  consumo: WHILE v_restante > 0 DO
    SET v_id = NULL;
    SELECT id, dias_saldo INTO v_id, v_saldo
      FROM vacation_periods
     WHERE user_id = p_user_id AND NOT caducado AND dias_saldo > 0
     ORDER BY periodo LIMIT 1;
    IF v_id IS NULL THEN
      LEAVE consumo;
    END IF;
    SET v_toma = LEAST(v_saldo, v_restante);
    UPDATE vacation_periods SET dias_consumidos = dias_consumidos + v_toma WHERE id = v_id;
    SET v_restante = v_restante - v_toma;
  END WHILE;

  -- Días adelantados: al período en curso.
  IF v_restante > 0 THEN
    SELECT id INTO v_ultimo FROM vacation_periods
     WHERE user_id = p_user_id AND NOT caducado ORDER BY periodo DESC LIMIT 1;
    IF v_ultimo IS NULL THEN
      SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'El empleado no tiene períodos de vacaciones generados';
    END IF;
    UPDATE vacation_periods SET dias_consumidos = dias_consumidos + v_restante WHERE id = v_ultimo;
  END IF;

  -- Fines de semana completos: al período abierto más antiguo.
  IF p_fds > 0 THEN
    UPDATE vacation_periods SET fines_semana_consumidos = fines_semana_consumidos + p_fds
     WHERE id = (SELECT id FROM (SELECT id FROM vacation_periods
                                  WHERE user_id = p_user_id AND NOT caducado
                                  ORDER BY periodo LIMIT 1) AS x);
  END IF;

  INSERT INTO vacation_movements (user_id, request_id, dias, saldo_previo, saldo_nuevo, motivo, created_by)
  SELECT p_user_id, p_request_id, -p_dias, v_saldo_prev, COALESCE(SUM(dias_saldo), 0),
         'Consumo de vacaciones aprobadas', p_por
    FROM vacation_periods WHERE user_id = p_user_id AND NOT caducado;
END $$

-- Se devuelve en orden inverso al consumo: del período más nuevo al más
-- antiguo.
DROP PROCEDURE IF EXISTS reversar_vacaciones $$
CREATE PROCEDURE reversar_vacaciones(p_user_id CHAR(36), p_dias DECIMAL(6,2),
                                     p_request_id CHAR(36), p_fds INT)
MODIFIES SQL DATA
BEGIN
  DECLARE v_restante DECIMAL(6,2) DEFAULT p_dias;
  DECLARE v_devuelve DECIMAL(6,2);
  DECLARE v_id CHAR(36);
  DECLARE v_consumidos DECIMAL(6,2);
  DECLARE v_saldo_prev DECIMAL(6,2);

  SELECT COALESCE(SUM(dias_saldo), 0) INTO v_saldo_prev
    FROM vacation_periods WHERE user_id = p_user_id AND NOT caducado;

  devolucion: WHILE v_restante > 0 DO
    SET v_id = NULL;
    SELECT id, dias_consumidos INTO v_id, v_consumidos
      FROM vacation_periods
     WHERE user_id = p_user_id AND NOT caducado AND dias_consumidos > 0
     ORDER BY periodo DESC LIMIT 1;
    IF v_id IS NULL THEN
      LEAVE devolucion;
    END IF;
    SET v_devuelve = LEAST(v_consumidos, v_restante);
    UPDATE vacation_periods SET dias_consumidos = dias_consumidos - v_devuelve WHERE id = v_id;
    SET v_restante = v_restante - v_devuelve;
  END WHILE;

  IF p_fds > 0 THEN
    UPDATE vacation_periods
       SET fines_semana_consumidos = GREATEST(0, fines_semana_consumidos - p_fds)
     WHERE id = (SELECT id FROM (SELECT id FROM vacation_periods
                                  WHERE user_id = p_user_id AND NOT caducado
                                  ORDER BY periodo LIMIT 1) AS x);
  END IF;

  INSERT INTO vacation_movements (user_id, request_id, dias, saldo_previo, saldo_nuevo, motivo)
  SELECT p_user_id, p_request_id, p_dias, v_saldo_prev, COALESCE(SUM(dias_saldo), 0),
         'Reversa por cancelación de solicitud'
    FROM vacation_periods WHERE user_id = p_user_id AND NOT caducado;
END $$

-- ----------------------------------------------------- región al insertar
-- La solicitud se atiende en la región de quien la pide.
DROP TRIGGER IF EXISTS requests_bi_region $$
CREATE TRIGGER requests_bi_region BEFORE INSERT ON requests FOR EACH ROW
FOLLOWS requests_bi_reglas
BEGIN
  IF NEW.region IS NULL THEN
    SET NEW.region = (SELECT COALESCE(u.region, region_de_ciudad(u.ciudad))
                        FROM users u WHERE u.id = NEW.user_id);
  END IF;
END $$

-- ------------------------------------------------- la máquina de estados
DROP TRIGGER IF EXISTS requests_bu_estado $$
CREATE TRIGGER requests_bu_estado BEFORE UPDATE ON requests FOR EACH ROW
FOLLOWS requests_bu_reglas
BEGIN
  DECLARE v_descuenta BOOLEAN DEFAULT FALSE;
  -- Variable LOCAL para los mensajes: una de sesión (@...) quedaría pegada a
  -- la conexión, y las conexiones se reutilizan entre peticiones.
  DECLARE v_mensaje VARCHAR(128);

  -- Las fechas de algo ya en trámite no se tocan, salvo por el ajuste
  -- formal, que deja constancia de quién, cuándo y por qué.
  IF NOT (NEW.fecha_inicio <=> OLD.fecha_inicio AND NEW.fecha_fin <=> OLD.fecha_fin
          AND NEW.tipo <=> OLD.tipo) THEN
    IF OLD.estado <> 'pendiente_jefe' AND COALESCE(@ajuste_en_curso, 0) <> 1 THEN
      SET v_mensaje = CONCAT('No se pueden modificar las fechas de una solicitud en estado ', OLD.estado);
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_mensaje;
    END IF;
    SET NEW.dias_solicitados = calcular_dias(NEW.tipo, NEW.fecha_inicio, NEW.fecha_fin);
    SET NEW.fines_semana = fines_de_semana_completos(NEW.fecha_inicio, NEW.fecha_fin);
  END IF;

  IF NOT (NEW.estado <=> OLD.estado) THEN
    IF NOT (
         (OLD.estado = 'pendiente_jefe' AND NEW.estado IN ('pendiente_rrhh', 'rechazado', 'cancelado'))
      -- Ruta invertida: el jefe decide último y su visto bueno aprueba.
      OR (OLD.estado = 'pendiente_jefe' AND NEW.estado = 'aprobado'
          AND NEW.ruta_aprobacion = 'rrhh_primero' AND NEW.rrhh_aprobado_por IS NOT NULL)
      OR (OLD.estado = 'pendiente_rrhh' AND NEW.estado IN ('aprobado', 'rechazado', 'cancelado'))
      -- Ruta invertida: Talento Humano autorizó y ahora confirma el jefe.
      OR (OLD.estado = 'pendiente_rrhh' AND NEW.estado = 'pendiente_jefe'
          AND NEW.ruta_aprobacion = 'rrhh_primero')
      OR (OLD.estado = 'aprobado' AND NEW.estado IN ('pendiente_anulacion', 'cancelado'))
      OR (OLD.estado = 'pendiente_anulacion' AND NEW.estado IN ('cancelado', 'aprobado'))
    ) THEN
      SET v_mensaje = CONCAT('Transición de estado inválida: ', OLD.estado, ' -> ', NEW.estado);
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_mensaje;
    END IF;

    -- En qué etapa se rechazó, para saber quién dijo que no.
    IF NEW.estado = 'rechazado' AND OLD.estado IN ('pendiente_jefe', 'pendiente_rrhh') THEN
      SET NEW.rechazado_en_etapa = IF(OLD.estado = 'pendiente_jefe', 'jefe', 'rrhh');
    END IF;

    IF NEW.estado = 'pendiente_rrhh' THEN
      SET NEW.jefe_aprobado_en = COALESCE(NEW.jefe_aprobado_en, NOW(6));
    END IF;
    IF NEW.estado = 'pendiente_jefe' AND OLD.estado = 'pendiente_rrhh' THEN
      SET NEW.rrhh_aprobado_en = COALESCE(NEW.rrhh_aprobado_en, NOW(6));
    END IF;
    IF NEW.estado = 'rechazado' THEN
      SET NEW.rechazado_en = COALESCE(NEW.rechazado_en, NOW(6));
    END IF;
    IF NEW.estado = 'pendiente_anulacion' THEN
      SET NEW.anulacion_solicitada_en = COALESCE(NEW.anulacion_solicitada_en, NOW(6));
    END IF;

    -- Anulación denegada: vuelve a estar vigente; el saldo no se tocó.
    IF NEW.estado = 'aprobado' AND OLD.estado = 'pendiente_anulacion' THEN
      SET NEW.anulacion_resuelta_en = COALESCE(NEW.anulacion_resuelta_en, NOW(6));
    ELSE
      IF NEW.tipo = 'vacacion' THEN
        SET v_descuenta = TRUE;
      ELSE
        SET v_descuenta = COALESCE((SELECT descuenta_vacaciones FROM permission_types
                                     WHERE id = NEW.permission_type_id), FALSE);
      END IF;

      IF NEW.estado = 'aprobado' THEN
        SET NEW.rrhh_aprobado_en = COALESCE(NEW.rrhh_aprobado_en, NOW(6));
        SET NEW.qr_hash = COALESCE(NEW.qr_hash, UUID());
        SET NEW.qr_emitido_en = COALESCE(NEW.qr_emitido_en, NOW(6));
        -- El QR vale hasta la medianoche que sigue al último día.
        SET NEW.qr_expira_en = COALESCE(NEW.qr_expira_en, TIMESTAMP(DATE_ADD(NEW.fecha_fin, INTERVAL 1 DAY)));
        IF v_descuenta THEN
          CALL consumir_vacaciones(NEW.user_id, NEW.dias_solicitados, NEW.id,
                                   NEW.fines_semana, NEW.rrhh_aprobado_por);
        END IF;
      END IF;

      -- Se devuelve el saldo al cancelar algo que ya se había descontado.
      IF NEW.estado = 'cancelado' AND OLD.estado IN ('aprobado', 'pendiente_anulacion') AND v_descuenta THEN
        CALL reversar_vacaciones(NEW.user_id, NEW.dias_solicitados, NEW.id, NEW.fines_semana);
        SET NEW.anulacion_resuelta_en = COALESCE(NEW.anulacion_resuelta_en, NOW(6));
        -- Un QR anulado deja de servir en garita.
        SET NEW.qr_expira_en = NOW(6);
      END IF;
    END IF;
  END IF;
END $$

-- ------------------------------------------------ auditoría y avisos
DROP TRIGGER IF EXISTS requests_ai_registro $$
CREATE TRIGGER requests_ai_registro AFTER INSERT ON requests FOR EACH ROW
BEGIN
  DECLARE v_nombre VARCHAR(255);
  INSERT INTO audit_logs (user_id, accion, entidad, entidad_id, detalle)
  VALUES (NEW.user_id, 'request_creada', 'requests', NEW.id,
          JSON_OBJECT('tipo', NEW.tipo, 'dias', NEW.dias_solicitados,
                      'inicio', NEW.fecha_inicio, 'fin', NEW.fecha_fin,
                      'es_adelanto', CAST(IF(NEW.es_adelanto, 'true', 'false') AS JSON)));

  IF NEW.jefe_id IS NOT NULL THEN
    SELECT nombre INTO v_nombre FROM users WHERE id = NEW.user_id;
    INSERT INTO notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
    VALUES (NEW.jefe_id, 'solicitud_pendiente', 'info',
      CONCAT('Nueva solicitud de ', v_nombre),
      CONCAT(v_nombre, ' solicitó ', NEW.tipo, ' del ', DATE_FORMAT(NEW.fecha_inicio, '%d/%m/%Y'),
             ' al ', DATE_FORMAT(NEW.fecha_fin, '%d/%m/%Y'), ' (', NEW.dias_solicitados,
             ' días). Requiere su aprobación.'),
      'requests', NEW.id, '/dashboard.html#aprobaciones');
  END IF;
END $$

DROP TRIGGER IF EXISTS requests_au_registro $$
CREATE TRIGGER requests_au_registro AFTER UPDATE ON requests FOR EACH ROW
BEGIN
  DECLARE v_nombre VARCHAR(255);
  IF NOT (NEW.estado <=> OLD.estado) THEN
    INSERT INTO audit_logs (user_id, accion, entidad, entidad_id, detalle)
    VALUES (NEW.user_id, 'request_estado_cambiado', 'requests', NEW.id,
            JSON_OBJECT('de', OLD.estado, 'a', NEW.estado, 'motivo_rechazo', NEW.motivo_rechazo));

    SELECT nombre INTO v_nombre FROM users WHERE id = NEW.user_id;

    IF NEW.estado = 'pendiente_rrhh' THEN
      INSERT INTO notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      SELECT u.id, 'solicitud_pendiente', 'info',
        CONCAT('Solicitud Nº ', COALESCE(NEW.folio, 0), ' de ', v_nombre, ' aprobada por el jefe'),
        CONCAT('La solicitud de ', v_nombre, ' (', DATE_FORMAT(NEW.fecha_inicio, '%d/%m/%Y'), ' al ',
               DATE_FORMAT(NEW.fecha_fin, '%d/%m/%Y'), ') espera la aprobación de Talento Humano.'),
        'requests', NEW.id, '/dashboard.html#aprobaciones'
        FROM users u WHERE u.rol IN ('rrhh', 'admin') AND u.activo;

    ELSEIF NEW.estado = 'pendiente_anulacion' THEN
      INSERT INTO notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      SELECT u.id, 'solicitud_pendiente', 'advertencia',
        CONCAT(v_nombre, ' pide anular la solicitud Nº ', COALESCE(NEW.folio, 0)),
        CONCAT('Motivo: ', COALESCE(NEW.anulacion_motivo, 'no indicado'), '. Si se autoriza, se devuelven ',
               NEW.dias_solicitados, ' día(s) y el código QR deja de servir.'),
        'requests', NEW.id, '/dashboard.html#aprobaciones'
        FROM users u WHERE u.rol IN ('rrhh', 'admin') AND u.activo;

    ELSEIF NEW.estado = 'aprobado' AND OLD.estado = 'pendiente_anulacion' THEN
      INSERT INTO notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      VALUES (NEW.user_id, 'solicitud_rechazada', 'advertencia',
        CONCAT('No se autorizó anular su solicitud Nº ', COALESCE(NEW.folio, 0)),
        CONCAT('Su solicitud del ', DATE_FORMAT(NEW.fecha_inicio, '%d/%m/%Y'), ' al ',
               DATE_FORMAT(NEW.fecha_fin, '%d/%m/%Y'), ' sigue vigente. Motivo: ',
               COALESCE(NEW.anulacion_rechazada_motivo, 'no especificado')),
        'requests', NEW.id, '/dashboard.html');

    ELSEIF NEW.estado = 'aprobado' THEN
      INSERT INTO notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      VALUES (NEW.user_id, 'solicitud_aprobada', 'info',
        CONCAT('Su solicitud Nº ', COALESCE(NEW.folio, 0), ' fue aprobada'),
        CONCAT('Su solicitud del ', DATE_FORMAT(NEW.fecha_inicio, '%d/%m/%Y'), ' al ',
               DATE_FORMAT(NEW.fecha_fin, '%d/%m/%Y'),
               ' fue aprobada. Ya puede descargar su código QR de salida.'),
        'requests', NEW.id, '/dashboard.html');

    ELSEIF NEW.estado = 'rechazado' THEN
      INSERT INTO notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      VALUES (NEW.user_id, 'solicitud_rechazada', 'advertencia',
        CONCAT('Su solicitud Nº ', COALESCE(NEW.folio, 0), ' fue rechazada'),
        CONCAT('Su solicitud del ', DATE_FORMAT(NEW.fecha_inicio, '%d/%m/%Y'), ' al ',
               DATE_FORMAT(NEW.fecha_fin, '%d/%m/%Y'), ' fue rechazada. Motivo: ',
               COALESCE(NEW.motivo_rechazo, 'no especificado')),
        'requests', NEW.id, '/dashboard.html');

    ELSEIF NEW.estado = 'cancelado' AND OLD.estado = 'pendiente_anulacion' THEN
      INSERT INTO notifications (user_id, tipo, severidad, titulo, mensaje, entidad, entidad_id, accion_url)
      VALUES (NEW.user_id, 'informativo', 'info',
        CONCAT('Se anuló su solicitud Nº ', COALESCE(NEW.folio, 0)),
        CONCAT('Talento Humano autorizó la anulación. Se devolvieron ', NEW.dias_solicitados,
               ' día(s) a su saldo.'),
        'requests', NEW.id, '/dashboard.html');
    END IF;
  END IF;
END $$

DELIMITER ;
