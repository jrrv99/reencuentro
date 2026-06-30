FROM python:3.12-slim

WORKDIR /app

# psycopg[binary] y pgvector no necesitan libpq del sistema (wheels incluyen todo).
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt

# Código fuente — en dev se sobreescribe con el volume mount del compose.
COPY . .

EXPOSE 8000

# migrate es idempotente: seguro correrlo en cada arranque.
CMD ["sh", "-c", "python manage.py migrate && python manage.py runserver 0.0.0.0:8000"]
