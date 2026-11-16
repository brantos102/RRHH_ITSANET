-- =====================================================================
-- 0019 · Corregir un rechazo por error
--
-- Quien rechazó una solicitud por error (o Talento Humano) puede corregir la
-- decisión: la solicitud vuelve a la etapa en que se rechazó y se aprueba en
-- el mismo paso, con un motivo que queda en la bitácora.
--
-- Cambia dos disparadores de 0005, sin tocar nada más de su lógica:
--   · requests_bu_estado admite rechazado → pendiente_jefe / pendiente_rrhh,
--     solo con la marca de sesión @reconsideracion_en_curso que pone la
--     aplicación (como @ajuste_en_curso para los ajustes de fechas);
--   · requests_au_registro no avisa «aprobada por el jefe» cuando la
--     solicitud vuelve de un rechazo.
--
-- Idempotente: se recrean con DROP IF EXISTS.
-- =====================================================================

DELIMITER $$

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
      -- Un rechazo por error se corrige: vuelve a la etapa en que se rechazó.
      -- Solo por la vía de la aplicación (reconsiderar), que exige motivo y
      -- deja bitácora; nunca por un UPDATE suelto.
      OR (OLD.estado = 'rechazado' AND NEW.estado IN ('pendiente_jefe', 'pendiente_rrhh')
          AND COALESCE(@reconsideracion_en_curso, 0) = 1)
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

DROP TRIGGER IF EXISTS requests_au_registro $$
CREATE TRIGGER requests_au_registro AFTER UPDATE ON requests FOR EACH ROW
BEGIN
  DECLARE v_nombre VARCHAR(255);
  IF NOT (NEW.estado <=> OLD.estado) THEN
    INSERT INTO audit_logs (user_id, accion, entidad, entidad_id, detalle)
    VALUES (NEW.user_id, 'request_estado_cambiado', 'requests', NEW.id,
            JSON_OBJECT('de', OLD.estado, 'a', NEW.estado, 'motivo_rechazo', NEW.motivo_rechazo));

    SELECT nombre INTO v_nombre FROM users WHERE id = NEW.user_id;

    -- Al corregir un rechazo la solicitud vuelve un instante a su etapa y se
    -- aprueba en el mismo paso: ese «vuelve» no es una aprobación del jefe.
    IF NEW.estado = 'pendiente_rrhh' AND OLD.estado <> 'rechazado' THEN
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
