# Зареждаме Celery заедно с Django, за да работи @shared_task в events/tasks.py.
from .celery import app as celery_app

__all__ = ["celery_app"]
