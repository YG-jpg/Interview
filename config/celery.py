"""
Настройка на Celery. Взима настройките от settings.py (тези, които започват с CELERY_)
и намира задачите в tasks.py на всяко приложение.
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
