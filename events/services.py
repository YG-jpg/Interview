"""
Всички правила за резервациите са събрани тук, на едно място.

И API-то (events/views.py), и сайтът (pages/views.py) викат функциите от този
файл. Така едно правило (напр. "не може да се резервират повече билети, отколкото
има") е написано само веднъж и важи и за двете места.

Основната идея за сигурност, когато много хора резервират едновременно:
броячът booked_tickets се променя само с една атомарна UPDATE заявка в PostgreSQL
(чрез F() изрази). Стойността никога не се чете в Python, за да се промени и
запише обратно - затова две заявки не могат едновременно да "видят", че е
останал 1 билет, и двете да го вземат.
"""
import logging
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import Booking, Event, WaitlistEntry

logger = logging.getLogger(__name__)

# Колко минути се пазят билетите, преди потребителят да потвърди резервацията.
RESERVATION_MINUTES = 5


# Грешка с обяснение за потребителя (напр. "Only 2 tickets left.").
# API-то я връща като {"detail": "..."} с код 400, а сайтът - като червено съобщение.
class BookingError(Exception):
    pass


def reserve_tickets(user, event_id, tickets, idempotency_key=None):
    """
    Запазва (резервира) билети за 5 минути. Потребителят трябва да потвърди
    резервацията дотогава, иначе release_expired_bookings() връща билетите.

    Връща двойка (booking, created). created е False, когато същият
    idempotency_key вече е бил изпратен - тогава връщаме старата резервация,
    вместо да резервираме втори път (напр. при двоен клик или повторена заявка
    заради лоша връзка).
    """
    # Проверка на входа: 0 или отрицателен брой билети няма смисъл.
    if tickets < 1:
        raise BookingError("You must book at least 1 ticket.")

    # Ако тази заявка вече е идвала (същият ключ), връщаме вече направената резервация.
    if idempotency_key:
        old_booking = Booking.objects.filter(user=user, idempotency_key=idempotency_key).first()
        if old_booking:
            return old_booking, False

    try:
        with transaction.atomic():
            # Проверяваме и променяме брояча с ЕДНА заявка, вътре в базата:
            #   UPDATE event SET booked_tickets = booked_tickets + 2
            #   WHERE id = 1 AND booked_tickets <= total_tickets - 2
            # Ако има достатъчно свободни билети, редът се променя (updated = 1).
            # Ако няма - не се променя нищо (updated = 0).
            # Postgres изпълнява такива заявки за един и същи ред една след друга
            # (заключва реда), затова 2 заявки никога не могат да вземат последния билет.
            # Проверява се и че събитието още не е започнало (starts_at > сега).
            updated = Event.objects.filter(
                pk=event_id,
                starts_at__gt=timezone.now(),
                booked_tickets__lte=F("total_tickets") - tickets,
            ).update(booked_tickets=F("booked_tickets") + tickets)

            if not updated:
                raise BookingError(why_booking_failed(event_id))

            # Резервацията се създава в същата транзакция като UPDATE-а: или стават и
            # двете неща, или нито едно (ако нещо се счупи, броячът се връща обратно).
            booking = Booking.objects.create(
                user=user,
                event_id=event_id,
                tickets=tickets,
                expires_at=timezone.now() + timedelta(minutes=RESERVATION_MINUTES),
                idempotency_key=idempotency_key,
            )
    except IntegrityError:
        # Същият idempotency key е изпратен два пъти в един и същи момент и другата
        # заявка е спечелила (базата не позволява два еднакви ключа за един потребител).
        # Нашият UPDATE е върнат обратно (rollback), затова просто връщаме другата резервация.
        if idempotency_key is None:
            raise
        return Booking.objects.get(user=user, idempotency_key=idempotency_key), False

    # Казваме на всички отворени браузъри (през WebSocket) колко билета са останали.
    send_availability(event_id)
    return booking, True


def why_booking_failed(event_id):
    """Обяснява защо UPDATE-ът не е променил нищо: няма такова събитие, започнало е или няма достатъчно билети."""
    event = Event.objects.filter(pk=event_id).first()
    if event is None:
        return "Event not found."
    if event.starts_at <= timezone.now():
        return "This event has already started."
    return f"Only {event.available_tickets} tickets left."


def confirm_booking(user, booking_id):
    # Потвърждава само резервация, която още чака (pending) и не е изтекла.
    # Всичко е в една UPDATE заявка, затова не може да се случи по същото време
    # с фоновата задача, която маркира изтеклите резервации.
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
    """Отказва резервация (pending или confirmed) и връща билетите на събитието."""
    # Търсим само сред резервациите на ТОЗИ потребител - чужда резервация не може да се откаже.
    booking = Booking.objects.filter(pk=booking_id, user=user).first()
    if booking is None:
        raise BookingError("Booking not found.")

    released = release_tickets(booking, Booking.CANCELLED, from_statuses=[Booking.PENDING, Booking.CONFIRMED])
    if not released:
        raise BookingError("This booking is already cancelled or expired.")


def release_expired_bookings():
    """
    Пуска се на всеки 30 секунди от Celery (виж CELERY_BEAT_SCHEDULE в settings.py).
    Връща билетите от резервациите, които не са потвърдени навреме. Връща колко са били.
    """
    expired = Booking.objects.filter(status=Booking.PENDING, expires_at__lte=timezone.now())
    count = 0
    for booking in expired:
        if release_tickets(booking, Booking.EXPIRED, from_statuses=[Booking.PENDING]):
            count += 1
    return count


def release_tickets(booking, new_status, from_statuses):
    """Връща билетите на една резервация. Връща False, ако някой друг вече го е направил."""
    with transaction.atomic():
        # Само една заявка може да смени статуса (UPDATE ... WHERE status IN (...)), затова
        # билетите се връщат само веднъж, дори при много едновременни откази.
        changed = Booking.objects.filter(pk=booking.pk, status__in=from_statuses).update(status=new_status)
        if changed:
            Event.objects.filter(pk=booking.event_id).update(booked_tickets=F("booked_tickets") - booking.tickets)

    if not changed:
        return False

    from .tasks import process_waitlist  # импортираме тук, за да няма кръгов импорт (tasks.py импортира services.py)

    # Обновяваме броя в браузърите и даваме шанс на хората от листата на чакащите.
    send_availability(booking.event_id)
    process_waitlist.delay(booking.event_id)
    return True


def join_waitlist(user, event_id, tickets=1):
    """Записва потребителя в листата на чакащите. Само ако събитието е разпродадено."""
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
    """Маха потребителя от листата на чакащите."""
    deleted, _ = WaitlistEntry.objects.filter(user=user, event_id=event_id).delete()
    if not deleted:
        raise BookingError("You are not on the waiting list.")


def process_waitlist(event_id):
    """
    Вика се (от Celery), когато се освободят билети. Първите хора в листата на
    чакащите получават нормална резервация за 5 минути, която виждат в "My bookings".
    Повтаряме, докато има достатъчно свободни билети за следващия човек.
    """
    while True:
        with transaction.atomic():
            # Заключваме първия запис (SELECT ... FOR UPDATE), за да не му дадат
            # билети два worker-а едновременно.
            entry = WaitlistEntry.objects.select_for_update().filter(event_id=event_id).first()
            if entry is None:
                return
            try:
                reserve_tickets(entry.user, event_id, entry.tickets)
            except BookingError:
                return  # няма достатъчно свободни билети за следващия човек
            entry.delete()
        logger.info("Waiting list: reserved %s tickets for %s", entry.tickets, entry.user)


def send_availability(event_id):
    """
    Обновяване на живо: казва на всеки браузър, отворил това събитие, колко билета
    са останали. Съобщението минава през Redis (channel layer) до WebSocket сървъра
    (consumers.py), а той го праща на браузърите.
    """
    try:
        event = Event.objects.get(pk=event_id)
        async_to_sync(get_channel_layer().group_send)(
            f"event_{event_id}",
            {"type": "tickets.update", "available_tickets": event.available_tickets},
        )
    except Exception:
        # Резервацията вече е записана. Проблем с обновяването на живо не бива да я развали.
        logger.exception("Could not send availability update for event %s", event_id)
