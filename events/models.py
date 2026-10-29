import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.signals import pre_delete
from django.dispatch import receiver


class Event(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    total_tickets = models.PositiveIntegerField()
    # Only changed with F() updates in services.py, never by hand.
    booked_tickets = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            # Postgres itself will refuse to overbook, even if there is a bug in the code.
            models.CheckConstraint(condition=Q(booked_tickets__lte=F("total_tickets")), name="event_not_overbooked"),
        ]

    def __str__(self):
        return self.title

    @property
    def available_tickets(self):
        return self.total_tickets - self.booked_tickets

    def clean(self):
        if self.total_tickets is not None and self.total_tickets < self.booked_tickets:
            raise ValidationError({"total_tickets": f"{self.booked_tickets} tickets are already booked."})

    def save(self, *args, **kwargs):
        # When the admin saves an event, don't write back an old booked_tickets value.
        if not self._state.adding and "update_fields" not in kwargs:
            kwargs["update_fields"] = ["title", "description", "location", "starts_at", "total_tickets"]
        super().save(*args, **kwargs)


class Booking(models.Model):
    PENDING = "pending"        # tickets are held for 5 minutes
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"        # not confirmed in time
    STATUS_CHOICES = [
        (PENDING, "Pending"),
        (CONFIRMED, "Confirmed"),
        (CANCELLED, "Cancelled"),
        (EXPIRED, "Expired"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="bookings")
    tickets = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=PENDING)
    expires_at = models.DateTimeField(null=True, blank=True)
    code = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)  # goes into the QR code
    idempotency_key = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "idempotency_key"], name="unique_idempotency_key_per_user"),
        ]

    def __str__(self):
        return f"{self.user} - {self.event} ({self.tickets}, {self.status})"


class WaitlistEntry(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="waitlist")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="waitlist")
    tickets = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "event"], name="one_waitlist_entry_per_user"),
        ]

    def __str__(self):
        return f"{self.user} waits for {self.event}"


@receiver(pre_delete, sender=Booking)
def give_tickets_back(sender, instance, **kwargs):
    # A booking was deleted (in the admin, or its user was deleted).
    # Lock the row and check the status again, it may have been cancelled at the same moment.
    still_active = Booking.objects.select_for_update().filter(
        pk=instance.pk, status__in=[Booking.PENDING, Booking.CONFIRMED]
    ).exists()
    if still_active:
        Event.objects.filter(pk=instance.event_id).update(booked_tickets=F("booked_tickets") - instance.tickets)
