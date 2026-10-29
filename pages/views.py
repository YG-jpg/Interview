import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from events import services
from events.models import Event

from .forms import BookingForm


def event_list(request):
    events = Event.objects.all()
    return render(request, "pages/event_list.html", {"events": events})


def event_detail(request, pk):
    event = get_object_or_404(Event, pk=pk)
    form = BookingForm(initial={"idempotency_key": uuid.uuid4()})
    on_waitlist = False
    if request.user.is_authenticated:
        on_waitlist = event.waitlist.filter(user=request.user).exists()
    return render(request, "pages/event_detail.html", {
        "event": event,
        "form": form,
        "on_waitlist": on_waitlist,
        "websocket_port": settings.WEBSOCKET_PORT,
    })


@login_required
@require_POST
def book_event(request, pk):
    form = BookingForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please enter a number of tickets (at least 1).")
        return redirect("event_detail", pk=pk)

    tickets = form.cleaned_data["tickets"]
    key = form.cleaned_data["idempotency_key"]
    try:
        booking, created = services.reserve_tickets(request.user, pk, tickets, idempotency_key=key)
    except services.BookingError as e:
        messages.error(request, str(e))
        return redirect("event_detail", pk=pk)

    if created:
        messages.success(request, f"Reserved {tickets} tickets. Confirm within {services.RESERVATION_MINUTES} minutes.")
    else:
        messages.info(request, "This reservation was already made.")
    return redirect("my_bookings")


@login_required
def my_bookings(request):
    bookings = request.user.bookings.select_related("event")
    return render(request, "pages/my_bookings.html", {"bookings": bookings})


@login_required
@require_POST
def confirm_booking_view(request, pk):
    try:
        services.confirm_booking(request.user, pk)
    except services.BookingError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Booking confirmed.")
    return redirect("my_bookings")


@login_required
@require_POST
def cancel_booking_view(request, pk):
    try:
        services.cancel_booking(request.user, pk)
    except services.BookingError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Booking cancelled.")
    return redirect("my_bookings")


@login_required
@require_POST
def join_waitlist_view(request, pk):
    try:
        services.join_waitlist(request.user, pk)
    except services.BookingError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "You joined the waiting list.")
    return redirect("event_detail", pk=pk)


@login_required
@require_POST
def leave_waitlist_view(request, pk):
    try:
        services.leave_waitlist(request.user, pk)
    except services.BookingError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "You left the waiting list.")
    return redirect("event_detail", pk=pk)


def register(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f"Welcome, {user.username}!")
            return redirect("event_list")
    else:
        form = UserCreationForm()
    return render(request, "pages/register.html", {"form": form})
