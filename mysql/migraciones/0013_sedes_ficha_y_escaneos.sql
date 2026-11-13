-- =====================================================================
-- 0013 · Sedes con sus regiones, discapacidad, tipo de contrato, foto y
--        escaneo de los documentos firmados
--
-- 1. Sedes. La tabla `regiones` es, en realidad, cada SEDE de Talento
--    Humano (Quito, Guayaquil) y la zona que atiende. Se le agrega qué
--    regiones naturales del Ecuador cubre (Costa, Sierra, Amazonía,
--    Insular), para que una sede nueva —Cuenca, Manta— se cree desde el
--    sistema y se le asignen ciudades. Las ciudades llevan su provincia y
--    su región natural.
--    Los firmantes dejan de estar atados a «sierra» o «costa»: valen para
--    cualquier sede registrada.
--
-- 2. Discapacidad (LOPDP Art. 26: dato sensible; base legal: CT Art. 42
--    num. 33 y Ley Orgánica de Discapacidades). Se agrega el tipo y si la
--    persona es SUSTITUTA (cuida a un familiar con discapacidad, LOD Art. 48).
--    El porcentaje y el carné ya existían en `users` pero no se pedían.
--
-- 3. Tipo de contrato y fin del contrato: visibles en Mi ficha, solo
--    lectura. Los cambia Talento Humano.
--
-- 4. Documentos firmados: el escaneo del papel firmado se guarda en el
--    servidor (fuera del repositorio y de la web pública), con su huella
--    SHA-256, quién lo subió y cuándo. Es lo que se presenta en una
--    auditoría.
--
-- Idempotente.
-- =====================================================================

DELIMITER $$

DROP PROCEDURE IF EXISTS _migracion_0013 $$
CREATE PROCEDURE _migracion_0013()
BEGIN
  -- ---------------------------------------------------------------- sedes
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'regiones'
                    AND column_name = 'regiones_naturales') THEN
    ALTER TABLE regiones
      ADD COLUMN regiones_naturales VARCHAR(60) NULL
        COMMENT 'Regiones del Ecuador que atiende: costa, sierra, amazonia, insular (separadas por coma).'
        AFTER sede,
      ADD COLUMN orden INT NOT NULL DEFAULT 100 AFTER activo;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'ciudades_region'
                    AND column_name = 'provincia') THEN
    ALTER TABLE ciudades_region
      ADD COLUMN provincia VARCHAR(60) NULL AFTER ciudad,
      ADD COLUMN region_natural VARCHAR(10) NULL
        COMMENT 'costa, sierra, amazonia o insular' AFTER provincia,
      ADD CONSTRAINT ciudades_region_natural_valida
        CHECK (region_natural IS NULL OR region_natural IN ('costa', 'sierra', 'amazonia', 'insular'));
  END IF;

  -- Firmantes: de la lista fija a la tabla de sedes.
  IF EXISTS (SELECT 1 FROM information_schema.check_constraints
              WHERE constraint_schema = DATABASE()
                AND constraint_name = 'firmantes_rrhh_region_valida') THEN
    ALTER TABLE firmantes_rrhh DROP CHECK firmantes_rrhh_region_valida;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints
                  WHERE constraint_schema = DATABASE() AND table_name = 'firmantes_rrhh'
                    AND constraint_name = 'firmantes_rrhh_region_fkey') THEN
    ALTER TABLE firmantes_rrhh
      ADD CONSTRAINT firmantes_rrhh_region_fkey FOREIGN KEY (region) REFERENCES regiones(codigo);
  END IF;

  -- ----------------------------------------------------------- discapacidad
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'users'
                    AND column_name = 'tipo_discapacidad') THEN
    ALTER TABLE users
      ADD COLUMN tipo_discapacidad VARCHAR(20) NULL
        COMMENT 'fisica, intelectual, auditiva, visual, psicosocial, multiple. Dato sensible.'
        AFTER carnet_conadis,
      ADD COLUMN sustituto_discapacidad TINYINT(1) NOT NULL DEFAULT 0
        COMMENT 'Persona sustituta: tiene a cargo a un familiar con discapacidad (LOD Art. 48).'
        AFTER tipo_discapacidad,
      ADD CONSTRAINT users_tipo_discapacidad_valido
        CHECK (tipo_discapacidad IS NULL OR tipo_discapacidad IN
               ('fisica', 'intelectual', 'auditiva', 'visual', 'psicosocial', 'multiple'));
  END IF;

  -- ------------------------------------------------- escaneo de lo firmado
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = DATABASE() AND table_name = 'informes_firmados'
                    AND column_name = 'escaneo_ruta') THEN
    ALTER TABLE informes_firmados
      ADD COLUMN escaneo_ruta VARCHAR(255) NULL
        COMMENT 'Ruta dentro de ADJUNTOS_DIR del documento firmado y escaneado.',
      ADD COLUMN escaneo_nombre VARCHAR(160) NULL,
      ADD COLUMN escaneo_mime VARCHAR(60) NULL,
      ADD COLUMN escaneo_bytes INT NULL,
      ADD COLUMN escaneo_sha256 CHAR(64) NULL
        COMMENT 'Huella del archivo: prueba que no se alteró después de subirlo.',
      ADD COLUMN escaneo_subido_por CHAR(36) NULL,
      ADD COLUMN escaneo_subido_en DATETIME(6) NULL,
      ADD CONSTRAINT informes_firmados_escaneo_por_fkey
        FOREIGN KEY (escaneo_subido_por) REFERENCES users(id) ON DELETE SET NULL;
  END IF;
END $$

CALL _migracion_0013() $$
DROP PROCEDURE IF EXISTS _migracion_0013 $$

-- El buzón del departamento de cualquier sede: rrhh_correo_<código>.
DROP FUNCTION IF EXISTS rrhh_correo_de_region $$
CREATE FUNCTION rrhh_correo_de_region(p_region VARCHAR(40))
RETURNS TEXT
READS SQL DATA
BEGIN
  RETURN cfg_texto(CONCAT('rrhh_correo_', COALESCE(NULLIF(p_region, ''), 'sierra')));
END $$

DELIMITER ;

UPDATE regiones SET regiones_naturales = 'sierra,amazonia', orden = 10
 WHERE codigo = 'sierra' AND regiones_naturales IS NULL;
UPDATE regiones SET regiones_naturales = 'costa,insular', orden = 20
 WHERE codigo = 'costa' AND regiones_naturales IS NULL;

-- Provincia y región natural de las ciudades ya registradas. Solo donde
-- falta: lo que Talento Humano corrija desde el sistema no se pisa.
UPDATE ciudades_region c
  JOIN (
    SELECT 'BABAHOYO' AS ciudad, 'Los Ríos' AS provincia, 'costa' AS rn UNION ALL
    SELECT 'BAHIA DE CARAQUEZ', 'Manabí', 'costa' UNION ALL
    SELECT 'CHONE', 'Manabí', 'costa' UNION ALL
    SELECT 'DAULE', 'Guayas', 'costa' UNION ALL
    SELECT 'DURAN', 'Guayas', 'costa' UNION ALL
    SELECT 'EL TRIUNFO', 'Guayas', 'costa' UNION ALL
    SELECT 'ESMERALDAS', 'Esmeraldas', 'costa' UNION ALL
    SELECT 'GALAPAGOS', 'Galápagos', 'insular' UNION ALL
    SELECT 'GUAYAQUIL', 'Guayas', 'costa' UNION ALL
    SELECT 'HUAQUILLAS', 'El Oro', 'costa' UNION ALL
    SELECT 'JIPIJAPA', 'Manabí', 'costa' UNION ALL
    SELECT 'LA LIBERTAD', 'Santa Elena', 'costa' UNION ALL
    SELECT 'MACHALA', 'El Oro', 'costa' UNION ALL
    SELECT 'MANTA', 'Manabí', 'costa' UNION ALL
    SELECT 'MILAGRO', 'Guayas', 'costa' UNION ALL
    SELECT 'NARANJAL', 'Guayas', 'costa' UNION ALL
    SELECT 'PASAJE', 'El Oro', 'costa' UNION ALL
    SELECT 'PLAYAS', 'Guayas', 'costa' UNION ALL
    SELECT 'PORTOVIEJO', 'Manabí', 'costa' UNION ALL
    SELECT 'PUERTO AYORA', 'Galápagos', 'insular' UNION ALL
    SELECT 'PUERTO BAQUERIZO MORENO', 'Galápagos', 'insular' UNION ALL
    SELECT 'QUEVEDO', 'Los Ríos', 'costa' UNION ALL
    SELECT 'SALINAS', 'Santa Elena', 'costa' UNION ALL
    SELECT 'SAMBORONDON', 'Guayas', 'costa' UNION ALL
    SELECT 'SANTA ELENA', 'Santa Elena', 'costa' UNION ALL
    SELECT 'SANTO DOMINGO', 'Santo Domingo de los Tsáchilas', 'costa' UNION ALL
    SELECT 'VENTANAS', 'Los Ríos', 'costa' UNION ALL
    SELECT 'ALAUSI', 'Chimborazo', 'sierra' UNION ALL
    SELECT 'AMBATO', 'Tungurahua', 'sierra' UNION ALL
    SELECT 'AZOGUES', 'Cañar', 'sierra' UNION ALL
    SELECT 'CAÑAR', 'Cañar', 'sierra' UNION ALL
    SELECT 'CAYAMBE', 'Pichincha', 'sierra' UNION ALL
    SELECT 'COCA', 'Orellana', 'amazonia' UNION ALL
    SELECT 'CUENCA', 'Azuay', 'sierra' UNION ALL
    SELECT 'EL COCA', 'Orellana', 'amazonia' UNION ALL
    SELECT 'GUARANDA', 'Bolívar', 'sierra' UNION ALL
    SELECT 'IBARRA', 'Imbabura', 'sierra' UNION ALL
    SELECT 'LAGO AGRIO', 'Sucumbíos', 'amazonia' UNION ALL
    SELECT 'LATACUNGA', 'Cotopaxi', 'sierra' UNION ALL
    SELECT 'LOJA', 'Loja', 'sierra' UNION ALL
    SELECT 'MACAS', 'Morona Santiago', 'amazonia' UNION ALL
    SELECT 'MACHACHI', 'Pichincha', 'sierra' UNION ALL
    SELECT 'NUEVA LOJA', 'Sucumbíos', 'amazonia' UNION ALL
    SELECT 'OTAVALO', 'Imbabura', 'sierra' UNION ALL
    SELECT 'PELILEO', 'Tungurahua', 'sierra' UNION ALL
    SELECT 'PILLARO', 'Tungurahua', 'sierra' UNION ALL
    SELECT 'PUYO', 'Pastaza', 'amazonia' UNION ALL
    SELECT 'QUITO', 'Pichincha', 'sierra' UNION ALL
    SELECT 'RIOBAMBA', 'Chimborazo', 'sierra' UNION ALL
    SELECT 'SALCEDO', 'Cotopaxi', 'sierra' UNION ALL
    SELECT 'SANGOLQUI', 'Pichincha', 'sierra' UNION ALL
    SELECT 'SUCUA', 'Morona Santiago', 'amazonia' UNION ALL
    SELECT 'TENA', 'Napo', 'amazonia' UNION ALL
    SELECT 'TULCAN', 'Carchi', 'sierra' UNION ALL
    SELECT 'ZAMORA', 'Zamora Chinchipe', 'amazonia'
  ) d ON d.ciudad = c.ciudad
   SET c.provincia = COALESCE(c.provincia, d.provincia),
       c.region_natural = COALESCE(c.region_natural, d.rn);

-- Los campos nuevos de la ficha y quién decide sobre cada uno.
INSERT IGNORE INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES
  ('porcentaje_discapacidad', 'Porcentaje de discapacidad', 'revisado',
   'El que consta en su carné o certificado. Lo verifica Talento Humano.', 101),
  ('carnet_conadis', 'Carné o certificado de discapacidad', 'revisado',
   'Número del carné del CONADIS o del certificado del Ministerio de Salud.', 102),
  ('tipo_discapacidad', 'Tipo de discapacidad', 'revisado', NULL, 103),
  ('sustituto_discapacidad', 'Persona sustituta', 'revisado',
   'Tiene a su cargo a un familiar con discapacidad (Ley Orgánica de Discapacidades, Art. 48).', 104),
  ('tipo_contrato', 'Tipo de contrato', 'bloqueado',
   'Lo registra Talento Humano según su contrato firmado.', 215),
  ('contrato_fin', 'Fin del contrato', 'bloqueado',
   'Solo en contratos a plazo. Lo registra Talento Humano.', 216);

UPDATE campos_ficha
   SET etiqueta = 'Tiene discapacidad',
       ayuda = 'Dato sensible (LOPDP): solo lo ven usted y Talento Humano. Da derecho a los permisos y protecciones de ley.'
 WHERE campo = 'tiene_discapacidad';

-- Para leer los pedidos de cambio: «Sí» y «No» en lugar de 1 y 0.
CREATE OR REPLACE VIEW v_cambios_ficha_pendientes AS
SELECT c.id, c.user_id, u.cedula, u.nombre AS persona, u.departamento, u.ciudad,
       COALESCE(u.region, 'sierra') AS region, c.campo, f.etiqueta,
       c.valor_anterior, c.valor_nuevo, c.motivo, c.created_at,
       CASE WHEN c.campo = 'jefe_id'
            THEN COALESCE((SELECT j.nombre FROM users j WHERE j.id = c.valor_anterior), c.valor_anterior)
            WHEN c.campo IN ('tiene_discapacidad', 'sustituto_discapacidad')
            THEN CASE c.valor_anterior WHEN '1' THEN 'Sí' WHEN '0' THEN 'No' ELSE c.valor_anterior END
            ELSE c.valor_anterior END AS anterior_legible,
       CASE WHEN c.campo = 'jefe_id'
            THEN COALESCE((SELECT j.nombre FROM users j WHERE j.id = c.valor_nuevo), c.valor_nuevo)
            WHEN c.campo IN ('tiene_discapacidad', 'sustituto_discapacidad')
            THEN CASE c.valor_nuevo WHEN '1' THEN 'Sí' WHEN '0' THEN 'No' ELSE c.valor_nuevo END
            ELSE c.valor_nuevo END AS nuevo_legible
  FROM cambios_ficha c
  JOIN users u ON u.id = c.user_id
  JOIN campos_ficha f ON f.campo = c.campo
 WHERE c.estado = 'pendiente'
 ORDER BY c.created_at;
