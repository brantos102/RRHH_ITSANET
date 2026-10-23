"""Convertir valores de PostgreSQL a MySQL, en un solo sitio.

Lo usan dos cosas que tienen que coincidir exactamente: los datos de
referencia de la instalación (0003_datos_base.sql) y el traslado de datos del
día del corte. Si convirtieran distinto, un mismo dato quedaría escrito de
dos formas según por dónde entró.

Las conversiones que importan:

  uuid               texto de 36 caracteres
  boolean            1 / 0
  timestamptz        hora de Ecuador SIN zona. PostgreSQL guarda el instante
                     en UTC; MySQL lo guarda en hora local, que es como lo
                     lee cualquiera que abra la base y como lo escribe la
                     aplicación (que fija la zona -05:00 en cada conexión).
  jsonb, arreglos    texto JSON, sin escapar las tildes
  numeric            texto, para no pasar por un float y perder un centavo
  inet               texto
"""
from __future__ import annotations

import datetime as dt
import decimal
import ipaddress
import json
import uuid
from typing import Any

ECUADOR = dt.timezone(dt.timedelta(hours=-5))


def a_mysql(valor: Any) -> Any:
    """Un valor leído de PostgreSQL, listo para pasarlo como parámetro a MySQL."""
    if valor is None:
        return None
    if isinstance(valor, bool):
        return 1 if valor else 0
    if isinstance(valor, uuid.UUID):
        return str(valor)
    if isinstance(valor, dt.datetime):
        if valor.tzinfo is not None:
            valor = valor.astimezone(ECUADOR).replace(tzinfo=None)
        return valor
    if isinstance(valor, (dt.date, dt.time)):
        return valor
    if isinstance(valor, decimal.Decimal):
        return str(valor)
    if isinstance(valor, (dict, list)):
        return json.dumps(valor, ensure_ascii=False, default=str)
    if isinstance(valor, (ipaddress.IPv4Address, ipaddress.IPv6Address,
                          ipaddress.IPv4Interface, ipaddress.IPv6Interface)):
        return str(valor)
    return valor


def literal_sql(valor: Any) -> str:
    """El mismo valor, escrito como literal SQL para un archivo .sql."""
    import pymysql.converters as conv

    v = a_mysql(valor)
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, dt.datetime):
        return f"'{v.isoformat(sep=' ')}'"
    if isinstance(v, (dt.date, dt.time)):
        return f"'{v.isoformat()}'"
    return "'" + conv.escape_string(str(v)) + "'"
