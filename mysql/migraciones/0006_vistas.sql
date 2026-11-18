-- =====================================================================
-- 0006 · Vistas
--
-- Las 37 vistas de PostgreSQL que usan el backend, los guiones de
-- verificación y los documentos de cumplimiento, traducidas a MySQL.
--
-- No se trasladan dos: v_garita_actividad y v_visitantes_dentro. Filtran
-- con is_guardia() y auth.uid(), que leen la identidad de la sesión de
-- Supabase; en MySQL no existe esa sesión. Ninguna parte del sistema las
-- consulta: la garita usa v_garita_hoy, que sí está aquí.
--
-- Traducciones que se repiten:
--   count(*) FILTER (WHERE c)   COUNT(CASE WHEN c THEN 1 END)
--   sum(x)   FILTER (WHERE c)   SUM(CASE WHEN c THEN x END)
--   a IS DISTINCT FROM b        NOT (a <=> b)
--   fecha - fecha (días)        DATEDIFF(...)
--   (fecha + hora)::timestamp   TIMESTAMP(fecha, hora)
--   epoch(now() - t)            TIMESTAMPDIFF(MICROSECOND, t, NOW(6)) / 1e6
--   cardinality(roles)          JSON_LENGTH(roles)
--
-- Se comprueban fila por fila contra las de PostgreSQL con los mismos
-- datos (mysql/pruebas/test_vistas_diferencial.py).
-- =====================================================================

CREATE OR REPLACE VIEW v_acumulacion_excesiva AS
SELECT u.id AS user_id, u.cedula, u.nombre, u.cargo, u.departamento, u.ciudad,
       COALESCE(u.region, 'sierra') AS region, u.fecha_ingreso,
       anios_cumplidos(u.fecha_ingreso) AS anios,
       j.nombre AS jefe,
       u.dias_vacaciones AS saldo,
       COUNT(CASE WHEN p.devengado AND p.dias_saldo > 0 THEN p.id END) AS periodos_sin_gozar,
       SUM(CASE WHEN p.devengado AND p.dias_saldo > 0 THEN p.dias_saldo END) AS dias_de_anios_cumplidos,
       MIN(CASE WHEN p.devengado AND p.dias_saldo > 0 THEN p.fecha_hasta END) AS desde_cuando_arrastra
  FROM users u
  LEFT JOIN vacation_periods p ON p.user_id = u.id
  LEFT JOIN users j ON j.id = u.jefe_id
 WHERE u.activo
 GROUP BY u.id, u.cedula, u.nombre, u.cargo, u.departamento, u.ciudad, u.region,
          u.fecha_ingreso, j.nombre, u.dias_vacaciones
HAVING COUNT(CASE WHEN p.devengado AND p.dias_saldo > 0 THEN p.id END) >= cfg_int('acumulacion_aviso_periodos')
 ORDER BY periodos_sin_gozar DESC, dias_de_anios_cumplidos DESC;

CREATE OR REPLACE VIEW v_antiguedad_referencia AS
SELECT anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables,
       CASE
         WHEN anios_hasta IS NULL THEN CONCAT(anios_desde, ' años o más')
         WHEN anios_hasta = anios_desde THEN CONCAT(anios_desde, ' años')
         ELSE CONCAT(anios_desde, '-', anios_hasta, ' años')
       END AS rango
  FROM antiguedad_referencia
 ORDER BY anios_desde;

CREATE OR REPLACE VIEW v_caducidad AS
SELECT caducidad_activa() AS activa,
       cfg_int('acumulacion_max_anios') AS anios_de_acumulacion,
       (SELECT COUNT(*) FROM vacation_periods WHERE caducado) AS periodos_caducados,
       (SELECT COUNT(*) FROM vacation_periods WHERE vence_en IS NOT NULL) AS periodos_con_fecha_de_vencimiento;

CREATE OR REPLACE VIEW v_calendario_equipo AS
SELECT r.id AS request_id, CAST(NULL AS SIGNED) AS historico_id, 'solicitud' AS procedencia,
       r.folio, u.id AS user_id, u.nombre, u.cargo, u.departamento, u.jefe_id,
       r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin, r.dias_solicitados, r.estado,
       CASE r.tipo WHEN 'vacacion' THEN 'Vacaciones' ELSE 'Permiso' END AS motivo_general,
       r.reemplazo_id, s.nombre AS reemplazo_nombre, r.ajustada_en,
       (r.fecha_fin < CURRENT_DATE()) AS ya_ocurrio
  FROM requests r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN users s ON s.id = r.reemplazo_id
 WHERE r.estado IN ('pendiente_jefe', 'pendiente_rrhh', 'pendiente_anulacion', 'aprobado', 'cancelado')
UNION ALL
SELECT NULL, h.id, 'historico', NULL, u.id, u.nombre, u.cargo, u.departamento, u.jefe_id,
       h.fecha_inicio, h.fecha_fin, NULL, NULL, h.dias, 'aprobado', 'Vacaciones',
       NULL, NULL, NULL, TRUE
  FROM vacaciones_historicas h
  JOIN users u ON u.id = h.user_id
 WHERE u.activo;

CREATE OR REPLACE VIEW v_cambios_ficha_pendientes AS
SELECT c.id, c.user_id, u.cedula, u.nombre AS persona, u.departamento, u.ciudad,
       COALESCE(u.region, 'sierra') AS region, c.campo, f.etiqueta,
       c.valor_anterior, c.valor_nuevo, c.motivo, c.created_at,
       CASE WHEN c.campo = 'jefe_id'
            THEN COALESCE((SELECT j.nombre FROM users j WHERE j.id = c.valor_anterior), c.valor_anterior)
            ELSE c.valor_anterior END AS anterior_legible,
       CASE WHEN c.campo = 'jefe_id'
            THEN COALESCE((SELECT j.nombre FROM users j WHERE j.id = c.valor_nuevo), c.valor_nuevo)
            ELSE c.valor_nuevo END AS nuevo_legible
  FROM cambios_ficha c
  JOIN users u ON u.id = c.user_id
  JOIN campos_ficha f ON f.campo = c.campo
 WHERE c.estado = 'pendiente'
 ORDER BY c.created_at;

CREATE OR REPLACE VIEW v_catalogo_permisos AS
SELECT c.id AS categoria_id, c.codigo AS categoria_codigo, c.nombre AS categoria_nombre,
       c.descripcion AS categoria_descripcion, c.ayuda AS categoria_ayuda, c.orden AS categoria_orden,
       t.id AS tipo_id, t.codigo AS tipo_codigo, t.nombre AS tipo_nombre,
       t.descripcion AS tipo_descripcion, t.requiere_adjunto, t.requiere_justificacion,
       t.remunerado, t.descuenta_vacaciones, t.max_dias, t.max_horas, t.legal_ref,
       t.guia_ejemplo, t.guia_adjuntos, t.admite_horas, t.horas_antes, t.horas_despues,
       t.orden AS tipo_orden
  FROM permission_categories c
  JOIN permission_types t ON t.category_id = c.id
 WHERE c.activo AND t.activo;

CREATE OR REPLACE VIEW v_conversaciones_bandeja AS
SELECT c.id, c.user_id, u.nombre AS persona, u.cedula, u.cargo, u.departamento, u.ciudad,
       c.region, c.asunto, c.estado, c.updated_at, c.created_at, a.nombre AS atendida_por,
       (SELECT COUNT(*) FROM mensajes m
         WHERE m.conversacion_id = c.id AND m.leido_en IS NULL AND NOT m.es_rrhh) AS sin_leer,
       (SELECT m.texto FROM mensajes m WHERE m.conversacion_id = c.id
         ORDER BY m.created_at DESC LIMIT 1) AS ultimo_mensaje
  FROM conversaciones c
  JOIN users u ON u.id = c.user_id
  LEFT JOIN users a ON a.id = c.atendida_por;

CREATE OR REPLACE VIEW v_cuentas_de_prueba AS
SELECT u.id AS user_id, u.cedula, u.nombre, u.email, u.rol, u.cargo, u.departamento,
       u.fecha_ingreso, u.activo,
       (SELECT COUNT(*) FROM users s WHERE s.jefe_id = u.id AND s.activo) AS a_cargo,
       (SELECT COUNT(*) FROM requests r WHERE r.user_id = u.id) AS solicitudes,
       (SELECT COUNT(*) FROM vacaciones_historicas h WHERE h.user_id = u.id) AS historicas,
       CASE
         WHEN (SELECT COUNT(*) FROM vacaciones_historicas h WHERE h.user_id = u.id) > 0
           OR (SELECT COUNT(*) FROM requests r WHERE r.user_id = u.id) > 0
           THEN 'Persona real con correo de prueba: corríjale el correo y revise su rol'
         WHEN (SELECT COUNT(*) FROM users s WHERE s.jefe_id = u.id AND s.activo) > 0
           THEN 'Tiene gente a cargo: reasígnela antes de tocar esta cuenta'
         ELSE 'Sin actividad: probablemente es una cuenta de prueba y se puede desactivar'
       END AS que_hacer
  FROM users u
 WHERE u.email LIKE '%.test' OR u.email LIKE '%.invalid' OR u.email LIKE '%@ejemplo.%'
 ORDER BY u.rol, u.nombre;

-- Los meses del período en curso se cuentan con TIMESTAMPDIFF(MONTH), que da
-- lo mismo que age() de PostgreSQL: es el cálculo de dias_devengados_al, ya
-- comprobado contra PostgreSQL en decenas de miles de fechas.
CREATE OR REPLACE VIEW v_devengo_cotejo AS
WITH base AS (
  SELECT u.id AS user_id, u.cedula, u.nombre, u.departamento, u.fecha_ingreso,
         anios_cumplidos(u.fecha_ingreso) AS anios_cumplidos,
         anios_cumplidos(u.fecha_ingreso) + 1 AS periodo_en_curso
    FROM users u WHERE u.activo
), meses AS (
  SELECT b.*,
         LEAST(GREATEST(TIMESTAMPDIFF(MONTH,
                 DATE_ADD(b.fecha_ingreso, INTERVAL b.periodo_en_curso - 1 YEAR), CURRENT_DATE()), 0), 12)
           AS meses_del_periodo
    FROM base b
)
SELECT m.user_id, m.cedula, m.nombre, m.departamento, m.fecha_ingreso, m.anios_cumplidos,
       m.periodo_en_curso, m.meses_del_periodo,
       dias_por_antiguedad(m.periodo_en_curso) AS tope_anual_del_periodo,
       dias_devengados_en_curso(m.fecha_ingreso, m.periodo_en_curso) AS devengado_hoja,
       ROUND(dias_por_antiguedad(m.periodo_en_curso) * m.meses_del_periodo / 12.0, 2) AS devengado_prorrateado,
       (SELECT COALESCE(SUM(p.dias_asignados), 0) FROM vacation_periods p
         WHERE p.user_id = m.user_id AND p.devengado AND NOT p.caducado) AS devengado_de_anios_cumplidos
  FROM meses m;

CREATE OR REPLACE VIEW v_ficha_sin_confirmar AS
SELECT u.id, u.cedula, u.nombre, u.cargo, u.departamento, u.ciudad,
       COALESCE(u.region, 'sierra') AS region, j.nombre AS jefe, u.correo_pendiente,
       (u.cargo_confirmado_en IS NOT NULL) AS cargo_confirmado,
       (u.jefe_confirmado_en IS NOT NULL) AS jefe_confirmado
  FROM users u
  LEFT JOIN users j ON j.id = u.jefe_id
 WHERE u.activo AND (u.correo_pendiente OR u.cargo_confirmado_en IS NULL
                     OR u.jefe_confirmado_en IS NULL OR u.jefe_id IS NULL);

CREATE OR REPLACE VIEW v_fichas_incompletas AS
SELECT u.id AS user_id, u.cedula, u.nombre, u.departamento, u.cargo, u.rol,
       (u.email IS NULL) AS sin_correo,
       (u.cargo IS NULL OR TRIM(u.cargo) = '') AS sin_cargo,
       (u.departamento IS NULL OR TRIM(u.departamento) = '') AS sin_departamento,
       (u.fecha_nacimiento IS NULL) AS sin_nacimiento,
       (u.telefono IS NULL OR TRIM(u.telefono) = '') AS sin_telefono,
       (u.jefe_id IS NULL AND u.rol = 'empleado') AS sin_jefe,
       CASE
         WHEN u.jefe_id IS NULL AND u.rol = 'empleado' THEN 'Sin jefe: sus solicitudes no le llegan a nadie'
         WHEN u.email IS NULL AND u.fecha_nacimiento IS NULL
           THEN 'No puede entrar: sin correo y sin fecha de nacimiento para el primer ingreso'
         WHEN u.cargo IS NULL OR TRIM(u.cargo) = '' THEN 'Sin cargo registrado'
         ELSE 'Faltan datos de contacto'
       END AS lo_principal,
       (u.email IS NULL)
       + (u.cargo IS NULL OR TRIM(u.cargo) = '')
       + (u.departamento IS NULL OR TRIM(u.departamento) = '')
       + (u.fecha_nacimiento IS NULL)
       + (u.telefono IS NULL OR TRIM(u.telefono) = '')
       + (u.jefe_id IS NULL AND u.rol = 'empleado') AS huecos
  FROM users u
 WHERE u.activo AND (u.email IS NULL OR u.cargo IS NULL OR TRIM(u.cargo) = ''
                     OR u.departamento IS NULL OR TRIM(u.departamento) = ''
                     OR u.fecha_nacimiento IS NULL OR u.telefono IS NULL OR TRIM(u.telefono) = ''
                     OR (u.jefe_id IS NULL AND u.rol = 'empleado'))
 ORDER BY (u.jefe_id IS NULL AND u.rol = 'empleado') DESC, u.nombre;

CREATE OR REPLACE VIEW v_fines_semana AS
SELECT p.user_id, u.cedula, u.nombre, u.departamento, p.periodo, p.fecha_desde, p.fecha_hasta,
       p.dias_asignados, p.dias_consumidos, p.dias_saldo,
       p.fines_semana_obligatorios, p.fines_semana_consumidos,
       situacion_fines_semana(p.devengado, p.dias_asignados, p.dias_consumidos) AS situacion,
       CASE situacion_fines_semana(p.devengado, p.dias_asignados, p.dias_consumidos)
         WHEN 'cumplido' THEN 'Gozó el período completo: los fines de semana van dentro'
         WHEN 'sin_gozar' THEN 'No ha tomado días de este período todavía'
         WHEN 'en_curso' THEN 'El año todavía corre'
         ELSE 'Gozó una parte: Talento Humano confirma si los fines de semana estaban dentro'
       END AS explicacion
  FROM vacation_periods p
  JOIN users u ON u.id = p.user_id
 WHERE NOT p.caducado AND u.activo;

CREATE OR REPLACE VIEW v_garita_hoy AS
WITH movimientos AS (
  SELECT r1.id AS request_id,
         MIN(CASE WHEN a.tipo_acceso = 'salida_empleado' AND a.autorizado THEN a.created_at END) AS salio_en
    FROM requests r1
    LEFT JOIN access_logs a ON a.request_id = r1.id
   GROUP BY r1.id
)
SELECT r.id AS request_id, r.folio, u.id AS user_id, u.cedula, u.nombre, u.cargo, u.departamento,
       r.tipo, pt.nombre AS categoria, r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin,
       m.salio_en, r.retorno_en, r.retorno_exceso_minutos,
       (r.hora_fin IS NOT NULL AND r.fecha_inicio = r.fecha_fin) AS debe_volver_hoy,
       CASE WHEN r.hora_fin IS NOT NULL AND r.fecha_inicio = r.fecha_fin
            THEN TIMESTAMP(r.fecha_fin, r.hora_fin) END AS se_espera_a_las,
       CASE
         WHEN m.salio_en IS NULL THEN 'sin_salir'
         WHEN r.retorno_en IS NOT NULL THEN 'completo'
         WHEN NOT (r.hora_fin IS NOT NULL AND r.fecha_inicio = r.fecha_fin) THEN 'no_vuelve_hoy'
         WHEN NOW(6) > TIMESTAMP(r.fecha_fin, r.hora_fin) THEN 'fuera_atrasado'
         ELSE 'fuera'
       END AS situacion,
       CASE WHEN m.salio_en IS NOT NULL AND r.retorno_en IS NULL AND r.hora_fin IS NOT NULL
                 AND r.fecha_inicio = r.fecha_fin AND NOW(6) > TIMESTAMP(r.fecha_fin, r.hora_fin)
            THEN ROUND(TIMESTAMPDIFF(MICROSECOND, TIMESTAMP(r.fecha_fin, r.hora_fin), NOW(6)) / 60000000.0)
       END AS minutos_de_atraso
  FROM requests r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN permission_types pt ON pt.id = r.permission_type_id
  LEFT JOIN movimientos m ON m.request_id = r.id
 WHERE r.estado = 'aprobado' AND CURRENT_DATE() BETWEEN r.fecha_inicio AND r.fecha_fin;

CREATE OR REPLACE VIEW v_historial_vacaciones AS
SELECT h.user_id, CAST(NULL AS SIGNED) AS folio, h.fecha_inicio, h.fecha_fin, h.dias,
       'historico' AS procedencia,
       'Registrado por Talento Humano antes de este sistema' AS detalle,
       h.fila_origen
  FROM vacaciones_historicas h
UNION ALL
SELECT r.user_id, r.folio, r.fecha_inicio, r.fecha_fin, r.dias_solicitados,
       'solicitud', 'Solicitada y autorizada en el sistema', NULL
  FROM requests r
 WHERE r.tipo = 'vacacion' AND r.estado = 'aprobado';

CREATE OR REPLACE VIEW v_historico_resumen AS
SELECT u.id AS user_id, u.cedula, u.nombre, u.departamento,
       COUNT(h.id) AS vacaciones_registradas,
       COALESCE(SUM(h.dias), 0) AS dias_gozados_historicos,
       MIN(h.fecha_inicio) AS primera, MAX(h.fecha_fin) AS ultima,
       u.dias_vacaciones AS saldo_actual
  FROM users u
  LEFT JOIN vacaciones_historicas h ON h.user_id = u.id
 WHERE u.activo
 GROUP BY u.id, u.cedula, u.nombre, u.departamento, u.dias_vacaciones
 ORDER BY u.nombre;

CREATE OR REPLACE VIEW v_informe_solicitudes AS
SELECT r.id AS solicitud_id, r.folio, DATE(r.created_at) AS fecha_solicitud,
       r.fecha_inicio, r.fecha_fin, r.dias_solicitados, r.horas_solicitadas, r.tipo,
       COALESCE(pt.nombre, CASE r.tipo WHEN 'vacacion' THEN 'Vacaciones' ELSE 'Permiso' END) AS tipo_detalle,
       r.estado, u.id AS user_id, u.cedula, u.nombre AS solicitante, u.departamento, u.cargo,
       u.tipo_contrato, j.nombre AS jefe, h.nombre AS rrhh, rp.nombre AS reemplazo,
       r.es_adelanto, r.descripcion, r.motivo_rechazo, r.rechazado_en_etapa,
       r.jefe_aprobado_en, r.rrhh_aprobado_en, r.rechazado_en, r.qr_usado_en,
       (SELECT COUNT(*) FROM request_attachments a WHERE a.request_id = r.id) AS adjuntos
  FROM requests r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN users j ON j.id = COALESCE(r.jefe_aprobado_por, r.jefe_id)
  LEFT JOIN users h ON h.id = r.rrhh_aprobado_por
  LEFT JOIN users rp ON rp.id = r.reemplazo_id
  LEFT JOIN permission_types pt ON pt.id = r.permission_type_id;

CREATE OR REPLACE VIEW v_informes_firmados AS
SELECT i.id, i.user_id, u.cedula, u.nombre, u.departamento, u.region, i.tipo, i.request_id,
       r.folio AS solicitud_folio, i.folio, i.emitido_en, i.impresiones, i.ultima_impresion,
       e.nombre AS emitido_por, a.nombre AS autorizado_por, i.autorizado_en, i.autorizacion_motivo,
       (i.autorizado_por IS NOT NULL) AS es_reemision,
       (i.emitido_en = MAX(i.emitido_en) OVER (PARTITION BY i.user_id, i.tipo)) AS es_el_vigente
  FROM informes_firmados i
  JOIN users u ON u.id = i.user_id
  LEFT JOIN users e ON e.id = i.emitido_por
  LEFT JOIN users a ON a.id = i.autorizado_por
  LEFT JOIN requests r ON r.id = i.request_id;

CREATE OR REPLACE VIEW v_jefaturas AS
SELECT u.id, u.nombre, u.cargo, u.departamento, COALESCE(u.region, 'sierra') AS region,
       (SELECT COUNT(*) FROM users s WHERE s.jefe_id = u.id AND s.activo) AS a_cargo
  FROM users u
 WHERE u.activo AND (u.rol IN ('jefe', 'rrhh', 'admin')
                     OR EXISTS (SELECT 1 FROM users s WHERE s.jefe_id = u.id AND s.activo))
 ORDER BY u.nombre;

CREATE OR REPLACE VIEW v_jefaturas_admin AS
SELECT u.id, u.nombre, u.rol, u.cargo, u.departamento, COALESCE(u.region, 'sierra') AS region,
       (SELECT COUNT(*) FROM users s WHERE s.jefe_id = u.id AND s.activo) AS a_cargo,
       (SELECT COUNT(*) FROM requests r WHERE r.jefe_id = u.id AND r.estado = 'pendiente_jefe') AS esperando,
       (u.email IS NOT NULL AND u.email NOT LIKE '%.test' AND u.email NOT LIKE '%.invalid') AS puede_entrar,
       j.nombre AS reporta_a
  FROM users u
  LEFT JOIN users j ON j.id = u.jefe_id
 WHERE u.activo AND (u.rol IN ('jefe', 'rrhh', 'admin')
                     OR EXISTS (SELECT 1 FROM users s WHERE s.jefe_id = u.id AND s.activo))
 ORDER BY u.nombre;

CREATE OR REPLACE VIEW v_jerarquia AS
SELECT u.id AS user_id, u.cedula, u.nombre, u.rol, u.cargo, u.departamento,
       j.id AS jefe_id, j.nombre AS jefe_nombre, j.activo AS jefe_activo,
       (SELECT COUNT(*) FROM users s WHERE s.jefe_id = u.id AND s.activo) AS a_cargo,
       CASE
         WHEN u.jefe_id = u.id THEN 'Es su propio jefe'
         WHEN j.id IS NOT NULL AND NOT j.activo THEN 'Su jefe está inactivo'
         WHEN u.jefe_id IS NULL AND u.rol = 'empleado' THEN 'Sin jefe asignado'
         WHEN u.rol IN ('jefe', 'rrhh', 'admin')
              AND (SELECT COUNT(*) FROM users s WHERE s.jefe_id = u.id AND s.activo) = 0
           THEN 'Tiene rol de mando y nadie a cargo'
       END AS problema
  FROM users u
  LEFT JOIN users j ON j.id = u.jefe_id
 WHERE u.activo;

CREATE OR REPLACE VIEW v_jornadas_detalle AS
SELECT j.id AS jornada_id, t.id AS temporal_id, t.cedula, t.nombre, t.labor, t.proveedor, t.activo,
       j.fecha, j.entrada_en, j.salida_en, j.horas, (j.salida_en IS NULL) AS sin_cerrar,
       e.nombre AS registro_entrada, s.nombre AS registro_salida, j.observacion
  FROM jornadas_temporales j
  JOIN personal_temporal t ON t.id = j.temporal_id
  LEFT JOIN users e ON e.id = j.registro_entrada
  LEFT JOIN users s ON s.id = j.registro_salida;

CREATE OR REPLACE VIEW v_jornadas_sin_cerrar AS
SELECT j.id AS jornada_id, t.id AS temporal_id, t.cedula, t.nombre, t.labor, t.proveedor,
       j.fecha, j.entrada_en, DATEDIFF(CURRENT_DATE(), j.fecha) AS dias_sin_cerrar
  FROM jornadas_temporales j
  JOIN personal_temporal t ON t.id = j.temporal_id
 WHERE j.salida_en IS NULL AND j.fecha < CURRENT_DATE()
 ORDER BY j.fecha, t.nombre;

CREATE OR REPLACE VIEW v_legal_colaborador AS
SELECT l.codigo, l.norma, l.articulo, l.titulo, l.categoria, l.orden,
       CASE WHEN l.visibilidad = 'resumen' THEN l.resumen ELSE l.texto END AS texto,
       l.visibilidad AS modo
  FROM legal_references l
 WHERE l.visibilidad <> 'oculto';

CREATE OR REPLACE VIEW v_lineamientos AS
SELECT l.id, l.ambito, l.texto, l.orden, l.activo, l.actualizado_en,
       u.nombre AS actualizado_por_nombre
  FROM lineamientos_solicitud l
  LEFT JOIN users u ON u.id = l.actualizado_por
 ORDER BY l.ambito, l.orden, l.id;

CREATE OR REPLACE VIEW v_panel_configuracion AS
SELECT b.clave, b.titulo, b.descripcion, b.visible, b.orden, b.esencial, b.roles, b.cuerpo,
       b.actualizado_en, u.nombre AS actualizado_por_nombre,
       (JSON_LENGTH(b.roles) = 0) AS para_todos
  FROM panel_bloques b
  LEFT JOIN users u ON u.id = b.actualizado_por
 ORDER BY b.orden, b.clave;

CREATE OR REPLACE VIEW v_pasivo_vacaciones AS
SELECT COALESCE(u.departamento, 'SIN ÁREA') AS departamento,
       COALESCE(u.ciudad, 'SIN CIUDAD') AS ciudad,
       COUNT(*) AS personas,
       SUM(u.dias_vacaciones) AS dias_por_pagar,
       SUM(CASE WHEN u.dias_vacaciones > 30 THEN u.dias_vacaciones END) AS dias_de_quienes_pasan_de_30,
       ROUND(AVG(u.dias_vacaciones), 2) AS promedio_por_persona,
       MAX(u.dias_vacaciones) AS el_mas_alto
  FROM users u
 WHERE u.activo AND u.dias_vacaciones > 0
 GROUP BY COALESCE(u.departamento, 'SIN ÁREA'), COALESCE(u.ciudad, 'SIN CIUDAD')
 ORDER BY dias_por_pagar DESC;

CREATE OR REPLACE VIEW v_resumen_general AS
SELECT COALESCE(u.departamento, 'Sin departamento') AS departamento,
       CAST(DATE_FORMAT(r.created_at, '%Y-%m-01') AS DATE) AS mes,
       r.tipo,
       COUNT(*) AS solicitudes,
       COUNT(CASE WHEN r.estado = 'aprobado' THEN 1 END) AS aprobadas,
       COUNT(CASE WHEN r.estado = 'rechazado' THEN 1 END) AS rechazadas,
       ROUND(100.0 * COUNT(CASE WHEN r.estado = 'aprobado' THEN 1 END) / NULLIF(COUNT(*), 0), 1)
         AS porcentaje_aprobacion,
       SUM(CASE WHEN r.estado = 'aprobado' THEN r.dias_solicitados END) AS dias_aprobados
  FROM requests r
  JOIN users u ON u.id = r.user_id
 GROUP BY COALESCE(u.departamento, 'Sin departamento'),
          CAST(DATE_FORMAT(r.created_at, '%Y-%m-01') AS DATE), r.tipo;

CREATE OR REPLACE VIEW v_retornos AS
SELECT r.id AS request_id, r.folio, u.cedula, u.nombre, u.departamento, u.cargo,
       j.nombre AS jefe, r.tipo, pt.nombre AS categoria,
       r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin,
       (SELECT MIN(a.created_at) FROM access_logs a
         WHERE a.request_id = r.id AND a.tipo_acceso = 'salida_empleado' AND a.autorizado) AS salio_en,
       r.retorno_en, r.retorno_exceso_minutos, r.retorno_exceso_dias,
       CASE
         WHEN r.retorno_en IS NULL THEN 'sin registrar'
         WHEN COALESCE(r.retorno_exceso_minutos, 0) > 0 THEN 'volvió tarde'
         WHEN COALESCE(r.retorno_exceso_dias, 0) > 0 THEN 'volvió tarde'
         ELSE 'a tiempo'
       END AS puntualidad
  FROM requests r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN users j ON j.id = u.jefe_id
  LEFT JOIN permission_types pt ON pt.id = r.permission_type_id
 WHERE r.estado = 'aprobado'
   AND EXISTS (SELECT 1 FROM access_logs a
                WHERE a.request_id = r.id AND a.tipo_acceso = 'salida_empleado' AND a.autorizado);

CREATE OR REPLACE VIEW v_rrhh_por_region AS
SELECT u.id, u.nombre, u.email, u.cedula, u.cargo, u.ciudad,
       COALESCE(u.region, 'sierra') AS region, r.nombre AS region_nombre, r.sede
  FROM users u
  JOIN regiones r ON r.codigo = COALESCE(u.region, 'sierra')
 WHERE u.activo AND u.rol IN ('rrhh', 'admin') AND NOT u.correo_pendiente;

CREATE OR REPLACE VIEW v_saldos_desalineados AS
SELECT u.cedula, u.nombre, u.departamento, u.dias_vacaciones AS saldo_mostrado,
       COALESCE(SUM(CASE WHEN NOT p.caducado THEN p.dias_saldo END), 0) AS saldo_real,
       u.dias_vacaciones - COALESCE(SUM(CASE WHEN NOT p.caducado THEN p.dias_saldo END), 0) AS diferencia
  FROM users u
  LEFT JOIN vacation_periods p ON p.user_id = u.id
 WHERE u.activo
 GROUP BY u.id, u.cedula, u.nombre, u.departamento, u.dias_vacaciones
HAVING NOT (u.dias_vacaciones <=> COALESCE(SUM(CASE WHEN NOT p.caducado THEN p.dias_saldo END), 0));

CREATE OR REPLACE VIEW v_salidas AS
SELECT u.id, u.cedula, u.nombre, u.cargo, u.departamento, u.fecha_ingreso, u.fecha_salida,
       u.motivo_salida AS motivo, u.detalle_salida, q.nombre AS registrada_por,
       u.salida_registrada_en, anios_cumplidos(u.fecha_ingreso) AS anios_servicio,
       (SELECT COALESCE(SUM(p.dias_saldo), 0) FROM vacation_periods p
         WHERE p.user_id = u.id AND NOT p.caducado) AS dias_por_liquidar
  FROM users u
  LEFT JOIN users q ON q.id = u.salida_registrada_por
 WHERE NOT u.activo AND u.fecha_salida IS NOT NULL
 ORDER BY u.fecha_salida DESC;

CREATE OR REPLACE VIEW v_sin_correo AS
SELECT u.id, u.cedula, u.nombre, u.cargo, u.departamento, u.ciudad,
       COALESCE(u.region, 'sierra') AS region, u.telefono, u.fecha_ingreso, j.nombre AS jefe,
       (u.fecha_nacimiento IS NOT NULL) AS puede_probar_identidad
  FROM users u
  LEFT JOIN users j ON j.id = u.jefe_id
 WHERE u.activo AND (u.email IS NULL OR u.correo_pendiente)
 ORDER BY u.nombre;

CREATE OR REPLACE VIEW v_sin_entrada AS
SELECT u.id AS user_id, u.cedula, u.nombre, u.departamento, u.ciudad,
       (u.email IS NULL) AS sin_correo,
       (u.fecha_nacimiento IS NULL) AS sin_fecha_nacimiento,
       (u.fecha_ingreso IS NULL) AS sin_fecha_ingreso,
       u.ficha_completa, u.correo_pendiente,
       CASE
         WHEN u.fecha_nacimiento IS NULL AND u.fecha_ingreso IS NULL
           THEN 'Faltan la fecha de nacimiento y la de ingreso: no puede probar su identidad'
         WHEN u.fecha_nacimiento IS NULL THEN 'Falta la fecha de nacimiento: no puede probar su identidad'
         WHEN u.fecha_ingreso IS NULL THEN 'Falta la fecha de ingreso: no puede probar su identidad'
         ELSE 'Sin correo, pero puede entrar por primer ingreso'
       END AS motivo,
       CASE
         WHEN u.fecha_nacimiento IS NULL OR u.fecha_ingreso IS NULL
           THEN 'Complete la fecha que falta en su ficha, o registre su correo desde Colaboradores'
         ELSE 'Nada: dígale que use «Es mi primer ingreso» en la pantalla de acceso'
       END AS que_hacer
  FROM users u
 WHERE u.activo AND u.email IS NULL
 ORDER BY (u.fecha_nacimiento IS NULL OR u.fecha_ingreso IS NULL) DESC, u.nombre;

CREATE OR REPLACE VIEW v_talento_humano AS
SELECT u.id, u.nombre, u.email, u.rol, u.cargo, COALESCE(u.region, 'sierra') AS region,
       r.nombre AS region_nombre, r.sede, u.activo,
       (u.email IS NOT NULL AND NOT u.correo_pendiente
        AND u.email NOT LIKE '%.test' AND u.email NOT LIKE '%.invalid') AS puede_recibir,
       (SELECT COUNT(*) FROM requests q
         WHERE q.estado = 'pendiente_rrhh'
           AND COALESCE(q.region, 'sierra') = COALESCE(u.region, 'sierra')) AS esperando_en_su_region
  FROM users u
  LEFT JOIN regiones r ON r.codigo = COALESCE(u.region, 'sierra')
 WHERE u.rol IN ('rrhh', 'admin')
 ORDER BY COALESCE(u.region, 'sierra'), u.nombre;

CREATE OR REPLACE VIEW v_temporales_dentro AS
SELECT j.id AS jornada_id, t.id AS temporal_id, t.cedula, t.nombre, t.labor, t.proveedor,
       j.entrada_en,
       ROUND(TIMESTAMPDIFF(MICROSECOND, j.entrada_en, NOW(6)) / 3600000000.0, 2) AS horas_hasta_ahora
  FROM jornadas_temporales j
  JOIN personal_temporal t ON t.id = j.temporal_id
 WHERE j.fecha = CURRENT_DATE() AND j.salida_en IS NULL
 ORDER BY j.entrada_en;

CREATE OR REPLACE VIEW v_trazabilidad_empleado AS
SELECT u.id AS user_id, u.cedula, u.nombre, u.departamento, u.fecha_ingreso,
       anios_cumplidos(u.fecha_ingreso) AS anios_servicio,
       u.dias_vacaciones AS saldo_actual,
       COUNT(r.id) AS solicitudes_totales,
       COUNT(CASE WHEN r.estado = 'aprobado' THEN 1 END) AS aprobadas,
       COUNT(CASE WHEN r.estado = 'rechazado' THEN 1 END) AS rechazadas,
       COUNT(CASE WHEN r.estado IN ('pendiente_jefe', 'pendiente_rrhh') THEN 1 END) AS en_tramite,
       COUNT(CASE WHEN r.estado = 'cancelado' THEN 1 END) AS canceladas,
       COALESCE(SUM(CASE WHEN r.estado = 'aprobado' AND r.tipo = 'vacacion' THEN r.dias_solicitados END), 0)
         AS dias_vacaciones_tomados,
       COALESCE(SUM(CASE WHEN r.estado = 'aprobado' AND r.tipo = 'permiso' THEN r.dias_solicitados END), 0)
         AS dias_permiso_tomados,
       MAX(r.created_at) AS ultima_solicitud
  FROM users u
  LEFT JOIN requests r ON r.user_id = u.id
 WHERE u.activo
 GROUP BY u.id, u.cedula, u.nombre, u.departamento, u.fecha_ingreso, u.dias_vacaciones;

CREATE OR REPLACE VIEW v_trazabilidad_solicitudes AS
SELECT r.id AS solicitud_id, r.folio, u.cedula, u.nombre AS empleado, u.departamento, u.cargo,
       r.tipo, pt.nombre AS categoria_permiso, pt.legal_ref AS base_legal,
       r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin, r.dias_solicitados,
       r.horas_solicitadas, r.fines_semana, r.es_adelanto, r.descripcion, r.justificacion,
       rp.nombre AS reemplazo, r.estado, r.created_at AS fecha_solicitud,
       j.nombre AS jefe, r.jefe_aprobado_en, h.nombre AS aprobador_rrhh, r.rrhh_aprobado_en,
       x.nombre AS rechazado_por, r.rechazado_en_etapa, r.rechazado_en, r.motivo_rechazo,
       r.qr_emitido_en, r.qr_usado_en,
       (SELECT COUNT(*) FROM request_attachments a WHERE a.request_id = r.id) AS adjuntos,
       (SELECT COUNT(*) FROM request_signatures s WHERE s.request_id = r.id) AS firmas,
       CASE r.estado
         WHEN 'aprobado' THEN 'Aprobada'
         WHEN 'rechazado' THEN CONCAT('Rechazada por ',
              CASE r.rechazado_en_etapa WHEN 'jefe' THEN 'el jefe inmediato' ELSE 'Talento Humano' END)
         WHEN 'cancelado' THEN 'Cancelada'
         ELSE 'En trámite'
       END AS resultado
  FROM requests r
  JOIN users u ON u.id = r.user_id
  LEFT JOIN users j ON j.id = r.jefe_id
  LEFT JOIN users h ON h.id = r.rrhh_aprobado_por
  LEFT JOIN users x ON x.id = r.rechazado_por
  LEFT JOIN users rp ON rp.id = r.reemplazo_id
  LEFT JOIN permission_types pt ON pt.id = r.permission_type_id;
