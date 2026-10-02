-- ---------------------------------------------------------------------------
-- 0039 · El respaldo se sugiere; la justificación no se perdona.
--
-- DOS CAMBIOS que vienen del uso real.
--
-- A. EL ADJUNTO DEJA DE SER UN MURO
--
--    «Cita médica» exigía adjuntar el respaldo para poder enviar. Suena
--    razonable hasta que se mira cómo ocurre de verdad: el colaborador pide
--    el permiso desde el teléfono, camino a la cita, y el certificado se lo
--    dan DESPUÉS de que el médico lo atienda. Exigirlo antes es pedir un
--    documento que todavía no existe.
--
--    Y el muro se cae por su propio peso cuando el almacenamiento falla: la
--    solicitud no se puede enviar aunque todo lo demás esté bien, y el
--    colaborador se queda sin pedir su permiso por un problema de servidor
--    que no es suyo.
--
--    Desde aquí se SUGIERE con claridad y no se bloquea. Quien aprueba ve si
--    vino con respaldo o sin él —ya lo veía— y decide, que es su trabajo.
--
-- B. LA JUSTIFICACIÓN SÍ ES OBLIGATORIA
--
--    Es lo único con lo que el jefe y Talento Humano pueden decidir. Hasta
--    ahora solo se exigía en vacaciones por encima del saldo; un permiso se
--    podía enviar con la descripción mínima y nada más.
--
--    La restricción entra como NOT VALID: las solicitudes ya registradas no
--    se tocan —hay tres sin justificación en la base de pruebas— y todas las
--    nuevas se comprueban. Cuando Talento Humano complete esas tres, se
--    puede validar con  alter table ... validate constraint ...
--
-- Idempotente.
-- ---------------------------------------------------------------------------

-- =========================================================================
-- A. El respaldo, sugerido
-- =========================================================================

create or replace function public.tg_requests_validar_requisitos()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
declare
  v_pt        public.permission_types%rowtype;
  v_adjuntos  int;
  v_minimo    numeric;
begin
  -- Se ejecuta al COMMIT: la solicitud pudo eliminarse en la misma
  -- transacción (o por cascada). En ese caso no hay nada que validar.
  if not exists (select 1 from public.requests where id = new.id) then
    return null;
  end if;

  select count(*) into v_adjuntos from public.request_attachments where request_id = new.id;

  -- Para un permiso, el respaldo se sugiere en la pantalla y quien aprueba ve
  -- si vino o no. Ya no se bloquea el envío: el certificado de una cita
  -- médica se emite DESPUÉS de la cita, y la firma dibujada se retiró del
  -- sistema en la migración 0037.

  if new.tipo = 'vacacion' then
    select coalesce(nullif(valor, '')::numeric, 0) into v_minimo
      from public.app_config where clave = 'vacaciones_bloque_minimo';
    v_minimo := coalesce(v_minimo, 0);

    -- Esto SÍ se mantiene: tomar menos del bloque mínimo es una excepción a
    -- la política, la autoriza Talento Humano y el documento que la sustenta
    -- es lo que queda en el expediente. No es lo mismo que un permiso.
    if v_minimo > 0 and ((new.fecha_fin - new.fecha_inicio) + 1) < v_minimo then
      if v_adjuntos = 0 then
        raise exception
          'Para tomar menos de % días debe adjuntar el documento que respalde la excepción.',
          v_minimo;
      end if;
    end if;
  end if;

  return null;
end;
$$;

comment on column public.permission_types.requiere_adjunto is
  'Si para este permiso SE SUGIERE adjuntar respaldo. Se muestra en la pantalla y quien aprueba ve si vino; no impide enviar.';


-- =========================================================================
-- B. La justificación, obligatoria en todo permiso
-- =========================================================================

alter table public.requests
  drop constraint if exists requests_permiso_justificado;

alter table public.requests
  add constraint requests_permiso_justificado
  check (
    tipo <> 'permiso'
    or (justificacion is not null and length(btrim(justificacion)) >= 10)
  ) not valid;

comment on constraint requests_permiso_justificado on public.requests is
  'Todo permiso lleva justificación: es lo único con lo que el jefe y Talento Humano pueden decidir. NOT VALID a propósito: lo ya registrado no se toca.';
