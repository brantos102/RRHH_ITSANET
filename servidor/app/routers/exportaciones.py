"""Exportar datos a pedido de Talento Humano o Administración.

Cinco informes —personal, saldos por período, solicitudes, vacaciones
gozadas y documentos firmados— filtrados por persona, grupo de personas,
área, cargo, sede, ciudad, tipo de contrato, equipo de un jefe, estado y
período.

TRAZABILIDAD (LOPDP): cada archivo que sale del sistema lleva un folio
(EXP-AAAA-NNNN), el motivo por el que se generó, quién y cuándo, y queda
registrado en `exportaciones` con la huella SHA-256 del archivo entregado.
Si mañana aparece un Excel con datos del personal donde no debía, el folio
impreso en él dice de dónde salió.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from ..audit import registrar
from ..db import ejecutar, obtener_todos, obtener_uno, transaccion
from ..deps import exigir_rol
from ..exportar import Informe, entregar

router = APIRouter(prefix="/admin/exportaciones", tags=["Exportaciones"])
RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]
LIMITE = 20000

ESTADOS = {"pendiente_jefe": "Espera al jefe", "pendiente_rrhh": "Espera a Talento Humano",
           "aprobado": "Aprobada", "rechazado": "Rechazada", "cancelado": "Cancelada",
           "pendiente_anulacion": "Anulación pedida"}

TIPOS = {
    "personas": {
        "titulo": "Personal",
        "descripcion": "Una fila por persona: cargo, área, sede, ingreso, antigüedad, contrato, "
                       "jefe y saldo de vacaciones.",
        "periodo": False,
        "columnas": [("cedula", "Cédula"), ("nombre", "Nombre"), ("cargo", "Cargo"),
                     ("area", "Área"), ("sede", "Sede"), ("ciudad", "Ciudad"),
                     ("fecha_ingreso", "Ingreso"), ("anios", "Años"), ("contrato", "Contrato"),
                     ("jefe", "Jefe inmediato"), ("dias_anuales", "Días por año"),
                     ("saldo", "Saldo (días)"), ("estado", "Estado"), ("email", "Correo")],
    },
    "saldos": {
        "titulo": "Saldos por período",
        "descripcion": "Una fila por período de vacaciones: asignados, gozados y saldo.",
        "periodo": False,
        "columnas": [("cedula", "Cédula"), ("nombre", "Nombre"), ("area", "Área"),
                     ("periodo", "Período"), ("desde", "Desde"), ("hasta", "Hasta"),
                     ("asignados", "Asignados"), ("consumidos", "Gozados"),
                     ("saldo", "Saldo"), ("situacion", "Situación")],
    },
    "solicitudes": {
        "titulo": "Solicitudes",
        "descripcion": "Vacaciones y permisos que empiezan en el período, con su estado, "
                       "aprobaciones y si el documento quedó firmado y escaneado.",
        "periodo": True,
        "columnas": [("folio", "N.º"), ("cedula", "Cédula"), ("nombre", "Nombre"),
                     ("area", "Área"), ("tipo", "Tipo"), ("inicio", "Inicio"), ("fin", "Fin"),
                     ("dias", "Días"), ("fines_semana", "Fines de semana"),
                     ("estado", "Estado"), ("creada", "Pedida el"),
                     ("jefe_aprobo", "Aprobó el jefe"), ("rrhh_aprobo", "Aprobó T. Humano"),
                     ("documento", "Documento")],
    },
    "historial": {
        "titulo": "Vacaciones gozadas",
        "descripcion": "Cada vacación gozada en el período, venga del sistema o de la hoja "
                       "histórica.",
        "periodo": True,
        "columnas": [("cedula", "Cédula"), ("nombre", "Nombre"), ("area", "Área"),
                     ("inicio", "Inicio"), ("fin", "Fin"), ("dias", "Días"),
                     ("procedencia", "Procedencia"), ("folio", "N.º solicitud")],
    },
    "documentos": {
        "titulo": "Documentos firmados",
        "descripcion": "Documentos emitidos en el período: impresiones, fechas anteriores "
                       "usadas, firma y escaneo (y si se subió el mismo día).",
        "periodo": True,
        "columnas": [("folio", "Folio"), ("tipo", "Documento"), ("cedula", "Cédula"),
                     ("nombre", "Nombre"), ("emitido", "Emitido"), ("impresiones", "Impresiones"),
                     ("fechas_anteriores", "Fechas anteriores"), ("firmado", "Firmado el"),
                     ("escaneado", "Escaneo subido el"), ("mismo_dia", "Escaneo el mismo día"),
                     ("huella", "Huella (SHA-256)")],
    },
}


class Filtros(BaseModel):
    personas: list[str] = Field(default_factory=list, max_length=1000)
    areas: list[str] = Field(default_factory=list, max_length=200)
    cargos: list[str] = Field(default_factory=list, max_length=300)
    sedes: list[str] = Field(default_factory=list, max_length=20)
    ciudades: list[str] = Field(default_factory=list, max_length=200)
    contratos: list[str] = Field(default_factory=list, max_length=10)
    jefe_id: str | None = Field(None, max_length=40)
    estado: Literal["activos", "inactivos", "todos"] = "activos"
    desde: date | None = None
    hasta: date | None = None


class Pedido(BaseModel):
    tipo: Literal["personas", "saldos", "solicitudes", "historial", "documentos"]
    formato: Literal["xlsx", "pdf", "csv"] = "xlsx"
    filtros: Filtros = Filtros()
    motivo: str = Field(..., min_length=10, max_length=300)


class Previa(BaseModel):
    tipo: Literal["personas", "saldos", "solicitudes", "historial", "documentos"]
    filtros: Filtros = Filtros()


def _en(columna: str, valores: list[str], params: list) -> str:
    params.extend(valores)
    return f"{columna} IN ({', '.join(['%s'] * len(valores))})"


def _donde(f: Filtros) -> tuple[str, list]:
    """Condiciones sobre `u` (users) y `g` (regiones). Solo marcadores %s."""
    c, p = [], []
    if f.estado == "activos":
        c.append("u.activo")
    elif f.estado == "inactivos":
        c.append("NOT u.activo")
    if f.personas:
        c.append(_en("u.id", f.personas, p))
    if f.areas:
        c.append(_en("u.departamento", f.areas, p))
    if f.cargos:
        c.append(_en("u.cargo", f.cargos, p))
    if f.sedes:
        c.append(_en("COALESCE(u.region, 'sierra')", f.sedes, p))
    if f.ciudades:
        c.append(_en("TRIM(u.ciudad)", f.ciudades, p))
    if f.contratos:
        c.append(_en("u.tipo_contrato", f.contratos, p))
    if f.jefe_id:
        c.append("u.jefe_id = %s")
        p.append(f.jefe_id)
    return (" AND ".join(c) or "TRUE"), p


def _periodo(f: Filtros) -> tuple[date, date]:
    hoy = date.today()
    desde = f.desde or date(hoy.year, 1, 1)
    hasta = f.hasta or hoy
    if desde > hasta:
        desde, hasta = hasta, desde
    return desde, hasta


async def _filas(tipo: str, f: Filtros, limite: int = LIMITE) -> list[dict]:
    donde, p = _donde(f)
    base = """FROM users u LEFT JOIN regiones g ON g.codigo = COALESCE(u.region, 'sierra')"""
    if tipo == "personas":
        sql = f"""SELECT u.cedula, u.nombre, u.cargo, u.departamento AS area, g.sede, u.ciudad,
                         u.fecha_ingreso, anios_cumplidos(u.fecha_ingreso) AS anios,
                         u.tipo_contrato AS contrato, j.nombre AS jefe,
                         dias_por_antiguedad(anios_cumplidos(u.fecha_ingreso) + 1) AS dias_anuales,
                         u.dias_vacaciones AS saldo, IF(u.activo, 'Activo', 'Inactivo') AS estado,
                         u.email
                    {base} LEFT JOIN users j ON j.id = u.jefe_id
                   WHERE {donde} ORDER BY u.nombre LIMIT {int(limite)}"""
    elif tipo == "saldos":
        sql = f"""SELECT u.cedula, u.nombre, u.departamento AS area, v.periodo,
                         v.fecha_desde AS desde, v.fecha_hasta AS hasta,
                         v.dias_asignados AS asignados, v.dias_consumidos AS consumidos,
                         v.dias_saldo AS saldo,
                         CASE WHEN v.caducado THEN 'Caducado' WHEN v.devengado THEN 'Cumplido'
                              ELSE 'En curso' END AS situacion
                    {base} JOIN vacation_periods v ON v.user_id = u.id
                   WHERE {donde} ORDER BY u.nombre, v.periodo LIMIT {int(limite)}"""
    elif tipo == "solicitudes":
        desde, hasta = _periodo(f)
        p += [desde, hasta]
        sql = f"""SELECT r.folio, u.cedula, u.nombre, u.departamento AS area,
                         IF(r.tipo = 'vacacion', 'Vacaciones', COALESCE(pt.nombre, 'Permiso')) AS tipo,
                         r.fecha_inicio AS inicio, r.fecha_fin AS fin, r.dias_solicitados AS dias,
                         r.fines_semana, r.estado, r.created_at AS creada,
                         r.jefe_aprobado_en AS jefe_aprobo, r.rrhh_aprobado_en AS rrhh_aprobo,
                         (SELECT CASE WHEN i.escaneo_ruta IS NOT NULL THEN 'Concluido (escaneado)'
                                      WHEN i.firmado_en IS NOT NULL THEN 'Firmado, sin escaneo'
                                      ELSE 'Sin firmar' END
                            FROM informes_firmados i WHERE i.request_id = r.id AND i.tipo = 'solicitud'
                           ORDER BY i.emitido_en DESC LIMIT 1) AS documento
                    {base} JOIN requests r ON r.user_id = u.id
                    LEFT JOIN permission_types pt ON pt.id = r.permission_type_id
                   WHERE {donde} AND r.fecha_inicio BETWEEN %s AND %s
                   ORDER BY r.fecha_inicio, u.nombre LIMIT {int(limite)}"""
    elif tipo == "historial":
        desde, hasta = _periodo(f)
        p += [desde, hasta]
        sql = f"""SELECT u.cedula, u.nombre, u.departamento AS area, h.fecha_inicio AS inicio,
                         h.fecha_fin AS fin, h.dias,
                         IF(h.procedencia = 'historico', 'Hoja histórica', 'Sistema') AS procedencia,
                         h.folio
                    {base} JOIN v_historial_vacaciones h ON h.user_id = u.id
                   WHERE {donde} AND h.fecha_inicio BETWEEN %s AND %s
                   ORDER BY h.fecha_inicio, u.nombre LIMIT {int(limite)}"""
    else:   # documentos
        desde, hasta = _periodo(f)
        p += [desde, hasta]
        sql = f"""SELECT i.folio, IF(i.tipo = 'trazabilidad', 'Constancia de goce', 'Solicitud') AS tipo,
                         u.cedula, u.nombre, i.emitido_en AS emitido, i.impresiones,
                         (SELECT COUNT(*) FROM impresiones_papel x
                           WHERE x.informe_id = i.id AND x.retroactiva) AS fechas_anteriores,
                         i.firmado_en AS firmado, i.escaneo_subido_en AS escaneado,
                         CASE WHEN i.escaneo_subido_en IS NULL THEN 'Pendiente'
                              WHEN DATE(i.escaneo_subido_en) <= DATE(COALESCE(i.firmado_en, i.escaneo_subido_en))
                              THEN 'Sí' ELSE 'No' END AS mismo_dia,
                         i.escaneo_sha256 AS huella
                    {base} JOIN informes_firmados i ON i.user_id = u.id
                   WHERE {donde} AND DATE(i.emitido_en) BETWEEN %s AND %s
                   ORDER BY i.emitido_en, u.nombre LIMIT {int(limite)}"""
    filas = await obtener_todos(sql, tuple(p))
    for fila in filas:
        if "estado" in fila and tipo == "solicitudes":
            fila["estado"] = ESTADOS.get(fila["estado"], fila["estado"])
        for clave in ("saldo", "asignados", "consumidos", "dias", "dias_anuales"):
            if clave in fila and fila[clave] is not None:
                fila[clave] = float(fila[clave])
    return filas


async def _describir(f: Filtros, tipo: str) -> list[tuple[str, str]]:
    """Los filtros en claro, para el encabezado del archivo."""
    d: list[tuple[str, str]] = [("Estado del personal", {"activos": "Activos", "inactivos": "Inactivos",
                                                         "todos": "Todos"}[f.estado])]
    if f.personas:
        nombres = await obtener_todos(
            f"SELECT nombre FROM users WHERE id IN ({', '.join(['%s'] * len(f.personas))}) ORDER BY nombre",
            tuple(f.personas))
        d.append(("Personas", ", ".join(n["nombre"] for n in nombres[:20])
                  + (f" y {len(nombres) - 20} más" if len(nombres) > 20 else "")))
    for etiqueta, valores in (("Áreas", f.areas), ("Cargos", f.cargos), ("Ciudades", f.ciudades),
                              ("Contratos", f.contratos)):
        if valores:
            d.append((etiqueta, ", ".join(valores)))
    if f.sedes:
        sedes = {s["codigo"]: s["sede"] for s in await obtener_todos("SELECT codigo, sede FROM regiones")}
        d.append(("Sedes", ", ".join(sedes.get(s, s) for s in f.sedes)))
    if f.jefe_id:
        jefe = await obtener_uno("SELECT nombre FROM users WHERE id = %s", (f.jefe_id,))
        d.append(("Equipo de", (jefe or {}).get("nombre", "—")))
    if TIPOS[tipo]["periodo"]:
        desde, hasta = _periodo(f)
        d.append(("Período", f"{desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"))
    return d


@router.get("/opciones")
async def opciones(usuario: RRHH) -> dict:
    """Qué se puede exportar y con qué valores filtrar."""
    async def valores(sql: str) -> list[str]:
        return [f["v"] for f in await obtener_todos(sql) if f["v"]]
    return {
        "tipos": [{"clave": k, "titulo": v["titulo"], "descripcion": v["descripcion"],
                   "periodo": v["periodo"], "columnas": [c[1] for c in v["columnas"]]}
                  for k, v in TIPOS.items()],
        "areas": await valores("SELECT DISTINCT departamento AS v FROM users ORDER BY 1"),
        "cargos": await valores("SELECT DISTINCT cargo AS v FROM users ORDER BY 1"),
        "ciudades": await valores("SELECT DISTINCT TRIM(ciudad) AS v FROM users ORDER BY 1"),
        "sedes": await obtener_todos("SELECT codigo, sede FROM regiones WHERE activo ORDER BY orden, codigo"),
        "contratos": ["indefinido", "eventual", "ocasional", "temporada", "obra_cierta", "prueba",
                      "aprendizaje", "pasantia"],
        "jefes": [{**j, "id": str(j["id"])} for j in await obtener_todos(
            """SELECT DISTINCT j.id, j.nombre FROM users j JOIN users u ON u.jefe_id = j.id
                WHERE u.activo ORDER BY j.nombre""")],
    }


@router.post("/previa")
async def previa(datos: Previa, usuario: RRHH) -> dict:
    """Cuántas filas saldrían y las primeras, antes de generar el archivo."""
    filas = await _filas(datos.tipo, datos.filtros, LIMITE + 1)
    columnas = TIPOS[datos.tipo]["columnas"]
    return {"filas": min(len(filas), LIMITE), "excede": len(filas) > LIMITE,
            "columnas": [c[1] for c in columnas],
            "muestra": [[f.get(c[0]) for c in columnas] for f in filas[:8]]}


@router.post("")
async def exportar(datos: Pedido, request: Request, usuario: RRHH) -> Response:
    filas = await _filas(datos.tipo, datos.filtros)
    if not filas:
        raise HTTPException(status_code=422, detail={"mensaje": "No hay datos con esos filtros."})
    t = TIPOS[datos.tipo]
    async with transaccion():
        anio = date.today().year
        n = (await obtener_uno(
            "SELECT COUNT(*) + 1 AS n FROM exportaciones WHERE YEAR(created_at) = %s FOR UPDATE",
            (anio,)))["n"]
        folio = f"EXP-{anio}-{int(n):04d}"
        informe = Informe(titulo=t["titulo"], columnas=t["columnas"], filas=filas,
                          filtros=await _describir(datos.filtros, datos.tipo),
                          generado_por=f"{usuario['nombre']} ({usuario['rol']})",
                          folio=folio, motivo=datos.motivo.strip())
        respuesta = entregar(informe, datos.formato)
        huella = hashlib.sha256(respuesta.body).hexdigest()
        await ejecutar(
            """INSERT INTO exportaciones (folio, tipo, formato, filtros, motivo, filas, sha256, generado_por)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (folio, datos.tipo, datos.formato, json.dumps(datos.filtros.model_dump(mode="json")),
             datos.motivo.strip(), len(filas), huella, str(usuario["id"])))
    await registrar(request, "datos_exportados", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="exportaciones", entidad_id=folio,
                    detalle={"tipo": datos.tipo, "formato": datos.formato, "filas": len(filas),
                             "motivo": datos.motivo.strip(), "sha256": huella})
    respuesta.headers["X-Folio"] = folio
    respuesta.headers["X-Sha256"] = huella
    respuesta.headers["Content-Disposition"] = (
        f'attachment; filename="{folio}-{datos.tipo}.{datos.formato}"')
    return respuesta


@router.get("")
async def historial(usuario: RRHH, limite: int = 100) -> list[dict]:
    """Quién exportó qué, cuándo y para qué."""
    filas = await obtener_todos(
        """SELECT e.folio, e.tipo, e.formato, e.filtros, e.motivo, e.filas, e.sha256, e.created_at,
                  u.nombre AS por
             FROM exportaciones e LEFT JOIN users u ON u.id = e.generado_por
            ORDER BY e.created_at DESC LIMIT %s""", (min(max(limite, 1), 500),))
    return [{**f, "filtros": json.loads(f["filtros"]) if isinstance(f["filtros"], str) else f["filtros"],
             "titulo": TIPOS.get(f["tipo"], {}).get("titulo", f["tipo"])} for f in filas]
