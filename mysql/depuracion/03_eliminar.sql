-- ===========================================================================
-- 03 · ELIMINAR FILAS (MySQL)
--
-- Lo que se borra no vuelve. Este archivo dice, para cada tabla, qué se lleva
-- por delante cada DELETE y cuál es la alternativa cuando la hay.
--
-- La regla que resume todo lo demás: EN ESTE SISTEMA CASI NADA SE BORRA. Una
-- solicitud anulada queda anulada, una persona que se va queda inactiva, y
-- una bitácora no se toca. Un dato que se esfuma es un dato que nadie puede
-- auditar, y eso frente a una inspección vale menos que no haberlo tenido.
-- ===========================================================================


-- ===========================================================================
-- A. LO QUE NUNCA SE BORRA
-- ===========================================================================
--
--   users                  Arrastra en cascada todo su expediente. Se
--                          desactiva (ver A.6 de 02_corregir.sql).
--   audit_logs             Es la prueba de quién hizo qué. Un disparador lo
--   access_logs            impide con cualquier usuario, también con root.
--   data_consents          La LOPDP obliga a poder demostrar el
--   data_subject_requests  consentimiento y su ejercicio.
--   requests aprobadas     Son el respaldo de una ausencia que ya ocurrió.
--                          Se anulan, no se borran.
--
-- Si de verdad hace falta purgar bitácoras por retención, lo hace la tarea
-- de retención del sistema, que deja constancia. No por «limpiar».


-- ===========================================================================
-- B. LO QUE SÍ SE PUEDE BORRAR, Y CÓMO
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- B.1 Vacaciones históricas cargadas mal
--
-- Es lo más habitual: una fila de la hoja que estaba equivocada. No arrastra
-- nada —ninguna tabla depende de `vacaciones_historicas`— y tampoco toca el
-- saldo, que viene de `vacation_periods`.
--
-- Cada fila guarda su número de fila en la hoja (`fila_origen`), así que se
-- puede cotejar con el archivo antes de borrar.
-- ---------------------------------------------------------------------------
start transaction;

-- Ver qué se va a borrar, con la fila de la hoja de la que salió.
select h.id, u.cedula, u.nombre, h.fecha_inicio, h.fecha_fin, h.dias,
       h.fila_origen, h.cargado_en
  from vacaciones_historicas h
  join users u on u.id = h.user_id
 where h.id in (<<<123, 456>>>);

delete from vacaciones_historicas
 where id in (<<<123, 456>>>);

rollback;


-- ---------------------------------------------------------------------------
-- B.2 Borrar TODO el historial de una persona y volver a cargarlo
--
-- Cuando su nombre estaba mal escrito y se corrigió, o cuando la hoja cambió.
-- Después hay que volver a correr el guion de carga.
-- ---------------------------------------------------------------------------
start transaction;

select count(*) as se_van_a_borrar, sum(h.dias) as dias
  from vacaciones_historicas h
  join users u on u.id = h.user_id
 where u.cedula = '<<<0000000000>>>';

delete h from vacaciones_historicas h
  join users u on u.id = h.user_id
 where u.cedula = '<<<0000000000>>>';

rollback;


-- ---------------------------------------------------------------------------
-- B.3 Las repetidas del 1.7, dejando una de cada
--
-- Se queda la de identificador más bajo, que es la que entró primero.
-- EN MYSQL la lista de repetidas va en una subconsulta derivada: MySQL no
-- deja borrar de una tabla leyendo la misma tabla directamente (error 1093).
-- ---------------------------------------------------------------------------
start transaction;

select count(*) as sobrantes
  from (select row_number() over (partition by user_id, fecha_inicio, fecha_fin, dias
                                  order by id) as n
          from vacaciones_historicas) r
 where r.n > 1;

delete from vacaciones_historicas
 where id in (select id from (
         select id, row_number() over (partition by user_id, fecha_inicio, fecha_fin, dias
                                       order by id) as n
           from vacaciones_historicas) r
        where r.n > 1);

rollback;


-- ---------------------------------------------------------------------------
-- B.4 Solicitudes de prueba
--
-- ARRASTRA, y en cascada: adjuntos, firmas y ajustes de esa solicitud se van
-- con ella. La bitácora de accesos NO se borra: se queda apuntando a nada,
-- que es lo correcto —el guardia sí vio salir a alguien—.
--
-- EN MYSQL, borrar una solicitud aprobada NO devuelve los días: el saldo
-- se devuelve al CANCELARLA. Por eso primero se cancela y después se borra.
--
-- Solo para lo que de verdad sea de prueba. Una solicitud real no se borra:
-- se cancela (B.5).
-- ---------------------------------------------------------------------------
start transaction;

select r.folio, u.nombre, r.tipo, r.estado, r.fecha_inicio, r.descripcion,
       (select count(*) from request_attachments a where a.request_id = r.id) as adjuntos,
       (select count(*) from request_signatures s where s.request_id = r.id) as firmas
  from requests r
  join users u on u.id = r.user_id
 where r.descripcion like '%<<<comprobacion automatica>>>%';

-- 1. Cancelar lo aprobado: devuelve los días.
update requests
   set estado = 'cancelado'
 where estado in ('aprobado', 'pendiente_anulacion')
   and descripcion like '%<<<comprobacion automatica>>>%';

-- 2. Borrar.
delete from requests
 where descripcion like '%<<<comprobacion automatica>>>%';

rollback;


-- ---------------------------------------------------------------------------
-- B.5 Una solicitud real: se cancela, no se borra
-- ---------------------------------------------------------------------------
start transaction;

update requests
   set estado = 'cancelado'
 where folio = <<<1234>>>;

select folio, estado, dias_solicitados from requests where folio = <<<1234>>>;

rollback;


-- ---------------------------------------------------------------------------
-- B.6 Personal temporal
--
-- ARRASTRA sus jornadas. Si las jornadas ya se pagaron, no lo borre:
-- desactívelo, y el registro de lo trabajado queda para sustentarlo.
-- ---------------------------------------------------------------------------
start transaction;

select t.cedula, t.nombre,
       (select count(*) from jornadas_temporales j where j.temporal_id = t.id) as jornadas
  from personal_temporal t
 where t.cedula = '<<<0000000000>>>';

-- Lo recomendable:
update personal_temporal set activo = false
 where cedula = '<<<0000000000>>>';

-- Solo si de verdad se registró por error y no tiene jornadas pagadas:
-- delete from personal_temporal where cedula = '<<<0000000000>>>';

rollback;


-- ---------------------------------------------------------------------------
-- B.7 Conversaciones del chat
--
-- ARRASTRA sus mensajes. Se pueden cerrar en vez de borrar.
-- ---------------------------------------------------------------------------
start transaction;

update conversaciones
   set estado = 'cerrada', cerrada_en = now(6)
 where id = '<<<UUID>>>';

rollback;


-- ---------------------------------------------------------------------------
-- B.8 Códigos de acceso viejos
--
-- Esto sí se puede limpiar sin pensarlo: son códigos de un solo uso ya
-- consumidos o vencidos. No los mira nadie.
-- ---------------------------------------------------------------------------
start transaction;

select count(*) as codigos_viejos from auth_otp
 where expira_en < now() - interval 7 day;

delete from auth_otp
 where expira_en < now() - interval 7 day;

rollback;


-- ---------------------------------------------------------------------------
-- B.9 Avisos leídos y vencidos
-- ---------------------------------------------------------------------------
start transaction;

delete from notifications
 where leida_en is not null
   and leida_en < now() - interval 90 day;

rollback;


-- ===========================================================================
-- C. QUÉ ARRASTRA CADA BORRADO, TABLA POR TABLA
--
-- Lo dice la propia base. Corra esto cuando dude de un DELETE que va a
-- escribir: es más fiable que cualquier lista, porque sale del esquema tal
-- como está hoy.
-- ===========================================================================
select rc.referenced_table_name                          as si_borra_de,
       rc.table_name                                     as se_afecta,
       k.column_name                                     as por_la_columna,
       case rc.delete_rule
         when 'CASCADE'     then 'SE BORRA EN CASCADA'
         when 'SET NULL'    then 'se queda, pierde la referencia'
         when 'SET DEFAULT' then 'se queda, toma el valor por defecto'
         else                    'BLOQUEA el borrado'
       end                                               as consecuencia
  from information_schema.referential_constraints rc
  join information_schema.key_column_usage k
    on k.constraint_schema = rc.constraint_schema
   and k.constraint_name   = rc.constraint_name
   and k.table_name        = rc.table_name
   and k.ordinal_position  = 1
 where rc.constraint_schema = database()
 order by case rc.delete_rule when 'CASCADE' then 1 when 'RESTRICT' then 2
                              when 'NO ACTION' then 2 else 3 end,
          1, 2;


-- ===========================================================================
-- D. ANTES DE CONFIRMAR CUALQUIER BORRADO MASIVO
--
-- Cuente lo que va a quedar, no lo que va a irse. Es la comprobación que
-- atrapa el WHERE mal escrito.
-- ===========================================================================
select 'personas activas'      as tabla, count(*) as filas from users where activo
union all select 'solicitudes',          count(*) from requests
union all select 'vacaciones históricas', count(*) from vacaciones_historicas
union all select 'períodos',              count(*) from vacation_periods
union all select 'jornadas temporales',   count(*) from jornadas_temporales
order by 1;
