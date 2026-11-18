-- =====================================================================
-- 0021 · Eliminar una solicitud con justificación y jefe alterno
--
-- Eliminar: la solicitud NO se borra de la base (la bitácora y los saldos
-- tienen que poder explicarse siempre). Se marca como eliminada, con quién,
-- cuándo y por qué, y deja de verse en las listas de trabajo. Si estaba en
-- trámite o aprobada, además pasa a «cancelado» (y devuelve los días si ya
-- se habían descontado, como cualquier cancelación).
--
-- Jefe alterno: cuando el jefe directo no tiene correo, está ausente o no
-- existe, la solicitud la puede decidir otra jefatura SOLO esa vez. El jefe
-- de la ficha no cambia: se guarda quién era (jefe_original_id) y por qué
-- se usó otro (jefe_alterno_motivo).
--
-- Idempotente.
-- =====================================================================

DELIMITER $$

DROP PROCEDURE IF EXISTS _migracion_0021 $$
CREATE PROCEDURE _migracion_0021()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'requests'
                    AND column_name = 'eliminada_en') THEN
    ALTER TABLE requests
      ADD COLUMN eliminada_en DATETIME(6) NULL
        COMMENT 'Cuándo se eliminó (borrado lógico: la fila se conserva)',
      ADD COLUMN eliminada_por CHAR(36) NULL COMMENT 'Quién la eliminó',
      ADD COLUMN eliminacion_motivo VARCHAR(500) NULL COMMENT 'Por qué se eliminó',
      ADD CONSTRAINT requests_eliminada_por_fkey
        FOREIGN KEY (eliminada_por) REFERENCES users(id) ON DELETE SET NULL,
      ADD KEY idx_requests_eliminada (eliminada_en);
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'requests'
                    AND column_name = 'jefe_original_id') THEN
    ALTER TABLE requests
      ADD COLUMN jefe_original_id CHAR(36) NULL
        COMMENT 'El jefe directo cuando la decide un jefe alterno (la ficha no cambia)',
      ADD COLUMN jefe_alterno_motivo VARCHAR(300) NULL
        COMMENT 'Por qué la decide un jefe alterno',
      ADD CONSTRAINT requests_jefe_original_fkey
        FOREIGN KEY (jefe_original_id) REFERENCES users(id) ON DELETE SET NULL;
  END IF;
END $$

CALL _migracion_0021() $$
DROP PROCEDURE IF EXISTS _migracion_0021 $$

DELIMITER ;
