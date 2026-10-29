"""
Админ панелът на организатора (/admin/): създава, редактира и трие събития
и гледа резервациите.
"""
from django.contrib import admin

from .models import Booking, Event, WaitlistEntry


# Таблица с резервациите вътре в страницата на събитието.
class BookingInline(admin.TabularInline):
    # Само за гледане. Резервациите се създават и променят само чрез services.py.
    model = Booking
    extra = 0
    fields = ["user", "tickets", "status", "expires_at", "created_at"]
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# Събитията: списък с колони, търсене по заглавие и място, резервациите отдолу.
@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["title", "starts_at", "location", "total_tickets", "booked_tickets", "available_tickets"]
    search_fields = ["title", "location"]
    inlines = [BookingInline]


# Резервации се правят само чрез services.py, който проверява лимита на билетите.
# Тук организаторът може само да ги гледа или да изтрие някоя (билетите се връщат).
@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "tickets", "status", "expires_at", "created_at"]
    list_filter = ["status", "event"]
    readonly_fields = ["user", "event", "tickets", "status", "expires_at", "code", "idempotency_key", "created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# Листата на чакащите.
@admin.register(WaitlistEntry)
class WaitlistEntryAdmin(admin.ModelAdmin):
    list_display = ["user", "event", "tickets", "created_at"]
    list_filter = ["event"]
