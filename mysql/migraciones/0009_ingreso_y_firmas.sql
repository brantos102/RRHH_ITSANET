-- =====================================================================
-- 0009 · Primer ingreso por correo, ficha inicial y firmas de Talento Humano
--
-- 1. Cómo se comprueba la identidad en el PRIMER ingreso de quien no tiene
--    correo registrado (`alta_verificacion`):
--      correo       registra su correo y entra con el código que le llega
--                   ahí (lo que se usa mientras falten fechas de nacimiento)
--      nacimiento   además debe escribir su fecha de nacimiento, que se
--                   compara con el expediente
--    Lo cambia Talento Humano o Administración desde el sistema, cuando la
--    cobertura de fechas de nacimiento sea suficiente.
--
-- 2. Qué se pide al entrar por primera vez, antes de usar el sistema
--    (`ficha_inicial_campos`): fecha de nacimiento, confirmar la fecha de
--    ingreso, confirmar jefe y cargo, teléfono y contacto de emergencia.
--
-- 3. Quién firma por Talento Humano en cada sede (`firmantes_rrhh`), para
--    los documentos de vacaciones.
--
-- 4. Cuándo firmó el colaborador sus documentos en Talento Humano
--    (`informes_firmados.firmado_en`), que es lo que cierra el trámite.
--
-- Idempotente: se puede volver a aplicar sin error ni duplicados.
-- =====================================================================

INSERT IGNORE INTO app_config (clave, valor, descripcion) VALUES
  ('alta_verificacion', 'correo',
   'Primer ingreso de quien no tiene correo: «correo» (registra su correo y entra con el código) o «nacimiento» (además debe coincidir su fecha de nacimiento).'),
  ('ficha_inicial_campos', 'fecha_nacimiento,fecha_ingreso,jefe,cargo,telefono,emergencia',
   'Lo que se pide al entrar por primera vez, antes de usar el sistema. Separado por comas.'),
  ('empresa_telefono', '+593 99 871 2831', 'Teléfono del pie de los documentos.'),
  ('empresa_correo', 'webpage@flexnetecuador.com', 'Correo del pie de los documentos.'),
  ('empresa_web', 'www.flexnetecuador.com', 'Sitio web del pie de los documentos.');

INSERT IGNORE INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES
  ('fecha_nacimiento', 'Fecha de nacimiento', 'revisado',
   'Con ella se comprueba su identidad. Si está mal, pida la corrección: la revisa Talento Humano.', 205);

DELIMITER $$

DROP PROCEDURE IF EXISTS _migracion_0009 $$
CREATE PROCEDURE _migracion_0009()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'users'
                    AND column_name = 'fecha_ingreso_confirmada_en') THEN
    ALTER TABLE users
      ADD COLUMN fecha_ingreso_confirmada_en DATETIME(6) NULL
        COMMENT 'Cuándo la persona confirmó que su fecha de ingreso es correcta.'
        AFTER jefe_confirmado_en;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'informes_firmados'
                    AND column_name = 'firmado_en') THEN
    ALTER TABLE informes_firmados
      ADD COLUMN firmado_en DATETIME(6) NULL
        COMMENT 'Cuándo Talento Humano recibió el documento firmado por el colaborador.',
      ADD COLUMN firmado_registrado_por CHAR(36) NULL,
      ADD CONSTRAINT informes_firmados_firmado_por_fkey
        FOREIGN KEY (firmado_registrado_por) REFERENCES users(id) ON DELETE SET NULL;
  END IF;
END $$

CALL _migracion_0009() $$
DROP PROCEDURE IF EXISTS _migracion_0009 $$

DELIMITER ;

-- Quién firma por Talento Humano en cada sede. `principal` es la cabeza del
-- departamento en esa sede: sale por defecto en los documentos, y quien
-- imprime puede elegir a otro de la lista.
CREATE TABLE IF NOT EXISTS firmantes_rrhh (
  id          BIGINT NOT NULL AUTO_INCREMENT,
  region      VARCHAR(20) NOT NULL COMMENT 'sierra (Quito) o costa (Guayaquil)',
  user_id     CHAR(36) NOT NULL,
  cargo_firma VARCHAR(120) NULL COMMENT 'Cómo firma: «Jefe de Talento Humano». Vacío = su cargo.',
  principal   TINYINT(1) NOT NULL DEFAULT 0,
  -- Un solo principal por sede: la columna generada vale la región solo
  -- para el principal, y el índice único hace el resto.
  principal_unico VARCHAR(20) GENERATED ALWAYS AS (IF(principal, region, NULL)) VIRTUAL,
  creado_en   DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  creado_por  CHAR(36) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY firmantes_rrhh_persona_sede (region, user_id),
  UNIQUE KEY firmantes_rrhh_un_principal (principal_unico),
  CONSTRAINT firmantes_rrhh_region_valida CHECK (region IN ('sierra', 'costa')),
  CONSTRAINT firmantes_rrhh_user_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT firmantes_rrhh_creado_por_fkey FOREIGN KEY (creado_por) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Quién firma por Talento Humano en cada sede los documentos de vacaciones.';
