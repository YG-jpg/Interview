import threading
from datetime import timedelta

from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from . import services
from .models import Booking, Event


def make_event(total_tickets=10, days_from_now=7):
    return Event.objects.create(
        title="Rock Concert",
        location="Sofia",
        starts_at=timezone.now() + timedelta(days=days_from_now),
        total_tickets=total_tickets,
    )


class ApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="ivan", password="secret123")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.event = make_event(total_tickets=10)

    def test_register(self):
        client = APIClient()
        response = client.post("/api/register/", {"username": "maria", "password": "secret123"})
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("password", response.data)
        self.assertTrue(User.objects.filter(username="maria").exists())

    def test_login_required(self):
        response = APIClient().get("/api/events/")
        self.assertEqual(response.status_code, 401)

    def test_list_events(self):
        response = self.client.get("/api/events/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["available_tickets"], 10)

    def test_event_not_found(self):
        response = self.client.get("/api/events/999/")
        self.assertEqual(response.status_code, 404)

    def test_book_tickets(self):
        response = self.client.post("/api/bookings/", {"event": self.event.id, "tickets": 3})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["tickets"], 3)
        self.assertEqual(response.data["event"]["booked_tickets"], 3)
        self.assertEqual(response.data["event"]["available_tickets"], 7)

    def test_cannot_book_more_than_available(self):
        response = self.client.post("/api/bookings/", {"event": self.event.id, "tickets": 11})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Only 10 tickets left.")
        self.assertEqual(Booking.objects.count(), 0)

    def test_cannot_book_zero_tickets(self):
        response = self.client.post("/api/bookings/", {"event": self.event.id, "tickets": 0})
        self.assertEqual(response.status_code, 400)

    def test_cannot_book_past_event(self):
        past_event = make_event(days_from_now=-1)
        response = self.client.post("/api/bookings/", {"event": past_event.id, "tickets": 1})
        self.assertEqual(response.status_code, 400)

    def test_my_bookings_shows_only_my_bookings(self):
        other_user = User.objects.create_user(username="other", password="secret123")
        Booking.objects.create(user=self.user, event=self.event, tickets=1)
        Booking.objects.create(user=other_user, event=self.event, tickets=2)

        response = self.client.get("/api/bookings/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["tickets"], 1)

    def test_cancel_booking(self):
        booking = Booking.objects.create(user=self.user, event=self.event, tickets=4)
        response = self.client.delete(f"/api/bookings/{booking.id}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.event.available_tickets, 10)

    def test_cannot_cancel_other_users_booking(self):
        other_user = User.objects.create_user(username="other", password="secret123")
        booking = Booking.objects.create(user=other_user, event=self.event, tickets=1)
        response = self.client.delete(f"/api/bookings/{booking.id}/")
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Booking.objects.filter(id=booking.id).exists())


class ConcurrentBookingTests(TransactionTestCase):
    """
    Many threads try to book at the same moment.

    TransactionTestCase is needed here because every thread uses its own
    database connection, and it must see data that is really committed.
    """

    def run_in_threads(self, how_many, work):
        # A Barrier makes all threads wait and then start at the same moment.
        barrier = threading.Barrier(how_many)

        def worker(number):
            barrier.wait()
            try:
                work(number)
            finally:
                connection.close()  # every thread has its own DB connection

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(how_many)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    def test_no_overbooking_when_many_users_book_at_once(self):
        event = make_event(total_tickets=5)
        users = [User.objects.create_user(username=f"user{i}", password="x") for i in range(20)]
        results = []  # list.append is thread-safe in Python

        def book(number):
            try:
                services.book_tickets(users[number], event.id, 1)
                results.append("ok")
            except services.BookingError:
                results.append("sold out")

        self.run_in_threads(20, book)

        self.assertEqual(results.count("ok"), 5)
        self.assertEqual(results.count("sold out"), 15)
        event.refresh_from_db()
        self.assertEqual(event.booked_tickets, 5)
        self.assertEqual(event.available_tickets, 0)

    def test_bookings_and_cancels_at_the_same_time(self):
        event = make_event(total_tickets=10)
        user = User.objects.create_user(username="ivan", password="x")
        old_bookings = [Booking.objects.create(user=user, event=event, tickets=1) for _ in range(5)]

        def book_or_cancel(number):
            if number < 5:
                services.cancel_booking(user, old_bookings[number].id)
            else:
                try:
                    services.book_tickets(user, event.id, 1)
                except services.BookingError:
                    pass

        self.run_in_threads(15, book_or_cancel)

        # Whatever order the threads ran in, we never go over the limit.
        event.refresh_from_db()
        self.assertLessEqual(event.booked_tickets, 10)
        self.assertGreaterEqual(event.available_tickets, 0)
