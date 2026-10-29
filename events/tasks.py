from celery import shared_task

from . import services


@shared_task
def release_expired_bookings():
    return services.release_expired_bookings()


@shared_task
def process_waitlist(event_id):
    services.process_waitlist(event_id)
