-- =====================================================================
--  ¿Qué migraciones están aplicadas?
--  Ejecute esto ANTES de los smoke tests para saber qué le falta.
-- =====================================================================
select
  m.migracion,
  m.objeto_clave,
  case when to_regclass(m.objeto_clave) is not null
         or exists (select 1 from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                     where n.nspname = 'public' and p.proname = m.objeto_clave)
       then '✅ aplicada' else '❌ FALTA' end as estado,
  m.contiene
from (values
  ('0001_init_schema',        'public.requests',          'tablas base, RLS, triggers, Realtime'),
  ('0002_reglas_ecuador',     'public.vacation_periods',  'antigüedad, fines de semana, permisos, firmas'),
  ('0003_storage',            'request_attachments',      'adjuntos (los buckets solo existen en Supabase)'),
  ('0004_normativa',          'public.notifications',     'glosario legal, alertas, cargas familiares, LOPDP')
) as m(migracion, objeto_clave, contiene)
order by m.migracion;
