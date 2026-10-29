# Образът (image) на приложението. От него тръгват web, worker и websocket.
# Основа: малък Linux с Python 3.13.
FROM python:3.13-slim

# Python да не пише .pyc файлове и да показва логовете веднага (без буфер).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Първо само requirements.txt: така Docker кешира инсталираните пакети и не ги
# инсталира наново при всяка промяна в кода.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# После - целият код.
COPY . .

# Събираме CSS/JS на админа в една папка, за да може WhiteNoise да ги сервира.
# Настройките изискват SECRET_KEY, за да се заредят; този се ползва само за тази стъпка.
RUN SECRET_KEY=only-for-collectstatic python manage.py collectstatic --noinput

EXPOSE 8000

# Gunicorn: 2 процеса, всеки с 4 нишки = 8 заявки едновременно.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4"]
