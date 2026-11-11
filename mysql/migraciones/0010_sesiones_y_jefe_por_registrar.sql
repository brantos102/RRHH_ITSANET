-- =====================================================================
-- 0010 · Sesiones por dispositivo y jefe por registrar
--
-- 1. `sesiones`: cada ingreso queda registrado con su dispositivo. Una
--    cédula tiene a lo sumo `sesiones_simultaneas` sesiones abiertas (1 por
--    defecto): al entrar desde otro dispositivo, la sesión anterior se cierra
--    y se avisa por correo. Si roban el celular o la computadora, basta con
--    entrar desde otro equipo —o que Talento Humano cierre sus sesiones— para
--    que el robado quede fuera.
--
-- 2. `jefe_por_registrar`: cuando el colaborador indica un jefe que no está
--    en el sistema, escribe su nombre y queda como pedido para Talento
--    Humano, que lo registra en Jefaturas. No cambia nada por sí solo.
--
-- Idempotente.
-- =====================================================================

CREATE TABLE IF NOT EXISTS sesiones (
  id            CHAR(36) NOT NULL COMMENT 'Va dentro del token (sid).',
  user_id       CHAR(36) NOT NULL,
  dispositivo   VARCHAR(120) NULL COMMENT 'Legible: «Chrome en Android».',
  dispositivo_id CHAR(64) NULL COMMENT 'Huella SHA-256 del identificador que guarda el navegador.',
  user_agent    VARCHAR(500) NULL,
  ip            VARCHAR(64) NULL,
  creada_en     DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  ultimo_uso    DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  expira_en     DATETIME(6) NOT NULL,
  cerrada_en    DATETIME(6) NULL,
  motivo_cierre VARCHAR(30) NULL,
  cerrada_por   CHAR(36) NULL,
  PRIMARY KEY (id),
  KEY sesiones_abiertas (user_id, cerrada_en, expira_en),
  CONSTRAINT sesiones_motivo_valido CHECK (motivo_cierre IS NULL OR motivo_cierre IN
    ('salida', 'otro_dispositivo', 'mismo_dispositivo', 'cerrada_por_usuario', 'talento_humano')),
  CONSTRAINT sesiones_user_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT sesiones_cerrada_por_fkey FOREIGN KEY (cerrada_por) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Cada ingreso al sistema y desde qué dispositivo. Permite sesión única y cerrar sesiones a distancia.';

INSERT IGNORE INTO app_config (clave, valor, descripcion) VALUES
  ('sesiones_simultaneas', '1',
   'Cuántos dispositivos puede tener abiertos a la vez una misma cédula. Al entrar desde uno más, se cierra el más antiguo.');

INSERT IGNORE INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES
  ('jefe_por_registrar', 'Jefe que no está registrado', 'revisado',
   'El colaborador indicó un jefe que no está en el sistema. Regístrelo en Jefaturas y asígnelo; al aprobar, solo se marca como atendido.', 245);
