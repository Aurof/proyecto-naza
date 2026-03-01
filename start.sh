#!/bin/bash
echo "Ejecutando migraciones..."
python manage.py migrate --noinput

echo "Creando superusuario de emergencia..."
# Esto crea un usuario llamado 'admin' con clave 'admin123' y correo 'admin@naza.com'. 
# Si el usuario ya existe, esto simplemente dará un error menor que ignoraremos, pero no dañará la app.
python manage.py createsuperuser --noinput --username admin --email admin@naza.com || true
python manage.py shell -c "from django.contrib.auth.models import User; u = User.objects.get(username='admin'); u.set_password('123admin123'); u.save()" || true

echo "Iniciando Gunicorn..."
exec gunicorn naza.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --threads 4 --timeout 60 --access-logfile - --error-logfile - --log-level debug
