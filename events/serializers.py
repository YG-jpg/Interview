from django.contrib.auth.models import User
from rest_framework import serializers

from .models import Booking, Event


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ["id", "username", "password"]

    def create(self, validated_data):
        # create_user() saves the password as a hash, never as plain text.
        return User.objects.create_user(**validated_data)


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            "id", "title", "description", "location", "starts_at",
            "total_tickets", "booked_tickets", "available_tickets",
        ]


class BookingSerializer(serializers.ModelSerializer):
    """Used to show a booking (output)."""
    event = EventSerializer(read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "event", "tickets", "created_at"]


class CreateBookingSerializer(serializers.Serializer):
    """Used to read the body of POST /api/bookings/ (input)."""
    event = serializers.IntegerField()
    tickets = serializers.IntegerField(min_value=1, default=1)
