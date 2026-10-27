# Imagen del backend. Probada en Fly.io, Render y Railway.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Las dependencias primero: así la capa se reaprovecha entre despliegues
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Sin privilegios: si algo se rompe, no se rompe como root
RUN useradd --create-home --uid 1000 rrhh && chown -R rrhh:rrhh /app
USER rrhh

EXPOSE 8000

# El puerto lo fija la plataforma; 8000 es el de reserva
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
