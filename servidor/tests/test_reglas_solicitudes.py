"""Crear una solicitud en Python, comparado con PostgreSQL intento por intento.

Cientos de intentos al azar (con semilla fija) sobre la muestra: vacaciones y
cada tipo de permiso, rangos alrededor de hoy, que empiezan lunes o terminan
viernes, con y sin excepción, justificaciones cortas y largas, por horas,
encima de otra solicitud viva, de alguien dado de baja, con y sin adjunto.
Cada intento se hace en las dos bases. Tiene que pasar lo mismo: o se
rechaza con el mismo mensaje y la misma pista, o se crea con los mismos
días, saldo, ruta, estado, documentos, avisos y bitácora.
"""
from __future__ import annotations

import datetime as dt
import random
import uuid
from collections import Counter

import pytest

from app import errores
from app.db import obtener_todos, obtener_uno
from app.reglas import solicitudes
from tests.diferencial import json_normal, muestra, y_deshacer  # noqa: F401

CALCULADAS = ["dias_solicitados", "saldo_al_solicitar", "jefe_id", "estado", "fines_semana",
              "horas_solicitadas", "es_adelanto", "ruta_aprobacion", "bloque_menor_justificado", "region"]


def _intentos(pg, n: int, semilla: int = 7):
    azar = random.Random(semilla)
    hoy = pg.execute("select current_date as d").fetchone()["d"]
    personas = [f["id"] for f in pg.execute(
        "select id from users where rol <> 'guardia' order by cedula").fetchall()]
    tipos = pg.execute("select id, admite_horas from permission_types order by id").fetchall()
    vivas = pg.execute("""select user_id, fecha_inicio, fecha_fin, hora_inicio, hora_fin
                            from requests where estado in
                            ('pendiente_jefe','pendiente_rrhh','pendiente_anulacion','aprobado')""").fetchall()
    for k in range(n):
        caso: dict = {"id": uuid.uuid4(), "descripcion": "Intento de la prueba diferencial"}
        if k % 9 == 0 and vivas:
            v = azar.choice(vivas)
            caso.update(user_id=v["user_id"], fecha_inicio=v["fecha_inicio"], fecha_fin=v["fecha_fin"],
                        tipo="vacacion")
        else:
            caso["user_id"] = azar.choice(personas)
            inicio = hoy + dt.timedelta(days=azar.randint(-30, 120))
            if azar.random() < 0.3:     # empieza lunes
                inicio += dt.timedelta(days=(7 - inicio.weekday()) % 7)
            largo = azar.choice([0, 1, 2, 4, 6, 7, 10, 13, 15, 20])
            fin = inicio + dt.timedelta(days=largo)
            if azar.random() < 0.3:     # termina viernes
                fin += dt.timedelta(days=(4 - fin.weekday()) % 7)
            caso.update(fecha_inicio=inicio, fecha_fin=fin,
                        tipo="vacacion" if azar.random() < 0.55 else "permiso")
        if caso["tipo"] == "permiso":
            t = azar.choice(tipos + [{"id": 999, "admite_horas": False}])
            caso["permission_type_id"] = t["id"]
            if t["admite_horas"] and azar.random() < 0.6:
                caso["fecha_fin"] = caso["fecha_inicio"]
                h = azar.randint(6, 16)
                caso["hora_inicio"] = dt.time(h)
                caso["hora_fin"] = dt.time(min(h + azar.choice([1, 2, 4, 9, -1]), 23), azar.choice([0, 30]))
        caso["bloque_menor_justificado"] = azar.random() < 0.3
        caso["justificacion"] = azar.choice([
            None, "corta", "Justificación media de prueba",
            "Justificación suficientemente larga para una excepción de la política"])
        caso["adjunto"] = azar.random() < 0.3
        yield caso


def _en_pg(pg, caso) -> tuple[dict | None, tuple | None]:
    cols = ["id", "user_id", "tipo", "fecha_inicio", "fecha_fin", "descripcion", "justificacion",
            "bloque_menor_justificado", "permission_type_id", "hora_inicio", "hora_fin"]
    presentes = [c for c in cols if c in caso]
    pg.execute("savepoint intento")
    try:
        pg.execute(f"insert into requests ({', '.join(presentes)}) "
                   f"values ({', '.join(['%s'] * len(presentes))})", tuple(caso[c] for c in presentes))
        if caso["adjunto"]:
            pg.execute("""insert into request_attachments
                            (request_id, storage_path, nombre_archivo, mime_type, tamano_bytes)
                          values (%s, 'x/y/z.pdf', 'respaldo.pdf', 'application/pdf', 1000)""", (caso["id"],))
        # El requisito del adjunto se comprueba al confirmar; aquí se fuerza.
        pg.execute("set constraints all immediate")
    except Exception as exc:  # noqa: BLE001
        d = exc.diag
        pg.execute("rollback to savepoint intento")
        return None, (d.message_primary, d.message_hint or "", d.constraint_name or "")
    # Fuera del try: un error de la propia prueba no puede pasar por un
    # rechazo de la regla.
    foto = _foto_pg(pg, caso)
    pg.execute("rollback to savepoint intento")
    return foto, None


def _foto_pg(pg, caso):
    r = pg.execute(f"select {', '.join(CALCULADAS)} from requests where id = %s", (caso["id"],)).fetchone()
    return {
        "fila": json_normal(r),
        "periodos": json_normal(pg.execute(
            """select periodo, dias_asignados, dias_consumidos, devengado from vacation_periods
                where user_id = %s order by periodo""", (caso["user_id"],)).fetchall()),
        "informes": sorted(f["tipo"] for f in pg.execute(
            "select tipo from informes_firmados where user_id = %s", (caso["user_id"],)).fetchall()),
        "avisos": sorted(json_normal(pg.execute(
            """select user_id, tipo, severidad, titulo, mensaje from notifications
                where entidad_id = %s""", (str(caso["id"]),)).fetchall()), key=str),
        "bitacora": json_normal(pg.execute(
            "select accion, detalle from audit_logs where entidad_id = %s", (str(caso["id"]),)).fetchall()),
    }


async def _en_my(caso) -> tuple[dict | None, tuple | None]:
    datos = {k: v for k, v in caso.items() if k != "adjunto"}
    adjuntos = [{"storage_path": "x/y/z.pdf", "nombre_archivo": "respaldo.pdf",
                 "mime_type": "application/pdf", "tamano_bytes": 1000}] if caso["adjunto"] else []
    resultado = (None, None)
    async with y_deshacer():
        try:
            await solicitudes.crear_solicitud(datos, adjuntos, subido_por=caso["user_id"])
        except errores.ReglaDeNegocio as exc:
            resultado = (None, (exc.mensaje, exc.pista, ""))
        except Exception as exc:  # noqa: BLE001
            if errores.numero_de_error(exc) is None:
                raise
            resultado = (None, ("", "", errores.restriccion_de(exc) or str(exc)))
        else:
            r = await obtener_uno(f"SELECT {', '.join(CALCULADAS)} FROM requests WHERE id = %s", (caso["id"],))
            resultado = ({
                "fila": json_normal(r),
                "periodos": json_normal(await obtener_todos(
                    """SELECT periodo, dias_asignados, dias_consumidos, devengado FROM vacation_periods
                        WHERE user_id = %s ORDER BY periodo""", (caso["user_id"],))),
                "informes": sorted(f["tipo"] for f in await obtener_todos(
                    "SELECT tipo FROM informes_firmados WHERE user_id = %s", (caso["user_id"],))),
                "avisos": sorted(json_normal(await obtener_todos(
                    """SELECT user_id, tipo, severidad, titulo, mensaje FROM notifications
                        WHERE entidad_id = %s""", (caso["id"],))), key=str),
                "bitacora": json_normal(await obtener_todos(
                    "SELECT accion, detalle FROM audit_logs WHERE entidad_id = %s", (caso["id"],))),
            }, None)
    return resultado


async def test_cada_intento_termina_igual_en_las_dos_bases(muestra):
    desenlaces: Counter = Counter()
    for caso in _intentos(muestra, 350):
        foto_pg, err_pg = _en_pg(muestra, caso)
        foto_my, err_my = await _en_my(caso)
        if err_pg is not None:
            mensaje_pg, pista_pg, restriccion_pg = err_pg
            assert err_my is not None, f"PostgreSQL rechazó y MySQL aceptó: {err_pg} · {caso}"
            if restriccion_pg:
                assert err_my[2] == restriccion_pg, caso
            else:
                assert err_my[:2] == (mensaje_pg, pista_pg), caso
            desenlaces[mensaje_pg.split(":")[0][:50] if not restriccion_pg else restriccion_pg] += 1
        else:
            assert err_my is None, f"MySQL rechazó y PostgreSQL aceptó: {err_my} · {caso}"
            assert foto_my == foto_pg, caso
            desenlaces[f"creada ({foto_pg['fila']['ruta_aprobacion']})"] += 1
    # Que la muestra de intentos haya recorrido de verdad las reglas.
    print("\n" + "\n".join(f"{n:4}  {k}" for k, n in desenlaces.most_common()))
    assert desenlaces["creada (estandar)"] > 20 and desenlaces["creada (rrhh_primero)"] > 5
    assert len(desenlaces) >= 10


@pytest.mark.parametrize("tipo", ["vacacion", "permiso"])
async def test_previsualizar_igual(muestra, tipo):
    tipos = [f["id"] for f in muestra.execute("select id from permission_types order by id").fetchall()]
    for caso in list(_intentos(muestra, 120, semilla=11)):
        pt = caso.get("permission_type_id") or (tipos[0] if tipo == "permiso" else None)
        en_pg = muestra.execute("select previsualizar_solicitud(%s, %s, %s, %s, %s) as p",
                                (caso["user_id"], tipo, caso["fecha_inicio"], caso["fecha_fin"], pt)).fetchone()["p"]
        en_my = await solicitudes.previsualizar_solicitud(caso["user_id"], tipo, caso["fecha_inicio"],
                                                          caso["fecha_fin"], pt)
        assert json_normal(en_my) == json_normal(en_pg), caso


@pytest.mark.parametrize("segundo, choca", [
    ((dt.time(12), dt.time(14)), False),     # entra justo cuando el otro termina
    ((dt.time(7), dt.time(9)), False),       # termina justo cuando el otro empieza
    ((dt.time(11, 30), dt.time(13)), True),  # se pisan media hora
    ((dt.time(10), dt.time(11)), True),      # dentro del otro
])
async def test_dos_permisos_por_horas_el_mismo_dia(muestra, segundo, choca):
    """Salir a las 12:00 de uno y entrar a las 12:00 del otro no es un choque."""
    persona = muestra.execute("""select u.id from users u where u.activo and u.rol = 'empleado'
                                   and not exists (select 1 from requests r where r.user_id = u.id)
                                 order by cedula limit 1""").fetchone()["id"]
    tipo = muestra.execute("""select id from permission_types
                               where admite_horas and not requiere_justificacion and activo
                                 and (max_horas is null or max_horas >= 3)
                               order by id limit 1""").fetchone()["id"]
    dia = muestra.execute("select current_date + 20 as d").fetchone()["d"]
    while dia.weekday() >= 5:
        dia += dt.timedelta(days=1)
    base = {"user_id": persona, "tipo": "permiso", "permission_type_id": tipo, "fecha_inicio": dia,
            "fecha_fin": dia, "descripcion": "Permiso por horas de la prueba",
            "justificacion": "Justificación del permiso", "adjunto": False}
    primero = {**base, "id": uuid.uuid4(), "hora_inicio": dt.time(9), "hora_fin": dt.time(12)}
    otro = {**base, "id": uuid.uuid4(), "hora_inicio": segundo[0], "hora_fin": segundo[1]}

    muestra.execute("savepoint dos")
    try:
        cols = [c for c in primero if c != "adjunto"]
        muestra.execute(f"insert into requests ({', '.join(cols)}) values ({', '.join(['%s'] * len(cols))})",
                        tuple(primero[c] for c in cols))
        folio_pg = muestra.execute("select folio from requests where id = %s",
                                   (primero["id"],)).fetchone()["folio"]
        _, err_pg = _en_pg(muestra, otro)
    finally:
        muestra.execute("rollback to savepoint dos")

    err_my = None
    async with y_deshacer():
        folio_my = (await solicitudes.crear_solicitud({k: v for k, v in primero.items() if k != "adjunto"}))["folio"]
        try:
            await solicitudes.crear_solicitud({k: v for k, v in otro.items() if k != "adjunto"})
        except errores.ReglaDeNegocio as exc:
            err_my = (exc.mensaje, exc.pista, "")

    assert (err_pg is not None) == choca
    if choca:
        # Cada base numera con su propio contador, que no devuelve números al
        # deshacer: el folio citado tiene que ser el del primer permiso EN
        # ESA BASE. Fuera de eso, el mensaje es el mismo.
        assert f"Nº {folio_pg}," in err_pg[0] and err_pg[1] == f"solape|{folio_pg}"
        assert f"Nº {folio_my}," in err_my[0] and err_my[1] == f"solape|{folio_my}"
        assert err_my[0].replace(str(folio_my), "#") == err_pg[0].replace(str(folio_pg), "#")
    else:
        assert err_my is None
