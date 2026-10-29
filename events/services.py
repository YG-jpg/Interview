"""
Business logic for bookings.

The API views and the HTML pages both call these functions, so the booking
rules live in one place only.
"""
from django.db import transaction
from django.utils import timezone

from .models import Booking, Event


class BookingError(Exception):
    """Raised when a booking cannot be made. The message is shown to the user."""


def book_tickets(user, event_id, tickets):
    """
    Book `tickets` tickets for `user` and return the new Booking.

    This is safe when many threads (or many servers) book at the same time:
    select_for_update() locks the event row in the database until the
    transaction ends. A second request for the same event waits here until
    the first one has finished, and then it sees the updated ticket count.
    So we can never sell more tickets than the event has.
    """
    if tickets < 1:
        raise BookingError("You must book at least 1 ticket.")

    with transaction.atomic():
        try:
            event = Event.objects.select_for_update().get(pk=event_id)
        except Event.DoesNotExist:
            raise BookingError("Event not found.")

        if event.starts_at <= timezone.now():
            raise BookingError("This event has already started.")

        available = event.available_tickets
        if tickets > available:
            raise BookingError(f"Only {available} tickets left.")

        booking = Booking.objects.create(user=user, event=event, tickets=tickets)

    return booking


def cancel_booking(user, booking_id):
    """
    Cancel one of the user's bookings. The tickets become available again.

    We lock the event row here too, so a cancel and a booking for the same
    event never run at the same moment.
    """
    with transaction.atomic():
        try:
            booking = Booking.objects.get(pk=booking_id, user=user)
        except Booking.DoesNotExist:
            raise BookingError("Booking not found.")

        Event.objects.select_for_update().get(pk=booking.event_id)
        booking.delete()
