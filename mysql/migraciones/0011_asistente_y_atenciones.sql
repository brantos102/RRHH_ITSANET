-- =====================================================================
-- 0011 · Asistente guiado y quién está atendiendo qué
--
-- 1. `atenciones`: cuando alguien de Talento Humano toma un pendiente
--    (un cambio de ficha, una solicitud, una consulta del chat, una firma),
--    los demás lo ven «en revisión por X» y no lo trabajan dos personas a la
--    vez. Caduca sola a las 4 horas: si quien lo tomó se fue, vuelve a quedar
--    libre.
--
-- 2. `asistente_respuestas`: lo que el asistente responde además de lo que
--    ya sabe del sistema (saldo, solicitudes, jefe, feriados…). Las escribe y
--    corrige Talento Humano desde Administración, sin tocar código.
--
-- 3. `asistente_consultas`: de qué se pregunta, para mejorar las respuestas.
--    Mínimo de datos (LOPDP): NO se guarda quién preguntó; el texto solo se
--    guarda cuando el asistente no supo responder, recortado a 200
--    caracteres, y se borra a los 90 días.
--
-- Idempotente.
-- =====================================================================

CREATE TABLE IF NOT EXISTS atenciones (
  tipo       VARCHAR(20) NOT NULL COMMENT 'cambio_ficha, solicitud, chat, firma',
  entidad_id VARCHAR(64) NOT NULL,
  user_id    CHAR(36) NOT NULL COMMENT 'Quién de Talento Humano lo tomó',
  tomado_en  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (tipo, entidad_id),
  CONSTRAINT atenciones_tipo_valido CHECK (tipo IN ('cambio_ficha', 'solicitud', 'chat', 'firma')),
  CONSTRAINT atenciones_user_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Quién de Talento Humano está revisando cada pendiente, para no trabajarlo dos veces.';

CREATE TABLE IF NOT EXISTS asistente_respuestas (
  id              BIGINT NOT NULL AUTO_INCREMENT,
  titulo          VARCHAR(120) NOT NULL COMMENT 'Cómo aparece como sugerencia',
  palabras_clave  VARCHAR(500) NOT NULL COMMENT 'Separadas por coma: «uniforme, dotación»',
  respuesta       TEXT NOT NULL,
  enlace_texto    VARCHAR(80) NULL,
  enlace_url      VARCHAR(300) NULL,
  activo          TINYINT(1) NOT NULL DEFAULT 1,
  orden           INT NOT NULL DEFAULT 100,
  actualizado_por CHAR(36) NULL,
  updated_at      DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  CONSTRAINT asistente_respuestas_por_fkey FOREIGN KEY (actualizado_por) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Respuestas del asistente que redacta Talento Humano.';

CREATE TABLE IF NOT EXISTS asistente_consultas (
  id         BIGINT NOT NULL AUTO_INCREMENT,
  tema       VARCHAR(40) NOT NULL COMMENT 'Qué entendió el asistente, o sin_respuesta',
  respondida TINYINT(1) NOT NULL,
  texto      VARCHAR(200) NULL COMMENT 'Solo si no supo responder. Sin datos de quién preguntó.',
  region     VARCHAR(20) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY asistente_consultas_fecha (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='De qué se pregunta al asistente. Anónimo; se borra a los 90 días.';
