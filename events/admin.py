from django.contrib import admin

from .models import Booking, Event, WaitlistEntry


class BookingInline(admin.TabularInline):
    model = Booking
    extra = 0
    readonly_fields = ["user", "tickets", "status", "created_at"]
    can_delete = False


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "starts_at", "location", "total_tickets", "booked_tickets", "available_tickets"]
    search_fields = ["title", "location"]
    inlines = [BookingInline]


# Bookings are made only through services.py, which checks the ticket limit.
# Here the organizer can only look at them.
@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "tickets", "status", "expires_at", "created_at"]
    list_filter = ["status", "event"]
    readonly_fields = ["user", "event", "tickets", "status", "expires_at", "code", "idempotency_key", "created_at"]

    def has_add_permission(self, request):
        return False


@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "tickets", "created_at"]
    list_filter = ["event"]
