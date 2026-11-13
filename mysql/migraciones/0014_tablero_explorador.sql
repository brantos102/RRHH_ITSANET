-- =====================================================================
-- 0014 · Tableros que arma Talento Humano (al estilo de Power BI)
--
-- 1. `tablero_vistas`: cada gráfico que alguien de Talento Humano arma en
--    el explorador —una medida (personas, días de saldo, días gozados,
--    solicitudes, altas, bajas) por una dimensión (sede, área, ciudad,
--    cargo, contrato, antigüedad, mes…) con sus filtros— y guarda en su
--    tablero. Puede compartirlo con el resto del departamento.
--    Solo guarda la DEFINICIÓN del gráfico; los números se calculan al
--    abrirlo y son siempre agregados (ningún nombre: LOPDP Art. 10).
--
-- 2. Bloque «Cuota de discapacidad»: cuántas personas con discapacidad (y
--    sustitutas) hay frente al 4 % que exige el Código del Trabajo (Art. 42,
--    num. 33) a quien tiene 25 o más trabajadores.
--
-- Idempotente.
-- =====================================================================

CREATE TABLE IF NOT EXISTS tablero_vistas (
  id          BIGINT NOT NULL AUTO_INCREMENT,
  nombre      VARCHAR(120) NOT NULL,
  medida      VARCHAR(30) NOT NULL,
  dimension   VARCHAR(30) NOT NULL,
  grafico     VARCHAR(12) NOT NULL DEFAULT 'barras' COMMENT 'barras, linea, tabla, cifra',
  filtros     JSON NOT NULL DEFAULT (JSON_OBJECT()) COMMENT '{sede, area, desde, hasta}',
  orden       INT NOT NULL DEFAULT 100,
  ancho       TINYINT NOT NULL DEFAULT 1 COMMENT '1 = media pantalla, 2 = completa',
  compartida  TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'La ve todo Talento Humano',
  creado_por  CHAR(36) NOT NULL,
  created_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at  DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY tablero_vistas_creador (creado_por, orden),
  CONSTRAINT tablero_vistas_grafico_valido CHECK (grafico IN ('barras', 'linea', 'tabla', 'cifra')),
  CONSTRAINT tablero_vistas_ancho_valido CHECK (ancho IN (1, 2)),
  CONSTRAINT tablero_vistas_creador_fkey FOREIGN KEY (creado_por) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='Gráficos que Talento Humano arma y guarda en su tablero. Solo la definición; los datos se calculan al verlos.';

INSERT IGNORE INTO tablero_bloques (clave, titulo, descripcion, pregunta, visible, orden, ajustes) VALUES
  ('cuota_discapacidad', 'Cuota de discapacidad',
   'Personas con discapacidad y sustitutas frente al 4 % de la planilla activa (CT Art. 42, num. 33; LOD Art. 47).',
   '¿Cumplimos la cuota legal de personas con discapacidad?', 1, 95,
   JSON_OBJECT('porcentaje', 4));
