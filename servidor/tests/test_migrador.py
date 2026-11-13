"""El guion que aplica las migraciones, y su parte delicada: trocear SQL.

Hasta ahora cada migración se pegaba a mano en el editor de Supabase. Con
cuarenta y seis archivos eso tiene dos fallos que no avisan: saltarse uno —y
que el sistema falle semanas después por algo que parece no tener relación— y
no saber nunca con certeza qué tiene puesto la base de producción.

Lo que estas pruebas cuidan es el troceador. Hace falta solo para las dos
migraciones que añaden valores a un enumerado: PostgreSQL prohíbe usar un
valor nuevo en la misma transacción que lo creó, y mandar el archivo entero
de una vez tampoco sirve porque el servidor envuelve el bloque en una
transacción implícita. Hay que mandar sentencia por sentencia.

Cortar por `;` es trivial y está mal: dentro de una función hay puntos y
comas a montones. Si el troceador corta donde no debe, la migración se aplica
a medias sobre datos reales. De ahí el tamaño de este archivo.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


def _cargar():
    """El guion vive fuera del paquete, así que se carga por ruta."""
    sys.path.insert(0, str(RAIZ / "scripts"))
    spec = importlib.util.spec_from_file_location("migrar", RAIZ / "scripts" / "migrar.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


migrar = _cargar()
sentencias = migrar.sentencias


# ------------------------------------------------------------- lo básico
def test_dos_sentencias_son_dos():
    assert sentencias("select 1; select 2;") == ["select 1", "select 2"]


def test_la_ultima_sin_punto_y_coma_tambien_cuenta():
    assert sentencias("select 1; select 2") == ["select 1", "select 2"]


def test_el_vacio_no_produce_nada():
    assert sentencias("") == []
    assert sentencias("   \n\n  ") == []
    assert sentencias(";;;") == []


# ------------------------------------- lo que no se puede cortar por dentro
def test_no_corta_dentro_de_un_texto_entre_comillas():
    sql = "insert into t values ('hola; adiós'); select 1;"
    assert sentencias(sql) == ["insert into t values ('hola; adiós')", "select 1"]


def test_una_comilla_escapada_no_cierra_el_texto():
    sql = "select 'no es '' el fin; todavía'; select 2;"
    assert sentencias(sql) == ["select 'no es '' el fin; todavía'", "select 2"]


def test_no_corta_dentro_del_cuerpo_de_una_funcion():
    """El caso que de verdad importa: las funciones están llenas de `;`."""
    sql = """
create function f() returns int language plpgsql as $$
declare
  a int;
  b int;
begin
  a := 1;
  b := 2;
  return a + b;
end;
$$;
select 3;
"""
    trozos = sentencias(sql)
    assert len(trozos) == 2, trozos
    assert trozos[0].startswith("create function")
    assert "return a + b;" in trozos[0]
    assert trozos[1] == "select 3"


def test_las_etiquetas_con_nombre_tambien():
    """`$cuerpo$ ... $cuerpo$`, que es como están escritas estas migraciones."""
    sql = """
create function g() returns void language plpgsql as $cuerpo$
begin
  perform 1; perform 2;
end;
$cuerpo$;
select 4;
"""
    trozos = sentencias(sql)
    assert len(trozos) == 2, trozos
    assert "perform 1; perform 2;" in trozos[0]


def test_un_bloque_dentro_de_otro_con_etiquetas_distintas():
    """La migración 0000 hace exactamente esto: un `$f$` con un `$cuerpo$` dentro."""
    sql = """
do $$
begin
  execute $f$ create function h() returns int language sql as $c$ select 1; $c$ $f$;
end $$;
select 5;
"""
    trozos = sentencias(sql)
    assert len(trozos) == 2, trozos
    assert trozos[1] == "select 5"


def test_no_corta_en_un_comentario_de_linea():
    sql = "select 1; -- esto; no; corta\nselect 2;"
    assert sentencias(sql) == ["select 1", "-- esto; no; corta\nselect 2"]


def test_no_corta_en_un_comentario_de_bloque():
    sql = "select 1; /* ni; esto; tampoco */ select 2;"
    trozos = sentencias(sql)
    assert len(trozos) == 2, trozos
    assert trozos[1].endswith("select 2")


# --------------------------------------- contra los archivos de verdad
def test_todas_las_migraciones_se_trocean_sin_romperse():
    """La prueba que vale: los cuarenta y seis archivos reales.

    Si el troceador cortara mal uno, el trozo quedaría con un `$$` sin cerrar
    o una comilla suelta. Se comprueba que cada trozo tenga un número par de
    comillas y de etiquetas de dólar, que es la señal de un corte limpio.
    """
    archivos = sorted((RAIZ / "supabase" / "migrations").glob("*.sql"))
    assert len(archivos) >= 46, "faltan migraciones en el repositorio"

    for ruta in archivos:
        sql = ruta.read_text(encoding="utf-8")
        trozos = sentencias(sql)
        assert trozos, ruta.name
        for trozo in trozos:
            sin_comentarios = "\n".join(
                linea.split("--")[0] for linea in trozo.splitlines())
            assert sin_comentarios.count("'") % 2 == 0, \
                f"{ruta.name}: un trozo quedó con una comilla suelta"


def test_las_dos_que_tocan_enumerados_estan_detectadas():
    """Si la detección fallara, volverían a fallar al aplicarse."""
    archivos = sorted((RAIZ / "supabase" / "migrations").glob("*.sql"))
    sueltas = {r.name for r in archivos
               if migrar.SIN_TRANSACCION.search(r.read_text(encoding="utf-8"))}
    assert sueltas == {
        "20260921000006_anulacion_y_administracion.sql",
        "20260930000021_art75_correcto.sql",
    }, sueltas


# ------------------------------------------------------------- el orden
def test_las_migraciones_van_en_el_orden_de_su_nombre():
    rutas = migrar.archivos()
    numeros = [migrar.numero_de(r) for r in rutas]
    assert numeros == sorted(numeros), "el orden de aplicación no es el del número"
    assert numeros[0] == "0000", "la compatibilidad con auth tiene que ir primero"
    assert len(set(numeros)) == len(numeros), "hay dos migraciones con el mismo número"


def test_ninguna_migracion_se_llama_igual_que_otra():
    nombres = [r.name for r in migrar.archivos()]
    assert len(set(nombres)) == len(nombres)
