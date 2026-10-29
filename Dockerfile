FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Put the admin CSS/JS into one folder so WhiteNoise can serve it.
RUN python manage.py collectstatic --noinput

EXPOSE 8000

# Gunicorn: 2 worker processes, each with 4 threads = 8 requests at the same time.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4"]
