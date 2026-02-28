#!/bin/bash
echo "Ejecutando migraciones..."
python manage.py migrate --noinput
echo "Iniciando Gunicorn..."
exec gunicorn naza.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 60 --access-logfile - --error-logfile - --log-level debug
