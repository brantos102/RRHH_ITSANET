#!/usr/bin/env python3
"""Comprueba que todo esté listo antes de arrancar.

Revisa la configuración, la conexión a la base, las migraciones aplicadas y
si hay con quién iniciar sesión. Dice qué falta y cómo resolverlo.

    python scripts/verificar.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# psycopg no arranca sobre el bucle de eventos que Windows usa por
# omisión. Ver scripts/_windows.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _windows  # noqa: F401,E402

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


def _hoja_de_vacaciones() -> Path:
    """La hoja de Talento Humano, si está a mano.

    Se busca al lado del repositorio y en Documentos, que es donde acaba
    siempre. Encontrarla permite dar el comando entero, con la ruta que
    funciona, en vez de un ejemplo que hay que adaptar.
    """
    for carpeta in (RAIZ.parent, RAIZ, Path.cwd(), Path.home() / "Documents"):
        if not carpeta.is_dir():
            continue
        for archivo in sorted(carpeta.glob("*.xls*")):
            if "VACACION" in archivo.name.upper():
                return archivo
    return RAIZ.parent / "REGISTRO_DE_VACACIONES.xlsx"


def revisar_versiones() -> None:
    """Un backend con librerías distintas a las ancladas falla de formas raras.

    Pasó de verdad: con otra versión de FastAPI el módulo de autenticación ni
    siquiera se importaba, y con otra de pydantic la bitácora devolvía 500.
    """
    from importlib.metadata import PackageNotFoundError, version

    # Lo que hace falta para EJECUTAR y lo que solo hace falta para PROBAR se
    # separan por el encabezado «# desarrollo» del requirements.txt. Sin esta
    # distinción, faltar `pypdf` —que solo se usa para leer un PDF dentro de
    # una prueba— bloqueaba el arranque del sistema entero.
    criticas: dict[str, str] = {}
    de_pruebas: dict[str, str] = {}
    destino = criticas
    for linea in (RAIZ / "backend" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if linea.lower().startswith("# desarrollo"):
            destino = de_pruebas
            continue
        if "==" in linea and not linea.startswith("#"):
            nombre, anclada = linea.split("==", 1)
            destino[nombre.split("[")[0]] = anclada

    def revisar(paquetes: dict[str, str]) -> tuple[list[str], list[str]]:
        faltan, distintas = [], []
        for paquete, anclada in paquetes.items():
            try:
                instalada = version(paquete)
            except PackageNotFoundError:
                faltan.append(paquete)
                continue
            if instalada != anclada:
                distintas.append(f"{paquete} {instalada} (anclada: {anclada})")
        return faltan, distintas

    faltantes, desajustes = revisar(criticas)
    faltan_pruebas, _ = revisar(de_pruebas)

    if faltantes:
        fallo(f"Faltan librerías: {', '.join(faltantes)}",
              "pip install -r backend/requirements.txt")
    elif desajustes:
        print(f"  {AVISO} Versiones distintas a las probadas:")
        for d in desajustes:
            print(f"    {GRIS}{d}{FIN}")
        print(f"    {GRIS}→ pip install -r backend/requirements.txt  (si algo falla raro){FIN}")
    else:
        print(f"  {OK} Librerías en las versiones probadas")

    # Las de pruebas no impiden usar el sistema: se avisa y se sigue.
    if faltan_pruebas and not faltantes:
        print(f"  {AVISO} Solo para ejecutar las pruebas falta: {', '.join(faltan_pruebas)}")
        print(f"    {GRIS}→ pip install {' '.join(faltan_pruebas)}   (no hace falta para usar el sistema){FIN}")


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

    revisar_versiones()

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
        ("0007 pilares de permiso", "public.v_catalogo_permisos"),
        ("0008 lineamientos y antigüedad", "public.v_antiguedad_referencia"),
        ("0009 campos de la planilla", "public.v_sin_correo"),
        ("0010 devengo mensual", None),          # es una función, no una tabla
        ("0011 carga masiva", None),
        ("0012 regiones de atención", "public.regiones"),
        ("0013 ficha y alta guiada", "public.campos_ficha"),
        ("0014 chat con Talento Humano", "public.conversaciones"),
        ("0015 sin ausencias solapadas", None),
        ("0016 saldo comprensible", None),
        ("0017 excepción sin regla de fin de semana", None),
        ("0018 hora real de regreso", "public.v_retornos"),
        ("0019 confirmar correo, cargo y jefe", "public.confirmaciones_correo"),
        ("0020 sin caducidad inventada", "public.v_caducidad"),
        ("0021 Art. 75 correcto y control de acumulación", "public.v_acumulacion_excesiva"),
        ("0022 correo en blanco de quien no lo tiene", None),
        ("0023 el calendario recuerda lo que pasó", None),
        ("0024 personal temporal", "public.personal_temporal"),
        ("0025 historial de vacaciones", "public.vacaciones_historicas"),
        ("0026 panel de garita del día", "public.v_garita_hoy"),
        ("0027 pantalla principal configurable", "public.panel_bloques"),
        ("0028 devengo como la hoja", "public.v_devengo_cotejo"),
        ("0029 nadie sin forma de entrar", "public.v_sin_entrada"),
        ("0030 lineamientos editables", "public.lineamientos_solicitud"),
        ("0031 ningún día se pierde", None),
        ("0032 el calendario recuerda los históricos", None),
        ("0033 fines de semana cumplidos", "public.v_fines_semana"),
        ("0034 personal temporal sin dinero", "public.v_jornadas_detalle"),
        ("0035 pantalla de depuración", "public.v_cuentas_de_prueba"),
        ("0036 alta y baja de jefaturas", "public.v_jefaturas_admin"),
        ("0037 departamento de Talento Humano", "public.v_talento_humano"),
    ]

    # Las migraciones que solo cambian funciones se comprueban por la función.
    funciones = {
        "0010 devengo mensual": "dias_devengados_en_curso",
        "0011 carga masiva": "caducar_periodos_de",
        "0015 sin ausencias solapadas": "ausencia_solapada",
        "0016 saldo comprensible": "saldo_desglosado",
    }

    # Hay migraciones que no crean nada: solo cambian el cuerpo de una función
    # que ya existía. Comprobar que la función existe no diría nada, así que se
    # busca la marca del cambio dentro de su código.
    # Y una que solo cambia una restricción: se comprueba la restricción.
    columnas_nulas = {
        "0022 correo en blanco de quien no lo tiene": ("users", "email"),
    }

    dentro_de = {
        "0017 excepción sin regla de fin de semana":
            ("tg_requests_before_insert", "bloque_menor_justificado"),
        # Esta no crea nada: corrige lo que un aviso le dice a la gente. Se
        # comprueba por el texto, porque que la función exista no dice nada
        # sobre lo que afirma.
        "0031 ningún día se pierde":
            ("generar_alertas_vacaciones", "Ningún día se pierde"),
    }

    # Y una que solo quita una línea de una vista: se comprueba que la vista
    # tenga la columna nueva, que es lo que esa línea hacía imposible.
    columnas_de_vista = {
        "0023 el calendario recuerda lo que pasó": ("v_calendario_equipo", "ya_ocurrio"),
        # Esta une las vacaciones de la hoja a la cuadrícula del mes: se
        # comprueba por la columna que dice de dónde viene cada ausencia.
        "0032 el calendario recuerda los históricos": ("v_calendario_equipo", "procedencia"),
    }
    for nombre, objeto in migraciones:
        if nombre in columnas_de_vista:
            vista, columna = columnas_de_vista[nombre]
            fila = await obtener_uno(
                """select count(*) > 0 as existe from information_schema.columns
                    where table_schema = 'public' and table_name = %s
                      and column_name = %s""",
                (vista, columna),
            )
        elif nombre in columnas_nulas:
            tabla, columna = columnas_nulas[nombre]
            fila = await obtener_uno(
                """select is_nullable = 'YES' as existe
                     from information_schema.columns
                    where table_schema = 'public' and table_name = %s
                      and column_name = %s""",
                (tabla, columna),
            )
            fila = fila or {"existe": False}
        elif nombre in dentro_de:
            funcion, marca = dentro_de[nombre]
            fila = await obtener_uno(
                """select coalesce(position(%s in prosrc) > 0, false) as existe
                     from pg_proc p join pg_namespace n on n.oid = p.pronamespace
                    where n.nspname = 'public' and p.proname = %s""",
                (marca, funcion),
            )
            fila = fila or {"existe": False}
        elif objeto is None:
            fila = await obtener_uno(
                """select exists (select 1 from pg_proc p
                                    join pg_namespace n on n.oid = p.pronamespace
                                   where n.nspname = 'public' and p.proname = %s) as existe""",
                (funciones[nombre],),
            )
        else:
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

    # El historial de vacaciones no viaja en el repositorio: son los datos
    # personales de 350 personas reales y no tienen por qué estar en GitHub.
    # Se carga desde la hoja de Talento Humano en cada instalación, y por eso
    # hay que decir aquí cuando falta: la migración crea la tabla vacía y la
    # pantalla queda diciendo «todavía no hay vacaciones registradas», que
    # parece un fallo del sistema y no un paso pendiente.
    historial = await obtener_uno(
        """select (select count(*) from public.vacaciones_historicas) as filas,
                  (select count(distinct user_id) from public.vacaciones_historicas) as personas""")
    if historial and historial["filas"]:
        print(f"  {OK} {historial['filas']} vacaciones históricas de "
              f"{historial['personas']} persona(s)")
    else:
        print(f"  {AVISO} Sin historial de vacaciones cargado")
        print(f"      {GRIS}El colaborador verá «Todavía no hay vacaciones registradas a su"
              f" nombre».{FIN}")
        print(f"      {GRIS}Cárguelo desde la hoja de Talento Humano. Primero sin "
              f"--aplicar, que solo dice qué haría:{FIN}")
        # La ruta completa del guion, no «scripts/...»: esa forma solo funciona
        # si uno está parado en la raíz del repositorio, y quien acaba de
        # ejecutar esto puede estar en cualquier sitio. Un guion que «no
        # existe» cuando existe es media hora perdida.
        guion = RAIZ / "scripts" / "cargar_historial.py"
        hoja = _hoja_de_vacaciones()
        print(f"          python \"{guion}\" \"{hoja}\"")
        print(f"          python \"{guion}\" \"{hoja}\" --aplicar")

    # Quien no tiene correo entra por «primer ingreso» probando su identidad.
    # Si además le falta la fecha de nacimiento o la de ingreso, ese camino
    # está cerrado y no le queda ninguno: ni código al correo ni alta guiada.
    # Es un encierro silencioso —la pantalla no lo dice— y por eso se cuenta.
    encerradas = await obtener_uno(
        """select count(*) as n from public.users
            where activo and email is null
              and (fecha_nacimiento is null or fecha_ingreso is null
                   or ficha_completa or not correo_pendiente)""")
    sin_correo = await obtener_uno(
        "select count(*) as n from public.users where activo and email is null")
    if encerradas and encerradas["n"]:
        fallo(f"{encerradas['n']} persona(s) sin correo y sin forma de entrar",
              "No tienen correo para el código ni datos para el primer ingreso. "
              "Consulte public.v_sin_entrada")
    elif sin_correo and sin_correo["n"]:
        print(f"  {OK} {sin_correo['n']} sin correo, todas con primer ingreso disponible")

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
    print(f"{VERDE}Todo listo.{FIN} Arranque con:")
    if sys.platform == "win32":
        # En Windows hacen falta dos ventanas y el lanzador que fija el bucle
        # de eventos; ./scripts/iniciar.sh es de Linux y aquí no corre.
        print("    python scripts\\servidor.py          (backend)")
        print("    cd frontend; python -m http.server 5500   (en otra ventana)")
        print(f"\n{GRIS}Luego abra http://127.0.0.1:5500{FIN}")
    else:
        print("    ./scripts/iniciar.sh")
    return 0


if __name__ == "__main__":
    os.chdir(RAIZ / "backend")
    sys.exit(main())
