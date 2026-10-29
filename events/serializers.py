from django.contrib.auth.models import User
from rest_framework import serializers

from .models import Booking, Event


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ["id", "username", "password"]

    def create(self, validated_data):
        # create_user() saves a hash of the password, not the password itself
        return User.objects.create_user(**validated_data)


class EventSerializer(serializers.ModelSerializer):
    class Meta:
        model = Event
        fields = [
            "id", "title", "description", "location", "starts_at",
            "total_tickets", "booked_tickets", "available_tickets",
        ]


class BookingSerializer(serializers.ModelSerializer):
    event = EventSerializer(read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "event", "tickets", "status", "expires_at", "created_at"]


class CreateBookingSerializer(serializers.Serializer):
    event = serializers.IntegerField()
    tickets = serializers.IntegerField(min_value=1, default=1)


class WaitlistSerializer(serializers.Serializer):
    tickets = serializers.IntegerField(min_value=1, default=1)
