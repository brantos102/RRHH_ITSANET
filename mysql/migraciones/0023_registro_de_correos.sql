-- =====================================================================
-- 0023 · Registro de los correos que envía el sistema
--
-- Para responder «¿le llegó el código a Fulano?» o «¿salió el recordatorio?»
-- sin leer el registro del servidor. Guarda lo mínimo (LOPDP): el destino
-- ENMASCARADO (ab***@dominio), el asunto SIN códigos de acceso, si salió,
-- por qué puerto y, si falló, el motivo corto. No guarda el contenido.
--
-- Se depura a los 90 días con la tarea mensual de retención.
-- Idempotente.
-- =====================================================================

CREATE TABLE IF NOT EXISTS correos_enviados (
  id BIGINT NOT NULL AUTO_INCREMENT,
  creado_en DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  destino VARCHAR(120) NOT NULL COMMENT 'Enmascarado: ab***@dominio',
  destino_hash CHAR(64) NULL COMMENT 'SHA-256 del correo en minúsculas, para buscar por persona sin guardarlo',
  asunto VARCHAR(255) NOT NULL COMMENT 'Sin códigos de acceso',
  resultado VARCHAR(10) NOT NULL,
  puerto INT NULL,
  intentos INT NULL,
  error VARCHAR(300) NULL,
  duracion_ms INT NULL,
  PRIMARY KEY (id),
  KEY idx_correos_fecha (creado_en),
  KEY idx_correos_hash (destino_hash),
  CONSTRAINT correos_resultado_valido CHECK (resultado IN ('enviado', 'fallido', 'consola'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Constancia de cada correo enviado por el sistema (sin contenido).';
