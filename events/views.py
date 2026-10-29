"""
REST API (JSON). Всеки endpoint е обикновена функция с декоратор @api_view.
Правилата за резервации не са тук, а в services.py - тук само четем входа,
викаме services и връщаме отговор. Адресите са в events/urls.py.
"""
import io
import uuid

import qrcode
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from . import services
from .models import Booking, Event
from .serializers import (
    BookingSerializer,
    CreateBookingSerializer,
    EventSerializer,
    RegisterSerializer,
    WaitlistSerializer,
)


class BookingRateThrottle(UserRateThrottle):
    """
    Ограничава колко резервации може да направи един потребител за минута.
    Лимитът е "bookings" в DEFAULT_THROTTLE_RATES в settings.py (10/minute).
    Брои се само POST (нова резервация), GET (списък) винаги минава.
    """
    scope = "bookings"

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


def error(message, code=status.HTTP_400_BAD_REQUEST):
    """Връща грешка във формата {"detail": "..."} (по подразбиране с код 400)."""
    return Response({"detail": message}, status=code)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    """
    POST /api/register/ - регистрация. Body: {"username": "...", "password": "..."}

    Не изисква login (AllowAny) и не проверява автентикация (authentication_classes([])).
    Входът се проверява в RegisterSerializer: потребителското име може да съдържа само
    букви, цифри и @ . + - _ (валидатор на Django), а паролата - всякакви символи.
    Паролата се пази като хеш. SQL injection не е възможна, защото ORM-ът праща
    стойностите отделно от SQL заявката (параметризирана заявка).
    """
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def event_list(request):
    """GET /api/events/ - всички събития."""
    events = Event.objects.all()
    return Response(EventSerializer(events, many=True).data)


@api_view(["GET"])
def event_detail(request, pk):
    """GET /api/events/<id>/ - едно събитие (404, ако го няма)."""
    event = get_object_or_404(Event, pk=pk)
    return Response(EventSerializer(event).data)


@api_view(["POST", "DELETE"])
def event_waitlist(request, pk):
    """POST - записване в листата на чакащите за разпродадено събитие. DELETE - отписване."""
    try:
        if request.method == "DELETE":
            services.leave_waitlist(request.user, pk)
            return Response(status=status.HTTP_204_NO_CONTENT)

        serializer = WaitlistSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.join_waitlist(request.user, pk, serializer.validated_data["tickets"])
    except services.BookingError as e:
        return error(str(e))
    return Response({"detail": "You are on the waiting list."}, status=status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@throttle_classes([UserRateThrottle, BookingRateThrottle])
def booking_list(request):
    """
    GET  - моите резервации
    POST - резервира билети за 5 минути. Body: {"event": 1, "tickets": 2}
           По избор хедър "Idempotency-Key: <uuid>". Ако същият ключ се изпрати
           отново, връщаме същата резервация, вместо да резервираме два пъти.
    Ограничение: до 10 нови резервации в минута на потребител (BookingRateThrottle).
    """
    if request.method == "GET":
        bookings = Booking.objects.filter(user=request.user).select_related("event")
        return Response(BookingSerializer(bookings, many=True).data)

    serializer = CreateBookingSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    # Ключът трябва да е валиден UUID, иначе връщаме 400.
    key = request.headers.get("Idempotency-Key")
    if key:
        try:
            key = uuid.UUID(key)
        except ValueError:
            return error("Idempotency-Key must be a UUID.")

    try:
        booking, created = services.reserve_tickets(
            request.user,
            serializer.validated_data["event"],
            serializer.validated_data["tickets"],
            idempotency_key=key,
        )
    except services.BookingError as e:
        return error(str(e))

    # 201 - нова резервация, 200 - същата резервация отпреди (същият ключ).
    code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return Response(BookingSerializer(booking).data, status=code)


@api_view(["GET", "DELETE"])
def booking_detail(request, pk):
    """GET - една от моите резервации. DELETE - отказва я. За чужда резервация - 404."""
    booking = get_object_or_404(Booking, pk=pk, user=request.user)

    if request.method == "GET":
        return Response(BookingSerializer(booking).data)

    try:
        services.cancel_booking(request.user, booking.pk)
    except services.BookingError as e:
        return error(str(e))
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
def booking_confirm(request, pk):
    """POST /api/bookings/<id>/confirm/ - потвърждава резервация, която още чака."""
    booking = get_object_or_404(Booking, pk=pk, user=request.user)
    try:
        booking = services.confirm_booking(request.user, booking.pk)
    except services.BookingError as e:
        return error(str(e))
    return Response(BookingSerializer(booking).data)


@api_view(["GET"])
def booking_qr(request, pk):
    """Билетът като QR код (PNG картинка). Само за потвърдени резервации."""
    booking = get_object_or_404(Booking, pk=pk, user=request.user)
    if booking.status != Booking.CONFIRMED:
        return error("Only confirmed bookings have a ticket.")

    # Правим QR код от уникалния код на резервацията и го връщаме като PNG, без да пишем файл.
    image = qrcode.make(str(booking.code))
    buffer = io.BytesIO()
    image.save(buffer)
    return HttpResponse(buffer.getvalue(), content_type="image/png")
