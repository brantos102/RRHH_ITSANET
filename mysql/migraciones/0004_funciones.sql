-- ---------------------------------------------------------------------------
-- 0004 · Las funciones auxiliares que se usan DENTRO de las consultas.
--
-- En PostgreSQL había 72 funciones que no eran disparadores. Se separan en
-- dos grupos y van a sitios distintos:
--
--   AQUÍ, en MySQL: las auxiliares escalares —reciben valores, devuelven un
--   valor— que se usan dentro de consultas y vistas. Cuántos años lleva
--   alguien, cuántos días le tocan por antigüedad, cuántos días hábiles hay
--   entre dos fechas. Viven en la base para que las vistas y las consultas
--   las sigan llamando igual que antes.
--
--   EN PYTHON (servidor/app/reglas/): las que devuelven estructuras o hacen
--   varios pasos —explicar un saldo, quitar una jefatura, dar de baja—. El
--   lenguaje de procedimientos de MySQL no devuelve tablas desde una función
--   ni tiene `format()`, y esa lógica se lee, se prueba y se depura mejor en
--   Python.
--
-- CADA FUNCIÓN SE COMPARÓ CONTRA SU ORIGINAL. Las pruebas de
-- mysql/pruebas/test_funciones_diferencial.py ejecutan el mismo cálculo en
-- PostgreSQL y en MySQL sobre miles de fechas —todos los días de varios
-- años, incluidos los 29 de febrero y los fines de mes— y exigen el mismo
-- resultado. Son las funciones de las que sale el saldo de vacaciones de 351
-- personas: un día de diferencia en un borde de mes no es un detalle.
--
-- TRES DIFERENCIAS DE MYSQL QUE SE RESUELVEN AQUÍ:
--
--   · No hay generate_series. Los conteos de días son un bucle día por día.
--     Con rangos de vacaciones —semanas, no años— el costo es nulo.
--   · No hay parámetros con valor por defecto ni dos funciones con el mismo
--     nombre. `anios_cumplidos` tenía un segundo parámetro opcional que nadie
--     usaba: aquí recibe solo la fecha de ingreso.
--   · No hay `age()`. Se usa TIMESTAMPDIFF, que cuenta años y meses
--     COMPLETOS igual que age(): comprobado fecha por fecha.
--
-- Con el registro binario activado (lo normal en MySQL 8), MySQL exige que
-- cada función declare si lee datos. Por eso todas llevan READS SQL DATA o
-- NO SQL: sin esa marca, crearlas fallaría con el error 1418.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

DELIMITER $$

-- ------------------------------------------------------------- parámetros
DROP FUNCTION IF EXISTS cfg_texto $$
CREATE FUNCTION cfg_texto(p_clave VARCHAR(255))
RETURNS TEXT
READS SQL DATA
BEGIN
  RETURN (SELECT NULLIF(TRIM(valor), '') FROM app_config WHERE clave = p_clave);
END $$

DROP FUNCTION IF EXISTS cfg_int $$
CREATE FUNCTION cfg_int(p_clave VARCHAR(255))
RETURNS INT
READS SQL DATA
BEGIN
  RETURN (SELECT CAST(valor AS SIGNED) FROM app_config WHERE clave = p_clave);
END $$

DROP FUNCTION IF EXISTS cfg_bool $$
CREATE FUNCTION cfg_bool(p_clave VARCHAR(255))
RETURNS BOOLEAN
READS SQL DATA
BEGIN
  RETURN COALESCE((SELECT LOWER(TRIM(valor)) = 'true' FROM app_config WHERE clave = p_clave), FALSE);
END $$

DROP FUNCTION IF EXISTS caducidad_activa $$
CREATE FUNCTION caducidad_activa()
RETURNS BOOLEAN
READS SQL DATA
BEGIN
  RETURN cfg_bool('caducidad_activa');
END $$

-- ------------------------------------------------------------- antigüedad
-- Años COMPLETOS de servicio a la fecha de hoy. TIMESTAMPDIFF(YEAR) cuenta
-- años cumplidos igual que extract(year from age(...)) de PostgreSQL,
-- incluido quien ingresó un 29 de febrero: cumple el 1 de marzo de los años
-- que no son bisiestos, en las dos bases.
DROP FUNCTION IF EXISTS anios_cumplidos $$
CREATE FUNCTION anios_cumplidos(p_fecha_ingreso DATE)
RETURNS INT
NO SQL
BEGIN
  RETURN GREATEST(0, TIMESTAMPDIFF(YEAR, p_fecha_ingreso, CURRENT_DATE()));
END $$

-- Igual, a una fecha de corte dada. La usan las pruebas para comparar
-- contra PostgreSQL en fechas que no son hoy, y los informes a una fecha.
DROP FUNCTION IF EXISTS anios_cumplidos_al $$
CREATE FUNCTION anios_cumplidos_al(p_fecha_ingreso DATE, p_corte DATE)
RETURNS INT
DETERMINISTIC
NO SQL
BEGIN
  RETURN GREATEST(0, TIMESTAMPDIFF(YEAR, p_fecha_ingreso, p_corte));
END $$

-- Antigüedad en años con dos decimales, para mostrar. PostgreSQL contaba
-- desde la medianoche UTC; aquí desde la medianoche de Ecuador, que es la
-- correcta. La diferencia —cinco horas en años de servicio— no mueve el
-- segundo decimal salvo en el instante exacto de un redondeo.
DROP FUNCTION IF EXISTS antiguedad_anios $$
CREATE FUNCTION antiguedad_anios(p_fecha_ingreso DATE)
RETURNS DECIMAL(10,2)
NO SQL
BEGIN
  RETURN ROUND(TIMESTAMPDIFF(SECOND, TIMESTAMP(p_fecha_ingreso), NOW()) / 31557600.0, 2);
END $$

-- Días que vale un período según el número de período (Art. 69): 15 base,
-- y desde el año indicado en vacaciones_anio_dia_extra (6) un día más por
-- año, hasta vacaciones_dias_extra_max (15) adicionales.
DROP FUNCTION IF EXISTS dias_por_antiguedad $$
CREATE FUNCTION dias_por_antiguedad(p_anios INT)
RETURNS DECIMAL(6,2)
READS SQL DATA
BEGIN
  IF p_anios <= 0 THEN
    RETURN 0;
  END IF;
  IF p_anios < cfg_int('vacaciones_anio_dia_extra') THEN
    RETURN cfg_int('vacaciones_dias_base');
  END IF;
  RETURN cfg_int('vacaciones_dias_base')
         + LEAST(p_anios - (cfg_int('vacaciones_anio_dia_extra') - 1),
                 cfg_int('vacaciones_dias_extra_max'));
END $$

-- Lo devengado en el período en curso: meses COMPLETOS dentro del período,
-- por la parte mensual de la base (15 / 12 = 1,25), acotado a doce. Los
-- días adicionales del Art. 69 se conceden enteros al cumplir el año, como
-- lo lleva Talento Humano en su hoja —salvo que el parámetro
-- vacaciones_extra_prorrateado diga lo contrario—.
DROP FUNCTION IF EXISTS dias_devengados_al $$
CREATE FUNCTION dias_devengados_al(p_ingreso DATE, p_periodo INT, p_corte DATE)
RETURNS DECIMAL(6,2)
READS SQL DATA
BEGIN
  DECLARE v_inicio DATE;
  DECLARE v_meses INT;
  DECLARE v_base DECIMAL(10,4);
  -- El período N empieza N-1 años después del ingreso. Un ingreso del 29
  -- de febrero empieza el 28 en los años que no son bisiestos, igual que
  -- en PostgreSQL.
  SET v_inicio = DATE_ADD(p_ingreso, INTERVAL (p_periodo - 1) YEAR);
  SET v_meses = LEAST(GREATEST(TIMESTAMPDIFF(MONTH, v_inicio, p_corte), 0), 12);
  IF cfg_bool('vacaciones_extra_prorrateado') THEN
    SET v_base = dias_por_antiguedad(p_periodo);
  ELSE
    SET v_base = cfg_int('vacaciones_dias_base');
  END IF;
  RETURN ROUND(v_base * v_meses / 12.0, 2);
END $$

DROP FUNCTION IF EXISTS dias_devengados_en_curso $$
CREATE FUNCTION dias_devengados_en_curso(p_ingreso DATE, p_periodo INT)
RETURNS DECIMAL(6,2)
READS SQL DATA
BEGIN
  RETURN dias_devengados_al(p_ingreso, p_periodo, CURRENT_DATE());
END $$

-- --------------------------------------------------------------- calendario
-- Lunes a viernes que no son feriado. Es lo que cuenta un PERMISO.
-- WEEKDAY(): 0 = lunes ... 6 = domingo.
DROP FUNCTION IF EXISTS dias_habiles $$
CREATE FUNCTION dias_habiles(p_inicio DATE, p_fin DATE)
RETURNS INT
READS SQL DATA
BEGIN
  DECLARE v_dia DATE;
  DECLARE v_n INT DEFAULT 0;
  IF p_inicio IS NULL OR p_fin IS NULL THEN
    RETURN 0;
  END IF;
  SET v_dia = p_inicio;
  WHILE v_dia <= p_fin DO
    IF WEEKDAY(v_dia) < 5
       AND NOT EXISTS (SELECT 1 FROM feriados f WHERE f.fecha = v_dia AND f.activo) THEN
      SET v_n = v_n + 1;
    END IF;
    SET v_dia = DATE_ADD(v_dia, INTERVAL 1 DAY);
  END WHILE;
  RETURN v_n;
END $$

-- Días que descuenta una solicitud. Un permiso cuenta días hábiles; unas
-- vacaciones cuentan días CALENDARIO menos feriados, con sábados y domingos
-- dentro, que es como las cuenta el Art. 69: quince días son quince.
DROP FUNCTION IF EXISTS calcular_dias $$
CREATE FUNCTION calcular_dias(p_tipo VARCHAR(20), p_inicio DATE, p_fin DATE)
RETURNS DECIMAL(6,2)
READS SQL DATA
BEGIN
  DECLARE v_dia DATE;
  DECLARE v_n INT DEFAULT 0;
  IF p_inicio IS NULL OR p_fin IS NULL OR p_fin < p_inicio THEN
    RETURN 0;
  END IF;
  IF p_tipo = 'permiso' THEN
    RETURN dias_habiles(p_inicio, p_fin);
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

-- Sábados cuyo domingo también cae dentro del rango: fines de semana
-- COMPLETOS. WEEKDAY() = 5 es sábado.
DROP FUNCTION IF EXISTS fines_de_semana_completos $$
CREATE FUNCTION fines_de_semana_completos(p_inicio DATE, p_fin DATE)
RETURNS INT
NO SQL
BEGIN
  DECLARE v_dia DATE;
  DECLARE v_n INT DEFAULT 0;
  IF p_inicio IS NULL OR p_fin IS NULL THEN
    RETURN 0;
  END IF;
  SET v_dia = p_inicio;
  WHILE v_dia <= p_fin DO
    IF WEEKDAY(v_dia) = 5 AND DATE_ADD(v_dia, INTERVAL 1 DAY) <= p_fin THEN
      SET v_n = v_n + 1;
    END IF;
    SET v_dia = DATE_ADD(v_dia, INTERVAL 1 DAY);
  END WHILE;
  RETURN v_n;
END $$

-- ------------------------------------------------------- fines de semana
DROP FUNCTION IF EXISTS situacion_fines_semana $$
CREATE FUNCTION situacion_fines_semana(p_devengado BOOLEAN, p_asignados DECIMAL(6,2),
                                       p_consumidos DECIMAL(6,2))
RETURNS VARCHAR(20)
DETERMINISTIC
NO SQL
BEGIN
  IF NOT p_devengado THEN RETURN 'en_curso'; END IF;
  IF p_consumidos <= 0 THEN RETURN 'sin_gozar'; END IF;
  IF p_consumidos >= p_asignados THEN RETURN 'cumplido'; END IF;
  RETURN 'por_confirmar';
END $$

DROP FUNCTION IF EXISTS fines_semana_pendientes $$
CREATE FUNCTION fines_semana_pendientes(p_user_id CHAR(36))
RETURNS INT
READS SQL DATA
BEGIN
  RETURN (SELECT COALESCE(SUM(GREATEST(0, p.fines_semana_obligatorios - p.fines_semana_consumidos)), 0)
            FROM vacation_periods p
           WHERE p.user_id = p_user_id
             AND NOT p.caducado
             AND situacion_fines_semana(p.devengado, p.dias_asignados, p.dias_consumidos)
                 = 'por_confirmar');
END $$

-- ------------------------------------------------------------------ varios
DROP FUNCTION IF EXISTS puede_citar $$
CREATE FUNCTION puede_citar(p_codigo VARCHAR(255))
RETURNS BOOLEAN
READS SQL DATA
BEGIN
  RETURN COALESCE((SELECT l.visibilidad <> 'oculto' FROM legal_references l
                    WHERE l.codigo = p_codigo), TRUE);
END $$

DROP FUNCTION IF EXISTS rrhh_correo_de_region $$
CREATE FUNCTION rrhh_correo_de_region(p_region VARCHAR(40))
RETURNS TEXT
READS SQL DATA
BEGIN
  RETURN cfg_texto(CASE WHEN COALESCE(p_region, 'sierra') = 'costa'
                        THEN 'rrhh_correo_costa' ELSE 'rrhh_correo_sierra' END);
END $$

-- La colación utf8mb4_0900_ai_ci ya ignora tildes y mayúsculas, así que no
-- hace falta quitar las tildes antes de comparar como en PostgreSQL: la
-- comparación con = ya encuentra «QUITO» buscando «Quito».
DROP FUNCTION IF EXISTS region_de_ciudad $$
CREATE FUNCTION region_de_ciudad(p_ciudad VARCHAR(255))
RETURNS VARCHAR(40)
READS SQL DATA
BEGIN
  RETURN COALESCE((SELECT c.region FROM ciudades_region c
                    WHERE c.ciudad = TRIM(COALESCE(p_ciudad, '')) LIMIT 1),
                  'sierra');
END $$

-- Sin autenticación: responde solo verdadero o falso, para no revelar si
-- una cédula existe cuando la respuesta es no. La cédula es casi pública en
-- Ecuador.
DROP FUNCTION IF EXISTS puede_completar_ficha $$
CREATE FUNCTION puede_completar_ficha(p_cedula VARCHAR(20))
RETURNS BOOLEAN
READS SQL DATA
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM users
     WHERE cedula = p_cedula AND activo
       AND (email IS NULL OR (correo_pendiente AND NOT ficha_completa)));
END $$

DELIMITER ;
