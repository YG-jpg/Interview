import uuid

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from . import services
from .models import Booking, Event
from .qr import make_qr_png
from .serializers import (
    BookingSerializer,
    CreateBookingSerializer,
    EventSerializer,
    RegisterSerializer,
    WaitlistSerializer,
)
from .throttles import BookingRateThrottle


def error(message, code=status.HTTP_400_BAD_REQUEST):
    return Response({"detail": message}, status=code)


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def event_list(request):
    events = Event.objects.all()
    return Response(EventSerializer(events, many=True).data)


@api_view(["GET"])
def event_detail(request, pk):
    event = get_object_or_404(Event, pk=pk)
    return Response(EventSerializer(event).data)


@api_view(["POST", "DELETE"])
def event_waitlist(request, pk):
    """POST - join the waiting list of a sold out event. DELETE - leave it."""
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
    GET  - my bookings
    POST - reserve tickets for 5 minutes. Body: {"event": 1, "tickets": 2}
           Optional header "Idempotency-Key: <uuid>". If the same key is sent
           again we return the same booking instead of booking twice.
    """
    if request.method == "GET":
        bookings = Booking.objects.filter(user=request.user).select_related("event")
        return Response(BookingSerializer(bookings, many=True).data)

    serializer = CreateBookingSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

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

    code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return Response(BookingSerializer(booking).data, status=code)


@api_view(["GET", "DELETE"])
def booking_detail(request, pk):
    """GET - one of my bookings. DELETE - cancel it."""
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
    booking = get_object_or_404(Booking, pk=pk, user=request.user)
    try:
        booking = services.confirm_booking(request.user, booking.pk)
    except services.BookingError as e:
        return error(str(e))
    return Response(BookingSerializer(booking).data)


@api_view(["GET"])
def booking_qr(request, pk):
    """The ticket as a QR code (PNG). Only for confirmed bookings."""
    booking = get_object_or_404(Booking, pk=pk, user=request.user)
    if booking.status != Booking.CONFIRMED:
        return error("Only confirmed bookings have a ticket.")
    return HttpResponse(make_qr_png(str(booking.code)), content_type="image/png")
