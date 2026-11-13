-- =====================================================================
-- 0016 · Catálogo de cargos y áreas, actualización masiva, teléfonos
--        adicionales y domicilio
--
-- 1. `areas` y `cargos`: el catálogo oficial. Antes los cargos y las áreas
--    eran el texto que hubiera en cada ficha («Bodega», «BODEGA», «bodega »).
--    Ahora Talento Humano los administra (crear, renombrar, unificar,
--    desactivar) y el colaborador elige del catálogo al entrar por primera
--    vez. Se siembra con lo que ya está en las fichas. Las fichas siguen
--    guardando el nombre como texto, así nada de lo existente cambia.
--
-- 2. Cargo y área pasan a «bloqueado»: los administra Talento Humano. El
--    colaborador solo los indica la primera vez, si no constaban.
--
-- 3. `cargas_masivas`: cada actualización masiva por Excel, con lo que
--    cambió persona por persona, quién la subió, quién la aplicó, el motivo
--    y la huella del archivo. Reemplaza a «corregirlo en la base».
--
-- 4. `telefonos_adicionales` y el domicilio por partes (provincia, cantón,
--    parroquia, calles, número, referencia): opcionales y los corrige la
--    propia persona.
--
-- Idempotente.
-- =====================================================================

CREATE TABLE IF NOT EXISTS areas (
  id         BIGINT NOT NULL AUTO_INCREMENT,
  nombre     VARCHAR(120) NOT NULL,
  activo     TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY areas_nombre (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Catálogo oficial de áreas. Lo administra Talento Humano.';

CREATE TABLE IF NOT EXISTS cargos (
  id         BIGINT NOT NULL AUTO_INCREMENT,
  nombre     VARCHAR(120) NOT NULL,
  area_id    BIGINT NULL COMMENT 'Área a la que pertenece; vacío = cargo general',
  activo     TINYINT(1) NOT NULL DEFAULT 1,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY cargos_nombre_area (nombre, area_id),
  CONSTRAINT cargos_area_fkey FOREIGN KEY (area_id) REFERENCES areas(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Catálogo oficial de cargos, por área. Lo administra Talento Humano.';

-- Siembra con lo que ya hay en las fichas (la colación no distingue
-- mayúsculas ni tildes: «BODEGA» y «Bodega» quedan como una sola).
INSERT IGNORE INTO areas (nombre)
SELECT DISTINCT TRIM(departamento) FROM users
 WHERE NULLIF(TRIM(COALESCE(departamento, '')), '') IS NOT NULL;

INSERT IGNORE INTO cargos (nombre, area_id)
SELECT DISTINCT TRIM(u.cargo), a.id
  FROM users u LEFT JOIN areas a ON a.nombre = TRIM(u.departamento)
 WHERE NULLIF(TRIM(COALESCE(u.cargo, '')), '') IS NOT NULL;

CREATE TABLE IF NOT EXISTS cargas_masivas (
  id           BIGINT NOT NULL AUTO_INCREMENT,
  folio        VARCHAR(20) NOT NULL,
  archivo      VARCHAR(160) NOT NULL,
  sha256       CHAR(64) NOT NULL,
  filas        INT NOT NULL,
  cambios      JSON NOT NULL COMMENT '[{cedula, nombre, campo, antes, despues}]',
  errores      JSON NOT NULL COMMENT '[{fila, cedula, mensaje}]',
  estado       VARCHAR(12) NOT NULL DEFAULT 'revisada',
  motivo       VARCHAR(300) NULL,
  subido_por   CHAR(36) NULL,
  subido_en    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  aplicado_por CHAR(36) NULL,
  aplicado_en  DATETIME(6) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY cargas_masivas_folio (folio),
  CONSTRAINT cargas_masivas_estado_valido CHECK (estado IN ('revisada', 'aplicada', 'descartada')),
  CONSTRAINT cargas_masivas_aplicada_con_motivo
    CHECK (estado <> 'aplicada' OR CHAR_LENGTH(TRIM(COALESCE(motivo, ''))) >= 10),
  CONSTRAINT cargas_masivas_subido_fkey FOREIGN KEY (subido_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT cargas_masivas_aplicado_fkey FOREIGN KEY (aplicado_por) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Actualizaciones masivas por Excel: qué cambió, quién y por qué.';

CREATE TABLE IF NOT EXISTS telefonos_adicionales (
  id         BIGINT NOT NULL AUTO_INCREMENT,
  user_id    CHAR(36) NOT NULL,
  numero     VARCHAR(20) NOT NULL,
  tipo       VARCHAR(10) NOT NULL DEFAULT 'celular',
  etiqueta   VARCHAR(60) NULL COMMENT 'Ej.: «WhatsApp», «casa de mis padres»',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY telefonos_adicionales_user (user_id),
  CONSTRAINT telefonos_adicionales_tipo_valido CHECK (tipo IN ('celular', 'fijo', 'trabajo', 'otro')),
  CONSTRAINT telefonos_adicionales_user_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Teléfonos adicionales de la persona (opcionales). Los corrige ella misma.';

DELIMITER $$

DROP PROCEDURE IF EXISTS _migracion_0016 $$
CREATE PROCEDURE _migracion_0016()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'users'
                    AND column_name = 'domicilio_provincia') THEN
    ALTER TABLE users
      ADD COLUMN domicilio_provincia   VARCHAR(60)  NULL AFTER direccion,
      ADD COLUMN domicilio_canton      VARCHAR(80)  NULL AFTER domicilio_provincia,
      ADD COLUMN domicilio_parroquia   VARCHAR(80)  NULL AFTER domicilio_canton,
      ADD COLUMN domicilio_calle       VARCHAR(120) NULL COMMENT 'Calle principal' AFTER domicilio_parroquia,
      ADD COLUMN domicilio_numero      VARCHAR(20)  NULL AFTER domicilio_calle,
      ADD COLUMN domicilio_interseccion VARCHAR(120) NULL COMMENT 'Calle secundaria' AFTER domicilio_numero,
      ADD COLUMN domicilio_referencia  VARCHAR(200) NULL AFTER domicilio_interseccion;
  END IF;
END $$

CALL _migracion_0016() $$
DROP PROCEDURE IF EXISTS _migracion_0016 $$

DELIMITER ;

UPDATE campos_ficha
   SET nivel = 'bloqueado',
       ayuda = 'Lo administra Talento Humano. Si no corresponde, escríbales por el chat.'
 WHERE campo IN ('cargo', 'departamento');

INSERT IGNORE INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES
  ('domicilio_provincia', 'Provincia (domicilio)', 'libre', NULL, 31),
  ('domicilio_canton', 'Cantón (domicilio)', 'libre', NULL, 32),
  ('domicilio_parroquia', 'Parroquia (domicilio)', 'libre', NULL, 33),
  ('domicilio_calle', 'Calle principal', 'libre', NULL, 34),
  ('domicilio_numero', 'Número de casa', 'libre', NULL, 35),
  ('domicilio_interseccion', 'Calle secundaria', 'libre', NULL, 36),
  ('domicilio_referencia', 'Referencia del domicilio', 'libre', NULL, 37);
