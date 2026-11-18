-- =====================================================================
-- 0022 · Revisión (refutación) de un registro del historial de vacaciones
--
-- La persona ve su historial por año y puede refutar un registro («no tomé
-- esos días»), siempre con evidencia: un correo exportado a PDF, una
-- captura, un documento. Talento Humano recibe el pedido con la evidencia
-- por correo y en el sistema, lo acepta o no, y responde.
--
-- Aceptarla NO cambia el saldo por sí sola: Talento Humano corrige el
-- registro o el saldo con las herramientas que ya existen, y esa corrección
-- queda en su propia bitácora.
--
-- Idempotente.
-- =====================================================================

CREATE TABLE IF NOT EXISTS refutaciones_historial (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id CHAR(36) NOT NULL,
  origen VARCHAR(10) NOT NULL COMMENT 'historico: hoja de Talento Humano · solicitud: tramitada en el sistema',
  historico_id BIGINT NULL,
  request_id CHAR(36) NULL,
  fecha_inicio DATE NOT NULL,
  fecha_fin DATE NOT NULL,
  dias DECIMAL(6,2) NOT NULL,
  motivo TEXT NOT NULL,
  estado VARCHAR(12) NOT NULL DEFAULT 'pendiente',
  respuesta TEXT NULL,
  resuelto_por CHAR(36) NULL,
  resuelto_en DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_refutaciones_user (user_id),
  KEY idx_refutaciones_estado (estado),
  CONSTRAINT refutaciones_origen_valido CHECK (origen IN ('historico', 'solicitud')),
  CONSTRAINT refutaciones_estado_valido CHECK (estado IN ('pendiente', 'aceptada', 'rechazada')),
  CONSTRAINT refutaciones_user_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT refutaciones_historico_fkey FOREIGN KEY (historico_id)
    REFERENCES vacaciones_historicas(id) ON DELETE SET NULL,
  CONSTRAINT refutaciones_request_fkey FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE SET NULL,
  CONSTRAINT refutaciones_resuelto_por_fkey FOREIGN KEY (resuelto_por) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Pedidos de revisión de un registro del historial de vacaciones, con evidencia.';

CREATE TABLE IF NOT EXISTS refutacion_evidencias (
  id BIGINT NOT NULL AUTO_INCREMENT,
  refutacion_id BIGINT NOT NULL,
  storage_path TEXT NOT NULL,
  nombre_archivo TEXT NOT NULL,
  mime_type VARCHAR(100) NOT NULL,
  tamano_bytes BIGINT NOT NULL,
  hash_sha256 CHAR(64) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_evidencias_refutacion (refutacion_id),
  CONSTRAINT evidencias_tamano CHECK (tamano_bytes > 0 AND tamano_bytes <= 10485760),
  CONSTRAINT evidencias_refutacion_fkey FOREIGN KEY (refutacion_id)
    REFERENCES refutaciones_historial(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Evidencia de una refutación: correo exportado, captura o documento.';
