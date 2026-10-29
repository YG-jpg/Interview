from django.contrib import admin

from .models import Booking, Event


class BookingInline(admin.TabularInline):
    model = Booking
    extra = 0
    readonly_fields = ["user", "tickets", "created_at"]
    can_delete = False


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "starts_at", "location", "total_tickets", "booked_tickets", "available_tickets"]
    search_fields = ["title", "location"]
    inlines = [BookingInline]


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "tickets", "created_at"]
    list_filter = ["event"]
