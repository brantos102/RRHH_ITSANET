-- =====================================================================
-- 0007 · Feriados nacionales 2026 y 2027
--
-- Faltaban en los datos base: sin ellos, calcular_dias() contaría un feriado
-- dentro de unas vacaciones como día gozado, y el sistema de PostgreSQL no lo
-- hacía. Son los mismos 22 que tiene hoy el sistema.
--
-- A REVISAR POR TALENTO HUMANO contra el calendario oficial de feriados de
-- cada año: el Gobierno traslada algunos por decreto (por ejemplo, la
-- Batalla de Pichincha de 2026 figura el domingo 24 de mayo). Se corrigen
-- desde la administración del sistema, no editando este archivo.
--
-- Una transacción. Si se vuelve a aplicar, no duplica nada.
-- =====================================================================
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2026-01-01', 'Año Nuevo', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2026-02-16', 'Carnaval', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2026-02-17', 'Carnaval', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2026-04-03', 'Viernes Santo', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2026-05-01', 'Día del Trabajo', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2026-05-24', 'Batalla de Pichincha', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2026-08-10', 'Primer Grito de Independencia', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2026-10-09', 'Independencia de Guayaquil', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2026-11-02', 'Día de los Difuntos', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2026-11-03', 'Independencia de Cuenca', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2026-12-25', 'Navidad', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2027-01-01', 'Año Nuevo', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2027-02-08', 'Carnaval', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2027-02-09', 'Carnaval', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2027-03-26', 'Viernes Santo', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2027-05-01', 'Día del Trabajo', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2027-05-24', 'Batalla de Pichincha', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2027-08-10', 'Primer Grito de Independencia', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2027-10-09', 'Independencia de Guayaquil', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2027-11-02', 'Día de los Difuntos', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2027-11-03', 'Independencia de Cuenca', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
INSERT INTO feriados (fecha, nombre, activo) VALUES ('2027-12-25', 'Navidad', 1)
  AS nuevo ON DUPLICATE KEY UPDATE nombre = nuevo.nombre, activo = nuevo.activo;
