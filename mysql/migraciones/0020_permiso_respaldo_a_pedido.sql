-- =====================================================================
-- 0020 · Permisos: justificación opcional y respaldo a pedido
--
-- Antes, un permiso no se registraba sin una justificación de 10
-- caracteres (además del motivo), y el formulario decía que ciertos tipos
-- «exigen adjuntar respaldo». Desde ahora:
--
--   · La justificación del permiso es OPCIONAL: el motivo (descripción)
--     sigue siendo obligatorio.
--   · El respaldo se puede adjuntar al pedirlo, o después. Si Talento
--     Humano lo necesita, lo pide desde el sistema con un mensaje; la
--     persona lo recibe por correo y lo adjunta desde «Mis solicitudes».
--     Queda constancia de quién lo pidió, cuándo, y cuándo se entregó.
--
-- Los disparadores de reglas se recrean igual que en 0002, sin la
-- comprobación de la justificación. Idempotente.
-- =====================================================================

DELIMITER $$

DROP TRIGGER IF EXISTS requests_bi_reglas $$
CREATE TRIGGER requests_bi_reglas BEFORE INSERT ON requests FOR EACH ROW
BEGIN
  IF NEW.reemplazo_id IS NOT NULL AND NEW.reemplazo_id = NEW.user_id THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''requests_reemplazo_distinto'' is violated.';
  END IF;
END $$

DROP TRIGGER IF EXISTS requests_bu_reglas $$
CREATE TRIGGER requests_bu_reglas BEFORE UPDATE ON requests FOR EACH ROW
BEGIN
  IF NEW.reemplazo_id IS NOT NULL AND NEW.reemplazo_id = NEW.user_id THEN
    SIGNAL SQLSTATE 'HY000' SET MYSQL_ERRNO = 3819,
      MESSAGE_TEXT = 'Check constraint ''requests_reemplazo_distinto'' is violated.';
  END IF;
END $$

DROP PROCEDURE IF EXISTS _migracion_0020 $$
CREATE PROCEDURE _migracion_0020()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'requests'
                    AND column_name = 'respaldo_pedido_en') THEN
    ALTER TABLE requests
      ADD COLUMN respaldo_pedido_en DATETIME(6) NULL
        COMMENT 'Cuándo Talento Humano pidió el respaldo (el más reciente)',
      ADD COLUMN respaldo_pedido_por CHAR(36) NULL
        COMMENT 'Quién de Talento Humano lo pidió',
      ADD COLUMN respaldo_pedido_mensaje VARCHAR(300) NULL
        COMMENT 'Qué documento se pide y para qué',
      ADD COLUMN respaldo_entregado_en DATETIME(6) NULL
        COMMENT 'Cuándo la persona adjuntó el respaldo pedido',
      ADD CONSTRAINT requests_respaldo_pedido_por_fkey
        FOREIGN KEY (respaldo_pedido_por) REFERENCES users(id) ON DELETE SET NULL;
  END IF;
END $$

CALL _migracion_0020() $$
DROP PROCEDURE IF EXISTS _migracion_0020 $$

DELIMITER ;

-- El lineamiento que decía «adjúntelo al pedirlo», solo si Talento Humano
-- no lo había reescrito.
UPDATE lineamientos_solicitud
   SET texto = 'El respaldo (un certificado, por ejemplo) puede adjuntarlo al pedir el permiso o después: si Talento Humano lo necesita, se lo pedirá y lo adjunta desde «Mis solicitudes».'
 WHERE ambito = 'permiso'
   AND texto = 'Si el permiso exige respaldo —un certificado médico, por ejemplo—, adjúntelo al pedirlo.';
