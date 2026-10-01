"""Dice por qué no se guarda un adjunto, y crea lo que falte.

El respaldo de un permiso —el certificado médico, la cita— va a Supabase
Storage. Si eso falla, la pantalla dice «No se pudo guardar el archivo.
Intente de nuevo.» y el colaborador lo intenta otra vez, con otra imagen,
con un PDF, y siempre falla igual: el archivo nunca fue el problema.

Las causas son tres y desde la pantalla son indistinguibles:

  · El bucket no existe en el proyecto de Supabase. Es lo habitual en una
    instalación nueva: las tablas se crean con las migraciones, pero los
    buckets de Storage no.
  · SUPABASE_SERVICE_ROLE_KEY es la clave «anon» y no la «service_role».
    La anon no puede escribir en un bucket privado.
  · Storage no está configurado en absoluto.

    python scripts/probar_adjuntos.py            revisa y prueba
    python scripts/probar_adjuntos.py --crear    crea los buckets que falten

Sube un archivo diminuto de prueba, lo vuelve a leer y lo borra. No toca
ningún adjunto real ni la base de datos.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _windows  # noqa: F401,E402
import _cli  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "backend"))

VERDE, ROJO, AMARILLO, GRIS, FIN = "\033[92m", "\033[91m", "\033[93m", "\033[90m", "\033[0m"

# Lo que cada bucket guarda, y por qué es privado.
BUCKETS = {
    "solicitudes": "Respaldos de permisos: certificados médicos, citas, documentos.",
    "firmas": "Firmas registradas de los colaboradores.",
}
LIMITE_BYTES = 10 * 1024 * 1024


async def listar(cliente, settings) -> tuple[int, object]:
    r = await cliente.get(f"{settings.supabase_url}/storage/v1/bucket",
                          headers={"Authorization": f"Bearer {settings.supabase_service_role_key}"})
    return r.status_code, (r.json() if r.status_code == 200 else r.text)


async def crear(cliente, settings, nombre: str):
    return await cliente.post(
        f"{settings.supabase_url}/storage/v1/bucket",
        headers={"Authorization": f"Bearer {settings.supabase_service_role_key}"},
        json={
            "id": nombre, "name": nombre,
            # Privado SIEMPRE: un certificado médico en un bucket público es
            # una URL que cualquiera adivina. Dato de salud, además (LOPDP).
            "public": False,
            "file_size_limit": LIMITE_BYTES,
        },
    )


async def principal(crear_faltantes: bool) -> int:
    if not (RAIZ / "backend" / ".env").exists():
        print(f"{ROJO}✗{FIN} No existe backend/.env. Cópielo de backend/.env.example.")
        return 1

    import httpx
    from app.config import get_settings
    from app.storage import por_que_fallo

    settings = get_settings()

    print("Configuración de Storage")
    print("────────────────────────")
    print(f"  SUPABASE_URL                {settings.supabase_url or '(vacío)'}")
    clave = settings.supabase_service_role_key
    print(f"  SUPABASE_SERVICE_ROLE_KEY   "
          f"{'•' * 10 + clave[-6:] if clave else '(vacío)'}  {GRIS}({len(clave)} caracteres){FIN}")
    print()

    if not (settings.supabase_url and clave):
        print(f"{ROJO}✗ Storage no está configurado.{FIN}\n")
        print("  Mientras falten esos dos valores, el backend NO sube nada y la")
        print("  solicitud queda registrada con un adjunto que no existe en ninguna")
        print("  parte. Complételos en backend/.env desde")
        print("      Supabase › Project Settings › API Keys\n")
        return 1

    # Una clave «anon» lleva role:anon dentro del JWT; la service_role, el suyo.
    # No se descifra nada: solo se mira el cuerpo, que va en claro.
    if "service_role" not in _cuerpo_del_jwt(clave):
        print(f"{AMARILLO}!{FIN} La clave no parece ser la «service_role».")
        print("  La clave «anon» no puede escribir en un bucket privado, y el síntoma")
        print("  es exactamente este. Cópiela de Supabase › Project Settings › API Keys.\n")

    async with httpx.AsyncClient(timeout=30) as cliente:
        codigo, cuerpo = await listar(cliente, settings)
        if codigo != 200:
            print(f"{ROJO}✗ No se pudo consultar los buckets (HTTP {codigo}).{FIN}\n")
            print(f"{GRIS}{str(cuerpo)[:300]}{FIN}\n")
            print(f"  {por_que_fallo(codigo, str(cuerpo))}")
            return 1

        existentes = {b.get("name") for b in cuerpo}
        print("Buckets")
        print("───────")
        faltan = []
        for nombre, para_que in BUCKETS.items():
            if nombre in existentes:
                datos = next(b for b in cuerpo if b.get("name") == nombre)
                publico = datos.get("public")
                marca = f"{ROJO}PÚBLICO{FIN}" if publico else f"{GRIS}privado{FIN}"
                print(f"  {VERDE}✓{FIN} {nombre:14} {marca}  {GRIS}{para_que}{FIN}")
                if publico:
                    print(f"      {ROJO}Un certificado médico en un bucket público es una "
                          f"URL que cualquiera puede abrir. Póngalo privado.{FIN}")
            else:
                print(f"  {ROJO}✗{FIN} {nombre:14} no existe   {GRIS}{para_que}{FIN}")
                faltan.append(nombre)
        print()

        if faltan and not crear_faltantes:
            print(f"{AMARILLO}Esto es lo que está fallando.{FIN} Para crearlos:")
            print("    python scripts/probar_adjuntos.py --crear")
            return 1

        for nombre in faltan:
            respuesta = await crear(cliente, settings, nombre)
            if respuesta.status_code in (200, 201):
                print(f"  {VERDE}✓{FIN} Bucket «{nombre}» creado, privado, límite 10 MB.")
            else:
                print(f"  {ROJO}✗{FIN} No se pudo crear «{nombre}» "
                      f"(HTTP {respuesta.status_code}): {respuesta.text[:200]}")
                print(f"      {por_que_fallo(respuesta.status_code, respuesta.text)}")
                return 1
        if faltan:
            print()

        # La prueba de verdad: subir, leer y borrar.
        print("Prueba de escritura")
        print("───────────────────")
        ruta = f"_prueba/{uuid.uuid4().hex}.txt"
        contenido = b"Prueba de scripts/probar_adjuntos.py. Se borra sola."
        for bucket in BUCKETS:
            subida = await cliente.post(
                f"{settings.supabase_url}/storage/v1/object/{bucket}/{ruta}",
                headers={"Authorization": f"Bearer {clave}",
                         "Content-Type": "text/plain", "x-upsert": "true"},
                content=contenido,
            )
            if subida.status_code not in (200, 201):
                print(f"  {ROJO}✗{FIN} {bucket}: no se pudo escribir "
                      f"(HTTP {subida.status_code})")
                print(f"      {GRIS}{subida.text[:200]}{FIN}")
                print(f"      {por_que_fallo(subida.status_code, subida.text)}")
                return 1

            leida = await cliente.get(
                f"{settings.supabase_url}/storage/v1/object/{bucket}/{ruta}",
                headers={"Authorization": f"Bearer {clave}"})
            igual = leida.status_code == 200 and leida.content == contenido

            await cliente.delete(
                f"{settings.supabase_url}/storage/v1/object/{bucket}/{ruta}",
                headers={"Authorization": f"Bearer {clave}"})

            if igual:
                print(f"  {VERDE}✓{FIN} {bucket}: escribe, lee lo mismo que escribió y borra.")
            else:
                print(f"  {AMARILLO}!{FIN} {bucket}: escribe, pero no se pudo releer "
                      f"(HTTP {leida.status_code}). Los adjuntos subirían pero no se verían.")
                return 1

    print(f"\n{VERDE}Listo.{FIN} Los adjuntos de las solicitudes ya se guardan.")
    return 0


def _cuerpo_del_jwt(clave: str) -> str:
    """El cuerpo del JWT, en claro. Si no lo parece, devuelve la clave entera."""
    import base64
    partes = clave.split(".")
    if len(partes) != 3:
        return clave
    try:
        relleno = partes[1] + "=" * (-len(partes[1]) % 4)
        return base64.urlsafe_b64decode(relleno).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001
        return clave


def main() -> int:
    p = argparse.ArgumentParser(
        description="Comprueba que los respaldos de las solicitudes se pueden guardar.")
    p.add_argument("--crear", action="store_true",
                   help="Crea los buckets que falten, privados y con límite de 10 MB.")
    args = _cli.analizar(p)
    try:
        return asyncio.run(principal(args.crear))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
