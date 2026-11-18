"""El expediente de una persona, en una sola pantalla.

Talento Humano y las jefaturas tenían los datos repartidos: la ficha en una
pantalla, los períodos de vacaciones en otra, las solicitudes en una tercera y
el historial de la hoja en un diálogo del panel de cada quien. Para responder
«¿cuándo tomó vacaciones Fulano y qué tiene pendiente?» había que ir a tres
sitios y cruzarlos a mano.

QUIÉN VE A QUIÉN. Un jefe ve a su gente y nada más. Talento Humano y la
administración ven a toda la planilla, que es su función. Nadie más entra
aquí: un compañero no tiene por qué leer el expediente de otro (LOPDP,
Art. 10) y el sistema no se lo ofrece ni se lo permite si prueba la dirección
a mano.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ..db import obtener_todos, obtener_uno
from ..deps import exigir_rol

router = APIRouter(prefix="/personas", tags=["Expediente de una persona"])

MANDO = Annotated[dict, Depends(exigir_rol("jefe", "rrhh", "admin"))]


def _alcance(usuario: dict) -> tuple[str, dict]:
    """A quién alcanza quien consulta. El jefe, solo a su gente."""
    if usuario["rol"] == "jefe":
        return "u.jefe_id = %(jefe)s", {"jefe": usuario["id"]}
    return "true", {}


@router.get("/buscar", summary="Buscar una persona por nombre o cédula")
async def buscar(usuario: MANDO, q: str = "", limite: int = 12) -> list[dict]:
    """Lo justo para elegir a quién abrir: nombre, cédula, cargo y área.

    Devuelve poco a propósito. Es un buscador de navegación, no un listado
    de la planilla: quien necesita la planilla entera tiene Colaboradores.
    """
    aguja = q.strip()
    if len(aguja) < 2:
        return []

    filtro, parametros = _alcance(usuario)
    digitos = "".join(c for c in aguja if c.isdigit())
    parametros |= {"like": f"%{aguja}%", "cedula": digitos,
                   "cedula_patron": f"{digitos}%", "limite": min(max(limite, 1), 50)}

    return await obtener_todos(
        f"""
        select u.id, u.cedula, u.nombre, u.cargo, u.departamento, u.ciudad
          from public.users u
         where u.activo and {filtro}
           and (public.sin_tildes(u.nombre) ilike public.sin_tildes(%(like)s)
                -- Por cédula solo cuando lo tecleado trae dígitos, y por el
                -- principio: así «1723» encuentra a quien empieza así y una
                -- búsqueda de texto no arrastra a toda la planilla.
                or (%(cedula)s <> '' and u.cedula like %(cedula_patron)s))
         order by u.nombre
         limit %(limite)s
        """,
        parametros,
    )


@router.get("/{user_id}", summary="El expediente completo de una persona")
async def expediente(user_id: str, usuario: MANDO) -> dict:
    filtro, parametros = _alcance(usuario)
    persona = await obtener_uno(
        f"""
        select u.id, u.cedula, u.nombre, u.cargo, u.departamento, u.ciudad,
               u.region, u.fecha_ingreso, u.rol, u.email, u.telefono,
               u.dias_vacaciones as saldo, u.activo,
               public.anios_cumplidos(u.fecha_ingreso) as anios,
               public.fines_semana_pendientes(u.id)    as fines_semana_pendientes,
               j.nombre as jefe_nombre
          from public.users u
          left join public.users j on j.id = u.jefe_id
         where u.id = %(id)s and {filtro}
        """,
        parametros | {"id": user_id},
    )
    if persona is None:
        # La misma respuesta para «no existe» y «no le corresponde»: un jefe
        # que prueba identificadores no debe poder averiguar quién trabaja
        # en otra área.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"mensaje": "No encontramos a esa persona entre las que usted puede consultar."},
        )

    solicitudes = await obtener_todos(
        """select r.folio, r.tipo, r.estado, r.fecha_inicio, r.fecha_fin,
                  r.dias_solicitados, r.hora_inicio, r.hora_fin, r.created_at,
                  t.nombre as subtipo
             from public.requests r
             left join public.permission_types t on t.id = r.permission_type_id
            where r.user_id = %s
            order by r.created_at desc limit 100""",
        (user_id,),
    )
    vacaciones = await obtener_todos(
        """select folio, fecha_inicio, fecha_fin, dias, procedencia, detalle
             from public.v_historial_vacaciones
            where user_id = %s order by fecha_inicio desc limit 200""",
        (user_id,),
    )
    periodos = await obtener_todos(
        """select periodo, fecha_desde, fecha_hasta, dias_asignados,
                  dias_consumidos, dias_saldo, devengado, caducado
             from public.vacation_periods
            where user_id = %s order by periodo""",
        (user_id,),
    )
    devengo = await obtener_uno(
        """select meses_del_periodo, tope_anual_del_periodo, devengado_hoja,
                  devengado_de_anios_cumplidos
             from public.v_devengo_cotejo where user_id = %s""",
        (user_id,),
    )

    return {
        "persona": {**persona, "id": str(persona["id"])},
        "devengo": devengo,
        "periodos": periodos,
        "solicitudes": [{**s, "folio": int(s["folio"])} for s in solicitudes],
        "vacaciones": [{**v, "dias": float(v["dias"]),
                        "folio": int(v["folio"]) if v["folio"] else None}
                       for v in vacaciones],
        "resumen": {
            "veces": len(vacaciones),
            "dias_gozados": round(sum(float(v["dias"]) for v in vacaciones), 2),
            "desde_la_hoja": sum(1 for v in vacaciones if v["procedencia"] == "historico"),
            "en_tramite": sum(1 for s in solicitudes
                              if s["estado"] in ("pendiente_jefe", "pendiente_rrhh")),
        },
    }
