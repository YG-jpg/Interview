"""
All the booking rules. The API and the website both call these functions.
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from . import realtime
from .models import Booking, Event, WaitlistEntry

logger = logging.getLogger(__name__)

RESERVATION_MINUTES = 5


class BookingError(Exception):
    pass


def reserve_tickets(user, event_id, tickets, idempotency_key=None):
    """
    Hold tickets for 5 minutes. The user has to confirm before that,
    otherwise release_expired_bookings() gives the tickets back.

    Returns (booking, created). created is False when the same
    idempotency_key was sent before - then we return the old booking.
    """
    if tickets < 1:
        raise BookingError("You must book at least 1 ticket.")

    if idempotency_key:
        old_booking = Booking.objects.filter(user=user, idempotency_key=idempotency_key).first()
        if old_booking:
            return old_booking, False

    try:
        with transaction.atomic():
            # Check and change the counter in ONE update, inside the database:
            # UPDATE event SET booked_tickets = booked_tickets + 2
            # WHERE id = 1 AND booked_tickets <= total_tickets - 2
            # Postgres runs these one by one for the same row, so 2 requests
            # can never both get the last ticket.
            updated = Event.objects.filter(
                pk=event_id,
                starts_at__gt=timezone.now(),
                booked_tickets__lte=F("total_tickets") - tickets,
            ).update(booked_tickets=F("booked_tickets") + tickets)

            if not updated:
                raise BookingError(why_booking_failed(event_id))

            booking = Booking.objects.create(
                user=user,
                event_id=event_id,
                tickets=tickets,
                expires_at=timezone.now() + timedelta(minutes=RESERVATION_MINUTES),
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        # Same idempotency key sent twice at the same moment and the other request won.
        # Our update was rolled back, so we just return the other booking.
        if idempotency_key is None:
            raise
        return Booking.objects.get(user=user, idempotency_key=idempotency_key), False

    realtime.send_availability(event_id)
    return booking, True


def why_booking_failed(event_id):
    event = Event.objects.filter(pk=event_id).first()
    if event is None:
        return "Event not found."
    if event.starts_at <= timezone.now():
        return "This event has already started."
    return f"Only {event.available_tickets} tickets left."


def confirm_booking(user, booking_id):
    # Works only if it is still pending and not expired. One UPDATE, so it can't
    # happen at the same time as the expire job.
    updated = Booking.objects.filter(
        pk=booking_id,
        user=user,
        status=Booking.PENDING,
        expires_at__gt=timezone.now(),
    ).update(status=Booking.CONFIRMED)

    if not updated:
        raise BookingError("Only a pending reservation can be confirmed. It may have expired.")
    return Booking.objects.get(pk=booking_id)


def cancel_booking(user, booking_id):
    booking = Booking.objects.filter(pk=booking_id, user=user).first()
    if booking is None:
        raise BookingError("Booking not found.")

    released = release_tickets(booking, Booking.CANCELLED, from_statuses=[Booking.PENDING, Booking.CONFIRMED])
    if not released:
        raise BookingError("This booking is already cancelled or expired.")


def release_expired_bookings():
    """Runs every 30 seconds in Celery (see CELERY_BEAT_SCHEDULE in settings)."""
    expired = Booking.objects.filter(status=Booking.PENDING, expires_at__lte=timezone.now())
    count = 0
    for booking in expired:
        if release_tickets(booking, Booking.EXPIRED, from_statuses=[Booking.PENDING]):
            count += 1
    return count


def release_tickets(booking, new_status, from_statuses):
    """Give the tickets of a booking back. Returns False if someone else already did it."""
    with transaction.atomic():
        # Only one request can change the status, so the tickets come back only once.
        changed = Booking.objects.filter(pk=booking.pk, status__in=from_statuses).update(status=new_status)
        if changed:
            Event.objects.filter(pk=booking.event_id).update(booked_tickets=F("booked_tickets") - booking.tickets)

    if not changed:
        return False

    from .tasks import process_waitlist  # import here to avoid a circular import

    realtime.send_availability(booking.event_id)
    process_waitlist.delay(booking.event_id)
    return True


def join_waitlist(user, event_id, tickets=1):
    event = Event.objects.filter(pk=event_id).first()
    if event is None:
        raise BookingError("Event not found.")
    if tickets < 1:
        raise BookingError("You must ask for at least 1 ticket.")
    if event.available_tickets >= tickets:
        raise BookingError("There are enough tickets, you can book them now.")

    entry, created = WaitlistEntry.objects.get_or_create(user=user, event=event, defaults={"tickets": tickets})
    if not created:
        raise BookingError("You are already on the waiting list.")
    return entry


def leave_waitlist(user, event_id):
    deleted, _ = WaitlistEntry.objects.filter(user=user, event_id=event_id).delete()
    if not deleted:
        raise BookingError("You are not on the waiting list.")


def process_waitlist(event_id):
    """
    Called (in Celery) when tickets are freed. The first people in the waiting
    list get a normal 5 minute reservation, which they see in their bookings.
    """
    while True:
        with transaction.atomic():
            # Lock the first entry so two workers don't give it tickets twice.
            entry = WaitlistEntry.objects.select_for_update().filter(event_id=event_id).first()
            if entry is None:
                return
            try:
                reserve_tickets(entry.user, event_id, entry.tickets)
            except BookingError:
                return  # not enough free tickets for the next person
            entry.delete()
        logger.info("Waiting list: reserved %s tickets for %s", entry.tickets, entry.user)
