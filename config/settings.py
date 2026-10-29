import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Настройките идват от променливи на средата (environment variables): от файла
# .env при Docker Compose и от ConfigMap + Secret при Kubernetes. В git не се пазят
# пароли и ключове (създава ги python scripts/make_secrets.py).

# DEBUG е изключен, освен ако изрично не го включиш. DEBUG=1 е само за твоя компютър:
# тогава Django показва подробни страници с грешки, които никой друг не бива да вижда.
DEBUG = os.environ.get("DEBUG", "0") == "1"

# SECRET_KEY подписва сесиите (бисквитката за login) и CSRF токените. Който го знае,
# може да се представи за друг потребител, затова не е в кода. Без ключ сайтът
# отказва да тръгне, освен в DEBUG режим.
SECRET_KEY = os.environ.get("SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set the SECRET_KEY environment variable (see .env.example).")
    SECRET_KEY = "insecure-key-only-for-debug"

# Имената на хостовете, на които отговаря сайтът, разделени със запетая. За всички
# други Django връща "400 Bad Request" (защита от фалшив Host хедър).
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host.strip()]

# Приложенията: вградените в Django, rest_framework (за API-то), channels (за WebSocket),
# events (API, модели и правила) и pages (сайтът с HTML страниците).
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    "events",
    "pages",
]

# Middleware - код, през който минава всяка заявка, преди да стигне до view-то. Тук са
# защитите: SecurityMiddleware (security хедъри), CsrfViewMiddleware (CSRF - фалшиви
# форми от други сайтове), сесиите и login-а. WhiteNoise сервира статичните файлове.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "config.urls"

# HTML шаблоните се търсят в папка templates/ на всяко приложение (APP_DIRS).
# Django автоматично екранира всичко, което шаблонът показва - защита от XSS.
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# WSGI е за нормалните HTTP заявки (Gunicorn), ASGI - за WebSocket (daphne).
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Базата данни е PostgreSQL. Всички заявки минават през Django ORM, който праща
# стойностите отделно от SQL-а (параметризирани заявки) - защита от SQL injection.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "NAME": os.environ.get("DB_NAME", "events"),
        "USER": os.environ.get("DB_USER", "events"),
        "PASSWORD": os.environ.get("DB_PASSWORD", "events"),
    }
}

# Език и часова зона. Датите се пазят в базата в UTC (USE_TZ = True).
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True

# Статичните файлове (CSS/JS на админа) се събират в една папка и се сервират от WhiteNoise.
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Типът на автоматичното поле id в таблиците (64-битово цяло число).
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# HTML страниците: къде да пращаме потребителя, за да влезе, и къде да отиде след login/logout.
LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/"

# Потребителите на API-то влизат с потребителско име + парола (HTTP Basic Auth).
# Session auth позволява на потребител, влязъл в сайта, да ползва API-то в браузъра.
# IsAuthenticated: по подразбиране всеки endpoint изисква влязъл потребител.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.BasicAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Ограничаване на заявките (rate limiting). Броячите се пазят в Redis (виж CACHES
    # по-долу), затова лимитът е общ за всички Gunicorn процеси и Kubernetes pod-ове.
    # anon - анонимни, user - влезли потребители, bookings - нови резервации (BookingRateThrottle в events/views.py).
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "200/minute",
        "user": "300/minute",
        "bookings": "10/minute",
    },
}

# Redis се ползва за 3 неща: броячите за rate limit, опашката със задачи на Celery
# и пращането на WebSocket съобщения между процесите.
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

# Channel layer: през него web процесът праща съобщения до WebSocket сървъра (daphne).
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# Celery - фонови задачи. Опашката е в Redis. Beat (графикът) пуска
# release_expired_bookings на всеки 30 секунди.
CELERY_BROKER_URL = REDIS_URL
CELERY_BEAT_SCHEDULE = {
    "release-expired-bookings": {
        "task": "events.tasks.release_expired_bookings",
        "schedule": 30.0,  # секунди
    },
}

# Портът на WebSocket сървъра (daphne). Страницата на събитието се свързва с него.
WEBSOCKET_PORT = os.environ.get("WEBSOCKET_PORT", "8001")

# Тестовете не се нуждаят от работещ Redis или Celery worker: пазим в паметта вместо
# в Redis, а задачите на Celery се изпълняват веднага (CELERY_TASK_ALWAYS_EAGER).
if "test" in sys.argv:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
    CELERY_TASK_ALWAYS_EAGER = True
