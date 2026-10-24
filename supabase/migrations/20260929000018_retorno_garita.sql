-- ============================================================================
-- 0018 · Cuándo volvió de verdad quien salió con permiso
-- ============================================================================
-- El tipo de acceso `retorno_empleado` existía desde la primera migración,
-- pero nadie lo escribía nunca: garita solo registraba la salida. De un
-- permiso de 12:00 a 15:00 quedaba constancia de que la persona salió, y
-- ninguna de si volvió a las 15:00, a las 17:00 o al día siguiente.
--
-- Ahora el mismo código QR leído por segunda vez registra el retorno. Es el
-- gesto que el guardia ya hace —pasar el código— sin pantalla nueva ni
-- procedimiento que memorizar.
--
-- Sobre medir el retraso: solo tiene sentido en los permisos por horas, donde
-- hay una hora de regreso declarada. En una ausencia de días completos no se
-- sabe a qué hora empieza el turno de esa persona, así que llamar «tarde» a
-- quien vuelve a las 08:00 del día siguiente sería inventarse un dato. Ahí se
-- cuentan días enteros de más, que sí es verificable.
--
-- Idempotente: se puede volver a ejecutar sin efectos.

alter table public.requests
  add column if not exists retorno_en             timestamptz,
  add column if not exists retorno_exceso_minutos integer,
  add column if not exists retorno_exceso_dias    integer,
  add column if not exists retorno_guardia        uuid references public.users(id);

comment on column public.requests.retorno_en is
  'Momento real en que la persona volvió, registrado por garita al leer su QR por segunda vez.';
comment on column public.requests.retorno_exceso_minutos is
  'Minutos de más sobre la hora declarada. Solo en permisos por horas; negativo si volvió antes.';
comment on column public.requests.retorno_exceso_dias is
  'Días enteros de más. Solo en ausencias de días completos.';

create index if not exists requests_retorno_idx
  on public.requests (retorno_en desc) where retorno_en is not null;

-- ------------------------------------------------------- registrar el retorno
create or replace function public.registrar_retorno(
  p_request_id uuid,
  p_guardia_id uuid,
  p_ip         inet    default null,
  p_agente     text    default null
) returns jsonb
language plpgsql
security definer
set search_path = public
as $ret$
declare
  v_sol      public.requests;
  v_usuario  public.users;
  v_rol      public.user_role;
  v_salida   timestamptz;
  v_esperado timestamptz;
  v_ahora    timestamptz := now();
  v_min      integer;
  v_dias     integer;
  v_por_horas boolean;
begin
  select rol into v_rol from public.users where id = p_guardia_id;
  if v_rol not in ('guardia', 'rrhh', 'admin') then
    raise exception 'Solo garita o Talento Humano registran el retorno';
  end if;

  select * into v_sol from public.requests where id = p_request_id for update;
  if not found then
    raise exception 'La solicitud no existe';
  end if;
  if v_sol.estado <> 'aprobado' then
    raise exception 'La solicitud no está aprobada (está en %)', v_sol.estado;
  end if;

  -- Sin salida previa no hay retorno que registrar: sería anotar que volvió
  -- alguien que nunca se fue.
  select created_at into v_salida
    from public.access_logs
   where request_id = p_request_id and tipo_acceso = 'salida_empleado' and autorizado
   order by created_at limit 1;
  if v_salida is null then
    raise exception 'No hay salida registrada para esta autorización: primero se registra la salida';
  end if;

  if v_sol.retorno_en is not null then
    raise exception 'El retorno ya quedó registrado el %',
      to_char(v_sol.retorno_en, 'DD/MM/YYYY HH24:MI');
  end if;

  select * into v_usuario from public.users where id = v_sol.user_id;

  v_por_horas := v_sol.hora_fin is not null and v_sol.fecha_inicio = v_sol.fecha_fin;

  if v_por_horas then
    v_esperado := (v_sol.fecha_fin + v_sol.hora_fin)::timestamptz;
    v_min  := round(extract(epoch from (v_ahora - v_esperado)) / 60.0);
    v_dias := null;
  else
    -- Se esperaba de vuelta el día siguiente al último de ausencia.
    v_esperado := (v_sol.fecha_fin + 1)::timestamptz;
    v_min  := null;
    v_dias := greatest(v_ahora::date - (v_sol.fecha_fin + 1), 0);
  end if;

  update public.requests set
    retorno_en             = v_ahora,
    retorno_exceso_minutos = v_min,
    retorno_exceso_dias    = v_dias,
    retorno_guardia        = p_guardia_id,
    updated_at             = now()
  where id = p_request_id;

  insert into public.access_logs
    (user_id, cedula, request_id, tipo_acceso, autorizado, guardia_id, ip, user_agent, metadata)
  values
    (v_sol.user_id, v_usuario.cedula, p_request_id, 'retorno_empleado', true,
     p_guardia_id, p_ip, p_agente,
     jsonb_build_object('esperado', v_esperado, 'exceso_minutos', v_min,
                        'exceso_dias', v_dias));

  return jsonb_build_object(
    'folio',           v_sol.folio,
    'nombre',          v_usuario.nombre,
    'cedula',          v_usuario.cedula,
    'salio',           v_salida,
    'volvio',          v_ahora,
    'esperado',        v_esperado,
    'por_horas',       v_por_horas,
    'exceso_minutos',  v_min,
    'exceso_dias',     v_dias,
    'a_tiempo',        coalesce(v_min, 0) <= 0 and coalesce(v_dias, 0) = 0
  );
end;
$ret$;

comment on function public.registrar_retorno(uuid, uuid, inet, text) is
  'Anota el retorno real de quien salió con permiso y lo compara con lo declarado.';

-- ------------------------------------------------------------- para informes
create or replace view public.v_retornos as
select r.id as request_id, r.folio, u.cedula, u.nombre, u.departamento, u.cargo,
       j.nombre as jefe,
       r.tipo, pt.nombre as categoria,
       r.fecha_inicio, r.fecha_fin, r.hora_inicio, r.hora_fin,
       (select min(created_at) from public.access_logs a
         where a.request_id = r.id and a.tipo_acceso = 'salida_empleado' and a.autorizado)
         as salio_en,
       r.retorno_en, r.retorno_exceso_minutos, r.retorno_exceso_dias,
       case
         when r.retorno_en is null then 'sin registrar'
         when coalesce(r.retorno_exceso_minutos, 0) > 0 then 'volvió tarde'
         when coalesce(r.retorno_exceso_dias, 0) > 0    then 'volvió tarde'
         else 'a tiempo'
       end as puntualidad
from public.requests r
join public.users u on u.id = r.user_id
left join public.users j on j.id = u.jefe_id
left join public.permission_types pt on pt.id = r.permission_type_id
where r.estado = 'aprobado'
  and exists (select 1 from public.access_logs a
               where a.request_id = r.id and a.tipo_acceso = 'salida_empleado' and a.autorizado);

comment on view public.v_retornos is
  'Quién salió con permiso, cuándo volvió y si se pasó de la hora declarada.';

grant select on public.v_retornos to authenticated;
