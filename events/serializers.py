"""
Serializer-ите превръщат JSON от заявката в проверени Python данни (валидация),
а моделите - обратно в JSON за отговора.
"""
from django.contrib.auth.models import User
from rest_framework import serializers

from .models import Booking, Event


class RegisterSerializer(serializers.ModelSerializer):
    """
    Регистрация на потребител.
    username се проверява от валидатора на модела User: само букви, цифри и @ . + - _,
    до 150 символа и да не е зает. password може да съдържа всякакви символи, минимум 6.
    write_only=True - паролата никога не се връща в отговора.
    """
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ["id", "username", "password"]

    def create(self, validated_data):
        # create_user() пази хеш на паролата (PBKDF2), а не самата парола
        return User.objects.create_user(**validated_data)


class EventSerializer(serializers.ModelSerializer):
    """Събитие в JSON, заедно с изчисленото поле available_tickets."""
    class Meta:
        model = Event
        fields = [
            "id", "title", "description", "location", "starts_at",
            "total_tickets", "booked_tickets", "available_tickets",
        ]


class BookingSerializer(serializers.ModelSerializer):
    """Резервация в JSON, със събитието вътре."""
    event = EventSerializer(read_only=True)

    class Meta:
        model = Booking
        fields = ["id", "event", "tickets", "status", "expires_at", "created_at"]


class CreateBookingSerializer(serializers.Serializer):
    """Входът при нова резервация: id на събитието и брой билети (поне 1)."""
    event = serializers.IntegerField()
    tickets = serializers.IntegerField(min_value=1, default=1)


class WaitlistSerializer(serializers.Serializer):
    """Входът при записване в листата на чакащите: брой билети (поне 1)."""
    tickets = serializers.IntegerField(min_value=1, default=1)
