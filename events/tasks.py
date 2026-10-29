"""
Фонови задачи на Celery. Изпълнява ги контейнерът worker, а не web, за да не
бавят HTTP заявките. Самата логика е в services.py.
"""
from celery import shared_task

from . import services


@shared_task
def release_expired_bookings():
    """Пуска се автоматично на всеки 30 секунди (CELERY_BEAT_SCHEDULE в settings.py)."""
    return services.release_expired_bookings()


@shared_task
def process_waitlist(event_id):
    """Пуска се, когато се освободят билети (services.release_tickets вика .delay())."""
    services.process_waitlist(event_id)
