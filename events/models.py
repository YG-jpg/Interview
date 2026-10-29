"""
Моделите - таблиците в базата: Event (събитие), Booking (резервация)
и WaitlistEntry (запис в листата на чакащите).
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.signals import pre_delete
from django.dispatch import receiver


# Събитие (концерт, конференция...). Организаторът го създава в админ панела.
class Event(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    location = models.CharField(max_length=200)
    starts_at = models.DateTimeField()
    total_tickets = models.PositiveIntegerField()
    # Колко билета са заети. Променя се само с F() UPDATE заявки в services.py, никога
    # на ръка (editable=False - не се показва за редакция в админа).
    booked_tickets = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["starts_at"]
        constraints = [
            # Самият Postgres ще откаже свръхрезервиране (booked_tickets > total_tickets),
            # дори ако има бъг в кода. Това е последната защита.
            models.CheckConstraint(condition=Q(booked_tickets__lte=F("total_tickets")), name="event_not_overbooked"),
        ]

    def __str__(self):
        return self.title

    @property
    def available_tickets(self):
        """Свободни билети = общо - заети. Изчислява се, не се пази в базата."""
        return self.total_tickets - self.booked_tickets

    def clean(self):
        """Проверка във формата на админа: общият брой не може да падне под вече заетите."""
        if self.total_tickets is not None and self.total_tickets < self.booked_tickets:
            raise ValidationError({"total_tickets": f"{self.booked_tickets} tickets are already booked."})

    def save(self, *args, **kwargs):
        # Когато админът запише събитие, не записваме обратно стара стойност на booked_tickets
        # (докато е гледал страницата, някой може да е резервирал). Записваме само тези полета.
        if not self._state.adding and "update_fields" not in kwargs:
            kwargs["update_fields"] = ["title", "description", "location", "starts_at", "total_tickets"]
        super().save(*args, **kwargs)


# Резервация: кой потребител, за кое събитие, колко билета и в какво състояние е.
class Booking(models.Model):
    PENDING = "pending"        # билетите се пазят 5 минути, чака потвърждение
    CONFIRMED = "confirmed"    # потвърдена, има QR код
    CANCELLED = "cancelled"    # отказана от потребителя, билетите са върнати
    EXPIRED = "expired"        # не е потвърдена навреме, билетите са върнати
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
    code = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)  # уникален код, който се слага в QR кода на билета
    idempotency_key = models.UUIDField(null=True, blank=True)  # пази от двойна резервация
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # Един потребител не може да има две резервации с един и същи ключ.
            models.UniqueConstraint(fields=["user", "idempotency_key"], name="unique_idempotency_key_per_user"),
        ]

    def __str__(self):
        return f"{self.user} - {self.event} ({self.tickets}, {self.status})"


# Запис в листата на чакащите за разпродадено събитие. Подредени са по реда на записване.
class WaitlistEntry(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="waitlist")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="waitlist")
    tickets = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            # Всеки потребител може да чака за едно събитие само веднъж.
            models.UniqueConstraint(fields=["user", "event"], name="one_waitlist_entry_per_user"),
        ]

    def __str__(self):
        return f"{self.user} waits for {self.event}"


# Сигнал: Django вика тази функция автоматично точно преди да изтрие Booking.
@receiver(pre_delete, sender=Booking)
def give_tickets_back(sender, instance, **kwargs):
    # Изтрива се резервация (в админа или защото е изтрит потребителят ѝ).
    # Заключваме реда и проверяваме статуса отново - може да е отказана в същия момент.
    # Връщаме билетите само ако е била активна (pending или confirmed), иначе вече са върнати.
    still_active = Booking.objects.select_for_update().filter(
        pk=instance.pk, status__in=[Booking.PENDING, Booking.CONFIRMED]
    ).exists()
    if still_active:
        Event.objects.filter(pk=instance.event_id).update(booked_tickets=F("booked_tickets") - instance.tickets)
