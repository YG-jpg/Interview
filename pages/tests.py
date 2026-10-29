import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events import services
from events.models import Booking, Event, WaitlistEntry


class PagesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="secret-pass-123")
        self.bob = User.objects.create_user(username="bob", password="secret-pass-123")
        self.event = Event.objects.create(
            title="Concert",
            description="A nice concert.",
            location="Sofia",
            starts_at=timezone.now() + timedelta(days=7),
            total_tickets=10,
        )

    def login(self):
        self.client.login(username="alice", password="secret-pass-123")

    def test_event_list_page_loads(self):
        response = self.client.get(reverse("event_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Concert")
        self.assertContains(response, "0 of 10 booked")

    def test_event_detail_page_loads(self):
        self.login()
        response = self.client.get(reverse("event_detail", args=[self.event.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A nice concert.")
        self.assertContains(response, "10</span> tickets left")
        self.assertContains(response, "Reserve")
        self.assertContains(response, "/ws/events/%s/" % self.event.pk)
        self.assertContains(response, 'name="idempotency_key"')

    def test_reserve_creates_pending_booking(self):
        self.login()
        response = self.client.post(reverse("book_event", args=[self.event.pk]), {"tickets": 3}, follow=True)
        self.assertRedirects(response, reverse("my_bookings"))
        self.assertContains(response, "Reserved 3 tickets. Confirm within 5 minutes.")
        self.assertContains(response, "expires at")
        booking = Booking.objects.get()
        self.assertEqual(booking.user, self.user)
        self.assertEqual(booking.tickets, 3)
        self.assertEqual(booking.status, Booking.PENDING)

    def test_same_idempotency_key_books_once(self):
        self.login()
        data = {"tickets": 2, "idempotency_key": str(uuid.uuid4())}
        self.client.post(reverse("book_event", args=[self.event.pk]), data)
        response = self.client.post(reverse("book_event", args=[self.event.pk]), data, follow=True)
        self.assertContains(response, "This reservation was already made.")
        self.assertEqual(Booking.objects.count(), 1)
        self.event.refresh_from_db()
        self.assertEqual(self.event.booked_tickets, 2)

    def test_cannot_book_more_than_available(self):
        self.login()
        response = self.client.post(reverse("book_event", args=[self.event.pk]), {"tickets": 11}, follow=True)
        self.assertContains(response, "Only 10 tickets left.")
        self.assertEqual(Booking.objects.count(), 0)

    def test_booking_requires_login(self):
        url = reverse("book_event", args=[self.event.pk])
        response = self.client.post(url, {"tickets": 1})
        self.assertRedirects(response, reverse("login") + "?next=" + url, fetch_redirect_response=False)
        self.assertEqual(Booking.objects.count(), 0)

    def test_my_bookings_requires_login(self):
        response = self.client.get(reverse("my_bookings"))
        self.assertEqual(response.status_code, 302)

    def test_confirm_booking(self):
        booking, _ = services.reserve_tickets(self.user, self.event.pk, 2)
        self.login()
        response = self.client.post(reverse("confirm_booking", args=[booking.pk]), follow=True)
        self.assertContains(response, "Booking confirmed.")
        self.assertContains(response, "/api/bookings/%s/qr/" % booking.pk)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.CONFIRMED)

    def test_cannot_confirm_someone_elses_booking(self):
        booking, _ = services.reserve_tickets(self.bob, self.event.pk, 2)
        self.login()
        self.client.post(reverse("confirm_booking", args=[booking.pk]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.PENDING)

    def test_cancel_booking(self):
        booking, _ = services.reserve_tickets(self.user, self.event.pk, 2)
        self.login()
        response = self.client.post(reverse("cancel_booking", args=[booking.pk]))
        self.assertRedirects(response, reverse("my_bookings"))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.CANCELLED)
        self.event.refresh_from_db()
        self.assertEqual(self.event.booked_tickets, 0)

    def test_cannot_cancel_someone_elses_booking(self):
        booking, _ = services.reserve_tickets(self.bob, self.event.pk, 2)
        self.login()
        self.client.post(reverse("cancel_booking", args=[booking.pk]))
        booking.refresh_from_db()
        self.assertEqual(booking.status, Booking.PENDING)
        self.event.refresh_from_db()
        self.assertEqual(self.event.booked_tickets, 2)

    def test_cancel_needs_post(self):
        booking, _ = services.reserve_tickets(self.user, self.event.pk, 2)
        self.login()
        response = self.client.get(reverse("cancel_booking", args=[booking.pk]))
        self.assertEqual(response.status_code, 405)

    def test_sold_out_shows_waitlist_form(self):
        services.reserve_tickets(self.bob, self.event.pk, 10)
        self.login()
        response = self.client.get(reverse("event_detail", args=[self.event.pk]))
        self.assertContains(response, "Join waiting list")
        self.assertNotContains(response, "Reserve</button>")

    def test_join_and_leave_waitlist(self):
        services.reserve_tickets(self.bob, self.event.pk, 10)
        self.login()
        response = self.client.post(reverse("join_waitlist", args=[self.event.pk]), follow=True)
        self.assertContains(response, "You are on the waiting list")
        self.assertTrue(WaitlistEntry.objects.filter(user=self.user, event=self.event).exists())

        response = self.client.post(reverse("leave_waitlist", args=[self.event.pk]), follow=True)
        self.assertContains(response, "Join waiting list")
        self.assertFalse(WaitlistEntry.objects.filter(user=self.user).exists())

    def test_register_logs_user_in(self):
        response = self.client.post(reverse("register"), {
            "username": "carol",
            "password1": "a-long-password-42",
            "password2": "a-long-password-42",
        })
        self.assertRedirects(response, reverse("event_list"))
        response = self.client.get(reverse("event_list"))
        self.assertContains(response, "Hi carol")

    def test_logout_with_post(self):
        self.login()
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("event_list"))
