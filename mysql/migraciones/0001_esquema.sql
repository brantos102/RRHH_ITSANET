-- ---------------------------------------------------------------------------
-- 0001 · El esquema del sistema en MySQL 8.0.
--
-- Traducido del esquema vivo de PostgreSQL —el que dejaron las 46
-- migraciones de supabase/migrations—, leyendo su catálogo columna por
-- columna. Comprobado: las 447 columnas de PostgreSQL están aquí, más tres
-- columnas generadas que emulan sus índices únicos parciales.
--
-- QUÉ CAMBIA RESPECTO DE POSTGRESQL, Y POR QUÉ
--
--   uuid             CHAR(36). Legible desde phpMyAdmin o Workbench; con 351
--                    personas no hay nada que optimizar.
--   citext           VARCHAR con colación utf8mb4_0900_ai_ci, que ignora
--                    mayúsculas Y tildes al comparar: «Suárez» = «suarez».
--   enumerados       VARCHAR + CHECK (... IN (...)). Añadir un valor es
--                    cambiar una línea, no recrear un tipo.
--   jsonb, arreglos  JSON.
--   timestamptz      DATETIME(6) en hora de Ecuador. La aplicación fija la
--                    zona -05:00 en cada conexión (Ecuador no tiene horario
--                    de verano).
--   text             TEXT, salvo donde hay que indexar (VARCHAR(255)) o donde
--                    un CHECK limita los valores (VARCHAR(40)). En PostgreSQL
--                    `text` no tiene límite; aquí tampoco puede tenerlo, o un
--                    texto largo se rechazaría —o, sin modo estricto, se
--                    recortaría sin avisar—.
--   updated_at       ON UPDATE CURRENT_TIMESTAMP(6): nativo, sin disparador.
--   secuencias       AUTO_INCREMENT.
--
-- ÍNDICES ÚNICOS PARCIALES. Tres eran reglas de negocio, no rendimiento:
-- un contacto de emergencia principal por persona, una firma activa por
-- persona y una sola constancia de goce sin autorización por persona. MySQL
-- no tiene índices parciales; se emulan con una columna generada VIRTUAL que
-- vale NULL fuera de la condición y un índice único sobre ella (UNIQUE
-- admite varios NULL). Comprobado que la tercera rechaza una segunda
-- constancia sin autorizar y acepta una reemisión autorizada.
--
-- Los índices parciales que eran solo de rendimiento (21) son índices
-- normales: con este volumen la diferencia no existe.
--
-- LO QUE NO ESTÁ AQUÍ. Diez restricciones CHECK de PostgreSQL que MySQL no
-- admite tal cual van como disparadores en la 0002. Las reglas de negocio
-- de las solicitudes van en Python (servidor/app/reglas/).
--
-- IDEMPOTENTE: todo es CREATE TABLE IF NOT EXISTS y los índices van dentro
-- de cada tabla, porque MySQL no tiene CREATE INDEX IF NOT EXISTS.
--
-- OJO: en MySQL el DDL confirma solo, no hay transacción que lo deshaga.
-- Si esta migración se corta a la mitad, quedan las tablas creadas hasta
-- ese punto, y volver a ejecutarla completa lo que falte.
-- ---------------------------------------------------------------------------

SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- Las tablas se crean en orden alfabético y varias se apuntan entre sí.
-- Sin esto MySQL rechazaría una clave foránea hacia una tabla que todavía
-- no existe.
SET FOREIGN_KEY_CHECKS = 0;

CREATE TABLE IF NOT EXISTS access_logs (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id CHAR(36) NULL,
  cedula TEXT NULL,
  visitor_id CHAR(36) NULL,
  request_id CHAR(36) NULL,
  tipo_acceso VARCHAR(24) NOT NULL,
  autorizado BOOLEAN NOT NULL DEFAULT TRUE,
  observacion TEXT NULL,
  guardia_id CHAR(36) NULL,
  ip VARCHAR(45) NULL,
  user_agent TEXT NULL,
  metadata JSON NOT NULL DEFAULT (JSON_OBJECT()),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT access_logs_guardia_id_fkey FOREIGN KEY (guardia_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT access_logs_request_id_fkey FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE SET NULL,
  CONSTRAINT access_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT access_logs_visitor_id_fkey FOREIGN KEY (visitor_id) REFERENCES visitors(id) ON DELETE SET NULL,
  PRIMARY KEY (id),
  CONSTRAINT access_logs_tipo_acceso_valido CHECK (tipo_acceso IN ('salida_empleado', 'retorno_empleado', 'ingreso_visita', 'salida_visita', 'acceso_denegado')),
  KEY idx_access_logs_fecha (created_at DESC),
  KEY idx_access_logs_user (user_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS altas_pendientes (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  cedula TEXT NOT NULL,
  token CHAR(36) NOT NULL DEFAULT (UUID()),
  expira_en DATETIME(6) NOT NULL DEFAULT (CURRENT_TIMESTAMP(6) + INTERVAL 30 MINUTE),
  usado_en DATETIME(6) NULL,
  ip VARCHAR(45) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT altas_pendientes_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  KEY altas_pendientes_token_idx (token),
  KEY altas_pendientes_user_idx (user_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Permiso temporal para completar la ficha de quien no tiene correo registrado. Dura 30 minutos y se usa una sola vez.';

CREATE TABLE IF NOT EXISTS antiguedad_referencia (
  anios_desde SMALLINT NOT NULL,
  anios_hasta SMALLINT NULL,
  dias_gozar SMALLINT NOT NULL,
  dias_laborables SMALLINT NOT NULL,
  dias_no_laborables SMALLINT NOT NULL,
  nota TEXT NULL,
  CONSTRAINT antiguedad_suma_coherente CHECK (((dias_laborables + dias_no_laborables) = dias_gozar)),
  PRIMARY KEY (anios_desde)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Tabla oficial de ITSANET: días de vacaciones por años laborados, con el desglose entre laborables y no laborables. Los días son calendario.';

CREATE TABLE IF NOT EXISTS app_config (
  clave VARCHAR(255) NOT NULL,
  valor TEXT NOT NULL,
  descripcion TEXT NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  legal_ref VARCHAR(255) NULL,
  CONSTRAINT app_config_legal_ref_fkey FOREIGN KEY (legal_ref) REFERENCES legal_references(codigo),
  PRIMARY KEY (clave)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS audit_logs (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id CHAR(36) NULL,
  cedula TEXT NULL,
  accion TEXT NOT NULL,
  entidad TEXT NULL,
  entidad_id TEXT NULL,
  ip VARCHAR(45) NULL,
  user_agent TEXT NULL,
  detalle JSON NOT NULL DEFAULT (JSON_OBJECT()),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT audit_logs_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
  PRIMARY KEY (id),
  KEY idx_audit_logs_fecha (created_at DESC),
  KEY idx_audit_logs_user (user_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS auth_otp (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  cedula VARCHAR(255) NOT NULL,
  user_id CHAR(36) NULL,
  email VARCHAR(255) NOT NULL,
  code_hash TEXT NOT NULL,
  intentos INT NOT NULL DEFAULT 0,
  max_intentos INT NOT NULL DEFAULT 5,
  expira_en DATETIME(6) NOT NULL,
  consumido_en DATETIME(6) NULL COMMENT 'Cuándo se usó para entrar. Nulo si nunca se usó.',
  ip VARCHAR(45) NULL,
  user_agent TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  anulado_en DATETIME(6) NULL COMMENT 'Cuándo dejó de servir sin haberse usado: lo reemplazó uno nuevo, o se agotaron los intentos.',
  CONSTRAINT auth_otp_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  KEY idx_auth_otp_cedula (cedula, created_at DESC),
  KEY idx_auth_otp_vigente (expira_en),
  KEY idx_auth_otp_sin_anular (cedula, created_at DESC),
  KEY idx_auth_otp_consumidos (cedula, consumido_en DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='OTP numérico enviado al correo del usuario. Solo se almacena el hash del código.';

CREATE TABLE IF NOT EXISTS cambios_ficha (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id CHAR(36) NOT NULL,
  campo VARCHAR(255) NOT NULL,
  valor_anterior TEXT NULL,
  valor_nuevo TEXT NOT NULL,
  motivo TEXT NULL,
  estado VARCHAR(255) NOT NULL DEFAULT ('pendiente'),
  resuelto_por CHAR(36) NULL,
  resuelto_en DATETIME(6) NULL,
  motivo_rechazo TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT cambios_ficha_estado_check CHECK ((estado IN ('pendiente', 'aprobado', 'rechazado'))),
  CONSTRAINT cambios_ficha_campo_fkey FOREIGN KEY (campo) REFERENCES campos_ficha(campo),
  CONSTRAINT cambios_ficha_resuelto_por_fkey FOREIGN KEY (resuelto_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT cambios_ficha_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  KEY cambios_ficha_pendientes_idx (estado, created_at),
  KEY cambios_ficha_usuario_idx (user_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Cambios de ficha que Talento Humano debe validar antes de que rijan. Queda el valor anterior para poder revertir.';

CREATE TABLE IF NOT EXISTS campos_ficha (
  campo VARCHAR(255) NOT NULL,
  etiqueta TEXT NOT NULL,
  nivel VARCHAR(40) NOT NULL,
  ayuda TEXT NULL,
  orden INT NOT NULL DEFAULT 100,
  CONSTRAINT campos_ficha_nivel_check CHECK ((nivel IN ('libre', 'revisado', 'confirmado', 'bloqueado'))),
  PRIMARY KEY (campo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS ciudades_region (
  ciudad VARCHAR(255) NOT NULL,
  region VARCHAR(255) NOT NULL,
  CONSTRAINT ciudades_region_region_fkey FOREIGN KEY (region) REFERENCES regiones(codigo),
  PRIMARY KEY (ciudad)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS confirmaciones_correo (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  email TEXT NOT NULL,
  token CHAR(36) NOT NULL DEFAULT (UUID()),
  expira_en DATETIME(6) NOT NULL DEFAULT (CURRENT_TIMESTAMP(6) + INTERVAL 24 HOUR),
  confirmado_en DATETIME(6) NULL,
  ip VARCHAR(45) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT confirmaciones_correo_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  KEY confirmaciones_correo_token_idx (token),
  KEY confirmaciones_correo_usuario_idx (user_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Correo declarado por la persona que todavía no rige. Se aplica cuando abre el enlace, dentro de las 24 horas.';

CREATE TABLE IF NOT EXISTS conversaciones (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  region VARCHAR(255) NOT NULL DEFAULT ('sierra'),
  asunto TEXT NULL,
  estado VARCHAR(255) NOT NULL DEFAULT ('abierta'),
  atendida_por CHAR(36) NULL,
  cerrada_en DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT conversaciones_estado_check CHECK ((estado IN ('abierta', 'cerrada'))),
  CONSTRAINT conversaciones_atendida_por_fkey FOREIGN KEY (atendida_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT conversaciones_region_fkey FOREIGN KEY (region) REFERENCES regiones(codigo),
  CONSTRAINT conversaciones_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  KEY conversaciones_persona_idx (user_id, updated_at DESC),
  KEY conversaciones_bandeja_idx (region, estado, updated_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Consultas de un colaborador a Talento Humano. Llegan al equipo de su región: cualquiera puede responder.';

CREATE TABLE IF NOT EXISTS data_consents (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  politica_version TEXT NOT NULL,
  finalidad TEXT NOT NULL,
  otorgado BOOLEAN NOT NULL DEFAULT TRUE,
  otorgado_en DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  revocado_en DATETIME(6) NULL,
  ip VARCHAR(45) NULL,
  user_agent TEXT NULL,
  CONSTRAINT data_consents_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  KEY idx_consents_user (user_id, otorgado_en DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Consentimiento informado del titular (LOPDP Art. 7). Se registra versión de política, finalidad, fecha e IP.';

CREATE TABLE IF NOT EXISTS data_subject_requests (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  tipo VARCHAR(29) NOT NULL,
  detalle TEXT NOT NULL,
  estado VARCHAR(20) NOT NULL DEFAULT ('recibida'),
  respuesta TEXT NULL,
  atendida_por CHAR(36) NULL,
  vence_en DATE NOT NULL DEFAULT (CURRENT_DATE + INTERVAL 15 DAY),
  atendida_en DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT data_subject_requests_atendida_por_fkey FOREIGN KEY (atendida_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT data_subject_requests_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  CONSTRAINT data_subject_requests_tipo_valido CHECK (tipo IN ('acceso', 'rectificacion', 'eliminacion', 'oposicion', 'portabilidad', 'decision_automatizada')),
  CONSTRAINT data_subject_requests_estado_valido CHECK (estado IN ('recibida', 'en_proceso', 'atendida', 'rechazada'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Ejercicio de derechos ARCO (LOPDP Art. 12-16). Plazo legal de atención: 15 días.';

CREATE TABLE IF NOT EXISTS emergency_contacts (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  nombre TEXT NOT NULL,
  parentesco VARCHAR(20) NOT NULL,
  telefono TEXT NOT NULL,
  telefono_alternativo TEXT NULL,
  direccion TEXT NULL,
  es_principal BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT emergency_contacts_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  principal_unico CHAR(36) GENERATED ALWAYS AS (IF(es_principal, user_id, NULL)) VIRTUAL,
  UNIQUE KEY idx_emergency_principal (principal_unico),
  CONSTRAINT emergency_contacts_parentesco_valido CHECK (parentesco IN ('conyuge', 'conviviente', 'hijo', 'padre', 'madre', 'hermano', 'abuelo', 'nieto', 'suegro', 'cunado', 'otro')),
  KEY idx_emergency_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS family_members (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  nombre TEXT NOT NULL,
  cedula TEXT NULL,
  parentesco VARCHAR(20) NOT NULL,
  grado_consanguinidad INT NOT NULL DEFAULT 1,
  fecha_nacimiento DATE NULL,
  es_carga_familiar BOOLEAN NOT NULL DEFAULT FALSE,
  tiene_discapacidad BOOLEAN NOT NULL DEFAULT FALSE,
  porcentaje_discapacidad INT NULL,
  observacion TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT family_members_grado_consanguinidad_check CHECK (((grado_consanguinidad >= 1) AND (grado_consanguinidad <= 4))),
  CONSTRAINT family_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  CONSTRAINT family_members_parentesco_valido CHECK (parentesco IN ('conyuge', 'conviviente', 'hijo', 'padre', 'madre', 'hermano', 'abuelo', 'nieto', 'suegro', 'cunado', 'otro')),
  KEY idx_family_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Cargas familiares y parientes. El grado de consanguinidad sustenta la licencia del Art. 42 núm. 30 (hasta 2do grado).';

CREATE TABLE IF NOT EXISTS feriados (
  fecha DATE NOT NULL,
  nombre TEXT NOT NULL,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (fecha)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS informes_firmados (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  tipo VARCHAR(20) NOT NULL,
  request_id CHAR(36) NULL,
  folio VARCHAR(255) NOT NULL,
  autorizado_por CHAR(36) NULL,
  autorizado_en DATETIME(6) NULL,
  autorizacion_motivo TEXT NULL,
  emitido_en DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  emitido_por CHAR(36) NULL,
  datos JSON NOT NULL COMMENT 'El contenido tal como se emitió. Reimprimir con los datos de hoy sería falsificar lo que se firmó.',
  impresiones INT NOT NULL DEFAULT 0,
  ultima_impresion DATETIME(6) NULL,
  CONSTRAINT informe_solicitud_con_solicitud CHECK ((((tipo = 'solicitud') AND (request_id IS NOT NULL)) OR ((tipo = 'trazabilidad') AND (request_id IS NULL)))),
  CONSTRAINT informes_firmados_autorizado_por_fkey FOREIGN KEY (autorizado_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT informes_firmados_emitido_por_fkey FOREIGN KEY (emitido_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT informes_firmados_request_id_fkey FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE,
  CONSTRAINT informes_firmados_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  CONSTRAINT informes_firmados_folio_key UNIQUE (folio),
  trazabilidad_unica CHAR(36) GENERATED ALWAYS AS (IF(tipo = 'trazabilidad' AND autorizado_por IS NULL, user_id, NULL)) VIRTUAL,
  UNIQUE KEY idx_trazabilidad_una_sola_vez (trazabilidad_unica),
  CONSTRAINT informes_firmados_tipo_valido CHECK (tipo IN ('trazabilidad', 'solicitud')),
  KEY idx_informes_firmados_persona (user_id, tipo, emitido_en DESC),
  KEY idx_informes_firmados_solicitud (request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Cada papel que el colaborador firma y presenta en Talento Humano, con la foto de lo que decía.';

CREATE TABLE IF NOT EXISTS jornadas_temporales (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  temporal_id CHAR(36) NOT NULL,
  fecha DATE NOT NULL DEFAULT (CURRENT_DATE),
  entrada_en DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  salida_en DATETIME(6) NULL,
  horas DECIMAL(5,2) NULL,
  registro_entrada CHAR(36) NULL,
  registro_salida CHAR(36) NULL,
  observacion TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT jornada_salida_posterior CHECK (((salida_en IS NULL) OR (salida_en >= entrada_en))),
  CONSTRAINT jornadas_temporales_registro_entrada_fkey FOREIGN KEY (registro_entrada) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT jornadas_temporales_registro_salida_fkey FOREIGN KEY (registro_salida) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT jornadas_temporales_temporal_id_fkey FOREIGN KEY (temporal_id) REFERENCES personal_temporal(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  CONSTRAINT jornada_unica_por_dia UNIQUE (temporal_id, fecha),
  KEY jornadas_fecha_idx (fecha DESC),
  KEY jornadas_abiertas_idx (temporal_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Una fila por operario y día. Sin salida registrada, la jornada no se puede pagar: el sistema la señala y no la inventa.';

CREATE TABLE IF NOT EXISTS legal_references (
  codigo VARCHAR(255) NOT NULL,
  norma TEXT NOT NULL,
  articulo TEXT NOT NULL,
  titulo TEXT NOT NULL,
  texto TEXT NOT NULL,
  url_oficial TEXT NULL,
  categoria TEXT NOT NULL DEFAULT ('laboral'),
  orden INT NOT NULL DEFAULT 100,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  visibilidad VARCHAR(40) NOT NULL DEFAULT ('completo') COMMENT 'completo = texto literal; resumen = la línea llana de resumen; oculto = no se muestra al colaborador.',
  resumen TEXT NULL COMMENT 'Explicación en lenguaje llano que Talento Humano sostiene. Obligatoria para usar el modo resumen.',
  visibilidad_en DATETIME(6) NULL,
  visibilidad_por CHAR(36) NULL,
  CONSTRAINT legal_resumen_si_resume CHECK (((visibilidad <> 'resumen') OR (COALESCE(TRIM(resumen), '') <> ''))),
  CONSTRAINT legal_visibilidad_valida CHECK ((visibilidad IN ('completo', 'resumen', 'oculto'))),
  CONSTRAINT legal_references_visibilidad_por_fkey FOREIGN KEY (visibilidad_por) REFERENCES users(id) ON DELETE SET NULL,
  PRIMARY KEY (codigo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Glosario que el aplicativo muestra al empleado para explicar de dónde sale cada regla y cada resultado.';

CREATE TABLE IF NOT EXISTS lineamientos_solicitud (
  id BIGINT NOT NULL AUTO_INCREMENT,
  ambito VARCHAR(255) NOT NULL DEFAULT ('ambos'),
  texto TEXT NOT NULL,
  orden SMALLINT NOT NULL DEFAULT 100,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  actualizado_en DATETIME(6) NULL,
  actualizado_por CHAR(36) NULL,
  CONSTRAINT lineamientos_solicitud_ambito_check CHECK ((ambito IN ('vacacion', 'permiso', 'ambos'))),
  CONSTRAINT lineamientos_solicitud_texto_check CHECK (((CHAR_LENGTH(TRIM(texto)) >= 5) AND (CHAR_LENGTH(TRIM(texto)) <= 400))),
  CONSTRAINT lineamientos_solicitud_actualizado_por_fkey FOREIGN KEY (actualizado_por) REFERENCES users(id) ON DELETE SET NULL,
  PRIMARY KEY (id),
  KEY lineamientos_orden_idx (ambito, activo, orden)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Las reglas internas que ve quien va a pedir vacaciones o un permiso. Las escribe Talento Humano: cambian por circular, no por versión del sistema.';

CREATE TABLE IF NOT EXISTS mensajes (
  id BIGINT NOT NULL AUTO_INCREMENT,
  conversacion_id CHAR(36) NOT NULL,
  autor_id CHAR(36) NOT NULL,
  es_rrhh BOOLEAN NOT NULL DEFAULT FALSE,
  texto TEXT NOT NULL,
  leido_en DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT mensajes_texto_check CHECK (((CHAR_LENGTH(TRIM(texto)) >= 1) AND (CHAR_LENGTH(TRIM(texto)) <= 2000))),
  CONSTRAINT mensajes_autor_id_fkey FOREIGN KEY (autor_id) REFERENCES users(id) ON DELETE CASCADE,
  CONSTRAINT mensajes_conversacion_id_fkey FOREIGN KEY (conversacion_id) REFERENCES conversaciones(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  KEY mensajes_conversacion_idx (conversacion_id, created_at),
  KEY mensajes_sin_leer_idx (conversacion_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS notifications (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  tipo VARCHAR(30) NOT NULL,
  severidad VARCHAR(20) NOT NULL DEFAULT ('info'),
  titulo TEXT NOT NULL,
  mensaje TEXT NOT NULL,
  legal_ref VARCHAR(255) NULL,
  entidad TEXT NULL,
  entidad_id TEXT NULL,
  accion_url TEXT NULL,
  clave_dedupe VARCHAR(255) NULL COMMENT 'Clave idempotente (usuario + tipo + período + mes) para que la tarea diaria no duplique alertas.',
  leida_en DATETIME(6) NULL,
  email_enviado_en DATETIME(6) NULL,
  expira_en DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT notifications_legal_ref_fkey FOREIGN KEY (legal_ref) REFERENCES legal_references(codigo),
  CONSTRAINT notifications_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  CONSTRAINT notifications_clave_dedupe_key UNIQUE (clave_dedupe),
  CONSTRAINT notifications_tipo_valido CHECK (tipo IN ('saldo_alto', 'vacaciones_por_caducar', 'periodo_caducado', 'solicitud_pendiente', 'solicitud_aprobada', 'solicitud_rechazada', 'documento_faltante', 'informativo', 'vacaciones_acumuladas')),
  CONSTRAINT notifications_severidad_valido CHECK (severidad IN ('info', 'advertencia', 'critica')),
  KEY idx_notif_user (user_id, created_at DESC),
  KEY idx_notif_no_leidas (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS panel_bloques (
  clave VARCHAR(255) NOT NULL,
  titulo TEXT NOT NULL,
  descripcion TEXT NOT NULL,
  visible BOOLEAN NOT NULL DEFAULT TRUE,
  orden SMALLINT NOT NULL,
  roles JSON NOT NULL DEFAULT (JSON_ARRAY()),
  esencial BOOLEAN NOT NULL DEFAULT FALSE,
  cuerpo TEXT NULL,
  actualizado_en DATETIME(6) NULL,
  actualizado_por CHAR(36) NULL,
  CONSTRAINT panel_esencial_siempre_visible CHECK ((NOT (esencial AND (NOT visible)))),
  CONSTRAINT panel_orden_valido CHECK (((orden >= 0) AND (orden <= 999))),
  CONSTRAINT panel_bloques_actualizado_por_fkey FOREIGN KEY (actualizado_por) REFERENCES users(id) ON DELETE SET NULL,
  PRIMARY KEY (clave),
  KEY panel_bloques_orden_idx (visible, orden)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Qué bloques se ven en la pantalla principal del colaborador, en qué orden y para qué roles. Ocultar un bloque no borra ningún dato.';

CREATE TABLE IF NOT EXISTS permission_categories (
  id SMALLINT NOT NULL AUTO_INCREMENT,
  codigo VARCHAR(255) NOT NULL,
  nombre TEXT NOT NULL,
  descripcion TEXT NOT NULL,
  ayuda TEXT NULL,
  orden INT NOT NULL DEFAULT 100,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  CONSTRAINT permission_categories_codigo_key UNIQUE (codigo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS permission_types (
  id SMALLINT NOT NULL AUTO_INCREMENT,
  codigo VARCHAR(255) NOT NULL,
  nombre TEXT NOT NULL,
  descripcion TEXT NULL,
  requiere_adjunto BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Si para este permiso SE SUGIERE adjuntar respaldo. Se muestra en la pantalla y quien aprueba ve si vino; no impide enviar.',
  requiere_justificacion BOOLEAN NOT NULL DEFAULT TRUE,
  requiere_firma BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'Exigir firma dibujada. Falso por omisión: el acceso por código al correo ya acredita la identidad. Talento Humano puede activarlo para un subtipo concreto.',
  remunerado BOOLEAN NOT NULL DEFAULT TRUE,
  descuenta_vacaciones BOOLEAN NOT NULL DEFAULT FALSE,
  max_dias DECIMAL(6,2) NULL,
  max_horas DECIMAL(5,2) NULL,
  base_legal TEXT NULL,
  orden INT NOT NULL DEFAULT 100,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  legal_ref VARCHAR(255) NULL,
  category_id SMALLINT NULL,
  guia_ejemplo TEXT NULL,
  guia_adjuntos TEXT NULL,
  admite_horas BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'El permiso puede pedirse por horas dentro de un mismo día, no solo por días completos.',
  horas_antes DECIMAL(3,1) NOT NULL DEFAULT 1 COMMENT 'Horas que se sugiere reservar antes de la hora del compromiso (traslado, espera).',
  horas_despues DECIMAL(3,1) NOT NULL DEFAULT 2,
  CONSTRAINT permission_types_category_id_fkey FOREIGN KEY (category_id) REFERENCES permission_categories(id),
  CONSTRAINT permission_types_legal_ref_fkey FOREIGN KEY (legal_ref) REFERENCES legal_references(codigo),
  PRIMARY KEY (id),
  CONSTRAINT permission_types_codigo_key UNIQUE (codigo),
  KEY permission_types_categoria_idx (category_id, orden)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Catálogo configurable por RRHH. Define qué exige cada tipo de permiso (respaldo, firma, descuento).';

CREATE TABLE IF NOT EXISTS personal_temporal (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  cedula VARCHAR(255) NOT NULL,
  nombre VARCHAR(255) NOT NULL,
  labor TEXT NULL,
  proveedor TEXT NULL,
  telefono TEXT NULL,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  observacion TEXT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  CONSTRAINT personal_temporal_cedula_key UNIQUE (cedula),
  KEY temporal_activo_idx (activo, nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Operarios temporales, identificados por su cédula. No son usuarios del sistema: no tienen acceso, ni vacaciones, ni jefe. El sistema registra quién vino y cuánto estuvo; cuánto se le paga lo decide Finanzas.';

CREATE TABLE IF NOT EXISTS regiones (
  codigo VARCHAR(255) NOT NULL,
  nombre TEXT NOT NULL,
  sede TEXT NOT NULL,
  descripcion TEXT NULL,
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (codigo)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Zonas de atención de Talento Humano. Cada solicitud se resuelve en la suya.';

CREATE TABLE IF NOT EXISTS request_adjustments (
  id BIGINT NOT NULL AUTO_INCREMENT,
  request_id CHAR(36) NOT NULL,
  fecha_inicio_ant DATE NOT NULL,
  fecha_fin_ant DATE NOT NULL,
  fecha_inicio_nueva DATE NOT NULL,
  fecha_fin_nueva DATE NOT NULL,
  dias_ant DECIMAL(6,2) NOT NULL,
  dias_nuevos DECIMAL(6,2) NOT NULL,
  motivo TEXT NOT NULL,
  resolucion TEXT NOT NULL,
  ajustado_por CHAR(36) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT request_adjustments_motivo_util CHECK ((CHAR_LENGTH(TRIM(motivo)) >= 15)),
  CONSTRAINT request_adjustments_rango_valido CHECK ((fecha_fin_nueva >= fecha_inicio_nueva)),
  CONSTRAINT request_adjustments_resolucion_util CHECK ((CHAR_LENGTH(TRIM(resolucion)) >= 15)),
  CONSTRAINT request_adjustments_ajustado_por_fkey FOREIGN KEY (ajustado_por) REFERENCES users(id),
  CONSTRAINT request_adjustments_request_id_fkey FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  KEY request_adjustments_request_idx (request_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Extensiones y correcciones que Talento Humano aplica a una ausencia ya autorizada. Inmutable: solo se inserta.';

CREATE TABLE IF NOT EXISTS request_attachments (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  request_id CHAR(36) NOT NULL,
  storage_path TEXT NOT NULL,
  nombre_archivo TEXT NOT NULL,
  mime_type VARCHAR(40) NOT NULL,
  tamano_bytes BIGINT NOT NULL,
  hash_sha256 TEXT NULL,
  subido_por CHAR(36) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT request_attachments_mime_permitido CHECK ((mime_type IN ('image/jpeg', 'image/png', 'image/webp', 'image/heic', 'application/pdf'))),
  CONSTRAINT request_attachments_tamano_bytes_check CHECK (((tamano_bytes > 0) AND (tamano_bytes <= 10485760))),
  CONSTRAINT request_attachments_request_id_fkey FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE,
  CONSTRAINT request_attachments_subido_por_fkey FOREIGN KEY (subido_por) REFERENCES users(id) ON DELETE SET NULL,
  PRIMARY KEY (id),
  KEY idx_attachments_request (request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Respaldos de la solicitud (foto/scan de cita médica, certificado, citación). Archivo en Supabase Storage.';

CREATE TABLE IF NOT EXISTS request_signatures (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  request_id CHAR(36) NOT NULL,
  user_id CHAR(36) NOT NULL,
  rol_firma VARCHAR(255) NOT NULL,
  signature_id CHAR(36) NULL,
  hash_sha256 TEXT NOT NULL,
  firmado_en DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  ip VARCHAR(45) NULL,
  user_agent TEXT NULL,
  CONSTRAINT request_signatures_rol_firma_check CHECK ((rol_firma IN ('solicitante', 'jefe', 'rrhh'))),
  CONSTRAINT request_signatures_request_id_fkey FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE,
  CONSTRAINT request_signatures_signature_id_fkey FOREIGN KEY (signature_id) REFERENCES signatures(id) ON DELETE SET NULL,
  CONSTRAINT request_signatures_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  CONSTRAINT request_signatures_request_id_rol_firma_key UNIQUE (request_id, rol_firma),
  KEY idx_request_signatures (request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Instantánea de la firma en el momento de firmar. Cambiar la firma registrada no altera solicitudes pasadas.';

CREATE TABLE IF NOT EXISTS requests (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  tipo VARCHAR(20) NOT NULL,
  fecha_inicio DATE NOT NULL,
  fecha_fin DATE NOT NULL,
  hora_inicio TIME NULL,
  hora_fin TIME NULL,
  dias_solicitados DECIMAL(6,2) NOT NULL DEFAULT 0,
  saldo_al_solicitar DECIMAL(6,2) NOT NULL DEFAULT 0,
  es_adelanto BOOLEAN NOT NULL DEFAULT FALSE,
  justificacion TEXT NULL,
  estado VARCHAR(27) NOT NULL DEFAULT ('pendiente_jefe'),
  jefe_id CHAR(36) NULL,
  jefe_token CHAR(36) NOT NULL DEFAULT (UUID()) COMMENT 'Token del link de aprobación enviado por correo al jefe inmediato.',
  jefe_aprobado_por CHAR(36) NULL,
  jefe_aprobado_en DATETIME(6) NULL,
  rrhh_token CHAR(36) NOT NULL DEFAULT (UUID()) COMMENT 'Token del link de aprobación enviado por correo a RRHH.',
  rrhh_aprobado_por CHAR(36) NULL,
  rrhh_aprobado_en DATETIME(6) NULL,
  rechazado_por CHAR(36) NULL,
  rechazado_en DATETIME(6) NULL,
  motivo_rechazo TEXT NULL,
  qr_hash CHAR(36) NULL COMMENT 'UUID que viaja dentro del código QR y se valida en garita.',
  qr_emitido_en DATETIME(6) NULL,
  qr_expira_en DATETIME(6) NULL,
  qr_usado_en DATETIME(6) NULL,
  qr_usos INT NOT NULL DEFAULT 0,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  permission_type_id SMALLINT NULL,
  descripcion TEXT NULL,
  fines_semana INT NOT NULL DEFAULT 0,
  omitir_regla_fds BOOLEAN NOT NULL DEFAULT FALSE,
  horas_solicitadas DECIMAL(5,2) NULL,
  folio BIGINT NOT NULL AUTO_INCREMENT COMMENT 'Número correlativo legible. Es el que se menciona por teléfono o en un correo.',
  reemplazo_id CHAR(36) NULL COMMENT 'Compañero que cubre las funciones. El jefe decide sabiendo quién asume el puesto.',
  rechazado_en_etapa VARCHAR(40) NULL,
  anulacion_motivo TEXT NULL COMMENT 'Por qué el empleado pide dejar sin efecto una solicitud ya aprobada.',
  anulacion_solicitada_en DATETIME(6) NULL,
  anulacion_resuelta_por CHAR(36) NULL,
  anulacion_resuelta_en DATETIME(6) NULL,
  anulacion_rechazada_motivo TEXT NULL,
  ruta_aprobacion VARCHAR(40) NOT NULL DEFAULT ('estandar') COMMENT 'estandar: jefe y luego Talento Humano. rrhh_primero: excepción a una regla de política, la autoriza Talento Humano antes que la jefatura.',
  bloque_menor_justificado BOOLEAN NOT NULL DEFAULT FALSE,
  ajustada_en DATETIME(6) NULL,
  ajustada_por CHAR(36) NULL,
  region VARCHAR(255) NULL,
  retorno_en DATETIME(6) NULL COMMENT 'Momento real en que la persona volvió, registrado por garita al leer su QR por segunda vez.',
  retorno_exceso_minutos INT NULL COMMENT 'Minutos de más sobre la hora declarada. Solo en permisos por horas; negativo si volvió antes.',
  retorno_exceso_dias INT NULL COMMENT 'Días enteros de más. Solo en ausencias de días completos.',
  retorno_guardia CHAR(36) NULL,
  CONSTRAINT requests_descripcion_max CHECK (((descripcion IS NULL) OR (CHAR_LENGTH(descripcion) <= 200))),
  CONSTRAINT requests_descripcion_obligatoria CHECK (((descripcion IS NOT NULL) AND (CHAR_LENGTH(TRIM(descripcion)) >= 5))),
  CONSTRAINT requests_justificacion_obligatoria CHECK (((tipo <> 'vacacion') OR (dias_solicitados <= saldo_al_solicitar) OR ((justificacion IS NOT NULL) AND (CHAR_LENGTH(TRIM(justificacion)) >= 10)))),
  CONSTRAINT requests_permiso_categorizado CHECK (((tipo <> 'permiso') OR (permission_type_id IS NOT NULL))),
  CONSTRAINT requests_rango_fechas CHECK ((fecha_fin >= fecha_inicio)),
  CONSTRAINT requests_rango_horas CHECK (((hora_fin IS NULL) OR (hora_inicio IS NULL) OR (hora_fin > hora_inicio))),
  CONSTRAINT requests_rechazado_en_etapa_check CHECK (((rechazado_en_etapa IS NULL) OR (rechazado_en_etapa IN ('jefe', 'rrhh')))),
  CONSTRAINT requests_ruta_aprobacion_valida CHECK ((ruta_aprobacion IN ('estandar', 'rrhh_primero'))),
  CONSTRAINT requests_ajustada_por_fkey FOREIGN KEY (ajustada_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT requests_anulacion_resuelta_por_fkey FOREIGN KEY (anulacion_resuelta_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT requests_jefe_aprobado_por_fkey FOREIGN KEY (jefe_aprobado_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT requests_jefe_id_fkey FOREIGN KEY (jefe_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT requests_permission_type_id_fkey FOREIGN KEY (permission_type_id) REFERENCES permission_types(id),
  CONSTRAINT requests_rechazado_por_fkey FOREIGN KEY (rechazado_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT requests_reemplazo_id_fkey FOREIGN KEY (reemplazo_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT requests_retorno_guardia_fkey FOREIGN KEY (retorno_guardia) REFERENCES users(id),
  CONSTRAINT requests_rrhh_aprobado_por_fkey FOREIGN KEY (rrhh_aprobado_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT requests_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  CONSTRAINT requests_qr_hash_key UNIQUE (qr_hash),
  UNIQUE KEY idx_requests_folio (folio),
  CONSTRAINT requests_tipo_valido CHECK (tipo IN ('permiso', 'vacacion')),
  CONSTRAINT requests_estado_valido CHECK (estado IN ('pendiente_jefe', 'pendiente_rrhh', 'pendiente_anulacion', 'aprobado', 'rechazado', 'cancelado')),
  KEY idx_requests_user (user_id, created_at DESC),
  KEY idx_requests_estado (estado),
  KEY idx_requests_jefe (jefe_id),
  KEY idx_requests_fechas (fecha_inicio, fecha_fin),
  KEY idx_requests_qr (qr_hash),
  KEY idx_requests_jefe_token (jefe_token),
  KEY idx_requests_rrhh_token (rrhh_token),
  KEY idx_requests_permission_type (permission_type_id),
  KEY idx_requests_reemplazo (reemplazo_id),
  KEY idx_requests_anulacion (estado),
  KEY requests_region_estado_idx (region, estado),
  KEY requests_solape_idx (user_id, fecha_inicio, fecha_fin),
  KEY requests_retorno_idx (retorno_en DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Solicitudes de permiso y vacaciones con flujo Jefe -> RRHH -> QR.';

CREATE TABLE IF NOT EXISTS signatures (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  tipo VARCHAR(20) NOT NULL DEFAULT ('dibujada'),
  contenido TEXT NULL,
  storage_path TEXT NULL,
  hash_sha256 TEXT NOT NULL,
  activa BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT signatures_tiene_contenido CHECK (((contenido IS NOT NULL) OR (storage_path IS NOT NULL))),
  CONSTRAINT signatures_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  activa_unica CHAR(36) GENERATED ALWAYS AS (IF(activa, user_id, NULL)) VIRTUAL,
  UNIQUE KEY idx_signature_activa (activa_unica),
  CONSTRAINT signatures_tipo_valido CHECK (tipo IN ('dibujada', 'imagen', 'certificado'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Firma registrada del usuario: dibujada con el mouse, imagen subida o certificado oficial.';

CREATE TABLE IF NOT EXISTS tablero_bloques (
  clave VARCHAR(255) NOT NULL,
  titulo TEXT NOT NULL,
  descripcion TEXT NOT NULL,
  pregunta TEXT NOT NULL,
  visible BOOLEAN NOT NULL DEFAULT TRUE,
  orden SMALLINT NOT NULL,
  roles JSON NOT NULL DEFAULT (JSON_ARRAY()),
  ajustes JSON NOT NULL DEFAULT (JSON_OBJECT()),
  actualizado_en DATETIME(6) NULL,
  actualizado_por CHAR(36) NULL,
  CONSTRAINT tablero_orden_valido CHECK (((orden >= 0) AND (orden <= 999))),
  CONSTRAINT tablero_bloques_actualizado_por_fkey FOREIGN KEY (actualizado_por) REFERENCES users(id) ON DELETE SET NULL,
  PRIMARY KEY (clave),
  KEY tablero_bloques_orden_idx (visible, orden)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Qué indicadores se ven en el tablero, en qué orden y con qué ajustes. Los números se calculan al pedirlos.';

CREATE TABLE IF NOT EXISTS users (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  auth_user_id CHAR(36) NULL,
  cedula VARCHAR(255) NOT NULL,
  nombre VARCHAR(255) NOT NULL,
  email VARCHAR(255) NULL COMMENT 'Correo personal donde la persona recibe su código de acceso. Nulo mientras no lo haya registrado: la empresa no lo inventa.',
  telefono TEXT NULL,
  rol VARCHAR(20) NOT NULL DEFAULT ('empleado'),
  cargo TEXT NULL,
  departamento TEXT NULL,
  jefe_id CHAR(36) NULL,
  dias_vacaciones DECIMAL(6,2) NOT NULL DEFAULT 0 COMMENT 'Saldo actual de vacaciones. Puede ser negativo cuando se aprueban días adelantados.',
  fecha_ingreso DATE NOT NULL,
  logros JSON NOT NULL DEFAULT (JSON_ARRAY()) COMMENT 'Arreglo JSON de logros/reconocimientos: [{"titulo":"...","fecha":"2026-01-01","detalle":"..."}]',
  activo BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  fecha_nacimiento DATE NULL,
  estado_civil VARCHAR(20) NULL,
  direccion TEXT NULL,
  ciudad TEXT NULL DEFAULT ('Quito'),
  provincia TEXT NULL DEFAULT ('Pichincha'),
  telefono_alternativo TEXT NULL,
  tipo_contrato VARCHAR(20) NULL DEFAULT ('indefinido'),
  fecha_salida DATE NULL,
  tipo_sangre VARCHAR(40) NULL,
  iess_afiliado BOOLEAN NOT NULL DEFAULT TRUE,
  tiene_discapacidad BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'Dato sensible (LOPDP Art. 4). Habilita permisos y beneficios de la Ley Orgánica de Discapacidades.',
  porcentaje_discapacidad INT NULL,
  carnet_conadis TEXT NULL,
  bodega VARCHAR(255) NULL COMMENT 'Bodega o sede donde presta servicios. Viene de la planilla de Talento Humano.',
  centro_costo TEXT NULL COMMENT 'Centro de costo al que se imputa. Permite informes por CECO.',
  cliente VARCHAR(255) NULL COMMENT 'Cliente al que está asignada la persona (Conecel, Difare, Flexnet…).',
  genero VARCHAR(40) NULL,
  contrato_fin DATE NULL COMMENT 'Fin del contrato vigente. Distinto de `fecha_salida`, que marca una baja efectiva.',
  correo_pendiente BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'La dirección registrada es un marcador, no un buzón real: esta persona NO puede recibir su código de acceso.',
  region VARCHAR(255) NULL COMMENT 'Región que atiende sus solicitudes. Se deduce de la ciudad; Talento Humano puede fijarla a mano.',
  foto_url TEXT NULL,
  ficha_completa BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'La persona ya completó sus datos de contacto la primera vez que entró.',
  ficha_completada_en DATETIME(6) NULL,
  cargo_confirmado_en DATETIME(6) NULL COMMENT 'Cuándo la propia persona confirmó que el cargo registrado es el suyo.',
  jefe_confirmado_en DATETIME(6) NULL COMMENT 'Cuándo la propia persona confirmó que el jefe registrado es el suyo.',
  motivo_salida VARCHAR(30) NULL COMMENT 'Causa de terminación según el Código del Trabajo. Las vacaciones no gozadas se pagan en todos los casos (Art. 76).',
  detalle_salida TEXT NULL COMMENT 'Lo que no cabe en la causa: el número de acta, la fecha del visto bueno, el detalle del acuerdo.',
  salida_registrada_por CHAR(36) NULL,
  salida_registrada_en DATETIME(6) NULL,
  CONSTRAINT users_dias_rango CHECK (((dias_vacaciones >= -60) AND (dias_vacaciones <= 1200))),
  CONSTRAINT users_discapacidad_coherente CHECK (((NOT tiene_discapacidad) OR ((porcentaje_discapacidad IS NOT NULL) AND ((porcentaje_discapacidad >= 1) AND (porcentaje_discapacidad <= 100))))),
  CONSTRAINT users_email_formato CHECK (((email IS NULL) OR (REGEXP_LIKE(email, '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$')))),
  CONSTRAINT users_genero_valido CHECK (((genero IS NULL) OR (genero IN ('Masculino', 'Femenino', 'Otro')))),
  CONSTRAINT users_salida_posterior_ingreso CHECK (((fecha_salida IS NULL) OR (fecha_salida >= fecha_ingreso))),
  CONSTRAINT users_tipo_sangre_valido CHECK (((tipo_sangre IS NULL) OR (tipo_sangre IN ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')))),
  CONSTRAINT users_jefe_id_fkey FOREIGN KEY (jefe_id) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT users_region_fkey FOREIGN KEY (region) REFERENCES regiones(codigo),
  CONSTRAINT users_salida_registrada_por_fkey FOREIGN KEY (salida_registrada_por) REFERENCES users(id),
  PRIMARY KEY (id),
  CONSTRAINT users_auth_user_id_key UNIQUE (auth_user_id),
  CONSTRAINT users_cedula_key UNIQUE (cedula),
  CONSTRAINT users_email_key UNIQUE (email),
  CONSTRAINT users_rol_valido CHECK (rol IN ('admin', 'rrhh', 'jefe', 'empleado', 'guardia')),
  CONSTRAINT users_estado_civil_valido CHECK (estado_civil IN ('soltero', 'casado', 'union_hecho', 'divorciado', 'viudo')),
  CONSTRAINT users_tipo_contrato_valido CHECK (tipo_contrato IN ('indefinido', 'eventual', 'ocasional', 'temporada', 'obra_cierta', 'prueba', 'aprendizaje', 'pasantia')),
  CONSTRAINT users_motivo_salida_valido CHECK (motivo_salida IN ('renuncia', 'despido_intempestivo', 'visto_bueno_empleador', 'visto_bueno_trabajador', 'desahucio', 'fin_de_contrato', 'mutuo_acuerdo', 'jubilacion', 'fallecimiento', 'otro')),
  KEY idx_users_rol (rol),
  KEY idx_users_jefe (jefe_id),
  KEY idx_users_email (email),
  KEY users_bodega_idx (bodega),
  KEY users_cliente_idx (cliente),
  KEY users_correo_pendiente_idx (correo_pendiente),
  KEY users_region_rol_idx (region, rol),
  KEY users_nombre_idx (nombre)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS vacaciones_historicas (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id CHAR(36) NOT NULL,
  fecha_inicio DATE NOT NULL,
  fecha_fin DATE NOT NULL,
  dias DECIMAL(6,2) NOT NULL,
  origen TEXT NOT NULL DEFAULT ('hoja_talento_humano'),
  fila_origen INT NULL,
  cargado_en DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  cargado_por CHAR(36) NULL,
  CONSTRAINT historicas_rango CHECK ((fecha_fin >= fecha_inicio)),
  CONSTRAINT vacaciones_historicas_dias_check CHECK ((dias > 0)),
  CONSTRAINT vacaciones_historicas_cargado_por_fkey FOREIGN KEY (cargado_por) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT vacaciones_historicas_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  CONSTRAINT historicas_sin_repetir UNIQUE (user_id, fecha_inicio, fecha_fin),
  KEY historicas_usuario_idx (user_id, fecha_inicio DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Vacaciones tomadas antes de este sistema, tal como las anotó Talento Humano en su hoja. No son solicitudes: no tienen folio ni aprobación, y no tocan el saldo, que ya viene cargado de la misma fuente.';

CREATE TABLE IF NOT EXISTS vacation_movements (
  id BIGINT NOT NULL AUTO_INCREMENT,
  user_id CHAR(36) NOT NULL,
  request_id CHAR(36) NULL,
  dias DECIMAL(6,2) NOT NULL,
  saldo_previo DECIMAL(6,2) NOT NULL,
  saldo_nuevo DECIMAL(6,2) NOT NULL,
  motivo TEXT NOT NULL,
  created_by CHAR(36) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT vacation_movements_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT vacation_movements_request_id_fkey FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE SET NULL,
  CONSTRAINT vacation_movements_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  KEY idx_vac_mov_user (user_id, created_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS vacation_periods (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  user_id CHAR(36) NOT NULL,
  periodo INT NOT NULL,
  fecha_desde DATE NOT NULL,
  fecha_hasta DATE NOT NULL,
  dias_asignados DECIMAL(6,2) NOT NULL DEFAULT 0,
  dias_consumidos DECIMAL(6,2) NOT NULL DEFAULT 0,
  dias_saldo DECIMAL(6,2) GENERATED ALWAYS AS (dias_asignados - dias_consumidos) STORED,
  fines_semana_obligatorios INT NOT NULL DEFAULT 2,
  fines_semana_consumidos INT NOT NULL DEFAULT 0,
  devengado BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'false = período anticipado (el año aún no se cumple); puede quedar en saldo negativo por días adelantados.',
  vence_en DATE NULL,
  caducado BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT vacation_periods_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
  PRIMARY KEY (id),
  CONSTRAINT vacation_periods_user_id_periodo_key UNIQUE (user_id, periodo),
  KEY idx_vac_periods_user (user_id, periodo),
  KEY idx_vac_periods_abiertos (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Un registro por año de servicio. El saldo del empleado es la suma de los saldos no caducados.';

CREATE TABLE IF NOT EXISTS visitors (
  id CHAR(36) NOT NULL DEFAULT (UUID()),
  cedula VARCHAR(255) NOT NULL,
  nombre TEXT NOT NULL,
  empresa TEXT NULL,
  telefono TEXT NULL,
  motivo_visita TEXT NOT NULL,
  a_quien_visita CHAR(36) NULL,
  a_quien_visita_texto TEXT NULL,
  registrado_por CHAR(36) NULL,
  ingreso_en DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  salida_en DATETIME(6) NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT visitors_salida_posterior CHECK (((salida_en IS NULL) OR (salida_en >= ingreso_en))),
  CONSTRAINT visitors_a_quien_visita_fkey FOREIGN KEY (a_quien_visita) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT visitors_registrado_por_fkey FOREIGN KEY (registrado_por) REFERENCES users(id) ON DELETE SET NULL,
  PRIMARY KEY (id),
  KEY idx_visitors_cedula (cedula),
  KEY idx_visitors_dentro (ingreso_en DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
SET FOREIGN_KEY_CHECKS = 1;
