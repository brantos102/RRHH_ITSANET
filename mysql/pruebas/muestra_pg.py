"""Una base PostgreSQL de muestra, con personas INVENTADAS, para comparar.

Las pruebas diferenciales necesitan datos con variedad —gente en las dos
regiones, solicitudes en todos los estados, históricos, bajas, garita,
temporales, mensajes— y la base de pruebas local está casi vacía. Esto la
copia y la llena.

NINGÚN DATO ES DE UNA PERSONA REAL. Las cédulas empiezan por 17599 (válidas
por dígito verificador, fuera de la planilla), los correos son del dominio
.test, los nombres se arman de listas. Nada de esto sale de la base real ni
se guarda en el repositorio: se genera cada vez, con una semilla fija para
que dos ejecuciones den lo mismo.

Todo se genera con las funciones y disparadores de PostgreSQL —las
originales—, así que la muestra es exactamente lo que el sistema de hoy
produciría.
"""
from __future__ import annotations

import datetime as dt
import random
from collections import Counter

NOMBRES = ["Ana", "Luis", "María", "José", "Carmen", "Jorge", "Lucía", "Andrés", "Rosa", "Diego",
           "Paola", "Fernando", "Gabriela", "Raúl", "Verónica", "Iván", "Mónica", "Óscar"]
APELLIDOS = ["Suárez", "Núñez", "Peñafiel", "Zambrano", "Andrade", "Cevallos", "Muñoz", "Espinoza",
             "Vélez", "Ordóñez", "Castillo", "Jaramillo", "Benítez", "Guamán", "Ibarra"]
CARGOS = ["Operario de bodega", "Montacarguista", "Analista", "Asistente administrativo",
          "Supervisor de turno", None]
AREAS = ["Bodega", "Operaciones", "Administración", "Logística", None]


def cedula(n: int) -> str:
    base = f"17599{n:04d}"
    suma = 0
    for i, d in enumerate(base):
        p = int(d) * (2 if i % 2 == 0 else 1)
        suma += p - 9 if p > 9 else p
    return base + str((10 - suma % 10) % 10)


def crear(admin_url: str, plantilla: str, nombre: str) -> None:
    import psycopg
    with psycopg.connect(admin_url, autocommit=True) as c:
        c.execute(f'drop database if exists "{nombre}"')
        c.execute(f'create database "{nombre}" template "{plantilla}"')


def llenar(url: str, semilla: int = 2026) -> Counter:
    """Llena la base. Devuelve cuántas cosas de cada clase se crearon."""
    import psycopg
    from psycopg.rows import dict_row

    azar = random.Random(semilla)
    hecho: Counter = Counter()
    pg = psycopg.connect(url, row_factory=dict_row, autocommit=False)
    hoy = pg.execute("select current_date as d").fetchone()["d"]

    def intentar(clave: str, sql: str, params=()):
        pg.execute("savepoint s")
        try:
            fila = pg.execute(sql, params).fetchone() if "returning" in sql.lower() or \
                sql.lstrip().lower().startswith("select") else pg.execute(sql, params)
            pg.execute("release savepoint s")
            hecho[clave] += 1
            return fila
        except Exception:  # noqa: BLE001
            pg.execute("rollback to savepoint s")
            hecho[clave + " (rechazado)"] += 1
            return None

    ciudades = [r["ciudad"] for r in pg.execute("select ciudad from ciudades_region order by ciudad")]
    tipos = pg.execute("select id, admite_horas, requiere_adjunto from permission_types where activo "
                       "order by id").fetchall()

    def persona(n: int, rol: str, jefe=None, **extra) -> str | None:
        ingreso = extra.pop("ingreso", None) or (
            dt.date(azar.randint(1995, 2026), azar.randint(1, 12), azar.randint(1, 28)))
        if ingreso > hoy:
            ingreso = hoy - dt.timedelta(days=azar.randint(1, 300))
        datos = {
            "cedula": cedula(n),
            "nombre": f"{azar.choice(APELLIDOS)} {azar.choice(APELLIDOS)} {azar.choice(NOMBRES)}",
            "email": None if azar.random() < 0.25 else f"p{n}@muestra.test",
            "rol": rol, "fecha_ingreso": ingreso, "jefe_id": jefe,
            "ciudad": azar.choice(ciudades),
            "cargo": azar.choice(CARGOS), "departamento": azar.choice(AREAS),
            "telefono": None if azar.random() < 0.3 else f"09{azar.randint(10000000, 99999999)}",
            "fecha_nacimiento": None if azar.random() < 0.2 else dt.date(azar.randint(1965, 2004), 5, 17),
            **extra,
        }
        cols = ", ".join(datos)
        fila = intentar("persona", f"insert into users ({cols}) values ({', '.join(['%s'] * len(datos))}) "
                        "returning id", tuple(datos.values()))
        return fila["id"] if fila else None

    n = iter(range(1, 9999))
    admin = persona(next(n), "admin", ingreso=dt.date(2012, 2, 29))
    rrhh = [persona(next(n), "rrhh", admin, ciudad=c) for c in ("Quito", "Guayaquil")]
    jefes = [persona(next(n), "jefe", admin) for _ in range(6)]
    empleados = [persona(next(n), "empleado", azar.choice(jefes)) for _ in range(55)]
    empleados = [e for e in empleados if e]
    sin_jefe = persona(next(n), "empleado", None)
    todos = [p for p in [admin, *rrhh, *jefes, *empleados, sin_jefe] if p]

    for p in todos:
        intentar("periodos", "select generar_periodos_vacaciones(%s)", (p,))
    for p in azar.sample(empleados, 20):
        maximo = pg.execute("select coalesce(sum(dias_asignados),0) as s from vacation_periods "
                            "where user_id = %s and not caducado", (p,)).fetchone()["s"]
        saldo = round(azar.uniform(-5, float(maximo)), 2)
        intentar("saldo inicial", "select cargar_saldo_inicial(%s, %s::numeric, %s)",
                 (p, str(saldo), azar.randint(0, 2)))

    for p in azar.sample(empleados, 25):
        for _ in range(azar.randint(1, 3)):
            ini = dt.date(azar.randint(2016, 2025), azar.randint(1, 12), azar.randint(1, 20))
            dias = azar.randint(3, 15)
            intentar("histórico", """insert into vacaciones_historicas
                       (user_id, fecha_inicio, fecha_fin, dias, origen, fila_origen)
                     values (%s, %s, %s, %s, 'muestra', %s)""",
                     (p, ini, ini + dt.timedelta(days=dias - 1), dias, azar.randint(2, 900)))

    # --------------------------------------------------------- solicitudes
    caminos = [
        [], ["pendiente_rrhh"], ["pendiente_rrhh", "aprobado"], ["rechazado"],
        ["pendiente_rrhh", "rechazado"], ["cancelado"],
        ["pendiente_rrhh", "aprobado", "pendiente_anulacion"],
        ["pendiente_rrhh", "aprobado", "pendiente_anulacion", "cancelado"],
        ["pendiente_rrhh", "aprobado", "pendiente_anulacion", "aprobado"],
    ]
    aprobadas_hoy = []
    for p in empleados:
        for _ in range(azar.randint(0, 3)):
            vac = azar.random() < 0.6
            excepcion = azar.random() < 0.3
            if vac:
                ini = hoy + dt.timedelta(days=azar.randint(-20, 150))
                fin = ini + dt.timedelta(days=azar.randint(6, 20))
                fila = intentar("solicitud de vacaciones", """
                    insert into requests (user_id, tipo, fecha_inicio, fecha_fin, descripcion,
                                          justificacion, bloque_menor_justificado)
                    values (%s, 'vacacion', %s, %s, 'Vacaciones de muestra',
                            'Justificación de la muestra con más de treinta caracteres', %s)
                    returning id, estado""", (p, ini, fin, excepcion))
            else:
                t = azar.choice(tipos)
                ini = hoy + dt.timedelta(days=azar.randint(-5, 40))
                horas = t["admite_horas"] and azar.random() < 0.6
                fin = ini if horas else ini + dt.timedelta(days=azar.randint(0, 2))
                fila = intentar("solicitud de permiso", """
                    insert into requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                                          hora_inicio, hora_fin, descripcion, justificacion)
                    values (%s, 'permiso', %s, %s, %s, %s, %s, 'Permiso de muestra',
                            'Justificación del permiso de muestra')
                    returning id, estado""",
                    (p, t["id"], ini, fin, dt.time(9) if horas else None,
                     dt.time(12) if horas else None))
            if not fila:
                continue
            camino = azar.choice(caminos)
            if fila["estado"] == "pendiente_rrhh" and camino[:1] == ["pendiente_rrhh"]:
                camino = camino[1:]
            for estado in camino:
                extra = {"pendiente_anulacion": ", anulacion_motivo = 'Cambio de planes'",
                         "rechazado": ", motivo_rechazo = 'No hay cobertura ese período'"}.get(estado, "")
                ok = intentar(f"→ {estado}", f"update requests set estado = %s{extra} where id = %s",
                              (estado, fila["id"]))
                if ok is None:
                    break
            final = pg.execute("select estado, fecha_inicio, fecha_fin from requests where id = %s",
                               (fila["id"],)).fetchone()
            if final["estado"] == "aprobado" and final["fecha_inicio"] <= hoy <= final["fecha_fin"]:
                aprobadas_hoy.append((fila["id"], p))

    # Permisos por horas de HOY, aprobados: los que la garita ve pasar. Unos
    # ya debieron volver (de 7 a 8) y otros todavía no (de 7 a 23).
    por_horas = [t for t in tipos if t["admite_horas"] and not t["requiere_adjunto"]]
    for k, p in enumerate(azar.sample(empleados, 6)):
        fila = intentar("permiso de hoy", """
            insert into requests (user_id, tipo, permission_type_id, fecha_inicio, fecha_fin,
                                  hora_inicio, hora_fin, descripcion, justificacion)
            values (%s, 'permiso', %s, current_date, current_date, '07:00', %s,
                    'Permiso de muestra', 'Justificación del permiso de muestra')
            returning id""", (p, por_horas[k % len(por_horas)]["id"],
                              dt.time(8) if k % 2 == 0 else dt.time(23)))
        if fila:
            intentar("→ pendiente_rrhh", "update requests set estado = 'pendiente_rrhh' where id = %s", (fila["id"],))
            if intentar("→ aprobado", "update requests set estado = 'aprobado' where id = %s", (fila["id"],)):
                aprobadas_hoy.append((fila["id"], p))

    # ---------------------------------------------------- garita y retornos
    guardia = persona(next(n), "guardia", admin)
    for i, (rid, p) in enumerate(aprobadas_hoy):
        intentar("salida por garita", """insert into access_logs
                   (user_id, request_id, tipo_acceso, autorizado, guardia_id, created_at)
                 values (%s, %s, 'salida_empleado', true, %s, now() - interval '3 hours')""",
                 (p, rid, guardia))
        if i % 2 == 0:   # la mitad vuelve; la otra sigue fuera
            intentar("retorno", "select registrar_retorno(%s, %s, null, null)", (rid, guardia))

    # ------------------------------------------------------ documentos
    for i in pg.execute("select id from informes_firmados order by folio limit 10").fetchall():
        intentar("impresión", "select informe_impreso(%s)", (i["id"],))
    con_informe = pg.execute("select user_id from informes_firmados where tipo = 'trazabilidad' "
                             "order by folio limit 2").fetchall()
    for f in con_informe:
        intentar("reemisión", "select informe_trazabilidad_reemitir(%s, %s, %s)",
                 (f["user_id"], rrhh[0], "Se perdió el original en el archivo"))
    for r in pg.execute("select id, user_id from requests order by folio limit 8").fetchall():
        intentar("adjunto", """insert into request_attachments
                   (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes, subido_por)
                 values (%s, %s, 'certificado.pdf', 'application/pdf', 52000, %s)""",
                 (r["id"], f"{r['user_id']}/{r['id']}/x-certificado.pdf", r["user_id"]))

    # --------------------------------------------------------- temporales
    for k in range(6):
        t = intentar("temporal", """insert into personal_temporal (cedula, nombre, labor, proveedor)
                       values (%s, %s, 'Estiba', 'Proveedor de muestra') returning id""",
                     (cedula(5000 + k), f"Temporal {azar.choice(APELLIDOS)} {k}"))
        if not t:
            continue
        intentar("jornada vieja sin cerrar" if k % 3 == 0 else "jornada vieja", """
            insert into jornadas_temporales (temporal_id, fecha, entrada_en, salida_en, horas)
            values (%s, current_date - %s, now() - make_interval(days => %s, hours => 8),
                    case when %s then null else now() - make_interval(days => %s) end,
                    case when %s then null else 8 end)""",
            (t["id"], k + 1, k + 1, k % 3 == 0, k + 1, k % 3 == 0))
        if k < 4:
            intentar("entrada hoy", "select temporal_registrar_entrada(%s, %s, null)", (t["id"], guardia))
        if k < 2:
            intentar("salida hoy", "select temporal_registrar_salida(%s, %s, null)", (t["id"], guardia))

    # ------------------------------------------------- mensajes y fichas
    for p in azar.sample(empleados, 6):
        c = intentar("conversación", """insert into conversaciones (user_id, asunto)
                       values (%s, 'Consulta sobre mi saldo') returning id""", (p,))
        if c:
            for j in range(azar.randint(1, 4)):
                intentar("mensaje", """insert into mensajes (conversacion_id, autor_id, es_rrhh, texto,
                           created_at) values (%s, %s, %s, %s, now() - make_interval(mins => %s))""",
                         (c["id"], p if j % 2 == 0 else rrhh[0], j % 2 == 1, f"Mensaje {j} de muestra", 60 - j))
    for p in azar.sample(empleados, 6):
        intentar("cambio de ficha", "select solicitar_cambio_ficha(%s, %s, %s, %s)",
                 (p, azar.choice(["cargo", "jefe_id", "telefono"]),
                  str(azar.choice(jefes)) if azar.random() < 0.4 else "Dato corregido de muestra",
                  "Corrección pedida en la muestra"))
    for p in azar.sample(empleados, 3):
        intentar("baja", "select dar_de_baja(%s, %s, %s, %s, %s)",
                 (p, hoy - dt.timedelta(days=azar.randint(1, 60)),
                  azar.choice(["renuncia", "fin_de_contrato", "mutuo_acuerdo"]), "Baja de muestra", rrhh[0]))
    for k in range(3):
        intentar("visita", """insert into visitors (cedula, nombre, empresa, motivo_visita)
                   values (%s, %s, 'Empresa de muestra', 'Reunión')""",
                 (cedula(6000 + k), f"Visita {k}"))

    pg.commit()
    pg.close()
    return hecho
