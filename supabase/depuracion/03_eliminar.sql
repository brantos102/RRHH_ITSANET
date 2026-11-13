-- ===========================================================================
-- 03 · ELIMINAR FILAS
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
--   users                  Arrastra 17 tablas, 19 con las que cuelgan de
--                          las solicitudes. Se desactiva (ver A.6 de
--                          02_corregir.sql).
--   audit_logs             Es la prueba de quién hizo qué. Hay un disparador
--   access_logs            que lo impide... salvo si usted entró como
--                          `postgres`, que es justo lo que va a hacer en
--                          DBeaver. La protección no lo va a salvar: piénselo
--                          usted.
--   data_consents          La LOPDP obliga a poder demostrar el
--   data_subject_requests  consentimiento y su ejercicio.
--   requests aprobadas     Son el respaldo de una ausencia que ya ocurrió.
--                          Se anulan, no se borran.
--
-- Si de verdad hace falta purgar bitácoras por retención, hágalo por rango de
-- fechas y con un respaldo hecho el mismo día. No por «limpiar».


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
begin;

-- Ver qué se va a borrar, con la fila de la hoja de la que salió.
select h.id, u.cedula, u.nombre, h.fecha_inicio, h.fecha_fin, h.dias,
       h.fila_origen, h.cargado_en
  from public.vacaciones_historicas h
  join public.users u on u.id = h.user_id
 where h.id in (<<<123, 456>>>);

delete from public.vacaciones_historicas
 where id in (<<<123, 456>>>);

rollback;


-- ---------------------------------------------------------------------------
-- B.2 Borrar TODO el historial de una persona y volver a cargarlo
--
-- Cuando su nombre estaba mal escrito y se corrigió, o cuando la hoja cambió.
-- Después hay que volver a correr el guion de carga.
-- ---------------------------------------------------------------------------
begin;

select count(*) as se_van_a_borrar, sum(dias) as dias
  from public.vacaciones_historicas
 where user_id = (select id from public.users where cedula = '<<<0000000000>>>');

delete from public.vacaciones_historicas
 where user_id = (select id from public.users where cedula = '<<<0000000000>>>');

rollback;

-- Y después, desde PowerShell:
--   python scripts\cargar_historial.py ..\REGISTRO_DE_VACACIONE.xlsx --aplicar


-- ---------------------------------------------------------------------------
-- B.3 Las repetidas del 1.7, dejando una de cada
--
-- Se queda la de identificador más bajo, que es la que entró primero.
-- ---------------------------------------------------------------------------
begin;

with repetidas as (
  select id,
         row_number() over (partition by user_id, fecha_inicio, fecha_fin, dias
                            order by id) as n
    from public.vacaciones_historicas
)
select count(*) as sobrantes from repetidas where n > 1;

with repetidas as (
  select id,
         row_number() over (partition by user_id, fecha_inicio, fecha_fin, dias
                            order by id) as n
    from public.vacaciones_historicas
)
delete from public.vacaciones_historicas
 where id in (select id from repetidas where n > 1);

rollback;


-- ---------------------------------------------------------------------------
-- B.4 Solicitudes de prueba
--
-- ARRASTRA, y en cascada: adjuntos, firmas y ajustes de esa solicitud se van
-- con ella. La bitácora de accesos NO se borra: se queda apuntando a nada,
-- que es lo correcto —el guardia sí vio salir a alguien—.
--
-- Solo para lo que de verdad sea de prueba. Una solicitud real no se borra:
-- se cancela.
-- ---------------------------------------------------------------------------
begin;

select r.folio, u.nombre, r.tipo, r.estado, r.fecha_inicio, r.descripcion,
       (select count(*) from public.request_attachments a where a.request_id = r.id) as adjuntos,
       (select count(*) from public.request_signatures s where s.request_id = r.id) as firmas
  from public.requests r
  join public.users u on u.id = r.user_id
 where r.descripcion ilike '%<<<comprobacion automatica>>>%';

delete from public.requests
 where descripcion ilike '%<<<comprobacion automatica>>>%';

-- El saldo se devuelve solo al borrar una solicitud aprobada, pero conviene
-- comprobarlo.
select public.recalcular_saldos();

rollback;


-- ---------------------------------------------------------------------------
-- B.5 Una solicitud real: se cancela, no se borra
-- ---------------------------------------------------------------------------
begin;

update public.requests
   set estado = 'cancelado'
 where folio = <<<1234>>>;

select folio, estado, dias_solicitados from public.requests where folio = <<<1234>>>;

rollback;


-- ---------------------------------------------------------------------------
-- B.6 Personal temporal
--
-- ARRASTRA sus jornadas. Si las jornadas ya se pagaron, no lo borre:
-- desactívelo, y el registro de lo trabajado queda para sustentarlo.
-- ---------------------------------------------------------------------------
begin;

select t.cedula, t.nombre,
       (select count(*) from public.jornadas_temporales j where j.temporal_id = t.id) as jornadas
  from public.personal_temporal t
 where t.cedula = '<<<0000000000>>>';

-- Lo recomendable:
update public.personal_temporal set activo = false
 where cedula = '<<<0000000000>>>';

-- Solo si de verdad se registró por error y no tiene jornadas pagadas:
-- delete from public.personal_temporal where cedula = '<<<0000000000>>>';

rollback;


-- ---------------------------------------------------------------------------
-- B.7 Conversaciones del chat
--
-- ARRASTRA sus mensajes. Se pueden cerrar en vez de borrar.
-- ---------------------------------------------------------------------------
begin;

update public.conversaciones
   set estado = 'cerrada', cerrada_en = now()
 where id = '<<<UUID>>>';

rollback;


-- ---------------------------------------------------------------------------
-- B.8 Códigos de acceso viejos
--
-- Esto sí se puede limpiar sin pensarlo: son códigos de un solo uso ya
-- consumidos o vencidos. No los mira nadie.
-- ---------------------------------------------------------------------------
begin;

select count(*) as codigos_viejos from public.auth_otp
 where expira_en < now() - interval '7 days';

delete from public.auth_otp
 where expira_en < now() - interval '7 days';

rollback;


-- ---------------------------------------------------------------------------
-- B.9 Avisos leídos y vencidos
-- ---------------------------------------------------------------------------
begin;

delete from public.notifications
 where leida_en is not null
   and leida_en < now() - interval '90 days';

rollback;


-- ===========================================================================
-- C. QUÉ ARRASTRA CADA BORRADO, TABLA POR TABLA
--
-- Lo dice la propia base. Corra esto cuando dude de un DELETE que va a
-- escribir: es más fiable que cualquier lista que yo le deje aquí, porque
-- sale del esquema tal como está hoy.
-- ===========================================================================
select c.confrelid::regclass::text                       as si_borra_de,
       c.conrelid::regclass::text                        as se_afecta,
       a.attname                                         as por_la_columna,
       case c.confdeltype
         when 'c' then 'SE BORRA EN CASCADE'
         when 'n' then 'se queda, pierde la referencia'
         when 'd' then 'se queda, toma el valor por defecto'
         else          'BLOQUEA el borrado'
       end                                               as consecuencia
  from pg_constraint c
  join pg_attribute a on a.attrelid = c.conrelid and a.attnum = c.conkey[1]
 where c.contype = 'f' and c.connamespace = 'public'::regnamespace
 order by case c.confdeltype when 'c' then 1 when 'a' then 2 when 'r' then 2 else 3 end,
          1, 2;


-- ===========================================================================
-- D. ANTES DE CONFIRMAR CUALQUIER BORRADO MASIVO
--
-- Cuente lo que va a quedar, no lo que va a irse. Es la comprobación que
-- atrapa el WHERE mal escrito.
-- ===========================================================================
select 'personas activas'      as tabla, count(*) from public.users where activo
union all select 'solicitudes',          count(*) from public.requests
union all select 'vacaciones históricas', count(*) from public.vacaciones_historicas
union all select 'períodos',              count(*) from public.vacation_periods
union all select 'jornadas temporales',   count(*) from public.jornadas_temporales
order by 1;
