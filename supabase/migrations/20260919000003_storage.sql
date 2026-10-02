-- =====================================================================
--  Migración 0003 — Supabase Storage para adjuntos y firmas
--
--  Buckets privados:
--    solicitudes/<user_id>/<request_id>/<archivo>   respaldos de permisos
--    firmas/<user_id>/<archivo>                     firma registrada
--
--  Se ejecuta solo si existe el esquema `storage` (Supabase). En un
--  PostgreSQL local sin Storage, no hace nada.
-- =====================================================================

do $storage$
begin
  if not exists (select 1 from information_schema.schemata where schema_name = 'storage') then
    raise notice 'Esquema storage no disponible: se omite la configuración de buckets.';
    return;
  end if;

  -- ---- Buckets ----
  execute $sql$
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('solicitudes', 'solicitudes', false, 10485760,
            array['image/jpeg','image/png','image/webp','image/heic','application/pdf'])
    on conflict (id) do update
      set file_size_limit    = excluded.file_size_limit,
          allowed_mime_types = excluded.allowed_mime_types,
          public             = false
  $sql$;

  execute $sql$
    insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
    values ('firmas', 'firmas', false, 1048576,
            array['image/png','image/jpeg','image/svg+xml','application/pdf'])
    on conflict (id) do update
      set file_size_limit    = excluded.file_size_limit,
          allowed_mime_types = excluded.allowed_mime_types,
          public             = false
  $sql$;

  -- ---- Políticas del bucket `solicitudes` ----
  -- El primer nivel de la ruta es el user_id del dueño del archivo.
  execute 'drop policy if exists solicitudes_subir_propio on storage.objects';
  execute $sql$
    create policy solicitudes_subir_propio on storage.objects
      for insert to authenticated
      with check (
        bucket_id = 'solicitudes'
        and (storage.foldername(name))[1] = public.current_user_id()::text
      )
  $sql$;

  execute 'drop policy if exists solicitudes_leer on storage.objects';
  execute $sql$
    create policy solicitudes_leer on storage.objects
      for select to authenticated
      using (
        bucket_id = 'solicitudes'
        and (
          (storage.foldername(name))[1] = public.current_user_id()::text   -- su propio archivo
          or public.is_rrhh_o_admin()                                      -- RRHH / admin
          or exists (                                                      -- el jefe del dueño
            select 1 from public.users u
             where u.id::text = (storage.foldername(name))[1]
               and u.jefe_id = public.current_user_id()
          )
        )
      )
  $sql$;

  execute 'drop policy if exists solicitudes_borrar_propio on storage.objects';
  execute $sql$
    create policy solicitudes_borrar_propio on storage.objects
      for delete to authenticated
      using (
        bucket_id = 'solicitudes'
        and (storage.foldername(name))[1] = public.current_user_id()::text
        and exists (                       -- solo mientras la solicitud siga editable
          select 1 from public.requests r
           where r.user_id = public.current_user_id()
             and r.id::text = (storage.foldername(name))[2]
             and r.estado = 'pendiente_jefe'
        )
      )
  $sql$;

  -- ---- Políticas del bucket `firmas` ----
  execute 'drop policy if exists firmas_gestion_propia on storage.objects';
  execute $sql$
    create policy firmas_gestion_propia on storage.objects
      for all to authenticated
      using (
        bucket_id = 'firmas'
        and ((storage.foldername(name))[1] = public.current_user_id()::text
             or public.is_rrhh_o_admin())
      )
      with check (
        bucket_id = 'firmas'
        and (storage.foldername(name))[1] = public.current_user_id()::text
      )
  $sql$;

  raise notice 'Buckets `solicitudes` y `firmas` configurados.';
end
$storage$;
