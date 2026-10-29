"""
HTML pages for the website.

The booking rules are not here. They live in events/services.py, and these
views only call them and show the result to the user.
"""
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from events.models import Event
from events.services import BookingError, book_tickets, cancel_booking

from .forms import BookingForm


def event_list(request):
    events = Event.objects.all()
    return render(request, "pages/event_list.html", {"events": events})


def event_detail(request, pk):
    event = get_object_or_404(Event, pk=pk)
    form = BookingForm()
    return render(request, "pages/event_detail.html", {"event": event, "form": form})


@login_required
@require_POST
def book_event(request, pk):
    form = BookingForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Please enter a number of tickets (at least 1).")
        return redirect("event_detail", pk=pk)

    tickets = form.cleaned_data["tickets"]
    try:
        book_tickets(request.user, pk, tickets)
    except BookingError as e:
        messages.error(request, str(e))
        return redirect("event_detail", pk=pk)

    messages.success(request, f"Booked {tickets} tickets.")
    return redirect("my_bookings")


@login_required
def my_bookings(request):
    bookings = request.user.bookings.select_related("event")
    return render(request, "pages/my_bookings.html", {"bookings": bookings})


@login_required
@require_POST
def cancel_booking_view(request, pk):
    # Named "..._view" so it does not hide the cancel_booking service function.
    try:
        cancel_booking(request.user, pk)
    except BookingError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, "Booking cancelled.")
    return redirect("my_bookings")


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
