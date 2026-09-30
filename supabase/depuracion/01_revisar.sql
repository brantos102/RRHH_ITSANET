-- ===========================================================================
-- 01 · MIRAR SIN TOCAR
--
-- Todo aquí es SELECT. Ninguna de estas consultas cambia nada, así que se
-- pueden correr con confianza y a cualquier hora.
--
-- Empiece por aquí siempre. La mitad de lo que uno cree que hay que corregir
-- resulta estar bien, y la otra mitad no es lo que parecía.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- 1.1 El estado general, de un vistazo
-- ---------------------------------------------------------------------------
select 'personas activas'            as concepto, count(*)::text as valor from public.users where activo
union all select 'personas inactivas',           count(*)::text from public.users where not activo
union all select 'sin correo registrado',        count(*)::text from public.users where activo and email is null
union all select 'sin jefe asignado',            count(*)::text from public.users where activo and jefe_id is null and rol = 'empleado'
union all select 'sin fecha de nacimiento',      count(*)::text from public.users where activo and fecha_nacimiento is null
union all select 'solicitudes en trámite',       count(*)::text from public.requests where estado in ('pendiente_jefe','pendiente_rrhh')
union all select 'vacaciones históricas',        count(*)::text from public.vacaciones_historicas
union all select 'saldo total de la planilla',   round(coalesce(sum(dias_vacaciones),0),2)::text from public.users where activo
order by 1;


-- ---------------------------------------------------------------------------
-- 1.2 Quién NO PUEDE ENTRAR al sistema
--
-- Sin correo no llega el código de acceso. El camino alterno es «primer
-- ingreso», que pide la fecha de nacimiento y la de ingreso: a quien le falte
-- una de las dos no le queda ninguna puerta, y la pantalla no se lo dice.
-- ---------------------------------------------------------------------------
select cedula, nombre, departamento, motivo, que_hacer
  from public.v_sin_entrada
 order by (motivo like 'Faltan%' or motivo like 'Falta%') desc, nombre;


-- ---------------------------------------------------------------------------
-- 1.3 Cédulas que no pasan el dígito verificador
--
-- La base valida la cédula al insertar, pero los datos que entraron por carga
-- masiva pueden haber esquivado esa comprobación. Una cédula mal escrita
-- impide entrar y no se nota hasta que la persona lo intenta.
-- ---------------------------------------------------------------------------
select cedula, nombre, activo
  from public.users
 where not public.es_cedula_valida(cedula)
 order by activo desc, nombre;


-- ---------------------------------------------------------------------------
-- 1.4 Nombres sospechosos de estar mal escritos
--
-- Dobles espacios, espacios al inicio o al final, minúsculas sueltas. Nada de
-- esto rompe el sistema, pero sí rompe el emparejamiento con la hoja de
-- Talento Humano, que se hace por nombre exacto.
-- ---------------------------------------------------------------------------
select cedula, nombre, '['||nombre||']' as con_bordes,
       case when nombre <> btrim(nombre)              then 'espacios en los bordes'
            when nombre like '%  %'                   then 'dobles espacios'
            when nombre <> upper(nombre) and nombre <> initcap(nombre) then 'mayúsculas mezcladas'
            else 'revisar' end as problema
  from public.users
 where activo
   and (nombre <> btrim(nombre) or nombre like '%  %'
        or nombre ~ '[0-9]' or length(btrim(nombre)) < 6)
 order by nombre;


-- ---------------------------------------------------------------------------
-- 1.5 Saldos que no cuadran con sus períodos
--
-- `users.dias_vacaciones` tiene que ser la suma de los saldos no caducados.
-- Si aquí sale algo, es que alguien editó el número a mano o que un proceso
-- quedó a medias. Se arregla con `recalcular_saldos`, no con un UPDATE.
-- ---------------------------------------------------------------------------
select u.cedula, u.nombre,
       u.dias_vacaciones                              as saldo_guardado,
       coalesce(sum(p.dias_saldo) filter (where not p.caducado), 0) as saldo_real,
       round(u.dias_vacaciones - coalesce(sum(p.dias_saldo) filter (where not p.caducado), 0), 2) as diferencia
  from public.users u
  left join public.vacation_periods p on p.user_id = u.id
 where u.activo
 group by u.id, u.cedula, u.nombre, u.dias_vacaciones
having abs(u.dias_vacaciones - coalesce(sum(p.dias_saldo) filter (where not p.caducado), 0)) > 0.005
 order by abs(u.dias_vacaciones - coalesce(sum(p.dias_saldo) filter (where not p.caducado), 0)) desc;


-- ---------------------------------------------------------------------------
-- 1.6 Personas sin períodos de vacaciones generados
--
-- Sin períodos no hay saldo, y el panel les muestra cero. Pasa cuando alguien
-- se dio de alta directamente en la base en vez de por el sistema.
-- ---------------------------------------------------------------------------
select u.cedula, u.nombre, u.fecha_ingreso,
       public.anios_cumplidos(u.fecha_ingreso) as anios_cumplidos
  from public.users u
 where u.activo
   and not exists (select 1 from public.vacation_periods p where p.user_id = u.id)
 order by u.fecha_ingreso;


-- ---------------------------------------------------------------------------
-- 1.7 Vacaciones históricas repetidas
--
-- Misma persona y mismas fechas, cargadas dos veces. La carga las evita, pero
-- si la hoja trae la fila duplicada y alguien la corrige y vuelve a cargar,
-- pueden aparecer.
-- ---------------------------------------------------------------------------
select u.cedula, u.nombre, h.fecha_inicio, h.fecha_fin, h.dias,
       count(*) as veces, array_agg(h.id order by h.id) as ids,
       array_agg(h.fila_origen order by h.id) as filas_de_la_hoja
  from public.vacaciones_historicas h
  join public.users u on u.id = h.user_id
 group by u.cedula, u.nombre, h.fecha_inicio, h.fecha_fin, h.dias
having count(*) > 1
 order by u.nombre, h.fecha_inicio;


-- ---------------------------------------------------------------------------
-- 1.8 Vacaciones históricas imposibles
--
-- Antes de la fecha de ingreso, en el futuro, o de más días de los que caben
-- entre las dos fechas. Casi siempre es un error de tecleo en la hoja.
-- ---------------------------------------------------------------------------
select u.cedula, u.nombre, u.fecha_ingreso,
       h.id, h.fecha_inicio, h.fecha_fin, h.dias, h.fila_origen,
       case when h.fecha_inicio < u.fecha_ingreso then 'anterior a su ingreso'
            when h.fecha_inicio > current_date    then 'en el futuro'
            when h.dias > (h.fecha_fin - h.fecha_inicio + 1) then 'más días que fechas'
            when h.dias <= 0 then 'días cero o negativos'
       end as problema
  from public.vacaciones_historicas h
  join public.users u on u.id = h.user_id
 where h.fecha_inicio < u.fecha_ingreso
    or h.fecha_inicio > current_date
    or h.dias > (h.fecha_fin - h.fecha_inicio + 1)
    or h.dias <= 0
 order by u.nombre, h.fecha_inicio;


-- ---------------------------------------------------------------------------
-- 1.9 Jerarquía rota
--
-- Quien es su propio jefe, y quien reporta a alguien inactivo. Lo segundo
-- deja sus solicitudes sin quien las autorice.
-- ---------------------------------------------------------------------------
select u.cedula, u.nombre, j.nombre as jefe, j.activo as jefe_activo,
       case when u.jefe_id = u.id then 'es su propio jefe'
            when not j.activo     then 'su jefe está inactivo'
       end as problema
  from public.users u
  join public.users j on j.id = u.jefe_id
 where u.activo and (u.jefe_id = u.id or not j.activo)
 order by u.nombre;


-- ---------------------------------------------------------------------------
-- 1.10 Solicitudes atascadas
--
-- En trámite desde hace más de treinta días. O se olvidaron, o esperan a
-- alguien que ya no está.
-- ---------------------------------------------------------------------------
select r.folio, u.nombre, r.tipo, r.estado, r.fecha_inicio, r.fecha_fin,
       (current_date - r.created_at::date) as dias_esperando,
       j.nombre as jefe, j.activo as jefe_activo
  from public.requests r
  join public.users u on u.id = r.user_id
  left join public.users j on j.id = r.jefe_id
 where r.estado in ('pendiente_jefe', 'pendiente_rrhh')
   and r.created_at < now() - interval '30 days'
 order by r.created_at;


-- ---------------------------------------------------------------------------
-- 1.11 Jornadas de personal temporal sin salida
--
-- Una jornada sin cerrar no se puede pagar. El sistema las señala y no las
-- inventa: la salida la registra Talento Humano con la hora que corresponda.
-- ---------------------------------------------------------------------------
select t.cedula, t.nombre, j.fecha, j.entrada_en,
       (current_date - j.fecha) as dias_abierta
  from public.jornadas_temporales j
  join public.personal_temporal t on t.id = j.temporal_id
 where j.salida_en is null
 order by j.fecha;


-- ---------------------------------------------------------------------------
-- 1.12 Cuánto pesa cada tabla
--
-- Para saber dónde está el volumen antes de cualquier limpieza.
-- ---------------------------------------------------------------------------
select c.relname as tabla,
       to_char(c.reltuples::bigint, 'FM999G999G999') as filas_aprox,
       pg_size_pretty(pg_total_relation_size(c.oid)) as tamano
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r'
 order by pg_total_relation_size(c.oid) desc;
