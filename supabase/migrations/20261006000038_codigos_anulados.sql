-- ---------------------------------------------------------------------------
-- 0038 · Separar «el código se usó» de «el código se anuló».
--
-- `auth_otp.consumido_en` servía para tres cosas distintas:
--
--   1. La persona entró con ese código.
--   2. Pidió otro, y el anterior se anuló —solo hay uno vigente a la vez—.
--   3. Agotó los cinco intentos de teclearlo.
--
-- Mientras solo se miraba «¿hay un código vigente?», daba igual. Deja de dar
-- igual al contar: el tope de códigos por hora quiere distinguir a quien pide
-- y usa —un ingreso normal— de quien pide una y otra vez sin usar ninguno,
-- que es la forma que tiene el abuso. Con los tres casos marcados igual, esa
-- diferencia no se puede ver.
--
-- EL SÍNTOMA: alguien que entra, cierra sesión y vuelve a entrar —probando,
-- cambiando de pantalla en el teléfono, compartiendo el equipo de garita—
-- llegaba al tope en minutos y quedaba una hora fuera. Y el mensaje,
-- «Demasiados intentos», sugería que había hecho algo mal.
--
-- Desde aquí: `consumido_en` significa UNA sola cosa —entró con él— y
-- `anulado_en` recoge las otras dos.
--
-- Idempotente.
-- ---------------------------------------------------------------------------

alter table public.auth_otp
  add column if not exists anulado_en timestamptz;

comment on column public.auth_otp.consumido_en is
  'Cuándo se usó para entrar. Nulo si nunca se usó.';
comment on column public.auth_otp.anulado_en is
  'Cuándo dejó de servir sin haberse usado: lo reemplazó uno nuevo, o se agotaron los intentos.';

-- Un código deja de estar vigente por cualquiera de las dos vías.
-- (Nombre propio: `idx_auth_otp_vigente` ya existe desde el esquema inicial
--  con otra condición, y `create index if not exists` lo habría dado por
--  bueno sin crear este, que es el que hace falta.)
create index if not exists idx_auth_otp_sin_anular
  on public.auth_otp (cedula, created_at desc)
  where consumido_en is null and anulado_en is null;

-- Para contar rápido lo que el tope mira: lo pedido desde el último ingreso.
create index if not exists idx_auth_otp_consumidos
  on public.auth_otp (cedula, consumido_en desc)
  where consumido_en is not null;


-- =========================================================================
-- Cuántos códigos lleva pedidos sin entrar
--
-- Se cuenta desde su último ingreso, no desde hace una hora: entrar deja la
-- cuenta en cero, que es lo que distingue a quien usa el sistema de quien lo
-- está tanteando. Dentro de la ventana de una hora, siempre.
-- =========================================================================

create or replace function public.codigos_sin_usar(p_cedula text, p_ip inet default null)
returns table (por_cedula bigint, por_ip bigint)
language sql
stable
security definer
set search_path = public
as $$
  with ultimo_ingreso as (
    select max(consumido_en) as cuando
      from public.auth_otp
     where cedula = p_cedula and consumido_en is not null
  ),
  ultimo_desde_la_red as (
    select max(consumido_en) as cuando
      from public.auth_otp
     where p_ip is not null and ip = p_ip and consumido_en is not null
  )
  select
    count(*) filter (
      where o.cedula = p_cedula
        and o.consumido_en is null
        and o.created_at > coalesce((select cuando from ultimo_ingreso), '-infinity')
    ) as por_cedula,
    count(*) filter (
      where p_ip is not null and o.ip = p_ip
        and o.consumido_en is null
        and o.created_at > coalesce((select cuando from ultimo_desde_la_red), '-infinity')
    ) as por_ip
  from public.auth_otp o
  where o.created_at > now() - interval '1 hour';
$$;

comment on function public.codigos_sin_usar(text, inet) is
  'Códigos pedidos y no usados desde el último ingreso, dentro de la última hora. Entrar deja la cuenta en cero.';
