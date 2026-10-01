"""Levanta el bloqueo de «Demasiados intentos» de una persona.

El sistema frena a quien pide muchos códigos sin usar ninguno: es la forma
que tiene el abuso, y la protección debe quedarse. Pero al instalar, al
probar o cuando el correo no estaba llegando, uno pulsa «Enviar código»
varias veces en un minuto y acaba bloqueado por una hora sin haber hecho
nada malo.

    python scripts/desbloquear_acceso.py                      quién está bloqueado
    python scripts/desbloquear_acceso.py 0926687856           qué haría
    python scripts/desbloquear_acceso.py 0926687856 --aplicar lo hace

Lo que hace es anular los códigos pendientes de esa persona, que es lo que
la cuenta mira. No crea códigos, no da acceso a nadie y no
toca la contraseña de nada: el siguiente intento vuelve a pedir su código
por correo, como siempre. Queda constancia en la bitácora.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _windows  # noqa: F401,E402
import _cli  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

VERDE, AMARILLO, GRIS, FIN = "\033[92m", "\033[93m", "\033[90m", "\033[0m"


async def principal(cedula: str | None, aplicar: bool) -> int:
    from app.cedula import normalizar_cedula
    from app.config import get_settings
    from app.db import cerrar_pool, ejecutar, obtener_todos

    tope = get_settings().otp_max_envios_hora
    try:
        if not cedula:
            filas = await obtener_todos(
                """
                select o.cedula,
                       coalesce(u.nombre, '(no está registrada)') as nombre,
                       count(*) as pendientes,
                       max(o.created_at) as ultimo
                  from public.auth_otp o
                  left join public.users u on u.cedula = o.cedula
                 where o.created_at > now() - interval '1 hour'
                   and o.consumido_en is null and o.anulado_en is null
                 group by o.cedula, u.nombre
                having count(*) >= %s
                 order by count(*) desc
                """,
                (tope,),
            )
            if not filas:
                print(f"{VERDE}Nadie está bloqueado.{FIN}")
                print(f"{GRIS}El tope es de {tope} códigos sin usar por hora.{FIN}")
                return 0
            print(f"Bloqueadas ahora mismo (tope: {tope} códigos sin usar por hora):\n")
            for f in filas:
                print(f"  {f['cedula']}  {f['nombre']:<34} "
                      f"{f['pendientes']} sin usar, el último a las "
                      f"{f['ultimo'].strftime('%H:%M')}")
            print(f"\nPara levantar uno:\n"
                  f"    python scripts/desbloquear_acceso.py {filas[0]['cedula']} --aplicar")
            return 0

        limpia = normalizar_cedula(cedula)
        pendientes = await obtener_todos(
            """select id, created_at, email from public.auth_otp
                where cedula = %s and consumido_en is null and anulado_en is null
                  and created_at > now() - interval '1 hour'
                order by created_at""",
            (limpia,),
        )
        if not pendientes:
            print(f"{VERDE}La cédula {limpia} no tiene códigos sin usar en la última hora.{FIN}")
            print(f"{GRIS}Si aun así no puede entrar, el problema es otro: pruebe\n"
                  f"    python scripts/probar_correo.py{FIN}")
            return 0

        print(f"La cédula {limpia} tiene {len(pendientes)} código(s) sin usar "
              f"(el tope es {tope}):\n")
        for f in pendientes:
            print(f"  {f['created_at'].strftime('%H:%M:%S')}  → {f['email']}")

        if not aplicar:
            print(f"\n{AMARILLO}No se cambió nada.{FIN} Para levantarlo:")
            print(f"    python scripts/desbloquear_acceso.py {limpia} --aplicar")
            return 0

        # Anulados, no borrados: la constancia de que se pidieron se conserva,
        # y un código anulado no sirve para entrar aunque alguien lo tuviera.
        # Anulado y no «consumido»: nadie entró con ellos, y marcarlos como
        # usados falsearía la bitácora de ingresos.
        await ejecutar(
            """update public.auth_otp
                  set anulado_en = now(), expira_en = now() - interval '1 second'
                where cedula = %s and consumido_en is null and anulado_en is null
                  and created_at > now() - interval '1 hour'""",
            (limpia,),
        )
        await ejecutar(
            """insert into public.audit_logs (accion, cedula, detalle)
               values ('otp_desbloqueo_manual', %s,
                       jsonb_build_object('codigos', %s, 'por', 'scripts/desbloquear_acceso.py'))""",
            (limpia, len(pendientes)),
        )
        print(f"\n{VERDE}Listo.{FIN} {limpia} ya puede pedir su código otra vez.")
        print(f"{GRIS}Los códigos anteriores quedaron anulados: no sirven para entrar.{FIN}")
        return 0
    finally:
        await cerrar_pool()


def main() -> int:
    p = argparse.ArgumentParser(
        description="Levanta el bloqueo por demasiados códigos sin usar.")
    p.add_argument("cedula", nargs="?", help="Sin cédula, lista a quiénes afecta ahora.")
    p.add_argument("--aplicar", action="store_true", help="Sin esto, solo dice qué haría.")
    args = _cli.analizar(p)
    try:
        return asyncio.run(principal(args.cedula, args.aplicar))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
