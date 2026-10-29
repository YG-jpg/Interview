from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import services
from .models import Booking, Event
from .serializers import BookingSerializer, CreateBookingSerializer, EventSerializer, RegisterSerializer


@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def register(request):
    """POST /api/register/ - create a new user account."""
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    serializer.save()
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def event_list(request):
    """GET /api/events/ - list all events."""
    events = Event.objects.all()
    serializer = EventSerializer(events, many=True)
    return Response(serializer.data)


@api_view(["GET"])
def event_detail(request, pk):
    """GET /api/events/<id>/ - show one event."""
    event = get_object_or_404(Event, pk=pk)
    serializer = EventSerializer(event)
    return Response(serializer.data)


@api_view(["GET", "POST"])
def booking_list(request):
    """
    GET  /api/bookings/ - list my bookings.
    POST /api/bookings/ - book tickets. Body: {"event": 1, "tickets": 2}
    """
    if request.method == "GET":
        bookings = Booking.objects.filter(user=request.user).select_related("event")
        serializer = BookingSerializer(bookings, many=True)
        return Response(serializer.data)

    serializer = CreateBookingSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    try:
        booking = services.book_tickets(
            user=request.user,
            event_id=serializer.validated_data["event"],
            tickets=serializer.validated_data["tickets"],
        )
    except services.BookingError as error:
        return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(BookingSerializer(booking).data, status=status.HTTP_201_CREATED)


@api_view(["GET", "DELETE"])
def booking_detail(request, pk):
    """
    GET    /api/bookings/<id>/ - show one of my bookings.
    DELETE /api/bookings/<id>/ - cancel one of my bookings.
    """
    if request.method == "GET":
        # Filtering by user means you get 404 for other people's bookings.
        booking = get_object_or_404(Booking, pk=pk, user=request.user)
        return Response(BookingSerializer(booking).data)

    try:
        services.cancel_booking(user=request.user, booking_id=pk)
    except services.BookingError as error:
        return Response({"detail": str(error)}, status=status.HTTP_404_NOT_FOUND)

    return Response(status=status.HTTP_204_NO_CONTENT)
