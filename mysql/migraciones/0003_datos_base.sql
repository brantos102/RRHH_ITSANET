-- ---------------------------------------------------------------------------
-- 0003 · Los datos de referencia con los que nace el sistema.
--
-- Las migraciones de PostgreSQL no solo creaban tablas: también cargaban el
-- catálogo con el que el sistema funciona desde el primer día. Sin esto,
-- MySQL tendría las tablas vacías y nada funcionaría: no se podría dar de
-- alta a nadie (las regiones son obligatorias), ni pedir un permiso (no
-- habría tipos), ni calcular un saldo (no habría parámetros).
--
--   regiones, ciudades_region      Sierra y Costa, y qué ciudad va con cuál
--   app_config                     los parámetros: 15 días base, 1 día extra
--                                  desde el año 6, anticipación, bloque mínimo...
--   antiguedad_referencia          la tabla de días por años de servicio
--   permission_categories/types    los tres pilares y sus 22 tipos de permiso
--   legal_references               los artículos del Código del Trabajo y la
--                                  LOPDP, con sus resúmenes en lenguaje llano
--   lineamientos_solicitud         lo que se lee antes de enviar una solicitud
--   campos_ficha                   quién puede cambiar cada dato de la ficha
--   panel_bloques, tablero_bloques los bloques de la pantalla principal y del
--                                  tablero de indicadores
--
-- Exportado de una base PostgreSQL construida solo con las 46 migraciones,
-- sin datos de prueba, con el mismo convertidor que usa el traslado
-- (mysql/convertir.py).
--
-- Las tablas van en el orden de sus dependencias —las regiones antes que
-- las ciudades, los artículos de ley antes que los parámetros que los
-- citan—, con las claves foráneas activas, para que MySQL compruebe cada
-- referencia al cargarla.
--
-- NO PISA LO QUE YA ESTÉ. Cada fila va con ON DUPLICATE KEY UPDATE sobre su
-- propia clave, que no cambia nada: si Talento Humano ya ajustó un parámetro,
-- o si el traslado ya trajo los valores de producción, se quedan los suyos.
-- Se eligió esto y no INSERT IGNORE a propósito: IGNORE también se traga
-- errores de verdad —un texto truncado, un valor fuera de rango— sin avisar.
-- ---------------------------------------------------------------------------

SET NAMES utf8mb4 COLLATE utf8mb4_0900_ai_ci;

-- regiones: 2 fila(s)
INSERT INTO regiones (codigo, nombre, sede, descripcion, activo) VALUES ('sierra', 'Sierra y Oriente', 'Quito', 'Pichincha y el resto de la Sierra, más la Amazonía, atendidas desde Quito.', 1)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO regiones (codigo, nombre, sede, descripcion, activo) VALUES ('costa', 'Costa e Insular', 'Guayaquil', 'Guayas y el resto de la Costa, más Galápagos, atendidas desde Guayaquil.', 1)
  ON DUPLICATE KEY UPDATE codigo = codigo;

-- ciudades_region: 55 fila(s)
INSERT INTO ciudades_region (ciudad, region) VALUES ('QUITO', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('AMBATO', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('CUENCA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('LOJA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('RIOBAMBA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('IBARRA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('LATACUNGA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('TULCAN', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('AZOGUES', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('GUARANDA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('CAYAMBE', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('OTAVALO', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('SANGOLQUI', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('MACHACHI', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('ALAUSI', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('SALCEDO', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('PELILEO', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('PILLARO', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('CAÑAR', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('TENA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('PUYO', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('MACAS', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('ZAMORA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('NUEVA LOJA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('LAGO AGRIO', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('COCA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('EL COCA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('SUCUA', 'sierra')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('GUAYAQUIL', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('MACHALA', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('PORTOVIEJO', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('MANTA', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('ESMERALDAS', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('BABAHOYO', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('QUEVEDO', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('MILAGRO', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('DURAN', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('DAULE', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('SAMBORONDON', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('SALINAS', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('SANTA ELENA', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('LA LIBERTAD', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('PLAYAS', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('SANTO DOMINGO', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('CHONE', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('JIPIJAPA', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('VENTANAS', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('EL TRIUNFO', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('NARANJAL', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('PASAJE', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('HUAQUILLAS', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('BAHIA DE CARAQUEZ', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('PUERTO AYORA', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('PUERTO BAQUERIZO MORENO', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;
INSERT INTO ciudades_region (ciudad, region) VALUES ('GALAPAGOS', 'costa')
  ON DUPLICATE KEY UPDATE ciudad = ciudad;

-- legal_references: 37 fila(s)
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_71', 'Código del Trabajo del Ecuador', 'Art. 71', 'Liquidación para pago de vacaciones', 'La liquidación para el pago de vacaciones se hará en forma general y única, computando la veinticuatroava parte de lo percibido por el trabajador durante un año completo de trabajo.', NULL, 'vacaciones', 20, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ITSANET_ANTICIPACION', 'Lineamientos internos ITSANET', 'Lineamiento 1', 'Anticipación mínima', 'Las vacaciones deberán ser comunicadas con mínimo 10 días de anticipación, para que la jefatura pueda organizar la cobertura del puesto.', NULL, 'vacaciones', 300, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_42_30', 'Código del Trabajo del Ecuador', 'Art. 42 núm. 30', 'Permiso por calamidad doméstica', 'Es obligación del empleador conceder permiso o declarar en comisión de servicio hasta por un año, con sueldo, en casos de calamidad doméstica debidamente comprobada, y conceder tres días de licencia por fallecimiento del cónyuge o conviviente en unión de hecho o de sus parientes dentro del segundo grado de consanguinidad o afinidad.', NULL, 'permisos', 60, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_42_9', 'Código del Trabajo del Ecuador', 'Art. 42 núm. 9', 'Atención médica y enfermedad', 'Es obligación del empleador sujetarse al reglamento de seguridad e higiene y conceder al trabajador la atención médica necesaria, así como respetar los certificados médicos emitidos por el IESS.', NULL, 'permisos', 70, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_152', 'Código del Trabajo del Ecuador', 'Art. 152', 'Licencia por maternidad y paternidad', 'Toda mujer trabajadora tiene derecho a una licencia con remuneración de doce semanas por el nacimiento de su hija o hijo. El padre tiene derecho a licencia con remuneración por diez días por el nacimiento de su hija o hijo cuando el parto es normal, y por quince días en los casos de nacimientos múltiples o por cesárea.', NULL, 'permisos', 80, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_155', 'Código del Trabajo del Ecuador', 'Art. 155', 'Jornada por lactancia', 'Durante los doce meses posteriores al parto, la jornada de la madre lactante durará seis horas, de conformidad con la necesidad de la beneficiaria.', NULL, 'permisos', 90, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('LOD_ART_49', 'Ley Orgánica de Discapacidades', 'Art. 49', 'Permiso por cuidado de persona con discapacidad', 'La persona trabajadora que tenga bajo su responsabilidad a una persona con discapacidad severa tiene derecho a dos horas diarias de permiso para su cuidado, previa justificación.', NULL, 'permisos', 100, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('LOD_ART_47', 'Ley Orgánica de Discapacidades', 'Art. 47', 'Inclusión laboral', 'El empleador público o privado que cuente con un número mínimo de veinticinco trabajadores está obligado a contratar un mínimo de cuatro por ciento de personas con discapacidad.', NULL, 'laboral', 110, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('COD_DEMOCRACIA', 'Código de la Democracia', 'Art. 11', 'Permiso para sufragar', 'El ejercicio del derecho al voto es obligatorio. Los empleadores concederán el permiso necesario para que sus trabajadores acudan a sufragar sin descuento de su remuneración.', NULL, 'permisos', 120, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_42_29', 'Código del Trabajo del Ecuador', 'Art. 42 núm. 29', 'Facilidades para estudios', 'Es obligación del empleador suministrar cada año, en forma completamente gratuita, por lo menos un vestido adecuado para el trabajo y conceder a los trabajadores las facilidades necesarias para su instrucción y capacitación.', NULL, 'permisos', 65, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_42', 'Código del Trabajo del Ecuador', 'Art. 42', 'Obligaciones del empleador', 'Enumera las obligaciones del empleador, entre ellas conceder los permisos y licencias que la ley establece y facilitar al trabajador el cumplimiento de deberes legales ante entidades públicas.', NULL, 'permisos', 66, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('COGEP_ART_53', 'Código Orgánico General de Procesos', 'Art. 53', 'Deber de comparecer', 'Las personas citadas o notificadas por la autoridad judicial están obligadas a comparecer. El empleador concederá el permiso necesario para el cumplimiento de esta obligación.', NULL, 'permisos', 115, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('LOS_ART_79', 'Ley Orgánica de Salud', 'Art. 79', 'Donación voluntaria de sangre', 'La donación de sangre es un acto voluntario y solidario. Las instituciones públicas y privadas concederán a sus trabajadores el permiso necesario para donar sangre.', NULL, 'permisos', 135, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CC_ART_30', 'Código Civil del Ecuador', 'Art. 30', 'Caso fortuito o fuerza mayor', 'Se llama fuerza mayor o caso fortuito el imprevisto a que no es posible resistir, como un naufragio, un terremoto, el apresamiento de enemigos, los actos de autoridad ejercidos por un funcionario público, etcétera.', NULL, 'permisos', 155, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('POLITICA_INTERNA', 'Reglamento Interno de Trabajo', 'Política interna', 'Permiso por asunto personal', 'Permiso discrecional otorgado por la empresa para asuntos personales del trabajador. No corresponde a una licencia legal obligatoria, por lo que se imputa al saldo de vacaciones conforme a la política interna aprobada por Talento Humano.', NULL, 'permisos', 165, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('LOPDP_ART_4', 'Ley Orgánica de Protección de Datos Personales', 'Art. 4', 'Datos sensibles', 'Se consideran datos sensibles aquellos relativos a salud, datos genéticos y biométricos, origen étnico, condición migratoria, orientación sexual, religión, filiación política y situación de discapacidad. Su tratamiento requiere consentimiento expreso y medidas de seguridad reforzadas.', NULL, 'proteccion_datos', 200, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('LOPDP_ART_7', 'Ley Orgánica de Protección de Datos Personales', 'Art. 7', 'Consentimiento', 'El tratamiento de datos personales requiere el consentimiento libre, específico, informado e inequívoco del titular, salvo las excepciones previstas en la ley, entre ellas el cumplimiento de una obligación legal o la ejecución de una relación contractual laboral.', NULL, 'proteccion_datos', 210, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('LOPDP_ART_10', 'Ley Orgánica de Protección de Datos Personales', 'Art. 10', 'Principios', 'El tratamiento de datos personales se rige por los principios de juridicidad, lealtad, transparencia, finalidad, pertinencia y minimización, proporcionalidad, confidencialidad, calidad y exactitud, conservación, seguridad de datos personales y responsabilidad proactiva y demostrada.', NULL, 'proteccion_datos', 220, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('LOPDP_ART_12', 'Ley Orgánica de Protección de Datos Personales', 'Art. 12 al 16', 'Derechos del titular (ARCO)', 'El titular tiene derecho de acceso, rectificación y actualización, eliminación, oposición, portabilidad, y a no ser objeto de decisiones automatizadas. El responsable debe atender la solicitud en un plazo máximo de quince días.', NULL, 'proteccion_datos', 230, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('LOPDP_ART_37', 'Ley Orgánica de Protección de Datos Personales', 'Art. 37', 'Seguridad del tratamiento', 'El responsable y el encargado aplicarán medidas técnicas y organizativas apropiadas, incluidas la seudonimización y el cifrado, la capacidad de garantizar confidencialidad, integridad, disponibilidad y resiliencia, y un proceso de verificación y evaluación regular de su eficacia.', NULL, 'proteccion_datos', 240, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ISO27001_A5_15', 'ISO/IEC 27001:2022', 'Anexo A 5.15', 'Control de acceso', 'Se deben establecer y aplicar reglas de control de acceso físico y lógico a la información sobre la base de los requisitos del negocio y de seguridad de la información. En este sistema se implementa con Row Level Security por rol y con el principio de mínimo privilegio.', NULL, 'iso', 300, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ISO27001_A8_15', 'ISO/IEC 27001:2022', 'Anexo A 8.15', 'Registro de eventos (logging)', 'Se deben producir, almacenar, proteger y analizar registros de actividades, excepciones, fallos y eventos relevantes para la seguridad. En este sistema corresponde a audit_logs y access_logs, protegidos contra modificación y borrado.', NULL, 'iso', 310, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ISO27001_A5_34', 'ISO/IEC 27001:2022', 'Anexo A 5.34', 'Privacidad y protección de datos personales', 'La organización debe identificar y cumplir los requisitos relativos a la preservación de la privacidad y la protección de datos personales de acuerdo con la legislación aplicable.', NULL, 'iso', 320, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ISO9001_8_5_2', 'ISO 9001:2015', 'Cláusula 8.5.2', 'Identificación y trazabilidad', 'Cuando la trazabilidad sea un requisito, la organización debe controlar la identificación única de las salidas y conservar la información documentada necesaria para permitir la trazabilidad. En este sistema, cada solicitud tiene identificador único, historial de estados, firmas y bitácora de accesos.', NULL, 'iso', 330, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ITSANET_APROBACION', 'Lineamientos internos ITSANET', 'Lineamiento 2', 'Aprobación previa', 'Toda vacación debe ser planificada y aprobada previamente por la jefatura inmediata y Talento Humano. Registrar una fecha no significa que las vacaciones estén aprobadas.', NULL, 'vacaciones', 310, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ITSANET_DISPONIBILIDAD', 'Lineamientos internos ITSANET', 'Lineamiento 3', 'Disponibilidad de días', 'Antes de confirmar las vacaciones se debe consultar con Talento Humano la disponibilidad de días del colaborador.', NULL, 'vacaciones', 320, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ITSANET_ANULACION', 'Lineamientos internos ITSANET', 'Lineamiento 4', 'Anulación o modificación', 'Las vacaciones aprobadas podrán ser modificadas o anuladas únicamente por una necesidad operativa debidamente justificada y previa coordinación con Talento Humano.', NULL, 'vacaciones', 330, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ITSANET_ASUNTOS_PERSONALES', 'Lineamientos internos ITSANET', 'Lineamiento 5', 'Asuntos personales', 'Los asuntos personales no se registran como vacaciones sino como permiso. Para esos casos corresponde gestionar el permiso respectivo.', NULL, 'permisos', 340, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ITSANET_PROYECCION', 'Lineamientos internos ITSANET', 'Comunicado de proyección', 'Las fechas proyectadas son tentativas', 'Las fechas registradas en la proyección son tentativas y están sujetas a revisión y confirmación según las necesidades de la compañía. La programación considera la operación y demanda del servicio, la disponibilidad de reemplazos, la continuidad de las operaciones y las necesidades de cada área.', NULL, 'vacaciones', 350, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ITSANET_BLOQUE', 'Lineamientos internos ITSANET', 'Política de bloques', 'Las vacaciones se toman en bloques', 'La regla general es tomar el período completo que corresponde por antigüedad. El bloque mínimo aceptado es de 7 días seguidos. Solicitar menos es una excepción que exige justificación documentada y la autoriza Talento Humano antes que la jefatura.', NULL, 'vacaciones', 360, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('ITSANET_ADELANTO', 'Lineamientos internos ITSANET', 'Política de adelanto', 'Adelanto de días no devengados', 'Quien no tenga días disponibles puede solicitar un adelanto, pero ese camino lo autoriza primero Talento Humano: implica comprometer días que aún no se han generado.', NULL, 'vacaciones', 370, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CONST_ART_326_2', 'Constitución de la República del Ecuador', 'Art. 326 núm. 2', 'Irrenunciabilidad de los derechos laborales', 'Los derechos laborales son irrenunciables e intangibles. Será nula toda estipulación en contrario.', NULL, 'laboral', 77, 'completo', NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_69', 'Código del Trabajo del Ecuador', 'Art. 69', 'Vacaciones anuales', 'Todo trabajador tendrá derecho a gozar anualmente de un período ininterrumpido de quince días de descanso, incluidos los días no laborables. Los trabajadores que hubieren prestado servicios por más de cinco años en la misma empresa tendrán derecho a gozar adicionalmente de un día de vacaciones por cada uno de los años excedentes o recibirán en dinero la remuneración correspondiente a los días excedentes. El trabajador podrá no hacer uso de las vacaciones hasta por tres años consecutivos, a fin de acumularlas en el cuarto año.', NULL, 'vacaciones', 10, 'completo', 'Le corresponden quince días de descanso por cada año cumplido. Desde el sexto año se suma un día por año, hasta treinta días en total.', NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_75', 'Código del Trabajo del Ecuador', 'Art. 75', 'Acumulación de vacaciones', 'El trabajador podrá no hacer uso de las vacaciones hasta por tres años consecutivos, a fin de acumularlas en el cuarto año.', NULL, 'vacaciones', 50, 'completo', 'Si un año no alcanza a tomar sus vacaciones, no las pierde: puede acumularlas hasta tres años. Pasado ese plazo la empresa está obligada a programarlas, y por eso Talento Humano puede fijarle las fechas.', NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_76', 'Código del Trabajo del Ecuador', 'Art. 76', 'Compensación por vacaciones no gozadas', 'Si el trabajador no hubiere gozado de las vacaciones tendrá derecho al equivalente de las remuneraciones que correspondan al tiempo de las no gozadas, sin recargo. La liquidación se efectuará en la forma prevista en el artículo 71 de este Código.', NULL, 'vacaciones', 76, 'completo', 'Las vacaciones que no llegó a tomar no se pierden: se pagan al liquidar la relación de trabajo. No son dinero que se pueda pedir en lugar del descanso mientras sigue trabajando.', NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_73', 'Código del Trabajo del Ecuador', 'Art. 73', 'Fijación del período vacacional', 'En el contrato se hará constar el período en que el trabajador comenzará a gozar de vacaciones. No habiendo contrato escrito o de no haberse establecido en él, el empleador señalará el período vacacional, lo que deberá constar en un cuadro que se exhibirá en un lugar visible.', NULL, 'vacaciones', 30, 'completo', 'Las fechas se acuerdan con su jefe inmediato dentro del año siguiente al que generó el derecho. La empresa puede ajustarlas por necesidad del servicio.', NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;
INSERT INTO legal_references (codigo, norma, articulo, titulo, texto, url_oficial, categoria, orden, visibilidad, resumen, visibilidad_en, visibilidad_por) VALUES ('CT_ART_74', 'Código del Trabajo del Ecuador', 'Art. 74', 'Postergación por el empleador', 'Cuando se trate de labores técnicas o de confianza para las que sea difícil reemplazar al trabajador por corto tiempo, el empleador podrá negar la vacación en un año para acumularla necesariamente a la del año siguiente.', NULL, 'vacaciones', 40, 'completo', 'La empresa puede postergar sus vacaciones por necesidad del servicio, pero no puede dejarlas sin fecha: queda obligada a concederlas.', NULL, NULL)
  ON DUPLICATE KEY UPDATE codigo = codigo;

-- app_config: 25 fila(s)
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('fines_semana_obligatorios', '2', 'Fines de semana completos que deben consumirse en cada período', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('descripcion_max_chars', '200', 'Longitud máxima de la descripción de la solicitud', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('vacaciones_dias_base', '15', 'Días de vacaciones por año cumplido (Art. 69 Código del Trabajo)', 'CT_ART_69')
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('vacaciones_anio_dia_extra', '6', 'Año de antigüedad desde el cual se suma 1 día adicional por año', 'CT_ART_69')
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('vacaciones_dias_extra_max', '15', 'Tope de días adicionales por antigüedad (15 => máximo 30 días)', 'CT_ART_69')
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('acumulacion_max_anios', '3', 'Años que un período puede acumularse antes de caducar (Art. 75)', 'CT_ART_75')
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('alerta_saldo_alto', '30', 'Saldo acumulado a partir del cual se sugiere tomar vacaciones', 'CT_ART_75')
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('alerta_dias_por_caducar', '90', 'Días de anticipación con que se avisa que un período va a caducar', 'CT_ART_75')
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('retencion_audit_logs_meses', '84', 'Meses de conservación de la bitácora de auditoría (7 años)', 'LOPDP_ART_10')
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('retencion_access_logs_meses', '24', 'Meses de conservación de la bitácora de garita', 'LOPDP_ART_10')
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('politica_privacidad_version', '1.0', 'Versión vigente de la política de tratamiento de datos', 'LOPDP_ART_7')
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('vacaciones_bloque_minimo', '7', 'Días calendario mínimos por solicitud de vacaciones. Menos exige justificación documentada y lo autoriza primero Talento Humano.', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('mandato_descripcion', 'Declare toda la información pertinente: el motivo, el lugar, la hora y cuánto tiempo estará ausente. Su jefe inmediato y Talento Humano deciden únicamente con lo que usted escriba aquí y con lo que adjunte. Si falta un dato, la solicitud se devuelve y usted pierde el tiempo que quería ganar.', 'Texto que encabeza el campo de descripción en toda solicitud', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('vacaciones_anticipacion_dias', '10', 'Días de anticipación mínimos para solicitar vacaciones (Lineamiento 1)', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('vacaciones_bloque_sugerido', '15', 'Días que se proponen por omisión al solicitar vacaciones: el período completo', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('caducidad_activa', 'false', 'Si los días no gozados se extinguen al cumplirse el plazo de acumulación. El Art. 75 del Código del Trabajo PERMITE acumular hasta tres años; no obliga a extinguir. ITSANET no extingue: apagado.', 'CT_ART_75')
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('acumulacion_aviso_periodos', '3', 'Períodos cumplidos sin gozar a partir de los cuales Talento Humano debe programar las vacaciones (Art. 75 del Código del Trabajo).', 'CT_ART_75')
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('vacaciones_extra_prorrateado', 'false', 'Si los días adicionales por antigüedad (Art. 69) se acumulan mes a mes dentro del año en curso. En falso —como lo lleva Talento Humano— el año en curso acumula solo la parte base (1,25 días al mes) y los adicionales se conceden enteros al cumplir el año.', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('rrhh_correo_sierra', '', 'Correo del departamento de Talento Humano en la Sierra (Quito). Recibe copia de todo lo que se dirige al departamento. En blanco, solo reciben los buzones personales.', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('rrhh_correo_costa', '', 'Correo del departamento de Talento Humano en la Costa (Guayaquil). Recibe copia de todo lo que se dirige al departamento. En blanco, solo reciben los buzones personales.', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('firma_obligatoria', 'false', 'RETIRADO. La firma dibujada se quitó del sistema: el acceso con cédula y código de un solo uso al correo institucional identifica mejor a quien solicita. Este parámetro ya no tiene efecto.', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('trazabilidad_reemision', 'autorizada', 'Qué pasa cuando el colaborador vuelve a pedir su informe de trazabilidad. «autorizada»: hace falta que un administrador o Talento Humano lo autoricen, dejando el motivo. «libre»: lo puede reimprimir cuando quiera. El papel ya firmado nunca cambia: una reemisión es un documento nuevo con su propio folio.', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('empresa_razon_social', 'ITSANET S.A.', 'Razón social que encabeza los documentos que el colaborador firma.', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('empresa_ruc', '', 'RUC que se imprime en los documentos. En blanco, no se imprime la línea.', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO app_config (clave, valor, descripcion, legal_ref) VALUES ('empresa_ciudad', 'Quito', 'Ciudad que se imprime al pie de los documentos, antes de la fecha.', NULL)
  ON DUPLICATE KEY UPDATE clave = clave;

-- permission_categories: 3 fila(s)
INSERT INTO permission_categories (id, codigo, nombre, descripcion, ayuda, orden, activo) VALUES (1, 'calamidad_domestica', 'Calamidad doméstica', 'Hecho grave e imprevisto en su entorno familiar o su vivienda que exige su presencia inmediata.', 'Son situaciones que usted no pudo prever ni evitar. Código del Trabajo, Art. 42 núm. 30.', 10, 1)
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_categories (id, codigo, nombre, descripcion, ayuda, orden, activo) VALUES (2, 'cita_medica', 'Cita médica', 'Atención de salud suya o de quien depende de usted, incluidas las licencias que la ley reconoce.', 'Cubre desde una consulta de una hora hasta un reposo con certificado. Código del Trabajo, Art. 42 núm. 9.', 20, 1)
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_categories (id, codigo, nombre, descripcion, ayuda, orden, activo) VALUES (3, 'permiso_personal', 'Permiso personal', 'Obligaciones legales, trámites y asuntos propios que solo pueden atenderse en horario laboral.', 'Si el trámite puede hacerse fuera del horario, no corresponde este permiso.', 30, 1)
  ON DUPLICATE KEY UPDATE id = id;

-- permission_types: 22 fila(s)
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (1, 'cita_medica', 'Cita médica', NULL, 1, 1, 0, 1, 0, '1.00', '8.00', 'Art. 42 CT / Reglamento IESS', 10, 1, 'CT_ART_42_9', 2, 'Ej.: Tengo cita de control con el traumatólogo en el Hospital de los Valles, av. Interoceánica. La cita es a las 10:00. Salgo 09:00 y calculo volver a las 12:30 porque voy en transporte público.', 'Adjunte la captura o el documento del turno donde se lean la fecha, la hora y el establecimiento.', 1, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (17, 'emergencia_medica', 'Emergencia médica propia', 'Atención imprevista en emergencia, sin cita previa', 1, 1, 0, 1, 0, NULL, NULL, NULL, 15, 1, 'CT_ART_42_9', 2, 'Ej.: Me descompensé en la oficina con dolor en el pecho y acudí a emergencias del Hospital Metropolitano a las 11:20. Aviso desde la sala de espera e informaré el diagnóstico apenas me atiendan.', 'Hoja de atención de emergencia o el certificado que emita el establecimiento. Si aún no lo tiene, entréguelo al reincorporarse.', 1, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (18, 'acompanamiento_medico', 'Acompañamiento a cita médica de familiar', 'Acompañar a un familiar dependiente a su atención de salud', 1, 1, 0, 1, 0, '1.00', '8.00', NULL, 25, 1, 'CT_ART_42_9', 2, 'Ej.: Debo acompañar a mi hijo de 6 años a su control pediátrico en el Centro de Salud de Cotocollao. La cita es a las 08:30 y calculo estar en la oficina a las 11:00.', 'Turno de la cita del familiar y un documento que acredite el parentesco.', 1, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (2, 'enfermedad', 'Enfermedad (certificado médico)', NULL, 1, 1, 0, 1, 0, NULL, NULL, 'Art. 42 num. 9 CT / IESS', 20, 1, 'CT_ART_42_9', 2, 'Ej.: El médico del IESS me otorgó reposo por 3 días, del 12 al 14 de marzo, por un cuadro de gastroenteritis. Me reincorporo el 15 a primera hora.', 'Certificado de reposo del IESS o del médico tratante, con sello y número de registro profesional.', 0, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (7, 'lactancia', 'Permiso de lactancia', NULL, 0, 0, 0, 1, 0, NULL, '2.00', 'Art. 155 CT', 70, 1, 'CT_ART_155', 2, 'Ej.: Me reincorporo el 1 de julio y solicito la jornada reducida por lactancia hasta que mi hijo cumpla 12 meses. Entraré a las 08:00 y saldré a las 14:00.', 'Partida de nacimiento del menor.', 1, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (14, 'cuidado_discapacidad', 'Cuidado de persona con discapacidad', NULL, 1, 1, 0, 1, 0, NULL, '2.00', 'LOD Art. 49', 140, 1, 'LOD_ART_49', 2, 'Ej.: Mi madre tiene discapacidad del 60% y debo llevarla a su terapia en la av. América. La cita es a las 15:00 y calculo 2 horas.', 'Carné de discapacidad del familiar y el turno o cita a la que asistirá.', 1, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (12, 'sufragio', 'Sufragio electoral', NULL, 0, 0, 0, 1, 0, '1.00', NULL, 'Código de la Democracia', 120, 1, 'COD_DEMOCRACIA', 3, 'Ej.: Soy miembro de la junta receptora del voto en el recinto Colegio Mejía para las elecciones del 9 de febrero.', 'Notificación como miembro de junta o certificado de votación. Puede entregarlo después.', 1, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (9, 'estudios', 'Estudios o capacitación', NULL, 1, 1, 0, 1, 0, NULL, NULL, 'Art. 42 num. 29 CT', 90, 1, 'CT_ART_42_29', 3, 'Ej.: Rindo el examen final de la maestría en la PUCE el jueves 12, de 18:00 a 20:00, y necesito salir a las 17:00. Es la única fecha: la supletoria es en dos meses.', 'Calendario académico, convocatoria al examen o certificado de la institución.', 1, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (16, 'permiso_personal', 'Asunto personal (con cargo a vacaciones)', NULL, 0, 1, 0, 1, 1, '3.00', '8.00', 'Acuerdo interno', 160, 1, 'POLITICA_INTERNA', 3, 'Ej.: Necesito la mañana del viernes 7 para un asunto familiar en Sangolquí. Entiendo que se descuenta de mi saldo de vacaciones. Regreso a las 14:00.', 'No exige respaldo, pero adjunte lo que ayude a su jefe a dimensionar la urgencia.', 1, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (21, 'otro_salud', 'Otro motivo de salud', 'Atención de salud que no encaja en los anteriores', 1, 1, 0, 1, 0, NULL, NULL, NULL, 90, 1, 'CT_ART_42_9', 2, 'Ej.: Debo someterme a un examen de laboratorio en ayunas en el laboratorio de la av. Shyris. Me presento a las 07:00 y calculo estar en la oficina a las 10:00. No encontré una categoría que lo describa.', 'Adjunte la orden médica, el turno o el documento que respalde la atención. Al ser un motivo fuera de las categorías, el respaldo pesa más.', 1, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (22, 'otro_personal', 'Otro asunto personal', 'Obligación o trámite que no encaja en los anteriores', 1, 1, 0, 1, 0, NULL, NULL, NULL, 190, 1, 'CT_ART_42_29', 3, 'Ej.: Debo asistir a la lectura de un testamento en la notaría tercera de la av. Amazonas el martes 12 a las 09:00. Es la única fecha fijada por el notario y calculo 3 horas.', 'Adjunte la convocatoria, la notificación o el documento que respalde el compromiso. Al ser un motivo fuera de las categorías, el respaldo pesa más.', 1, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (5, 'maternidad', 'Licencia por maternidad', NULL, 1, 0, 0, 1, 0, '84.00', NULL, 'Art. 152 CT', 50, 1, 'CT_ART_152', 2, 'Ej.: Mi fecha probable de parto es el 20 de mayo. Solicito las 12 semanas de licencia desde esa fecha. Dejé al día el informe mensual y coordiné el traspaso con mi equipo.', 'Certificado médico con la fecha probable de parto. Tras el nacimiento, la partida de nacimiento o el certificado de nacido vivo.', 0, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (6, 'paternidad', 'Licencia por paternidad', NULL, 1, 0, 0, 1, 0, '15.00', NULL, 'Art. 152 CT', 60, 1, 'CT_ART_152', 2, 'Ej.: Mi hija nació el 3 de abril en la Clínica Pichincha. Solicito los días de licencia desde el 4 de abril.', 'Certificado de nacido vivo o partida de nacimiento.', 0, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (8, 'matrimonio', 'Matrimonio o unión de hecho', NULL, 1, 0, 0, 1, 0, '3.00', NULL, 'Art. 42 num. 30 CT', 80, 1, 'CT_ART_42_30', 3, 'Ej.: Me caso el 14 de junio en el Registro Civil de la av. Amazonas, a las 11:00. Solicito ese día y los dos siguientes.', 'Certificado de matrimonio o la constancia del turno en el Registro Civil.', 0, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (4, 'fallecimiento_familiar', 'Fallecimiento de familiar', NULL, 1, 1, 0, 1, 0, '3.00', NULL, 'Art. 42 num. 30 CT', 31, 1, 'CT_ART_42_30', 1, 'Ej.: Falleció mi padre el 8 de marzo en Ambato. Viajo hoy para el velorio y el sepelio, y regreso el 11 de marzo.', 'Certificado o acta de defunción. Si aún no lo tiene, entréguelo al reincorporarse.', 0, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (19, 'enfermedad_familiar', 'Enfermedad grave o accidente de familiar', 'Emergencia de salud de un familiar cercano que exige su presencia', 1, 1, 0, 1, 0, '3.00', NULL, NULL, 32, 1, 'CT_ART_42_30', 1, 'Ej.: Mi esposa sufrió un accidente de tránsito y está internada en el Hospital Vozandes. Debo acompañarla hoy y mañana porque no hay otro familiar en la ciudad.', 'Hoja de atención, certificado del hospital o parte policial del accidente.', 0, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (20, 'siniestro_domicilio', 'Siniestro en la vivienda', 'Incendio, inundación, robo u otro daño grave en su domicilio', 1, 1, 0, 1, 0, '2.00', NULL, NULL, 33, 1, 'CT_ART_42_30', 1, 'Ej.: Se rompió la tubería matriz y se inundó mi departamento en Carcelén. Debo estar presente para el plomero y el peritaje del seguro. Calculo el día completo.', 'Fotografías del daño y, según el caso, parte de bomberos, denuncia o informe del seguro.', 0, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (15, 'caso_fortuito', 'Caso fortuito o fuerza mayor', NULL, 0, 1, 0, 1, 0, NULL, NULL, 'Art. 30 Código Civil', 34, 1, 'CC_ART_30', 1, 'Ej.: Un deslave cerró la vía a Nono desde las 06:00 y no hay paso vehicular. Estoy retenido en el km 12 y adjunto la publicación del ECU-911. Llegaré apenas se habilite la vía.', 'Cualquier constancia del hecho: publicación oficial, parte policial o fotografía con fecha.', 0, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (3, 'calamidad_domestica', 'Otra calamidad doméstica', 'Hecho grave e imprevisto del hogar que no encaja en los anteriores', 1, 1, 0, 1, 0, '3.00', NULL, 'Art. 42 num. 30 CT', 39, 1, 'CT_ART_42_30', 1, 'Ej.: Mi hija de 8 años se quedó sola porque la persona que la cuida sufrió una emergencia y debo retirarla de la escuela en La Floresta a las 13:00. No tengo con quién dejarla el resto de la tarde.', 'Adjunte lo que documente el hecho. Si no existe documento, explique con el mayor detalle posible: es lo único con lo que contará quien decida.', 0, '1.0', '2.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (11, 'citacion_judicial', 'Citación judicial o notarial', NULL, 1, 1, 0, 1, 0, NULL, NULL, 'Art. 42 CT', 110, 1, 'COGEP_ART_53', 3, 'Ej.: Tengo citación de la Agencia Nacional de Tránsito para impugnar una multa que considero sin fundamento. La diligencia es a las 10:00 en la agencia de la av. Occidental. Voy en transporte público, así que calculo entre 1 y 2 horas fuera de la oficina.', 'La boleta de citación o notificación, y el documento del caso: la multa, el expediente o las fotografías que respalden su posición.', 1, '1.0', '3.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (10, 'tramite_gobierno', 'Trámite ante entidad pública', NULL, 1, 1, 0, 1, 0, '1.00', '8.00', 'Art. 42 CT', 100, 1, 'CT_ART_42', 3, 'Ej.: Debo renovar mi cédula en el Registro Civil del CCI. El turno es a las 08:00 del martes 5 y es el único disponible este mes. Calculo 2 horas.', 'El turno o la cita agendada, donde se lean la fecha, la hora y la institución.', 1, '1.0', '3.0')
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO permission_types (id, codigo, nombre, descripcion, requiere_adjunto, requiere_justificacion, requiere_firma, remunerado, descuenta_vacaciones, max_dias, max_horas, base_legal, orden, activo, legal_ref, category_id, guia_ejemplo, guia_adjuntos, admite_horas, horas_antes, horas_despues) VALUES (13, 'donacion_sangre', 'Donación de sangre', NULL, 1, 0, 0, 1, 0, '1.00', '4.00', 'Ley Orgánica de Salud', 130, 1, 'LOS_ART_79', 2, 'Ej.: Donaré sangre en la Cruz Roja de la av. Gran Colombia por un pedido para mi cuñado, internado en el Eugenio Espejo. Voy a las 09:00 y calculo regresar a las 12:00.', 'Comprobante de la donación emitido por la Cruz Roja o el banco de sangre. Puede entregarlo al volver.', 1, '0.5', '3.0')
  ON DUPLICATE KEY UPDATE id = id;

-- antiguedad_referencia: 16 fila(s)
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (1, 5, 15, 11, 4, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (6, 6, 16, 12, 4, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (7, 7, 17, 13, 4, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (8, 8, 18, 14, 4, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (9, 9, 19, 15, 4, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (10, 10, 20, 15, 5, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (11, 11, 21, 15, 6, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (12, 12, 22, 16, 6, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (13, 13, 23, 17, 6, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (14, 14, 24, 18, 6, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (15, 15, 25, 19, 6, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (16, 16, 26, 20, 6, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (17, 17, 27, 20, 7, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (18, 18, 28, 20, 8, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (19, 19, 29, 21, 8, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;
INSERT INTO antiguedad_referencia (anios_desde, anios_hasta, dias_gozar, dias_laborables, dias_no_laborables, nota) VALUES (20, NULL, 30, 22, 8, NULL)
  ON DUPLICATE KEY UPDATE anios_desde = anios_desde;

-- campos_ficha: 16 fila(s)
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('telefono', 'Teléfono personal', 'libre', 'Obligatorio: es como se le ubica si hay una urgencia con su solicitud.', 10)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('telefono_alternativo', 'Teléfono de emergencia', 'libre', 'De un familiar o allegado, para avisar si algo ocurre en la jornada.', 20)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('direccion', 'Dirección domiciliaria', 'libre', NULL, 30)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('ciudad', 'Ciudad', 'revisado', 'Define qué equipo de Talento Humano atiende sus solicitudes.', 40)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('foto_url', 'Foto de perfil', 'libre', NULL, 50)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('tipo_sangre', 'Tipo de sangre', 'libre', 'Útil en una emergencia. No se comparte con nadie fuera de Talento Humano.', 60)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('nombre', 'Nombre completo', 'revisado', 'Debe coincidir con su cédula: de aquí salen los documentos.', 80)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('estado_civil', 'Estado civil', 'revisado', NULL, 90)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('tiene_discapacidad', 'Discapacidad', 'revisado', 'Requiere carné del CONADIS para los permisos que la ley reconoce.', 100)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('cedula', 'Cédula', 'bloqueado', 'Identifica su expediente completo. Un error se corrige con Talento Humano.', 200)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('fecha_ingreso', 'Fecha de ingreso', 'bloqueado', 'De ella dependen sus días de vacaciones. La maneja Talento Humano.', 210)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('departamento', 'Área', 'bloqueado', NULL, 230)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('dias_vacaciones', 'Saldo de vacaciones', 'bloqueado', NULL, 250)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('email', 'Correo institucional', 'confirmado', 'Es donde llega su código de acceso. Lo cambia usted mismo: rige cuando abra el enlace que le enviamos a la dirección nueva.', 70)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('cargo', 'Cargo', 'revisado', 'Si el registrado no es el suyo, señale el correcto. Talento Humano lo confirma antes de que rija.', 220)
  ON DUPLICATE KEY UPDATE campo = campo;
INSERT INTO campos_ficha (campo, etiqueta, nivel, ayuda, orden) VALUES ('jefe_id', 'Jefe inmediato', 'revisado', 'Si el registrado no es el suyo, señale el correcto. Talento Humano lo confirma antes de que rija.', 240)
  ON DUPLICATE KEY UPDATE campo = campo;

-- lineamientos_solicitud: 7 fila(s)
INSERT INTO lineamientos_solicitud (id, ambito, texto, orden, activo, actualizado_en, actualizado_por) VALUES (1, 'vacacion', 'Se proponen 15 días, que es el período completo. La regla es tomarlo entero.', 10, 1, NULL, NULL)
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO lineamientos_solicitud (id, ambito, texto, orden, activo, actualizado_en, actualizado_por) VALUES (2, 'vacacion', 'Se comunican con 10 días de anticipación, para que su jefe organice la cobertura.', 20, 1, NULL, NULL)
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO lineamientos_solicitud (id, ambito, texto, orden, activo, actualizado_en, actualizado_por) VALUES (3, 'vacacion', 'Registrar una fecha no significa que estén aprobadas: deciden su jefe y Talento Humano.', 30, 1, NULL, NULL)
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO lineamientos_solicitud (id, ambito, texto, orden, activo, actualizado_en, actualizado_por) VALUES (4, 'vacacion', 'Los días son calendario: incluyen los fines de semana que caigan dentro.', 40, 1, NULL, NULL)
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO lineamientos_solicitud (id, ambito, texto, orden, activo, actualizado_en, actualizado_por) VALUES (5, 'vacacion', 'Para un asunto personal de un día, corresponde un permiso, no vacaciones.', 50, 1, NULL, NULL)
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO lineamientos_solicitud (id, ambito, texto, orden, activo, actualizado_en, actualizado_por) VALUES (6, 'permiso', 'Registrar el permiso no significa que esté aprobado: deciden su jefe y Talento Humano.', 10, 1, NULL, NULL)
  ON DUPLICATE KEY UPDATE id = id;
INSERT INTO lineamientos_solicitud (id, ambito, texto, orden, activo, actualizado_en, actualizado_por) VALUES (7, 'permiso', 'Si el permiso exige respaldo —un certificado médico, por ejemplo—, adjúntelo al pedirlo.', 20, 1, NULL, NULL)
  ON DUPLICATE KEY UPDATE id = id;

-- panel_bloques: 10 fila(s)
INSERT INTO panel_bloques (clave, titulo, descripcion, visible, orden, esencial, cuerpo, actualizado_en, actualizado_por) VALUES ('anuncio', 'Aviso de la empresa', 'Un mensaje que usted escribe y aparece arriba de todo. Sirve para comunicados cortos: cierre por feriado, plazo para pedir vacaciones, cambio de horario. Vacío, no se muestra.', 1, 5, 0, NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO panel_bloques (clave, titulo, descripcion, visible, orden, esencial, cuerpo, actualizado_en, actualizado_por) VALUES ('alertas', 'Avisos del sistema', 'Los que genera el sistema: días por vencer, solicitudes por corregir, datos por confirmar. Son de cada persona y no todos los ven.', 1, 10, 0, NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO panel_bloques (clave, titulo, descripcion, visible, orden, esencial, cuerpo, actualizado_en, actualizado_por) VALUES ('saldo', 'Días disponibles', 'La cifra grande de vacaciones con su explicación. Es la razón por la que la mayoría entra al sistema.', 1, 20, 1, NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO panel_bloques (clave, titulo, descripcion, visible, orden, esencial, cuerpo, actualizado_en, actualizado_por) VALUES ('antiguedad', 'Antigüedad', 'Años y meses en la empresa, y la fecha de ingreso.', 1, 30, 0, NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO panel_bloques (clave, titulo, descripcion, visible, orden, esencial, cuerpo, actualizado_en, actualizado_por) VALUES ('fines_semana', 'Fines de semana obligatorios', 'Cuántos fines de semana completos le faltan por consumir en su período de vacaciones.', 1, 40, 0, NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO panel_bloques (clave, titulo, descripcion, visible, orden, esencial, cuerpo, actualizado_en, actualizado_por) VALUES ('acciones', 'Botones para solicitar', 'Solicitar vacaciones y solicitar permiso. Sin esto nadie puede pedir nada desde el panel.', 1, 50, 1, NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO panel_bloques (clave, titulo, descripcion, visible, orden, esencial, cuerpo, actualizado_en, actualizado_por) VALUES ('calendario', 'Ausencias del equipo', 'El calendario de quién está fuera y cuándo. Útil para no dejar el puesto descubierto; puede reservarlo a jefatura si prefiere que no lo vea todo el personal.', 1, 60, 0, NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO panel_bloques (clave, titulo, descripcion, visible, orden, esencial, cuerpo, actualizado_en, actualizado_por) VALUES ('logros', 'Mis logros', 'Reconocimientos del colaborador. Se muestra solo a quien tiene alguno.', 1, 80, 0, NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO panel_bloques (clave, titulo, descripcion, visible, orden, esencial, cuerpo, actualizado_en, actualizado_por) VALUES ('solicitudes', 'Mis solicitudes', 'El historial propio con su estado. Es donde la persona sigue lo que pidió.', 1, 90, 1, NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO panel_bloques (clave, titulo, descripcion, visible, orden, esencial, cuerpo, actualizado_en, actualizado_por) VALUES ('papeles', 'Documentos para firmar', 'Los dos papeles de vacaciones que se imprimen, se firman a mano y se presentan en Talento Humano. Solo aparece a quien tenga alguno emitido.', 1, 85, 1, NULL, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;

-- tablero_bloques: 9 fila(s)
INSERT INTO tablero_bloques (clave, titulo, descripcion, pregunta, visible, orden, actualizado_en, actualizado_por) VALUES ('ausentes_hoy', 'Fuera hoy', 'Cuántas personas están hoy de vacaciones o con permiso aprobado. Es el número que decide si el turno se cubre.', '¿Cuánta gente falta hoy?', 1, 10, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO tablero_bloques (clave, titulo, descripcion, pregunta, visible, orden, actualizado_en, actualizado_por) VALUES ('activos', 'Colaboradores activos', 'La plantilla viva, con las altas y las bajas del año para saber si crece o se encoge.', '¿Cuántos somos?', 1, 20, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO tablero_bloques (clave, titulo, descripcion, pregunta, visible, orden, actualizado_en, actualizado_por) VALUES ('por_aprobar', 'Solicitudes por resolver', 'Lo que está esperando una decisión, y cuánto lleva esperando. Una solicitud sin resolver es alguien que no sabe si puede viajar.', '¿Qué está trabado?', 1, 30, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO tablero_bloques (clave, titulo, descripcion, pregunta, visible, orden, actualizado_en, actualizado_por) VALUES ('sin_jefe', 'Sin jefe asignado', 'Personas cuyo expediente no dice de quién dependen. Sus solicitudes no tienen a quién ir, y hay que resolverlas a mano.', '¿A quién le falta jefe?', 1, 40, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO tablero_bloques (clave, titulo, descripcion, pregunta, visible, orden, actualizado_en, actualizado_por) VALUES ('pasivo', 'Días acumulados sin gozar', 'Los días de vacaciones que la empresa debe. No caducan: el Art. 76 dice que se pagan, así que son dinero comprometido.', '¿Cuánto debemos en vacaciones?', 1, 50, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO tablero_bloques (clave, titulo, descripcion, pregunta, visible, orden, actualizado_en, actualizado_por) VALUES ('crecimiento', 'Altas y bajas por mes', 'Cómo se mueve la plantilla mes a mes. Sirve para ver si una bodega rota gente más rápido que las demás.', '¿Cómo cambia la plantilla?', 1, 60, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO tablero_bloques (clave, titulo, descripcion, pregunta, visible, orden, actualizado_en, actualizado_por) VALUES ('por_area', 'Reparto por área', 'Cuánta gente hay en cada departamento y cuántos días debe cada uno. Ordenado por lo que más pesa.', '¿Dónde está la gente?', 1, 70, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO tablero_bloques (clave, titulo, descripcion, pregunta, visible, orden, actualizado_en, actualizado_por) VALUES ('expedientes', 'Expedientes incompletos', 'Sin correo real, sin jefe o con el saldo descuadrado. Cada uno es un trámite que un día se va a trabar.', '¿Qué falta por completar?', 1, 80, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;
INSERT INTO tablero_bloques (clave, titulo, descripcion, pregunta, visible, orden, actualizado_en, actualizado_por) VALUES ('papeles', 'Papeles sin imprimir', 'Documentos emitidos que nadie imprimió todavía. Sin la copia firmada en el expediente, la solicitud consta registrada pero no verificada.', '¿Qué falta firmar?', 1, 90, NULL, NULL)
  ON DUPLICATE KEY UPDATE clave = clave;

