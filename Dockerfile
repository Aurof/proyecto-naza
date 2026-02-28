FROM python:3.11-slim

# Instalar dependencias del sistema para pycairo, mysqlclient, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcairo2-dev \
    pkg-config \
    python3-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copiar e instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copiar el resto del proyecto
COPY . .

# Recoger archivos estáticos
RUN python manage.py collectstatic --noinput || true

# Exponer el puerto
EXPOSE 8000

# Comando de inicio
CMD python manage.py migrate && gunicorn naza.wsgi:application --bind 0.0.0.0:$PORT
