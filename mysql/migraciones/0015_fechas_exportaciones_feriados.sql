-- =====================================================================
-- 0015 · Fecha al imprimir, exportaciones con trazabilidad, feriados
--        dentro de las vacaciones y tamaños de las tarjetas del tablero
--
-- 1. `impresiones_papel`: cada impresión de un documento, con la fecha que
--    se consignó en él. Por defecto es la de hoy. Como el sistema entra a
--    funcionar con vacaciones ya gozadas, Talento Humano puede consignar una
--    fecha ANTERIOR, con justificación, hasta `papeles_fechas_anteriores_max`
--    veces por documento (3). Cada una queda aquí y en la bitácora.
--
-- 2. `exportaciones`: cada archivo que sale del sistema (Excel, PDF, CSV):
--    quién, cuándo, qué informe, con qué filtros, para qué (motivo), cuántas
--    filas y la huella SHA-256 del archivo. LOPDP: los datos que salen del
--    sistema quedan identificados.
--
-- 3. Feriados dentro de unas vacaciones. La hoja de producción cuenta
--    TODOS los días entre el inicio y el fin (=fin−inicio+1): sábados,
--    domingos y feriados. Es lo que dice el Art. 69 del Código del Trabajo
--    («quince días de descanso, incluidos los días no laborables»). El
--    sistema descontaba los feriados aparte. Ahora sigue la regla de
--    producción, con un parámetro para volver a la anterior si Talento
--    Humano lo decide. Solo afecta a las solicitudes NUEVAS: lo ya
--    registrado conserva sus días.
--
-- 4. Tarjetas del tablero: cuatro tamaños (1 = un tercio, 2 = media,
--    3 = dos tercios, 4 = ancho completo) y gráfico de columnas.
--
-- Idempotente.
-- =====================================================================

INSERT IGNORE INTO app_config (clave, valor, descripcion, legal_ref) VALUES
  ('vacaciones_feriados_cuentan', 'true',
   'true: un feriado dentro de unas vacaciones cuenta como día de vacaciones, como en la hoja de producción (fin − inicio + 1) y el Art. 69 del Código del Trabajo («incluidos los días no laborables»). false: el feriado no se descuenta.',
   'CT_ART_69'),
  ('papeles_fechas_anteriores_max', '3',
   'Cuántas veces, en total, se puede imprimir un mismo documento con una fecha anterior a la de hoy. Cada vez exige justificación y queda en la bitácora.',
   NULL);

CREATE TABLE IF NOT EXISTS impresiones_papel (
  id              BIGINT NOT NULL AUTO_INCREMENT,
  informe_id      CHAR(36) NOT NULL,
  fecha_documento DATE NOT NULL COMMENT 'La fecha que se consignó en el documento',
  retroactiva     TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Anterior al día en que se imprimió',
  justificacion   VARCHAR(400) NULL,
  impreso_por     CHAR(36) NULL,
  impreso_en      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY impresiones_papel_informe (informe_id, retroactiva),
  CONSTRAINT impresiones_papel_retroactiva_justificada
    CHECK (retroactiva = 0 OR CHAR_LENGTH(TRIM(COALESCE(justificacion, ''))) >= 15),
  CONSTRAINT impresiones_papel_informe_fkey FOREIGN KEY (informe_id) REFERENCES informes_firmados(id) ON DELETE CASCADE,
  CONSTRAINT impresiones_papel_por_fkey FOREIGN KEY (impreso_por) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Cada impresión de un documento y la fecha consignada en él.';

CREATE TABLE IF NOT EXISTS exportaciones (
  id          BIGINT NOT NULL AUTO_INCREMENT,
  folio       VARCHAR(20) NOT NULL,
  tipo        VARCHAR(30) NOT NULL COMMENT 'personas, saldos, solicitudes, historial, documentos',
  formato     VARCHAR(5) NOT NULL,
  filtros     JSON NOT NULL,
  motivo      VARCHAR(300) NOT NULL COMMENT 'Para qué se exporta (LOPDP: finalidad)',
  filas       INT NOT NULL,
  sha256      CHAR(64) NOT NULL COMMENT 'Huella del archivo entregado',
  generado_por CHAR(36) NULL,
  created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY exportaciones_folio (folio),
  KEY exportaciones_fecha (created_at),
  CONSTRAINT exportaciones_formato_valido CHECK (formato IN ('xlsx', 'pdf', 'csv')),
  CONSTRAINT exportaciones_motivo_minimo CHECK (CHAR_LENGTH(TRIM(motivo)) >= 10),
  CONSTRAINT exportaciones_por_fkey FOREIGN KEY (generado_por) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Archivos que salieron del sistema: quién, qué, para qué y su huella.';

DELIMITER $$

DROP PROCEDURE IF EXISTS _migracion_0015 $$
CREATE PROCEDURE _migracion_0015()
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.check_constraints
              WHERE constraint_schema = DATABASE()
                AND constraint_name = 'tablero_vistas_ancho_valido'
                AND check_clause NOT LIKE '%4%') THEN
    ALTER TABLE tablero_vistas DROP CHECK tablero_vistas_ancho_valido;
    ALTER TABLE tablero_vistas
      ADD CONSTRAINT tablero_vistas_ancho_valido CHECK (ancho BETWEEN 1 AND 4);
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.check_constraints
              WHERE constraint_schema = DATABASE()
                AND constraint_name = 'tablero_vistas_grafico_valido'
                AND check_clause NOT LIKE '%columnas%') THEN
    ALTER TABLE tablero_vistas DROP CHECK tablero_vistas_grafico_valido;
    ALTER TABLE tablero_vistas ADD CONSTRAINT tablero_vistas_grafico_valido
      CHECK (grafico IN ('barras', 'columnas', 'linea', 'tabla', 'cifra'));
  END IF;
END $$

CALL _migracion_0015() $$
DROP PROCEDURE IF EXISTS _migracion_0015 $$

-- Días que descuenta una solicitud. Un permiso cuenta días hábiles. Unas
-- vacaciones cuentan días CALENDARIO, con sábados y domingos dentro; los
-- feriados, según el parámetro (por defecto, también cuentan).
DROP FUNCTION IF EXISTS calcular_dias $$
CREATE FUNCTION calcular_dias(p_tipo VARCHAR(20), p_inicio DATE, p_fin DATE)
RETURNS DECIMAL(6,2)
READS SQL DATA
BEGIN
  DECLARE v_dia DATE;
  DECLARE v_n INT DEFAULT 0;
  DECLARE v_feriados_cuentan BOOLEAN;
  IF p_inicio IS NULL OR p_fin IS NULL OR p_fin < p_inicio THEN
    RETURN 0;
  END IF;
  IF p_tipo = 'permiso' THEN
    RETURN dias_habiles(p_inicio, p_fin);
  END IF;
  SET v_feriados_cuentan = COALESCE(cfg_bool('vacaciones_feriados_cuentan'), TRUE);
  IF v_feriados_cuentan THEN
    RETURN DATEDIFF(p_fin, p_inicio) + 1;
  END IF;
  SET v_dia = p_inicio;
  WHILE v_dia <= p_fin DO
    IF NOT EXISTS (SELECT 1 FROM feriados f WHERE f.fecha = v_dia AND f.activo) THEN
      SET v_n = v_n + 1;
    END IF;
    SET v_dia = DATE_ADD(v_dia, INTERVAL 1 DAY);
  END WHILE;
  RETURN v_n;
END $$

DELIMITER ;
