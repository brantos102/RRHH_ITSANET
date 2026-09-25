#!/usr/bin/env bash
# Arranca el backend y el frontend para probar en local.
#   ./scripts/iniciar.sh
# Se detiene todo con Ctrl+C.
set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PUERTO_API="${PUERTO_API:-8000}"
PUERTO_WEB="${PUERTO_WEB:-5500}"

cd "$RAIZ"

# --- entorno de Python ---
if [ ! -d .venv ]; then
  echo "Creando entorno de Python…"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r backend/requirements.txt
fi

if [ ! -f backend/.env ]; then
  echo "Falta backend/.env. Copie el ejemplo y complete los valores:"
  echo "   cp backend/.env.example backend/.env"
  exit 1
fi

# --- el frontend debe apuntar al backend que se va a levantar ---
if ! grep -q "localhost:$PUERTO_API" frontend/config.js; then
  echo "Ajustando frontend/config.js para apuntar al puerto $PUERTO_API…"
  sed -i.bak -E "s|API: \"[^\"]*\"|API: \"http://localhost:$PUERTO_API\"|" frontend/config.js
  rm -f frontend/config.js.bak
fi

DETENIDO=0
limpiar() {
  [ "$DETENIDO" = 1 ] && return    # EXIT e INT se disparan juntos
  DETENIDO=1
  echo
  echo "Deteniendo…"
  kill "${PID_API:-}" "${PID_WEB:-}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap limpiar EXIT INT TERM

echo "Backend  → http://localhost:$PUERTO_API  (documentación en /docs)"
( cd backend && exec "$RAIZ/.venv/bin/python" -m uvicorn app.main:app \
    --host 0.0.0.0 --port "$PUERTO_API" --reload ) &
PID_API=$!

sleep 3
echo "Frontend → http://localhost:$PUERTO_WEB"
( cd frontend && exec python3 -m http.server "$PUERTO_WEB" --bind 0.0.0.0 >/dev/null 2>&1 ) &
PID_WEB=$!

echo
echo "Abra http://localhost:$PUERTO_WEB e ingrese con su cédula."
echo "Con EMAIL_BACKEND=console el código aparece aquí mismo, en esta terminal."
echo "Ctrl+C para detener."
echo

wait
