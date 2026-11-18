"""Levanta el sistema para que lo prueben otros, desde sus propias máquinas.

Existe porque «que entren los demás» tiene tres trampas y ninguna avisa:

  1. El backend atiende solo en el bucle local. Desde otro computador la
     pantalla carga y después dice «No se pudo conectar con el servidor»,
     sin que el backend registre nada: la petición jamás llegó.
  2. El navegador del colaborador envía `Origin: http://192.168.x.x:5500`,
     que no es `localhost` para él. Sin eso en CORS, el preflight se
     responde con un 400 seco y el síntoma es idéntico al anterior.
  3. El cortafuegos de Windows bloquea los puertos entrantes la primera vez
     y la pregunta sale en el equipo que sirve, no en el que prueba.

Aquí se resuelven las dos primeras y se avisa de la tercera con el comando
exacto. Lo único que hay que repartir es la dirección que imprime.

    python scripts/compartir.py
    python scripts/compartir.py --puerto-web 5501

Esto es para la red interna de la oficina, no para publicar. No habilita
HTTPS ni expone nada a internet: las direcciones privadas no se enrutan
fuera de la red local.
"""
from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _windows  # noqa: F401,E402
import _cli  # noqa: E402
import _puerto  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
VERDE, AMARILLO, GRIS, FIN = "\033[92m", "\033[93m", "\033[90m", "\033[0m"


def ip_de_la_red() -> str | None:
    """La dirección con la que esta máquina se ve desde la red.

    Se abre un socket UDP hacia afuera y se pregunta por qué interfaz
    saldría. No envía nada —UDP no establece conexión— y funciona sin
    internet: el sistema solo consulta su tabla de rutas. Es más fiable que
    `gethostbyname(gethostname())`, que en Windows devuelve 127.0.0.1 con
    frecuencia y en equipos con VPN devuelve la de la VPN.
    """
    sonda = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sonda.connect(("10.255.255.255", 1))
        direccion = sonda.getsockname()[0]
        return direccion if not direccion.startswith("127.") else None
    except OSError:
        return None
    finally:
        sonda.close()


def es_privada(ip: str) -> bool:
    """¿Es una dirección de red interna (RFC 1918)?"""
    partes = ip.split(".")
    if len(partes) != 4 or not all(p.isdigit() for p in partes):
        return False
    a, b = int(partes[0]), int(partes[1])
    return a == 10 or (a == 192 and b == 168) or (a == 172 and 16 <= b <= 31)


def comprobar_entorno() -> list[str]:
    """Lo que impediría que esto sirva de algo, dicho antes de arrancar."""
    problemas = []
    if not (RAIZ / "backend" / ".env").exists():
        problemas.append("Falta backend/.env. Cópielo de backend/.env.example.")
    else:
        texto = (RAIZ / "backend" / ".env").read_text(encoding="utf-8", errors="replace")
        for linea in texto.splitlines():
            if linea.strip().startswith("ENTORNO="):
                valor = linea.split("=", 1)[1].strip().strip('"').strip("'").lower()
                if valor in ("produccion", "production", "prod"):
                    problemas.append(
                        "ENTORNO=produccion en backend/.env: en producción solo valen los "
                        "orígenes de CORS_ORIGINS, así que los colaboradores no entrarán. "
                        "Para probar en la oficina, póngalo en «desarrollo».")
    if not (RAIZ / "frontend" / "vendor" / "tailwind.css").exists():
        problemas.append(
            "Falta frontend/vendor/tailwind.css: la interfaz se vería sin estilos. "
            "Regenérelo con  cd build  y  npm install  y  npm run estilos.")
    return problemas


def main() -> int:
    p = argparse.ArgumentParser(
        description="Levanta el sistema en la red interna para probarlo entre varios.")
    p.add_argument("--puerto-api", type=int, default=None,
                   help="Por omisión, el que la interfaz tiene configurado.")
    p.add_argument("--puerto-web", type=int, default=5500)
    p.add_argument("--solo-datos", action="store_true",
                   help="Solo imprime la dirección a repartir; no arranca nada.")
    args = _cli.analizar(p)
    if args.puerto_api is None:
        args.puerto_api = _puerto.de_la_interfaz()

    problemas = comprobar_entorno()
    for problema in problemas:
        print(f"{AMARILLO}!{FIN} {problema}")
    if problemas:
        print()

    ip = ip_de_la_red()
    if not ip:
        print(f"{AMARILLO}!{FIN} No encuentro la dirección de red de este equipo.")
        print("  ¿Está conectado a la red de la oficina? Sin red, solo podrá probar usted.")
        return 1
    if not es_privada(ip):
        print(f"{AMARILLO}!{FIN} Este equipo tiene una dirección pública ({ip}).")
        print("  Esto está pensado para la red interna. No lo use para publicar el sistema.")
        return 1

    web = f"http://{ip}:{args.puerto_web}"
    print("=" * 62)
    print("  Reparta esta dirección entre quienes van a probar:")
    print(f"\n      {VERDE}{web}{FIN}\n")
    print(f"  {GRIS}Cada quien entra con SU cédula y el código que le llega al correo.")
    print(f"  Todos ven lo mismo: una sola base, un solo sistema.{FIN}")
    print("=" * 62)
    print()
    print("Si desde otro equipo no carga, es el cortafuegos de Windows. Abra")
    print("PowerShell COMO ADMINISTRADOR en este equipo y ejecute una sola vez:")
    print(f'\n  New-NetFirewallRule -DisplayName "RRHH pruebas" -Direction Inbound '
          f'-Protocol TCP -LocalPort {args.puerto_web},{args.puerto_api} -Action Allow '
          f'-Profile Private\n')
    print(f"{GRIS}Para quitarla después:  "
          f'Remove-NetFirewallRule -DisplayName "RRHH pruebas"{FIN}')
    print()

    if args.solo_datos:
        return 0

    print("Arrancando. Ctrl+C detiene los dos servidores.\n")
    procesos = []
    try:
        procesos.append(subprocess.Popen(
            [sys.executable, str(RAIZ / "scripts" / "servidor.py"),
             "--host", "0.0.0.0", "--puerto", str(args.puerto_api)]))
        procesos.append(subprocess.Popen(
            [sys.executable, str(RAIZ / "scripts" / "frontend.py"),
             "--puerto", str(args.puerto_web)]))
        for proceso in procesos:
            proceso.wait()
    except KeyboardInterrupt:
        print("\nDeteniendo…")
    finally:
        for proceso in procesos:
            if proceso.poll() is None:
                proceso.terminate()
        for proceso in procesos:
            try:
                proceso.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proceso.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
