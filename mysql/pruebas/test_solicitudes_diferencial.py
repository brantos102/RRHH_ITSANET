"""El ciclo de vida de una solicitud, contra PostgreSQL, paso a paso.

Es la prueba que más importa de la migración. Aprobar unas vacaciones
descuenta días de los períodos de la persona —primero de los más antiguos—,
deja un movimiento con el saldo antes y después, avisa al colaborador y
queda en la bitácora. Anularlas devuelve los días en el orden inverso. Si
MySQL hiciera cualquiera de esas cosas distinto, el saldo de alguien
cambiaría en silencio.

Se arma la MISMA situación en las dos bases —la misma persona, los mismos
períodos, la misma solicitud— y se ejecutan los MISMOS cambios de estado.
Después de cada paso se comparan los períodos, el saldo de la ficha, los
movimientos, las notificaciones y la auditoría. Tienen que coincidir.

Todo se hace dentro de una transacción que se deshace al terminar, en las
dos bases: la referencia de PostgreSQL queda como estaba.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from decimal import Decimal

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row  # noqa: E402

PG_URL = os.environ.get(
    "PG_REFERENCIA_URL", "postgresql://postgres@/rrhh_v4?host=/var/lib/pgtest&port=55432")

CEDULA_PERSONA = "1750000000"
CEDULA_JEFE = "1750000018"
CEDULA_RRHH = "1750000026"
CEDULA_NUEVA = "1750000034"


# --------------------------------------------------------------- las bases
@pytest.fixture
def pg():
    try:
        con = psycopg.connect(PG_URL, row_factory=dict_row)   # sin autocommit: se deshace
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Sin la base PostgreSQL de referencia ({exc}); no se puede comparar")
    yield con
    con.rollback()
    con.close()


@pytest.fixture
def my(db):
    """La conexión MySQL de conftest, que se deshace al terminar."""
    import pymysql
    db.connection.cursorclass = pymysql.cursors.DictCursor
    return db


class Bases:
    """Ejecuta lo mismo en las dos bases. Los ids se generan aquí, iguales."""

    def __init__(self, pg, my):
        self.pg, self.my = pg, my
        self.ids: dict[str, str] = {}

    def pg_q(self, sql, params=()):
        return self.pg.execute(sql, params).fetchall()

    def my_q(self, sql, params=()):
        self.my.execute(sql, params)
        return list(self.my.fetchall())

    def persona(self, clave, cedula, nombre, rol, ingreso, jefe=None):
        pid = str(uuid.uuid4())
        self.ids[clave] = pid
        jefe_id = self.ids.get(jefe) if jefe else None
        self.pg.execute(
            """insert into public.users (id, cedula, nombre, email, rol, fecha_ingreso, jefe_id)
               values (%s, %s, %s, %s, %s, %s, %s)""",
            (pid, cedula, nombre, f"{cedula}@dif.test", rol, ingreso, jefe_id))
        # PostgreSQL genera los períodos solo al crear a la persona; en MySQL
        # eso lo hará la aplicación. Se parte de cero en las dos y cada prueba
        # pone exactamente los períodos que necesita.
        self.pg.execute("delete from public.vacation_movements where user_id = %s", (pid,))
        self.pg.execute("delete from public.vacation_periods where user_id = %s", (pid,))
        self.my.execute(
            """INSERT INTO users (id, cedula, nombre, email, rol, fecha_ingreso, jefe_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (pid, cedula, nombre, f"{cedula}@dif.test", rol, ingreso, jefe_id))
        return pid

    def periodo(self, clave, n, asignados, consumidos=0, fds_obl=2, fds_cons=0, devengado=True):
        desde = dt.date(2018 + n, 1, 1)
        fila = (str(uuid.uuid4()), self.ids[clave], n, desde, desde.replace(year=desde.year + 1),
                asignados, consumidos, desde.replace(year=desde.year + 4), devengado, fds_obl, fds_cons)
        sql = """insert into {}vacation_periods (id, user_id, periodo, fecha_desde, fecha_hasta,
                   dias_asignados, dias_consumidos, vence_en, devengado,
                   fines_semana_obligatorios, fines_semana_consumidos)
                 values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        self.pg.execute(sql.format("public."), fila)
        self.my.execute(sql.format(""), fila)

    def solicitud(self, clave, tipo, inicio, fin, permiso=None, excepcion=False):
        """La crea en PostgreSQL —donde los disparadores calculan días y
        estado— y copia ESA fila a MySQL. Lo que se compara es lo que pasa
        después, que es lo que vive en los disparadores de MySQL."""
        rid = str(uuid.uuid4())
        self.pg.execute(
            """insert into public.requests (id, user_id, tipo, fecha_inicio, fecha_fin, descripcion,
                 justificacion, permission_type_id, bloque_menor_justificado)
               values (%s, %s, %s, %s, %s, 'Prueba diferencial de la migración',
                 'Justificación suficiente para la prueba diferencial', %s, %s)""",
            (rid, self.ids[clave], tipo, inicio, fin, permiso, excepcion))
        self._periodos_como_en_mysql(self.ids[clave])
        fila = self.pg.execute("select * from public.requests where id = %s", (rid,)).fetchone()
        cols = ["id", "user_id", "tipo", "fecha_inicio", "fecha_fin", "descripcion", "justificacion",
                "permission_type_id", "dias_solicitados", "saldo_al_solicitar", "es_adelanto",
                "estado", "jefe_id", "fines_semana", "ruta_aprobacion", "bloque_menor_justificado",
                "region"]
        valores = [str(v) if isinstance(v, uuid.UUID) else v for v in (fila[c] for c in cols)]
        self.my.execute(
            f"INSERT INTO requests ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
            valores)
        return rid

    def _periodos_como_en_mysql(self, uid):
        """Al crear la solicitud, PostgreSQL completa los períodos que le
        faltan a la persona según su fecha de ingreso (generar_periodos_
        vacaciones). En MySQL eso lo hará la aplicación antes de insertar, y
        no es lo que compara esta prueba: se devuelven los períodos de
        PostgreSQL al estado con que empezaron las dos bases."""
        self.my.execute("""SELECT periodo, dias_asignados, devengado, vence_en, caducado
                             FROM vacation_periods WHERE user_id = %s""", (uid,))
        en_my = list(self.my.fetchall())
        self.pg.execute("delete from public.vacation_periods where user_id = %s and not (periodo = any(%s))",
                        (uid, [r["periodo"] for r in en_my]))
        for r in en_my:
            self.pg.execute("""update public.vacation_periods
                                  set dias_asignados = %s, devengado = %s, vence_en = %s, caducado = %s
                                where user_id = %s and periodo = %s""",
                            (r["dias_asignados"], bool(r["devengado"]), r["vence_en"], bool(r["caducado"]),
                             uid, r["periodo"]))

    def cambiar(self, rid, **campos):
        """El mismo UPDATE en las dos. Devuelve el error de cada una, si hubo."""
        asig = ", ".join(f"{k} = %s" for k in campos)
        vals = [str(v) if isinstance(v, uuid.UUID) else v for v in campos.values()]
        errores = []
        for nombre, ejecutar in (("pg", lambda: self.pg.execute(
                f"update public.requests set {asig} where id = %s", (*vals, rid))),
                                 ("my", lambda: self.my.execute(
                f"UPDATE requests SET {asig} WHERE id = %s", (*vals, rid)))):
            try:
                if nombre == "pg":
                    self.pg.execute("savepoint antes")
                ejecutar()
                errores.append(None)
            except Exception as exc:  # noqa: BLE001
                if nombre == "pg":
                    self.pg.execute("rollback to savepoint antes")
                errores.append(str(exc).split("\n")[0])
        return errores

    # ----------------------------------------------------- lo que se compara
    def estado_de(self, clave, rid=None) -> tuple[dict, dict]:
        uid = self.ids[clave]
        return self._foto(uid, rid, pg=True), self._foto(uid, rid, pg=False)

    def _foto(self, uid, rid, pg: bool):
        q = self.pg_q if pg else self.my_q
        p = "public." if pg else ""

        def num(v):
            return Decimal(str(v)).normalize() if v is not None else None

        periodos = [(r["periodo"], num(r["dias_consumidos"]), r["fines_semana_consumidos"])
                    for r in q(f"select periodo, dias_consumidos, fines_semana_consumidos "
                               f"from {p}vacation_periods where user_id = %s order by periodo", (uid,))]
        saldo = num(q(f"select dias_vacaciones from {p}users where id = %s", (uid,))[0]["dias_vacaciones"])
        movimientos = [(num(r["dias"]), num(r["saldo_previo"]), num(r["saldo_nuevo"]), r["motivo"])
                       for r in q(f"select dias, saldo_previo, saldo_nuevo, motivo from {p}vacation_movements "
                                  f"where user_id = %s order by created_at, id", (uid,))]
        foto = {"periodos": periodos, "saldo": saldo, "movimientos": movimientos}
        if rid:
            sol = q(f"select estado, rechazado_en_etapa, dias_solicitados, qr_hash is not null as con_qr, "
                    f"rrhh_aprobado_en is not null as fecha_rrhh, jefe_aprobado_en is not null as fecha_jefe, "
                    f"rechazado_en is not null as fecha_rechazo, anulacion_resuelta_en is not null as resuelta "
                    f"from {p}requests where id = %s", (rid,))[0]
            foto["solicitud"] = {k: (bool(v) if k.startswith(("con_", "fecha_", "resuelta")) else
                                     num(v) if k == "dias_solicitados" else str(v) if v is not None else None)
                                 for k, v in sol.items()}
            # Avisos al colaborador (los de Talento Humano dependen de cuántas
            # personas de RRHH hay en cada base, y se cuentan aparte).
            foto["avisos"] = [(r["tipo"], r["severidad"], r["titulo"], r["mensaje"])
                              for r in q(f"select tipo, severidad, titulo, mensaje from {p}notifications "
                                         f"where entidad_id = %s and user_id = %s order by created_at, titulo",
                                         (rid, uid))]
            foto["bitacora"] = [(r["accion"], _json(r["detalle"]))
                                for r in q(f"select accion, detalle from {p}audit_logs "
                                           f"where entidad_id = %s order by created_at, accion", (rid,))]
        return foto


def _json(v):
    """La bitácora guarda JSON; se normaliza para comparar sin importar el orden de las claves."""
    d = json.loads(v) if isinstance(v, (str, bytes)) else v
    return json.dumps({k: (str(Decimal(str(x)).normalize()) if isinstance(x, (int, float, Decimal))
                           and not isinstance(x, bool) else x)
                       for k, x in (d or {}).items()}, sort_keys=True)


def _sin_folio(foto):
    """El folio sale de una secuencia distinta en cada base: se quita del texto."""
    import re
    foto["avisos"] = sorted(tuple(re.sub(r"Nº \d+", "Nº #", str(x)) for x in fila)
                            for fila in foto.get("avisos", []))
    # PostgreSQL congela now() durante toda la transacción y MySQL no: el
    # orden por hora no es comparable. Se comparan como conjuntos.
    foto["bitacora"] = sorted(foto.get("bitacora", []))
    return foto


@pytest.fixture
def bases(pg, my):
    b = Bases(pg, my)
    b.persona("jefe", CEDULA_JEFE, "Jefe Diferencial", "jefe", dt.date(2015, 1, 1))
    b.persona("persona", CEDULA_PERSONA, "Persona Diferencial", "empleado", dt.date(2019, 1, 1), jefe="jefe")
    b.persona("rrhh", CEDULA_RRHH, "Talento Diferencial", "rrhh", dt.date(2016, 1, 1))
    return b


def _igual(bases, rid=None, clave="persona"):
    en_pg, en_my = bases.estado_de(clave, rid)
    assert _sin_folio(en_my) == _sin_folio(en_pg)


# ------------------------------------------------------------- escenarios
def test_aprobar_descuenta_de_los_periodos_mas_antiguos(bases):
    bases.periodo("persona", 1, 15, consumidos=5)     # le quedan 10
    bases.periodo("persona", 2, 15)                   # 15
    bases.periodo("persona", 3, 15, devengado=False)  # en curso
    _igual(bases)
    rid = bases.solicitud("persona", "vacacion", dt.date(2026, 12, 1), dt.date(2026, 12, 14))
    _igual(bases, rid)
    assert bases.cambiar(rid, estado="pendiente_rrhh", jefe_aprobado_por=bases.ids["jefe"]) == [None, None]
    _igual(bases, rid)
    assert bases.cambiar(rid, estado="aprobado", rrhh_aprobado_por=bases.ids["rrhh"]) == [None, None]
    _igual(bases, rid)


def test_lo_que_no_alcanza_queda_adelantado_en_el_periodo_en_curso(bases):
    # Alguien que entró este año: todavía no tiene un año completo.
    bases.persona("nueva", CEDULA_NUEVA, "Ingreso Reciente", "empleado", dt.date(2026, 3, 1), jefe="jefe")
    bases.periodo("nueva", 1, 6, devengado=False)
    rid = bases.solicitud("nueva", "vacacion", dt.date(2026, 12, 1), dt.date(2026, 12, 21))
    # Un adelanto compromete días que no existen: lo decide Talento Humano.
    assert bases.pg_q("select es_adelanto, estado from public.requests where id = %s", (rid,)) == [
        {"es_adelanto": True, "estado": "pendiente_rrhh"}]
    assert bases.cambiar(rid, estado="aprobado") == [None, None]
    _igual(bases, rid, clave="nueva")
    _, en_my = bases.estado_de("nueva", rid)
    assert en_my["saldo"] == -15, "el período en curso queda en negativo: 6 - 21"
    assert bases.cambiar(rid, estado="cancelado") == [None, None]
    _igual(bases, rid, clave="nueva")


def test_anular_devuelve_los_dias_del_mas_nuevo_al_mas_antiguo(bases):
    bases.periodo("persona", 1, 15, consumidos=5)
    bases.periodo("persona", 2, 15)
    bases.periodo("persona", 3, 15)
    rid = bases.solicitud("persona", "vacacion", dt.date(2026, 12, 1), dt.date(2026, 12, 21))
    bases.cambiar(rid, estado="pendiente_rrhh")
    bases.cambiar(rid, estado="aprobado")
    _igual(bases, rid)
    _, en_my = bases.estado_de("persona", rid)
    assert [p[1] for p in en_my["periodos"]] == [15, 11, 0], "21 días: los 10 que quedan del 1.º y 11 del 2.º"
    assert bases.cambiar(rid, estado="pendiente_anulacion", anulacion_motivo="Se suspendió el viaje") == [None, None]
    _igual(bases, rid)
    assert bases.cambiar(rid, estado="cancelado") == [None, None]
    _igual(bases, rid)


def test_negar_la_anulacion_no_toca_el_saldo(bases):
    bases.periodo("persona", 1, 15)
    rid = bases.solicitud("persona", "vacacion", dt.date(2026, 12, 1), dt.date(2026, 12, 8))
    bases.cambiar(rid, estado="pendiente_rrhh")
    bases.cambiar(rid, estado="aprobado")
    bases.cambiar(rid, estado="pendiente_anulacion", anulacion_motivo="Ya no viajo")
    assert bases.cambiar(rid, estado="aprobado", anulacion_rechazada_motivo="El puesto queda descubierto") == [None, None]
    _igual(bases, rid)


def test_rechazar_marca_la_etapa(bases):
    bases.periodo("persona", 1, 15)
    rid = bases.solicitud("persona", "vacacion", dt.date(2026, 12, 1), dt.date(2026, 12, 8))
    assert bases.cambiar(rid, estado="rechazado", motivo_rechazo="Cierre de inventario") == [None, None]
    _igual(bases, rid)


def test_rechazo_en_talento_humano(bases):
    bases.periodo("persona", 1, 15)
    rid = bases.solicitud("persona", "vacacion", dt.date(2026, 12, 1), dt.date(2026, 12, 8))
    bases.cambiar(rid, estado="pendiente_rrhh")
    assert bases.cambiar(rid, estado="rechazado", motivo_rechazo="Sin saldo suficiente") == [None, None]
    _igual(bases, rid)


def test_los_fines_de_semana_se_cargan_igual(bases):
    bases.periodo("persona", 1, 15, fds_obl=2)
    bases.periodo("persona", 2, 15, fds_obl=2)
    # Del lunes 30 de noviembre al domingo 13 de diciembre: dos fines de semana completos.
    rid = bases.solicitud("persona", "vacacion", dt.date(2026, 11, 30), dt.date(2026, 12, 13))
    bases.cambiar(rid, estado="pendiente_rrhh")
    bases.cambiar(rid, estado="aprobado")
    _igual(bases, rid)
    _, en_my = bases.estado_de("persona", rid)
    assert sum(p[2] for p in en_my["periodos"]) == 2, "dos fines de semana completos cargados"
    bases.cambiar(rid, estado="cancelado")
    _igual(bases, rid)


def test_un_permiso_que_no_descuenta_no_toca_el_saldo(bases, pg):
    bases.periodo("persona", 1, 15)
    tipo = pg.execute("""select id from public.permission_types
                          where not descuenta_vacaciones and not requiere_adjunto and activo
                          order by id limit 1""").fetchone()["id"]
    rid = bases.solicitud("persona", "permiso", dt.date(2026, 12, 2), dt.date(2026, 12, 2), permiso=tipo)
    bases.cambiar(rid, estado="pendiente_rrhh")
    assert bases.cambiar(rid, estado="aprobado") == [None, None]
    _igual(bases, rid)


def test_un_permiso_que_si_descuenta_toca_el_saldo(bases, pg):
    bases.periodo("persona", 1, 15)
    fila = pg.execute("""select id from public.permission_types
                          where descuenta_vacaciones and activo order by id limit 1""").fetchone()
    if fila is None:
        pytest.skip("No hay ningún tipo de permiso que descuente vacaciones en la referencia")
    rid = bases.solicitud("persona", "permiso", dt.date(2026, 12, 2), dt.date(2026, 12, 3), permiso=fila["id"])
    bases.cambiar(rid, estado="pendiente_rrhh")
    assert bases.cambiar(rid, estado="aprobado") == [None, None]
    _igual(bases, rid)


def test_excepcion_pasa_primero_por_talento_humano_y_despues_por_el_jefe(bases):
    """La ruta «rrhh_primero»: Talento Humano autoriza la excepción y la
    devuelve al jefe, que es quien la aprueba al final."""
    bases.periodo("persona", 1, 15)
    rid = bases.solicitud("persona", "vacacion", dt.date(2026, 12, 1), dt.date(2026, 12, 4), excepcion=True)
    _igual(bases, rid)
    assert bases.cambiar(rid, estado="pendiente_jefe", rrhh_aprobado_por=bases.ids["rrhh"]) == [None, None]
    _igual(bases, rid)
    assert bases.cambiar(rid, estado="aprobado", jefe_aprobado_por=bases.ids["jefe"]) == [None, None]
    _igual(bases, rid)


# ------------------------------------------------- lo que las dos rechazan
def test_saltarse_una_etapa_se_rechaza_en_las_dos(bases):
    bases.periodo("persona", 1, 15)
    rid = bases.solicitud("persona", "vacacion", dt.date(2026, 12, 1), dt.date(2026, 12, 8))
    en_pg, en_my = bases.cambiar(rid, estado="aprobado")
    assert en_pg and en_my, "las dos tienen que rechazar pendiente_jefe -> aprobado"
    assert "Transición de estado inválida: pendiente_jefe -> aprobado" in en_pg
    assert "Transición de estado inválida: pendiente_jefe -> aprobado" in en_my
    _igual(bases, rid)


def test_no_se_mueven_las_fechas_de_algo_aprobado(bases):
    bases.periodo("persona", 1, 15)
    rid = bases.solicitud("persona", "vacacion", dt.date(2026, 12, 1), dt.date(2026, 12, 8))
    bases.cambiar(rid, estado="pendiente_rrhh")
    bases.cambiar(rid, estado="aprobado")
    en_pg, en_my = bases.cambiar(rid, fecha_fin=dt.date(2026, 12, 20))
    assert en_pg and en_my
    assert "en estado aprobado" in en_pg and "en estado aprobado" in en_my
    _igual(bases, rid)


def test_mientras_esta_con_el_jefe_las_fechas_si_se_mueven_y_se_recalculan(bases):
    bases.periodo("persona", 1, 15)
    rid = bases.solicitud("persona", "vacacion", dt.date(2026, 12, 1), dt.date(2026, 12, 8))
    assert bases.cambiar(rid, fecha_fin=dt.date(2026, 12, 20)) == [None, None]
    _igual(bases, rid)


def test_talento_humano_recibe_el_aviso_en_las_dos(bases):
    """Uno por cada persona activa de RRHH o administración de cada base."""
    bases.periodo("persona", 1, 15)
    rid = bases.solicitud("persona", "vacacion", dt.date(2026, 12, 1), dt.date(2026, 12, 8))
    bases.cambiar(rid, estado="pendiente_rrhh")
    for consulta, p in ((bases.pg_q, "public."), (bases.my_q, "")):
        esperados = consulta(f"select count(*) as n from {p}users where rol in ('rrhh','admin') and activo")[0]["n"]
        recibidos = consulta(f"select count(*) as n from {p}notifications where entidad_id = %s "
                             f"and user_id <> %s and tipo = 'solicitud_pendiente' "
                             f"and titulo like %s", (rid, bases.ids["jefe"], "%aprobada por el jefe"))[0]["n"]
        assert recibidos == esperados
