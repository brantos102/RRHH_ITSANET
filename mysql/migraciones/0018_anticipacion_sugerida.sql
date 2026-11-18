-- =====================================================================
-- 0018 · La anticipación de las vacaciones pasa a ser una sugerencia
--
-- Desde ahora se pueden pedir vacaciones que empiecen mañana. Los días de
-- anticipación (vacaciones_anticipacion_dias) ya no bloquean: se muestran
-- como sugerencia y proponen la fecha inicial del formulario.
--
-- Por debajo del bloque mínimo, la solicitud la revisa primero Talento
-- Humano con el motivo que escriba la persona; el respaldo es opcional.
--
-- Solo cambia textos: la descripción de los parámetros y el lineamiento de
-- anticipación, este último únicamente si Talento Humano no lo había
-- reescrito. Idempotente.
-- =====================================================================

UPDATE app_config
   SET descripcion = 'Días de anticipación SUGERIDOS para pedir vacaciones. No bloquea: se pueden pedir desde mañana. Propone la fecha inicial del formulario.'
 WHERE clave = 'vacaciones_anticipacion_dias';

UPDATE app_config
   SET descripcion = 'Días calendario mínimos por solicitud de vacaciones. Con menos, la revisa primero Talento Humano con el motivo (respaldo opcional) y la ve como vacaciones emergentes.'
 WHERE clave = 'vacaciones_bloque_minimo';

UPDATE lineamientos_solicitud
   SET texto = 'Se sugiere pedirlas con 10 días de anticipación, para que su jefe organice la cobertura. Puede pedirlas desde mañana.'
 WHERE ambito = 'vacacion'
   AND texto = 'Se comunican con 10 días de anticipación, para que su jefe organice la cobertura.';

UPDATE lineamientos_solicitud
   SET texto = 'Para un asunto personal de un día, corresponde un permiso de día completo, no vacaciones.'
 WHERE ambito = 'vacacion'
   AND texto = 'Para un asunto personal de un día, corresponde un permiso, no vacaciones.';
