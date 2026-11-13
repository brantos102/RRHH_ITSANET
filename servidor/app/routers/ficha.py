"""Ficha personal: lo que cada quien corrige y lo que Talento Humano valida.

Un teléfono cambia, una dirección cambia, el contacto de emergencia cambia.
Obligar a que Talento Humano teclee cada uno de esos datos para 351 personas
es un cuello de botella sin ningún beneficio: nadie conoce mejor su propio
número. Pero el nombre, el correo o el estado civil sí deben validarse,
porque de ahí salen documentos.

Los cuatro niveles —libre, confirmado, revisado y bloqueado— viven en la
tabla `campos_ficha`, y quien decide es la base: una comprobación que solo
esté en este archivo la puede saltar cualquier cliente alterado.

«Confirmado» es el nivel del correo: lo cambia la propia persona, sin que
nadie apruebe nada, pero no rige hasta que abre el enlace que llega a la
dirección nueva. No hace falta que Talento Humano valide un buzón —nadie
conoce mejor el suyo—; hace falta comprobar que el buzón existe y es suyo,
y eso lo comprueba el buzón mismo.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from .. import notificaciones
from ..audit import ip_del_cliente, registrar
from ..db import ejecutar, obtener_todos, obtener_uno
from ..deps import exigir_rol, usuario_actual
from ..errores import traducir
from ..reglas import ficha as reglas_ficha
from ..reglas import ingreso
from ..reglas.personal import rrhh_de_region

router = APIRouter(tags=["Ficha personal"])


async def avisar_pedidos_a_rrhh(tareas: BackgroundTasks, persona_id, nombre: str, cedula: str,
                                pedidos: list[tuple[str, str]]) -> None:
    """Que Talento Humano se entere de un pedido de cambio de ficha.

    Dos vías, porque una sola fallaba en silencio: un pedido hecho desde
    «Mi ficha» quedaba guardado sin avisar a nadie, y quien revisa no sabía
    que tenía algo pendiente. Ahora:
      · aviso dentro del sistema (la campana) a cada integrante de Talento
        Humano de la sede —o a todo el equipo si la sede no tiene a nadie—,
        con enlace directo a «Cambios de ficha»;
      · y el correo de siempre.
    """
    if not pedidos:
        return
    region = (await obtener_uno("select coalesce(region, 'sierra') as r from users where id = %s",
                                (str(persona_id),)) or {}).get("r", "sierra")
    destinos = await rrhh_de_region(region)
    ultimo = await obtener_uno("select max(id) as n from cambios_ficha where user_id = %s",
                               (str(persona_id),))
    resumen = "; ".join(f"{e}: {v}" for e, v in pedidos)
    for d in destinos:
        if str(d["id"]) == str(persona_id):
            continue                      # nadie se avisa a sí mismo
        try:
            await ejecutar(
                """insert into notifications (user_id, tipo, severidad, titulo, mensaje, entidad,
                                              entidad_id, clave_dedupe, accion_url)
                   values (%s, 'informativo', 'advertencia', %s, %s, 'cambios_ficha', %s, %s, %s)
                   on duplicate key update clave_dedupe = clave_dedupe""",
                (str(d["id"]), "Cambio de ficha por revisar",
                 f"{nombre} ({cedula}) pide: {resumen}"[:500], str(persona_id),
                 f"ficha-{persona_id}-{(ultimo or {}).get('n')}-{d['id']}",
                 # Directo a resolverlo: abre Pendientes con los pedidos de
                 # esa persona listos para aprobar o rechazar.
                 f"administracion.html?atender=persona:{persona_id}#pendientes"))
        except Exception:  # noqa: BLE001 — el correo sale igual
            pass
    correos = [{"email": d["email"], "nombre": d["nombre"]} for d in destinos
               if d.get("email") and str(d["id"]) != str(persona_id)]
    if correos:
        tareas.add_task(notificaciones.avisar_correccion_de_ficha, correos, nombre, cedula, pedidos)

RRHH = Annotated[dict, Depends(exigir_rol("rrhh", "admin"))]


class CambiosLibres(BaseModel):
    """Solo campos de nivel «libre». La base rechaza cualquier otro."""
    telefono: str | None = Field(None, max_length=20)
    telefono_alternativo: str | None = Field(None, max_length=20)
    direccion: str | None = Field(None, max_length=200)
    tipo_sangre: str | None = Field(None, max_length=3)
    # La foto ya no es una dirección que se escribe: se sube a /mi-ficha/foto.
    # El domicilio por partes, como se escribe en Ecuador.
    domicilio_provincia: str | None = Field(None, max_length=60)
    domicilio_canton: str | None = Field(None, max_length=80)
    domicilio_parroquia: str | None = Field(None, max_length=80)
    domicilio_calle: str | None = Field(None, max_length=120)
    domicilio_numero: str | None = Field(None, max_length=20)
    domicilio_interseccion: str | None = Field(None, max_length=120)
    domicilio_referencia: str | None = Field(None, max_length=200)


DOMICILIO = ("domicilio_calle", "domicilio_numero", "domicilio_interseccion", "domicilio_parroquia",
             "domicilio_canton", "domicilio_provincia", "domicilio_referencia")


def direccion_de(d: dict) -> str | None:
    """«Av. Amazonas N34-12 y Naciones Unidas, Iñaquito, Quito, Pichincha (frente al parque)»."""
    calle = " ".join(x for x in (d.get("domicilio_calle"), d.get("domicilio_numero")) if x)
    if calle and d.get("domicilio_interseccion"):
        calle += f" y {d['domicilio_interseccion']}"
    partes = [x for x in (calle, d.get("domicilio_parroquia"), d.get("domicilio_canton"),
                          d.get("domicilio_provincia")) if x]
    texto = ", ".join(partes)
    if d.get("domicilio_referencia"):
        texto += f" ({d['domicilio_referencia']})"
    return texto[:200] or None


class Telefono(BaseModel):
    numero: str = Field(..., min_length=7, max_length=20)
    tipo: Literal["celular", "fijo", "trabajo", "otro"] = "celular"
    etiqueta: str | None = Field(None, max_length=60)


class SolicitudCambio(BaseModel):
    campo: str = Field(..., max_length=40)
    valor: str = Field(..., min_length=1, max_length=200)
    motivo: str | None = Field(None, max_length=300)


class DecisionCambio(BaseModel):
    accion: Literal["aprobar", "rechazar"]
    motivo: str | None = Field(None, max_length=300)


class CorreoNuevo(BaseModel):
    email: EmailStr


class ConfirmacionDatos(BaseModel):
    """Lo que la persona responde sobre su cargo y su jefe.

    Confirmar es tan informativo como corregir: saber que alguien miró su
    cargo y dijo «es este» separa lo verificado de lo que nadie revisó desde
    que se cargó la planilla.
    """
    cargo_correcto: bool
    jefe_correcto: bool
    cargo_propuesto: str | None = Field(None, max_length=120)
    jefe_propuesto_id: str | None = Field(None, max_length=40)


@router.get("/mi-ficha")
async def mi_ficha(usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    """La ficha completa, con qué se puede tocar y qué no, y por qué."""
    persona = await obtener_uno(
        """select u.cedula, u.nombre, u.email, u.telefono,
                  u.telefono_alternativo, u.direccion, u.ciudad, u.provincia,
                  u.tipo_sangre, u.foto_url, u.fecha_nacimiento, u.estado_civil,
                  u.fecha_ingreso, u.cargo, u.departamento, u.bodega, u.cliente,
                  u.centro_costo, u.dias_vacaciones, u.tiene_discapacidad,
                  u.porcentaje_discapacidad, u.carnet_conadis, u.tipo_discapacidad,
                  u.sustituto_discapacidad, u.tipo_contrato, u.contrato_fin,
                  u.domicilio_provincia, u.domicilio_canton, u.domicilio_parroquia, u.domicilio_calle,
                  u.domicilio_numero, u.domicilio_interseccion, u.domicilio_referencia,
                  coalesce(u.region, 'sierra') as region,
                  r.nombre as region_nombre, r.sede as region_sede,
                  j.nombre as jefe_nombre, u.jefe_id,
                  u.cargo_confirmado_en, u.jefe_confirmado_en, u.correo_pendiente,
                  (select c.email from confirmaciones_correo c
                    where c.user_id = u.id and c.confirmado_en is null
                      and c.expira_en > NOW(6)
                    order by c.created_at desc limit 1) as correo_por_confirmar
             from users u
             left join regiones r on r.codigo = coalesce(u.region, 'sierra')
             left join users j on j.id = u.jefe_id
            where u.id = %s""",
        (usuario["id"],),
    )
    campos = await obtener_todos(
        "select campo, etiqueta, nivel, ayuda from campos_ficha order by orden"
    )
    contactos = await obtener_todos(
        """select id, nombre, parentesco, telefono, es_principal
             from emergency_contacts where user_id = %s order by es_principal desc""",
        (usuario["id"],),
    )
    pendientes = await obtener_todos(
        """select c.id, c.campo, f.etiqueta, c.valor_anterior, c.valor_nuevo,
                  c.estado, c.motivo_rechazo, c.created_at
             from cambios_ficha c
             join campos_ficha f on f.campo = c.campo
            where c.user_id = %s order by c.created_at desc limit 20""",
        (usuario["id"],),
    )
    telefonos = await _telefonos(usuario["id"])
    return {
        "telefonos": telefonos,
        "persona": {**persona,
                    "dias_vacaciones": float(persona["dias_vacaciones"] or 0),
                    "jefe_id": str(persona["jefe_id"]) if persona["jefe_id"] else None},
        "campos": campos,
        "contactos_emergencia": [{**c, "id": str(c["id"])} for c in contactos],
        "cambios": [{**c, "id": int(c["id"])} for c in pendientes],
    }


@router.patch("/mi-ficha")
async def corregir_ficha(
    datos: CambiosLibres, request: Request,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Los datos que la persona corrige sola, sin esperar a nadie."""
    cambios = {k: v for k, v in datos.model_dump().items() if v is not None}
    if not cambios:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": "No hay nada que cambiar."},
        )

    try:
        await reglas_ficha.actualizar_ficha_libre(usuario["id"], cambios)
        if any(k in cambios for k in DOMICILIO):
            # La dirección de una línea (la que usan documentos e informes)
            # se arma con las partes del domicilio.
            d = await obtener_uno(f"select {', '.join(DOMICILIO)} from users where id = %s",
                                  (usuario["id"],))
            await ejecutar("update users set direccion = %s where id = %s",
                           (direccion_de(d), usuario["id"]))
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "ficha_actualizada", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"campos": list(cambios)})
    return {"mensaje": "Sus datos quedaron actualizados."}


@router.post("/mi-ficha/cambios", status_code=status.HTTP_201_CREATED)
async def pedir_cambio(
    datos: SolicitudCambio, request: Request, tareas: BackgroundTasks,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Lo que Talento Humano debe validar antes de que rija."""
    try:
        nuevo = await reglas_ficha.solicitar_cambio_ficha(
            usuario["id"], datos.campo, datos.valor, datos.motivo)
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "ficha_cambio_solicitado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"campo": datos.campo})
    etiqueta = (await obtener_uno("select etiqueta from campos_ficha where campo = %s",
                                  (datos.campo,)) or {}).get("etiqueta", datos.campo)
    valor = datos.valor
    if datos.campo == "jefe_id":
        valor = (await obtener_uno("select nombre from users where id = %s", (datos.valor,))
                 or {}).get("nombre", datos.valor)
    await avisar_pedidos_a_rrhh(tareas, usuario["id"], usuario["nombre"], usuario["cedula"],
                                [(etiqueta, valor)])
    return {
        "id": int(nuevo),
        "mensaje": "Su solicitud quedó registrada. Talento Humano la revisará; "
                   "mientras tanto sigue vigente el dato anterior.",
    }


class Discapacidad(BaseModel):
    """Lo que la persona declara sobre discapacidad. Dato sensible (LOPDP
    Art. 26): lo ven solo la persona y Talento Humano, y rige cuando Talento
    Humano lo verifica con el carné o el certificado."""
    tiene: bool
    porcentaje: int | None = Field(None, ge=1, le=100)
    tipo: Literal["fisica", "intelectual", "auditiva", "visual", "psicosocial", "multiple"] | None = None
    carnet: str | None = Field(None, max_length=40)
    sustituto: bool = False


@router.post("/mi-ficha/discapacidad", status_code=status.HTTP_201_CREATED)
async def declarar_discapacidad(
    datos: Discapacidad, request: Request, tareas: BackgroundTasks,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    if datos.tiene and (not datos.porcentaje or not (datos.carnet or "").strip()):
        raise HTTPException(status_code=422, detail={
            "mensaje": "Indique el porcentaje y el número del carné o certificado."})
    actual = await obtener_uno(
        """select tiene_discapacidad, porcentaje_discapacidad, carnet_conadis,
                  tipo_discapacidad, sustituto_discapacidad from users where id = %s""",
        (usuario["id"],))
    propuestos = {
        "porcentaje_discapacidad": str(datos.porcentaje) if datos.tiene and datos.porcentaje else None,
        "carnet_conadis": ((datos.carnet or "").strip() or None) if datos.tiene else None,
        "tipo_discapacidad": datos.tipo if datos.tiene else None,
        "tiene_discapacidad": "1" if datos.tiene else "0",
        "sustituto_discapacidad": "1" if datos.sustituto else "0",
    }
    pedidos = []
    try:
        for campo, valor in propuestos.items():
            previo = actual.get(campo)
            previo = None if previo is None else str(int(previo)) if isinstance(previo, (bool, int)) \
                else str(previo)
            if valor is None or valor == previo:
                continue
            await reglas_ficha.solicitar_cambio_ficha(usuario["id"], campo, valor, None)
            etiqueta = (await obtener_uno("select etiqueta from campos_ficha where campo = %s",
                                          (campo,)) or {}).get("etiqueta", campo)
            pedidos.append((etiqueta, {"1": "Sí", "0": "No"}.get(valor, valor)
                            if campo.endswith("discapacidad") and valor in ("0", "1") else valor))
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc
    if not pedidos:
        return {"mensaje": "No hay cambios respecto de lo registrado."}
    await registrar(request, "ficha_cambio_solicitado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"campos": "discapacidad"})
    await avisar_pedidos_a_rrhh(tareas, usuario["id"], usuario["nombre"], usuario["cedula"], pedidos)
    return {"mensaje": "Registrado. Talento Humano lo verificará con su carné o certificado; "
                       "llévelo o envíelo por el chat."}


@router.post("/mi-ficha/correo", status_code=status.HTTP_202_ACCEPTED)
async def cambiar_correo(
    datos: CorreoNuevo, request: Request, tareas: BackgroundTasks,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Declara una dirección nueva. Rige cuando se abre el enlace, no antes.

    Que el correo anterior siga vigente mientras tanto no es un detalle: si
    se aplicara de inmediato y la dirección tuviera un dedazo, la persona se
    quedaría sin poder recibir ni el código de acceso ni el de confirmación,
    y haría falta que Talento Humano la rescatara a mano.
    """
    try:
        fila = await reglas_ficha.pedir_confirmacion_correo(
            usuario["id"], str(datos.email), ip_del_cliente(request))
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    tareas.add_task(notificaciones.confirmar_direccion,
                    str(datos.email), usuario["nombre"], str(fila["token"]))

    await registrar(request, "correo_confirmacion_pedida", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], detalle={"correo": str(datos.email)})
    return {
        "mensaje": f"Le enviamos un enlace a {datos.email}. Ábralo dentro de las "
                   "próximas 24 horas para que la dirección empiece a regir. "
                   "Mientras tanto sigue vigente la anterior.",
    }


@router.post("/mi-ficha/confirmar")
async def confirmar_cargo_y_jefe(
    datos: ConfirmacionDatos, request: Request, tareas: BackgroundTasks,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """«Mi cargo es este y mi jefe es este» —o cuál debería ser.

    Lo que se confirma se marca y se acabó. Lo que se corrige NO se aplica:
    de quién depende cada persona decide a dónde va su solicitud a
    autorizarse, así que lo confirma Talento Humano. La persona señala, la
    empresa resuelve.
    """
    pedidos: list[tuple[str, str]] = []
    errores: list[str] = []

    if datos.cargo_correcto:
        await ejecutar("update users set cargo_confirmado_en = NOW(6) where id = %s",
                       (usuario["id"],))
    elif datos.cargo_propuesto and datos.cargo_propuesto.strip():
        try:
            await reglas_ficha.solicitar_cambio_ficha(
                usuario["id"], "cargo", datos.cargo_propuesto.strip(),
                "Corrección declarada al confirmar los datos")
            pedidos.append(("Cargo que indica", datos.cargo_propuesto.strip()))
        except Exception as exc:  # noqa: BLE001
            errores.append(str(getattr(traducir(exc), "detail", exc)))
    else:
        errores.append("Indique cuál es su cargo si el registrado no corresponde.")

    if datos.jefe_correcto:
        await ejecutar("update users set jefe_confirmado_en = NOW(6) where id = %s",
                       (usuario["id"],))
    elif datos.jefe_propuesto_id:
        jefe = await obtener_uno(
            "select nombre from v_jefaturas where id = %s", (datos.jefe_propuesto_id,)
        )
        if jefe is None:
            errores.append("La jefatura señalada no está en la lista.")
        else:
            try:
                await reglas_ficha.solicitar_cambio_ficha(
                    usuario["id"], "jefe_id", datos.jefe_propuesto_id,
                    "Corrección declarada al confirmar los datos")
                pedidos.append(("Jefe que indica", jefe["nombre"]))
            except Exception as exc:  # noqa: BLE001
                errores.append(str(getattr(traducir(exc), "detail", exc)))
    else:
        errores.append("Elija quién es su jefe inmediato si el registrado no corresponde.")

    if errores and not pedidos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": " ".join(errores)},
        )

    await avisar_pedidos_a_rrhh(tareas, usuario["id"], usuario["nombre"], usuario["cedula"],
                                pedidos)

    await registrar(request, "ficha_datos_confirmados", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"],
                    detalle={"cargo_ok": datos.cargo_correcto,
                             "jefe_ok": datos.jefe_correcto,
                             "correcciones": len(pedidos)})

    return {
        "mensaje": ("Gracias. Talento Humano revisará lo que indicó; mientras "
                    "tanto sigue vigente el dato anterior."
                    if pedidos else "Sus datos quedaron confirmados."),
        "en_revision": [e for e, _ in pedidos],
        "avisos": errores,
    }


@router.get("/catalogos/jefaturas")
async def jefaturas(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    """Nombre, cargo y área. Nada más: es lo justo para elegir en una lista.

    Ni cédula ni correo ni teléfono de terceros —LOPDP, Art. 10: no se
    recaba ni se expone más de lo que la finalidad exige—.
    """
    filas = await obtener_todos(
        """select id, nombre, cargo, departamento, a_cargo
             from v_jefaturas where id <> %s""",
        (usuario["id"],),
    )
    return [{**f, "id": str(f["id"]), "a_cargo": int(f["a_cargo"] or 0)} for f in filas]


@router.get("/rrhh/cambios-ficha")
async def cambios_pendientes(usuario: RRHH) -> list[dict]:
    """Bandeja de Talento Humano, acotada a su región."""
    if usuario["rol"] == "admin":
        filtro, parametros = "TRUE", ()
    else:
        # Su sede, y además las sedes que no tienen a nadie de Talento Humano:
        # si no, esos pedidos no los vería nadie.
        filtro = ("(region = %s or region not in "
                  "(select distinct region from v_rrhh_por_region))")
        parametros = (usuario.get("region") or "sierra",)

    filas = await obtener_todos(
        f"""select id, user_id, cedula, persona, departamento, ciudad, region,
                   campo, etiqueta, valor_anterior, valor_nuevo, motivo, created_at,
                   anterior_legible, nuevo_legible
              from v_cambios_ficha_pendientes where {filtro}""",
        parametros,
    )
    return [{**f, "id": int(f["id"]), "user_id": str(f["user_id"])} for f in filas]


@router.post("/rrhh/cambios-ficha/{cambio_id}")
async def resolver_cambio(
    cambio_id: int, datos: DecisionCambio, request: Request, usuario: RRHH,
) -> dict:
    if datos.accion == "rechazar" and len((datos.motivo or "").strip()) < 5:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"mensaje": "Indique por qué se rechaza: la persona debe saber qué corregir."},
        )
    try:
        fila = await reglas_ficha.resolver_cambio_ficha(
            cambio_id, datos.accion == "aprobar", usuario["id"], datos.motivo)
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    await registrar(request, "ficha_cambio_resuelto", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"],
                    detalle={"cambio": cambio_id, "accion": datos.accion})
    return {
        "mensaje": ("Cambio aplicado." if datos.accion == "aprobar"
                    else "Cambio rechazado. Se le avisó a la persona."),
        "campo": fila["campo"],
    }


# ------------------------------------------------------------ ficha inicial
# Lo que se pide al entrar por primera vez, antes de usar el sistema. Qué se
# pide lo decide Talento Humano (`ficha_inicial_campos`); lo que ya consta o
# ya se confirmó no se vuelve a pedir (reglas/ingreso.py).

class FichaInicialSesion(BaseModel):
    fecha_nacimiento: date | None = None
    fecha_ingreso_correcta: bool | None = None
    fecha_ingreso_propuesta: date | None = None
    fecha_ingreso_motivo: str | None = Field(None, max_length=300)
    jefe_correcto: bool | None = None
    jefe_propuesto_id: str | None = Field(None, max_length=40)
    # Si su jefe no está en la lista: nombres y apellidos, para que Talento
    # Humano lo registre.
    jefe_nombre_propuesto: str | None = Field(None, max_length=120)
    cargo_correcto: bool | None = None
    cargo_propuesto: str | None = Field(None, max_length=120)
    departamento_propuesto: str | None = Field(None, max_length=120)
    telefono: str | None = Field(None, max_length=20)
    emergencia_nombre: str | None = Field(None, max_length=120)
    emergencia_parentesco: Literal[
        "conyuge", "conviviente", "hijo", "padre", "madre", "hermano",
        "abuelo", "nieto", "suegro", "cunado", "otro",
    ] | None = None
    emergencia_telefono: str | None = Field(None, max_length=20)


def _digitos(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


@router.get("/catalogos/cargos")
async def catalogo_cargos(usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    """Los cargos y áreas que existen en la empresa, para sugerirlos al
    escribir. No son datos personales: no dice quién ocupa cada uno."""
    # El catálogo oficial (Administración › Cargos y áreas), no lo que haya
    # escrito en cada ficha.
    from ..reglas import catalogo as reglas_catalogo
    elegir = await reglas_catalogo.para_elegir()
    ciudades = await obtener_todos("select ciudad, region from ciudades_region order by ciudad")
    return {"cargos": [{"id": c["id"], "cargo": c["nombre"], "area": c["area"]} for c in elegir["cargos"]],
            "areas": [a["nombre"] for a in elegir["areas"]],
            "ciudades": [{"ciudad": c["ciudad"], "region": c["region"]} for c in ciudades]}


@router.get("/mi-ficha/inicial")
async def ficha_inicial(usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    """Qué falta, con lo que ya consta para mostrarlo y confirmarlo."""
    falta = await ingreso.pendientes(usuario["id"])
    p = await obtener_uno(
        """select u.nombre, u.cedula, u.fecha_nacimiento, u.fecha_ingreso, u.cargo,
                  u.departamento, j.nombre as jefe_nombre, j.cargo as jefe_cargo
             from users u left join users j on j.id = u.jefe_id
            where u.id = %s""", (usuario["id"],))
    return {
        "pendientes": falta,
        "persona": p,
        "jefaturas": ([{**j, "id": str(j["id"])} for j in await obtener_todos(
            "select id, nombre, cargo, departamento from v_jefaturas where id <> %s order by nombre",
            (usuario["id"],))] if "jefe" in falta else []),
    }


@router.post("/mi-ficha/inicial")
async def guardar_ficha_inicial(
    datos: FichaInicialSesion, request: Request, tareas: BackgroundTasks,
    usuario: Annotated[dict, Depends(usuario_actual)],
) -> dict:
    """Guarda lo respondido. Lo que la persona no puede cambiar sola —su fecha
    de ingreso, su jefe, su cargo— va como pedido a Talento Humano."""
    falta = await ingreso.pendientes(usuario["id"])
    uid = str(usuario["id"])
    hoy = date.today()
    errores: list[str] = []

    if "fecha_nacimiento" in falta:
        n = datos.fecha_nacimiento
        if n is None:
            errores.append("su fecha de nacimiento")
        elif not (date(hoy.year - 90, 1, 1) <= n <= date(hoy.year - 15, 12, 31)):
            raise HTTPException(status_code=422, detail={
                "mensaje": "Revise su fecha de nacimiento: no parece correcta."})
    if "fecha_ingreso" in falta:
        if datos.fecha_ingreso_correcta is None:
            errores.append("si su fecha de ingreso es correcta")
        elif datos.fecha_ingreso_correcta is False:
            if datos.fecha_ingreso_propuesta is None:
                errores.append("la fecha de ingreso que usted indica")
            elif datos.fecha_ingreso_propuesta > hoy:
                raise HTTPException(status_code=422, detail={
                    "mensaje": "La fecha de ingreso que indica no puede ser futura."})
    if "jefe" in falta:
        if datos.jefe_correcto is None:
            errores.append("si su jefe inmediato es correcto")
        elif datos.jefe_correcto is False and not datos.jefe_propuesto_id \
                and len((datos.jefe_nombre_propuesto or "").split()) < 2:
            errores.append("quién es su jefe inmediato (elíjalo o escriba nombres y apellidos)")
    if "cargo" in falta:
        sin_cargo = not ((await obtener_uno("select nullif(trim(coalesce(cargo, '')), '') as c "
                                            "from users where id = %s", (uid,))) or {}).get("c")
        if sin_cargo and not (datos.cargo_propuesto or "").strip():
            # No hay nada que confirmar: se elige del catálogo.
            errores.append("su cargo (elíjalo de la lista)")
        elif datos.cargo_correcto is None:
            errores.append("si su cargo es correcto")
        elif datos.cargo_correcto is False and not ((datos.cargo_propuesto or "").strip()
                                                    or (datos.departamento_propuesto or "").strip()):
            errores.append("cuál es su cargo o su área")
    if "telefono" in falta and len(_digitos(datos.telefono)) < 7:
        errores.append("su teléfono personal")
    if "emergencia" in falta and not ((datos.emergencia_nombre or "").strip()
                                      and len(_digitos(datos.emergencia_telefono)) >= 7):
        errores.append("un contacto de emergencia con nombre y teléfono")
    if errores:
        raise HTTPException(status_code=422, detail={
            "mensaje": "Falta " + ", ".join(errores) + "."})

    pedidos: list[tuple[str, str]] = []
    try:
        if "fecha_nacimiento" in falta:
            await ejecutar("update users set fecha_nacimiento = %s "
                           "where id = %s and fecha_nacimiento is null",
                           (datos.fecha_nacimiento, uid))
        if "telefono" in falta:
            await ejecutar("update users set telefono = %s where id = %s",
                           (_digitos(datos.telefono), uid))
        if "emergencia" in falta:
            await ejecutar(
                """insert into emergency_contacts (user_id, nombre, parentesco, telefono, es_principal)
                   values (%s, %s, %s, %s, true)
                   on duplicate key update nombre = values(nombre),
                     parentesco = values(parentesco), telefono = values(telefono)""",
                (uid, datos.emergencia_nombre.strip(), datos.emergencia_parentesco or "otro",
                 _digitos(datos.emergencia_telefono)))
        if "fecha_ingreso" in falta:
            if datos.fecha_ingreso_correcta:
                await ejecutar("update users set fecha_ingreso_confirmada_en = NOW(6) where id = %s",
                               (uid,))
            else:
                motivo = (datos.fecha_ingreso_motivo or "").strip()
                await reglas_ficha.solicitar_cambio_ficha(
                    uid, "fecha_ingreso", datos.fecha_ingreso_propuesta.isoformat(),
                    "Fecha estimada declarada por el colaborador al ingresar"
                    + (f": {motivo}" if motivo else ""), permitir_bloqueado=True)
                pedidos.append(("Fecha de ingreso que indica",
                                f"{datos.fecha_ingreso_propuesta:%d/%m/%Y}"))
        if "jefe" in falta:
            if datos.jefe_correcto:
                await ejecutar("update users set jefe_confirmado_en = NOW(6) where id = %s", (uid,))
            elif datos.jefe_propuesto_id:
                jefe = await obtener_uno("select nombre from v_jefaturas where id = %s",
                                         (datos.jefe_propuesto_id,))
                if jefe is None:
                    raise HTTPException(status_code=422, detail={
                        "mensaje": "La jefatura elegida no está en la lista vigente."})
                await reglas_ficha.solicitar_cambio_ficha(
                    uid, "jefe_id", datos.jefe_propuesto_id,
                    "Corrección declarada por el colaborador al ingresar")
                pedidos.append(("Jefe que indica", jefe["nombre"]))
            else:
                await reglas_ficha.pedir_registro_de_jefe(
                    uid, datos.jefe_nombre_propuesto,
                    "Jefe que el colaborador indicó al ingresar y no está registrado")
                pedidos.append(("Jefe que indica (no está registrado)",
                                " ".join(datos.jefe_nombre_propuesto.split())))
        if "cargo" in falta:
            if datos.cargo_correcto:
                await ejecutar("update users set cargo_confirmado_en = NOW(6) where id = %s", (uid,))
            else:
                actual = await obtener_uno("select cargo, departamento from users where id = %s", (uid,))
                cargo = (datos.cargo_propuesto or "").strip()
                area = (datos.departamento_propuesto or "").strip()
                pidio = False
                if cargo and cargo != (actual["cargo"] or ""):
                    await reglas_ficha.solicitar_cambio_ficha(
                        uid, "cargo", cargo, "Cargo declarado por el colaborador al ingresar",
                        permitir_bloqueado=True)
                    pedidos.append(("Cargo que indica", cargo))
                    pidio = True
                if area and area != (actual["departamento"] or ""):
                    await reglas_ficha.solicitar_cambio_ficha(
                        uid, "departamento", area,
                        "Área declarada por el colaborador al ingresar", permitir_bloqueado=True)
                    pedidos.append(("Área que indica", area))
                    pidio = True
                if not pidio:
                    # Lo que escribió es lo que ya constaba: queda confirmado.
                    await ejecutar("update users set cargo_confirmado_en = NOW(6) where id = %s", (uid,))
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise traducir(exc) from exc

    quedan = await ingreso.pendientes(uid)
    if not quedan:
        await ejecutar("update users set ficha_completa = true, ficha_completada_en = NOW(6) "
                       "where id = %s and not ficha_completa", (uid,))
    await registrar(request, "ficha_inicial_guardada", user_id=uid, cedula=usuario["cedula"],
                    detalle={"respondido": falta, "pedidos": [e for e, _ in pedidos]})

    await avisar_pedidos_a_rrhh(tareas, uid, usuario["nombre"], usuario["cedula"], pedidos)
    return {
        "pendientes": quedan,
        "en_revision": [e for e, _ in pedidos],
        "mensaje": "Gracias. Sus datos quedaron registrados."
                   + (" Lo que indicó como incorrecto lo revisará Talento Humano."
                      if pedidos else ""),
    }


# ------------------------------------------------------ contactos de emergencia
# Se registraban (en la bienvenida) y no se veían en ninguna parte: «Mi
# ficha» solo mostraba el teléfono alternativo, que es otro dato. Ahora se
# ven y se corrigen: la propia persona desde Mi ficha, y Talento Humano
# desde el expediente.

class Contacto(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=120)
    parentesco: Literal["conyuge", "conviviente", "hijo", "padre", "madre", "hermano",
                        "abuelo", "nieto", "suegro", "cunado", "otro"] = "otro"
    telefono: str = Field(..., min_length=7, max_length=20)
    telefono_alternativo: str | None = Field(None, max_length=20)
    es_principal: bool = False


async def _contactos(user_id) -> list[dict]:
    filas = await obtener_todos(
        """select id, nombre, parentesco, telefono, telefono_alternativo, es_principal
             from emergency_contacts where user_id = %s order by es_principal desc, created_at""",
        (str(user_id),))
    return [{**c, "id": str(c["id"]), "es_principal": bool(c["es_principal"])} for c in filas]


async def guardar_contacto(user_id, datos: Contacto, contacto_id: str | None = None) -> None:
    telefono = _digitos(datos.telefono)
    if len(telefono) < 7:
        raise HTTPException(status_code=422, detail={"mensaje": "El teléfono debe tener al menos 7 dígitos."})
    alterno = _digitos(datos.telefono_alternativo) or None
    from ..db import transaccion
    async with transaccion():
        hay = await obtener_uno("select count(*) as n from emergency_contacts where user_id = %s",
                                (str(user_id),))
        principal = datos.es_principal or not int(hay["n"] or 0)   # el primero es el principal
        if principal:
            await ejecutar("update emergency_contacts set es_principal = false where user_id = %s",
                           (str(user_id),))
        if contacto_id:
            n = await ejecutar(
                """update emergency_contacts set nombre = %s, parentesco = %s, telefono = %s,
                          telefono_alternativo = %s, es_principal = %s
                    where id = %s and user_id = %s""",
                (datos.nombre.strip(), datos.parentesco, telefono, alterno, principal,
                 contacto_id, str(user_id)))
            if not n:
                existe = await obtener_uno("select 1 as x from emergency_contacts where id = %s "
                                           "and user_id = %s", (contacto_id, str(user_id)))
                if existe is None:
                    raise HTTPException(status_code=404, detail={"mensaje": "Ese contacto no existe."})
        else:
            await ejecutar(
                """insert into emergency_contacts (user_id, nombre, parentesco, telefono,
                                                   telefono_alternativo, es_principal)
                   values (%s, %s, %s, %s, %s, %s)""",
                (str(user_id), datos.nombre.strip(), datos.parentesco, telefono, alterno, principal))
        # Siempre queda uno principal si hay alguno.
        await ejecutar(
            """update emergency_contacts set es_principal = true
                where user_id = %s and not exists (select 1 from (select id from emergency_contacts
                      where user_id = %s and es_principal) x)
                order by created_at limit 1""", (str(user_id), str(user_id)))


async def quitar_contacto(user_id, contacto_id: str) -> None:
    await ejecutar("delete from emergency_contacts where id = %s and user_id = %s",
                   (contacto_id, str(user_id)))
    await ejecutar(
        """update emergency_contacts set es_principal = true
            where user_id = %s and not exists (select 1 from (select id from emergency_contacts
                  where user_id = %s and es_principal) x)
            order by created_at limit 1""", (str(user_id), str(user_id)))


@router.get("/mi-ficha/contactos")
async def mis_contactos(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    return await _contactos(usuario["id"])


@router.post("/mi-ficha/contactos", status_code=status.HTTP_201_CREATED)
async def agregar_mi_contacto(datos: Contacto, request: Request,
                              usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    await guardar_contacto(usuario["id"], datos)
    await registrar(request, "contacto_emergencia_guardado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"])
    return {"mensaje": "Contacto de emergencia guardado.", "contactos": await _contactos(usuario["id"])}


@router.patch("/mi-ficha/contactos/{contacto_id}")
async def cambiar_mi_contacto(contacto_id: str, datos: Contacto, request: Request,
                              usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    await guardar_contacto(usuario["id"], datos, contacto_id)
    await registrar(request, "contacto_emergencia_guardado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"])
    return {"mensaje": "Contacto de emergencia actualizado.", "contactos": await _contactos(usuario["id"])}


@router.delete("/mi-ficha/contactos/{contacto_id}")
async def quitar_mi_contacto(contacto_id: str, request: Request,
                             usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    await quitar_contacto(usuario["id"], contacto_id)
    await registrar(request, "contacto_emergencia_quitado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"])
    return {"mensaje": "Contacto quitado.", "contactos": await _contactos(usuario["id"])}


@router.get("/admin/usuarios/{user_id}/contactos")
async def contactos_de(user_id: str, usuario: RRHH) -> list[dict]:
    return await _contactos(user_id)


@router.post("/admin/usuarios/{user_id}/contactos", status_code=status.HTTP_201_CREATED)
async def agregar_contacto_de(user_id: str, datos: Contacto, request: Request, usuario: RRHH) -> dict:
    await guardar_contacto(user_id, datos)
    await registrar(request, "contacto_emergencia_guardado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="users", entidad_id=user_id)
    return {"mensaje": "Contacto de emergencia guardado.", "contactos": await _contactos(user_id)}


@router.patch("/admin/usuarios/{user_id}/contactos/{contacto_id}")
async def cambiar_contacto_de(user_id: str, contacto_id: str, datos: Contacto, request: Request,
                              usuario: RRHH) -> dict:
    await guardar_contacto(user_id, datos, contacto_id)
    await registrar(request, "contacto_emergencia_guardado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="users", entidad_id=user_id)
    return {"mensaje": "Contacto actualizado.", "contactos": await _contactos(user_id)}


@router.delete("/admin/usuarios/{user_id}/contactos/{contacto_id}")
async def quitar_contacto_de(user_id: str, contacto_id: str, request: Request, usuario: RRHH) -> dict:
    await quitar_contacto(user_id, contacto_id)
    await registrar(request, "contacto_emergencia_quitado", user_id=str(usuario["id"]),
                    cedula=usuario["cedula"], entidad="users", entidad_id=user_id)
    return {"mensaje": "Contacto quitado.", "contactos": await _contactos(user_id)}


# ------------------------------------------------------ teléfonos adicionales
MAX_TELEFONOS = 5


async def _telefonos(user_id) -> list[dict]:
    filas = await obtener_todos(
        "select id, numero, tipo, etiqueta from telefonos_adicionales where user_id = %s order by id",
        (str(user_id),))
    return [{**f, "id": int(f["id"])} for f in filas]


async def _agregar_telefono(user_id, datos: Telefono) -> None:
    numero = _digitos(datos.numero)
    if len(numero) < 7:
        raise HTTPException(status_code=422, detail={"mensaje": "El número debe tener al menos 7 dígitos."})
    actuales = await _telefonos(user_id)
    if len(actuales) >= MAX_TELEFONOS:
        raise HTTPException(status_code=422, detail={
            "mensaje": f"Puede registrar hasta {MAX_TELEFONOS} teléfonos adicionales."})
    if any(t["numero"] == numero for t in actuales):
        raise HTTPException(status_code=409, detail={"mensaje": "Ese número ya está registrado."})
    await ejecutar("insert into telefonos_adicionales (user_id, numero, tipo, etiqueta) values (%s, %s, %s, %s)",
                   (str(user_id), numero, datos.tipo, (datos.etiqueta or "").strip() or None))


@router.get("/mi-ficha/telefonos")
async def mis_telefonos(usuario: Annotated[dict, Depends(usuario_actual)]) -> list[dict]:
    return await _telefonos(usuario["id"])


@router.post("/mi-ficha/telefonos", status_code=status.HTTP_201_CREATED)
async def agregar_mi_telefono(datos: Telefono, request: Request,
                              usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    await _agregar_telefono(usuario["id"], datos)
    await registrar(request, "telefono_agregado", user_id=str(usuario["id"]), cedula=usuario["cedula"])
    return {"mensaje": "Teléfono agregado."}


@router.delete("/mi-ficha/telefonos/{telefono_id}")
async def quitar_mi_telefono(telefono_id: int, request: Request,
                             usuario: Annotated[dict, Depends(usuario_actual)]) -> dict:
    n = await ejecutar("delete from telefonos_adicionales where id = %s and user_id = %s",
                       (telefono_id, str(usuario["id"])))
    if not n:
        raise HTTPException(status_code=404, detail={"mensaje": "Ese teléfono no existe."})
    await registrar(request, "telefono_quitado", user_id=str(usuario["id"]), cedula=usuario["cedula"])
    return {"mensaje": "Teléfono quitado."}


@router.get("/admin/usuarios/{user_id}/telefonos")
async def telefonos_de(user_id: str, usuario: RRHH) -> list[dict]:
    return await _telefonos(user_id)


@router.post("/admin/usuarios/{user_id}/telefonos", status_code=status.HTTP_201_CREATED)
async def agregar_telefono_de(user_id: str, datos: Telefono, request: Request, usuario: RRHH) -> dict:
    await _agregar_telefono(user_id, datos)
    await registrar(request, "telefono_agregado", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="users", entidad_id=user_id)
    return {"mensaje": "Teléfono agregado."}


@router.delete("/admin/usuarios/{user_id}/telefonos/{telefono_id}")
async def quitar_telefono_de(user_id: str, telefono_id: int, request: Request, usuario: RRHH) -> dict:
    n = await ejecutar("delete from telefonos_adicionales where id = %s and user_id = %s", (telefono_id, user_id))
    if not n:
        raise HTTPException(status_code=404, detail={"mensaje": "Ese teléfono no existe."})
    await registrar(request, "telefono_quitado", user_id=str(usuario["id"]), cedula=usuario["cedula"],
                    entidad="users", entidad_id=user_id)
    return {"mensaje": "Teléfono quitado."}
