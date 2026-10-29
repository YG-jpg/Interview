from django.conf import settings
from django.db import models
from django.db.models import Sum


class Event(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    total_tickets = models.PositiveIntegerField()

    class Meta:
        ordering = ["starts_at"]

    def __str__(self):
        return self.title

    @property
    def booked_tickets(self):
        return self.bookings.aggregate(total=Sum("tickets"))["total"] or 0

    @property
    def available_tickets(self):
        return self.total_tickets - self.booked_tickets


class Booking(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookings")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="bookings")
    tickets = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} - {self.event} ({self.tickets})"
