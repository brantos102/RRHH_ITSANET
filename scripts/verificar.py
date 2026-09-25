#!/usr/bin/env python3
"""Comprueba que todo esté listo antes de arrancar.

Revisa la configuración, la conexión a la base, las migraciones aplicadas y
si hay con quién iniciar sesión. Dice qué falta y cómo resolverlo.

    python scripts/verificar.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"
OK, MAL, AVISO = f"{VERDE}✓{FIN}", f"{ROJO}✗{FIN}", f"{AMARILLO}!{FIN}"

problemas: list[str] = []


def titulo(texto: str) -> None:
    print(f"\n{texto}\n{'─' * len(texto)}")


def fallo(mensaje: str, remedio: str) -> None:
    print(f"  {MAL} {mensaje}")
    print(f"    {GRIS}→ {remedio}{FIN}")
    problemas.append(mensaje)


def main() -> int:
    print("Verificación del sistema de permisos y vacaciones")

    # ---------------------------------------------------------- configuración
    titulo("1. Configuración")
    env = RAIZ / "backend" / ".env"
    if not env.exists():
        fallo("No existe backend/.env",
              "cp backend/.env.example backend/.env  y complete los valores")
        return resumen()
    print(f"  {OK} backend/.env encontrado")

    try:
        from app.config import get_settings
        settings = get_settings()
    except Exception as exc:  # noqa: BLE001
        fallo(f"backend/.env tiene un problema: {exc}",
              "Revise que estén DATABASE_URL y SUPABASE_JWT_SECRET")
        return resumen()

    if "<" in settings.database_url or not settings.database_url.startswith("postgres"):
        fallo("DATABASE_URL sigue con el valor de ejemplo",
              "Supabase → Project Settings → Database → Connection string (URI)")
    else:
        destino = settings.database_url.split("@")[-1].split("/")[0]
        print(f"  {OK} DATABASE_URL apunta a {destino}")

    if "<" in settings.supabase_jwt_secret or len(settings.supabase_jwt_secret) < 20:
        fallo("SUPABASE_JWT_SECRET sigue con el valor de ejemplo",
              "Supabase → Project Settings → API → JWT Settings → JWT Secret")
    else:
        print(f"  {OK} SUPABASE_JWT_SECRET configurado")

    if settings.email_backend == "console":
        print(f"  {AVISO} EMAIL_BACKEND=console: el código de acceso se imprimirá")
        print(f"    {GRIS}en la terminal del backend en vez de enviarse por correo.{FIN}")
        print(f"    {GRIS}Perfecto para la primera prueba.{FIN}")
    elif not settings.smtp_user:
        fallo("EMAIL_BACKEND=smtp pero falta SMTP_USER",
              "Ponga EMAIL_BACKEND=console para probar sin correo")
    else:
        print(f"  {OK} Correo por SMTP vía {settings.smtp_host}")

    # CORS: la causa habitual del 400 en OPTIONS y del «No se pudo conectar»
    if settings.es_produccion:
        print(f"  {OK} ENTORNO=produccion: solo los orígenes listados")
        print(f"    {GRIS}{', '.join(settings.origenes_permitidos) or 'ninguno'}{FIN}")
        if any(o.startswith("http://") for o in settings.origenes_permitidos):
            print(f"  {AVISO} Hay orígenes http:// en producción: publique con https")
        if not settings.origenes_permitidos:
            fallo("ENTORNO=produccion y CORS_ORIGINS vacío: el navegador no podrá llamar",
                  "Liste la URL del frontend en CORS_ORIGINS, o use ENTORNO=desarrollo")
    else:
        print(f"  {OK} ENTORNO=desarrollo: CORS acepta cualquier http://localhost:PUERTO")
        print(f"    {GRIS}y además {', '.join(settings.origenes_permitidos) or 'nada más'}{FIN}")

    if problemas:
        return resumen()

    # ------------------------------------------------------------ base de datos
    titulo("2. Base de datos")
    import asyncio
    return asyncio.run(revisar_base())


async def revisar_base() -> int:
    from app.db import cerrar_pool, obtener_todos, obtener_uno

    try:
        await obtener_uno("select 1 as ok")
        print(f"  {OK} Conexión establecida")
    except Exception as exc:  # noqa: BLE001
        fallo(f"No se pudo conectar: {str(exc)[:120]}",
              "Revise DATABASE_URL. Con el pooler use el puerto 6543")
        return resumen()

    # Migraciones, por un objeto representativo de cada una
    migraciones = [
        ("0001 esquema base", "public.requests"),
        ("0002 reglas Ecuador", "public.vacation_periods"),
        ("0004 normativa y alertas", "public.notifications"),
        ("0005 folio y calendario", "public.v_calendario_equipo"),
        ("0006 anulación y administración", "public.v_informe_solicitudes"),
    ]
    for nombre, objeto in migraciones:
        fila = await obtener_uno("select to_regclass(%s) is not null as existe", (objeto,))
        if fila["existe"]:
            print(f"  {OK} Migración {nombre}")
        else:
            fallo(f"Falta la migración {nombre}",
                  f"Ejecute el archivo correspondiente en supabase/migrations/")

    columna = await obtener_uno(
        """select count(*) as n from information_schema.columns
           where table_name = 'requests' and column_name = 'folio'"""
    )
    if not columna["n"]:
        fallo("La tabla requests no tiene la columna folio",
              "Falta aplicar la migración 0005")

    if problemas:
        await cerrar_pool()
        return resumen()

    # --------------------------------------------------------------- contenido
    titulo("3. Contenido")
    conteos = await obtener_uno(
        """
        select (select count(*) from public.users where activo) as personas,
               (select count(*) from public.users where rol in ('admin','rrhh') and activo) as administradores,
               (select count(*) from public.permission_types where activo) as tipos,
               (select count(*) from public.feriados where activo
                 and extract(year from fecha) = extract(year from current_date)) as feriados,
               (select count(*) from public.legal_references) as articulos
        """
    )

    if conteos["personas"]:
        print(f"  {OK} {conteos['personas']} persona(s) registrada(s)")
    else:
        fallo("No hay ninguna persona registrada: no podrá iniciar sesión",
              "Ejecute supabase/crear_mi_usuario.sql con su cédula y correo")

    if conteos["administradores"]:
        print(f"  {OK} {conteos['administradores']} con perfil de administración")
    else:
        fallo("Nadie tiene rol admin o rrhh",
              "Sin eso no podrá entrar a administración ni aprobar")

    print(f"  {OK} {conteos['tipos']} tipos de solicitud")
    print(f"  {OK} {conteos['articulos']} artículos en el glosario legal")
    if conteos["feriados"]:
        print(f"  {OK} {conteos['feriados']} feriados cargados para este año")
    else:
        print(f"  {AVISO} Sin feriados este año: todos los días contarán como laborables")

    # Quién puede entrar
    if conteos["personas"]:
        titulo("4. Con quién puede iniciar sesión")
        gente = await obtener_todos(
            """select cedula, nombre, rol::text, email from public.users
               where activo order by
                 case rol when 'admin' then 1 when 'rrhh' then 2 when 'jefe' then 3
                          when 'guardia' then 4 else 5 end, nombre
               limit 8"""
        )
        for p in gente:
            print(f"    {p['cedula']}  {p['nombre'][:24]:<24} {p['rol']:<9} {p['email']}")

    await cerrar_pool()
    return resumen()


def resumen() -> int:
    print()
    if problemas:
        print(f"{ROJO}Faltan {len(problemas)} cosa(s) antes de poder probar.{FIN}")
        return 1
    print(f"{VERDE}Todo listo.{FIN} Arranque con:  ./scripts/iniciar.sh")
    return 0


if __name__ == "__main__":
    os.chdir(RAIZ / "backend")
    sys.exit(main())
