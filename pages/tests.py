from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from events.models import Booking, Event


class PagesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="secret-pass-123")
        self.event = Event.objects.create(
            title="Concert",
            description="A nice concert.",
            location="Sofia",
            starts_at=timezone.now() + timedelta(days=7),
            total_tickets=10,
        )

    def test_event_list_page_loads(self):
        response = self.client.get(reverse("event_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Concert")
        self.assertContains(response, "0 of 10 booked")

    def test_event_detail_page_loads(self):
        response = self.client.get(reverse("event_detail", args=[self.event.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A nice concert.")

    def test_book_tickets(self):
        self.client.login(username="alice", password="secret-pass-123")
        response = self.client.post(reverse("book_event", args=[self.event.pk]), {"tickets": 3})
        self.assertRedirects(response, reverse("my_bookings"))
        booking = Booking.objects.get()
        self.assertEqual(booking.user, self.user)
        self.assertEqual(booking.tickets, 3)

    def test_cannot_book_more_than_available(self):
        self.client.login(username="alice", password="secret-pass-123")
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

    def test_cancel_booking(self):
        booking = Booking.objects.create(user=self.user, event=self.event, tickets=2)
        self.client.login(username="alice", password="secret-pass-123")
        response = self.client.post(reverse("cancel_booking", args=[booking.pk]))
        self.assertRedirects(response, reverse("my_bookings"))
        self.assertFalse(Booking.objects.filter(pk=booking.pk).exists())

    def test_cannot_cancel_someone_elses_booking(self):
        bob = User.objects.create_user(username="bob", password="secret-pass-123")
        booking = Booking.objects.create(user=bob, event=self.event, tickets=2)
        self.client.login(username="alice", password="secret-pass-123")
        self.client.post(reverse("cancel_booking", args=[booking.pk]))
        self.assertTrue(Booking.objects.filter(pk=booking.pk).exists())

    def test_cancel_needs_post(self):
        booking = Booking.objects.create(user=self.user, event=self.event, tickets=2)
        self.client.login(username="alice", password="secret-pass-123")
        response = self.client.get(reverse("cancel_booking", args=[booking.pk]))
        self.assertEqual(response.status_code, 405)

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
        self.client.login(username="alice", password="secret-pass-123")
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("event_list"))
