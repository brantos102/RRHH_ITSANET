-- =====================================================================
-- 0008 · Quién asignó el reemplazo, y si el jefe lo confirmó
--
-- El reemplazo lo elige el jefe inmediato: conoce la carga del equipo y
-- sabe si esa persona ya tiene otras tareas. Talento Humano lo confirma
-- para el registro, no lo cambia.
--
-- Cuando el jefe no eligió a nadie, Talento Humano puede asignar a alguien,
-- pero queda pendiente de que el jefe lo confirme o lo cambie: el reemplazo
-- puede tener otras actividades que solo su jefe conoce. Estas columnas
-- guardan esa historia:
--
--   reemplazo_asignado_por    'jefe' o 'rrhh'
--   reemplazo_confirmado_en   cuándo lo confirmó el jefe (nulo = pendiente)
--   reemplazo_confirmado_por  quién lo confirmó
--
-- MySQL 8.0 no tiene ADD COLUMN IF NOT EXISTS: un procedimiento temporal
-- comprueba cada columna antes de agregarla, para poder reaplicar la
-- migración sin error.
-- =====================================================================

DELIMITER $$

DROP PROCEDURE IF EXISTS _migracion_0008 $$
CREATE PROCEDURE _migracion_0008()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'requests'
                    AND column_name = 'reemplazo_asignado_por') THEN
    ALTER TABLE requests
      ADD COLUMN reemplazo_asignado_por VARCHAR(10) NULL
        COMMENT 'Quién asignó el reemplazo: jefe o rrhh. Si fue rrhh, el jefe debe confirmarlo.'
        AFTER reemplazo_id,
      ADD COLUMN reemplazo_confirmado_en DATETIME(6) NULL
        COMMENT 'Cuándo el jefe inmediato confirmó el reemplazo. Nulo: pendiente de su confirmación.'
        AFTER reemplazo_asignado_por,
      ADD COLUMN reemplazo_confirmado_por CHAR(36) NULL
        AFTER reemplazo_confirmado_en,
      ADD CONSTRAINT requests_reemplazo_asignado_valido
        CHECK (reemplazo_asignado_por IS NULL OR reemplazo_asignado_por IN ('jefe', 'rrhh')),
      ADD CONSTRAINT requests_reemplazo_confirmado_por_fkey
        FOREIGN KEY (reemplazo_confirmado_por) REFERENCES users(id) ON DELETE SET NULL;
  END IF;
END $$

CALL _migracion_0008() $$
DROP PROCEDURE IF EXISTS _migracion_0008 $$

DELIMITER ;

-- Lo que ya tenía reemplazo lo había elegido el jefe (era el único que podía).
UPDATE requests
   SET reemplazo_asignado_por = 'jefe'
 WHERE reemplazo_id IS NOT NULL AND reemplazo_asignado_por IS NULL;
