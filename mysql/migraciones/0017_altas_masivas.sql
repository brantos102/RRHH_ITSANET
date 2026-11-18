-- =====================================================================
-- 0017 · Registro masivo de personas nuevas (altas por Excel)
--
-- `cargas_masivas` ya guardaba las actualizaciones por Excel de personas
-- registradas. Ahora también guarda las ALTAS: personas que faltan en el
-- sistema y Talento Humano registra desde una plantilla, con su saldo
-- conciliado. La columna `tipo` las distingue en el historial.
--
-- Idempotente.
-- =====================================================================

DELIMITER $$

DROP PROCEDURE IF EXISTS _migracion_0017 $$
CREATE PROCEDURE _migracion_0017()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'cargas_masivas'
                    AND column_name = 'tipo') THEN
    ALTER TABLE cargas_masivas
      ADD COLUMN tipo VARCHAR(14) NOT NULL DEFAULT 'actualizacion'
        COMMENT 'actualizacion: cambia fichas existentes · altas: registra personas nuevas' AFTER folio,
      ADD CONSTRAINT cargas_masivas_tipo_valido CHECK (tipo IN ('actualizacion', 'altas'));
  END IF;
END $$

CALL _migracion_0017() $$
DROP PROCEDURE IF EXISTS _migracion_0017 $$

DELIMITER ;
