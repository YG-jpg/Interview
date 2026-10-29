"""
Тестове за API-то, правилата за резервации, админа, паралелните резервации и WebSocket.
Пускат се с: docker compose run --rm web python manage.py test
"""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

from asgiref.sync import async_to_sync
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.models import Sum
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle

from config.asgi import application

from . import services
from .models import Booking, Event, WaitlistEntry


def make_event(total_tickets=10, days_from_now=7):
    """Помощна функция: създава събитие след days_from_now дни (отрицателно = в миналото)."""
    return Event.objects.create(
        title="Rock Concert",
        location="Sofia",
        starts_at=timezone.now() + timedelta(days=days_from_now),
        total_tickets=total_tickets,
    )


def reserve(user, event, tickets=1):
    """Помощна функция: резервира билети и връща резервацията."""
    booking, created = services.reserve_tickets(user, event.id, tickets)
    return booking


def active_tickets(event):
    """Билетите в pending + confirmed резервации. Трябва винаги да е равно на event.booked_tickets."""
    active = event.bookings.filter(status__in=[Booking.PENDING, Booking.CONFIRMED])
    return active.aggregate(total=Sum("tickets"))["total"] or 0


class ApiTests(TestCase):
    """Тестове на REST API-то (/api/...)."""
    def setUp(self):
        cache.clear()  # нулираме броячите за rate limit
        self.user = User.objects.create_user(username="ivan", password="secret123")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.event = make_event(total_tickets=10)

    def test_register(self):
        response = APIClient().post("/api/register/", {"username": "maria", "password": "secret123"})
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("password", response.data)

    def test_login_required(self):
        response = APIClient().get("/api/events/")
        self.assertEqual(response.status_code, 401)

    def test_list_events(self):
        response = self.client.get("/api/events/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[0]["available_tickets"], 10)

    def test_event_not_found(self):
        response = self.client.get("/api/events/999/")
        self.assertEqual(response.status_code, 404)

    def test_reserve_tickets(self):
        response = self.client.post("/api/bookings/", {"event": self.event.id, "tickets": 3})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], "pending")
        self.assertEqual(response.data["event"]["available_tickets"], 7)

    def test_cannot_reserve_more_than_available(self):
        response = self.client.post("/api/bookings/", {"event": self.event.id, "tickets": 11})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Only 10 tickets left.")

    def test_cannot_reserve_zero_tickets(self):
        response = self.client.post("/api/bookings/", {"event": self.event.id, "tickets": 0})
        self.assertEqual(response.status_code, 400)

    def test_cannot_reserve_past_event(self):
        past_event = make_event(days_from_now=-1)
        response = self.client.post("/api/bookings/", {"event": past_event.id, "tickets": 1})
        self.assertEqual(response.status_code, 400)

    def test_confirm(self):
        booking = reserve(self.user, self.event, 2)
        response = self.client.post(f"/api/bookings/{booking.id}/confirm/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "confirmed")

    def test_cannot_confirm_expired_reservation(self):
        booking = reserve(self.user, self.event, 2)
        Booking.objects.filter(pk=booking.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        response = self.client.post(f"/api/bookings/{booking.id}/confirm/")
        self.assertEqual(response.status_code, 400)

    def test_my_bookings_shows_only_my_bookings(self):
        other_user = User.objects.create_user(username="other", password="secret123")
        reserve(self.user, self.event, 1)
        reserve(other_user, self.event, 2)
        response = self.client.get("/api/bookings/")
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["tickets"], 1)

    def test_cancel_gives_tickets_back(self):
        booking = reserve(self.user, self.event, 4)
        response = self.client.delete(f"/api/bookings/{booking.id}/")
        self.assertEqual(response.status_code, 204)
        booking.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(booking.status, "cancelled")
        self.assertEqual(self.event.available_tickets, 10)

    def test_cannot_cancel_twice(self):
        booking = reserve(self.user, self.event, 4)
        self.client.delete(f"/api/bookings/{booking.id}/")
        response = self.client.delete(f"/api/bookings/{booking.id}/")
        self.assertEqual(response.status_code, 400)
        self.event.refresh_from_db()
        self.assertEqual(self.event.booked_tickets, 0)

    def test_cannot_cancel_other_users_booking(self):
        other_user = User.objects.create_user(username="other", password="secret123")
        booking = reserve(other_user, self.event, 1)
        response = self.client.delete(f"/api/bookings/{booking.id}/")
        self.assertEqual(response.status_code, 404)

    def test_same_idempotency_key_books_only_once(self):
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        first = self.client.post("/api/bookings/", {"event": self.event.id, "tickets": 2}, headers=headers)
        second = self.client.post("/api/bookings/", {"event": self.event.id, "tickets": 2}, headers=headers)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data["id"], second.data["id"])
        self.event.refresh_from_db()
        self.assertEqual(self.event.booked_tickets, 2)

    def test_bad_idempotency_key(self):
        response = self.client.post("/api/bookings/", {"event": self.event.id}, headers={"Idempotency-Key": "abc"})
        self.assertEqual(response.status_code, 400)

    def test_qr_only_for_confirmed_booking(self):
        booking = reserve(self.user, self.event, 1)
        self.assertEqual(self.client.get(f"/api/bookings/{booking.id}/qr/").status_code, 400)

        services.confirm_booking(self.user, booking.id)
        response = self.client.get(f"/api/bookings/{booking.id}/qr/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")

    def test_rate_limit_on_bookings(self):
        with patch.dict(SimpleRateThrottle.THROTTLE_RATES, {"bookings": "2/minute"}):
            codes = [self.client.post("/api/bookings/", {"event": self.event.id}).status_code for _ in range(3)]
        self.assertEqual(codes, [201, 201, 429])

    def test_join_waitlist_only_when_sold_out(self):
        response = self.client.post(f"/api/events/{self.event.id}/waitlist/", {"tickets": 1})
        self.assertEqual(response.status_code, 400)

        other_user = User.objects.create_user(username="other", password="secret123")
        reserve(other_user, self.event, 10)
        response = self.client.post(f"/api/events/{self.event.id}/waitlist/", {"tickets": 1})
        self.assertEqual(response.status_code, 201)

        response = self.client.delete(f"/api/events/{self.event.id}/waitlist/")
        self.assertEqual(response.status_code, 204)


class ReservationTests(TestCase):
    """Резервации за 5 минути: изтичане, потвърждение и листата на чакащите."""
    def setUp(self):
        self.user = User.objects.create_user(username="ivan", password="x")
        self.event = make_event(total_tickets=10)

    def test_expired_reservations_give_tickets_back(self):
        old = reserve(self.user, self.event, 3)
        fresh = reserve(self.user, self.event, 2)
        Booking.objects.filter(pk=old.pk).update(expires_at=timezone.now() - timedelta(seconds=1))

        self.assertEqual(services.release_expired_bookings(), 1)

        old.refresh_from_db()
        fresh.refresh_from_db()
        self.event.refresh_from_db()
        self.assertEqual(old.status, "expired")
        self.assertEqual(fresh.status, "pending")
        self.assertEqual(self.event.booked_tickets, 2)

    def test_confirmed_booking_never_expires(self):
        booking = reserve(self.user, self.event, 3)
        services.confirm_booking(self.user, booking.id)
        Booking.objects.filter(pk=booking.pk).update(expires_at=timezone.now() - timedelta(seconds=1))

        self.assertEqual(services.release_expired_bookings(), 0)
        self.event.refresh_from_db()
        self.assertEqual(self.event.booked_tickets, 3)

    def test_freed_tickets_go_to_waiting_list(self):
        first = User.objects.create_user(username="first", password="x")
        second = User.objects.create_user(username="second", password="x")
        booking = reserve(self.user, self.event, 10)
        services.join_waitlist(first, self.event.id, 2)
        services.join_waitlist(second, self.event.id, 1)

        # В тестовете Celery изпълнява задачата веднага (CELERY_TASK_ALWAYS_EAGER)
        services.cancel_booking(self.user, booking.id)

        self.assertEqual(Booking.objects.get(user=first).status, "pending")
        self.assertEqual(Booking.objects.get(user=second).status, "pending")
        self.assertEqual(WaitlistEntry.objects.count(), 0)
        self.event.refresh_from_db()
        self.assertEqual(self.event.booked_tickets, 3)


class TicketCounterTests(TestCase):
    """Броячът booked_tickets винаги трябва да е верен."""
    def setUp(self):
        self.user = User.objects.create_user(username="ivan", password="x")
        self.event = make_event(total_tickets=10)

    def test_saving_an_old_copy_of_the_event_keeps_booked_tickets(self):
        old_copy = Event.objects.get(pk=self.event.pk)  # като страница в админа, отворена по-рано
        reserve(self.user, self.event, 3)
        old_copy.title = "New title"
        old_copy.save()

        self.event.refresh_from_db()
        self.assertEqual(self.event.title, "New title")
        self.assertEqual(self.event.booked_tickets, 3)

    def test_deleting_a_user_gives_tickets_back(self):
        reserve(self.user, self.event, 4)
        self.user.delete()
        self.event.refresh_from_db()
        self.assertEqual(self.event.booked_tickets, 0)

    def test_deleting_a_cancelled_booking_does_not_give_tickets_twice(self):
        reserve(self.user, self.event, 2)
        booking = reserve(self.user, self.event, 4)
        services.cancel_booking(self.user, booking.id)
        booking.delete()
        self.event.refresh_from_db()
        self.assertEqual(self.event.booked_tickets, 2)

    def test_total_tickets_cannot_go_below_booked(self):
        reserve(self.user, self.event, 4)
        self.event.refresh_from_db()
        self.event.total_tickets = 3
        with self.assertRaises(ValidationError):
            self.event.full_clean()


class AdminTests(TestCase):
    """Админът на организатора не трябва да може да заобиколи лимита на билетите."""

    def setUp(self):
        self.admin = User.objects.create_superuser(username="boss", password="x")
        self.client.force_login(self.admin)
        self.user = User.objects.create_user(username="ivan", password="x")
        self.event = make_event(total_tickets=10)
        self.booking = reserve(self.user, self.event, 4)

    def post_event_form(self, total_tickets):
        """Изпраща формата за редакция на събитие в админа с нов total_tickets."""
        starts_at = timezone.localtime(self.event.starts_at)
        return self.client.post(f"/admin/events/event/{self.event.pk}/change/", {
            "title": self.event.title,
            "description": "",
            "location": self.event.location,
            "starts_at_0": starts_at.strftime("%Y-%m-%d"),
            "starts_at_1": starts_at.strftime("%H:%M:%S"),
            "total_tickets": total_tickets,
            "bookings-TOTAL_FORMS": "0",
            "bookings-INITIAL_FORMS": "0",
        })

    def test_cannot_add_booking(self):
        response = self.client.get("/admin/events/booking/add/")
        self.assertEqual(response.status_code, 403)

    def test_cannot_change_booking(self):
        url = f"/admin/events/booking/{self.booking.pk}/change/"
        response = self.client.post(url, {"tickets": 9, "status": Booking.CONFIRMED})
        self.assertEqual(response.status_code, 403)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.tickets, 4)
        self.assertEqual(self.booking.status, Booking.PENDING)

    def test_event_page_shows_bookings_read_only(self):
        response = self.client.get(f"/admin/events/event/{self.event.pk}/change/")
        self.assertEqual(response.status_code, 200)
        # MAX_NUM_FORMS=0 скрива бутона "Add another" и няма полета за промяна.
        self.assertContains(response, 'name="bookings-MAX_NUM_FORMS" value="0"')
        self.assertNotContains(response, 'name="bookings-0-tickets"')
        self.assertNotContains(response, 'name="bookings-0-expires_at"')

    def test_deleting_a_booking_gives_tickets_back(self):
        response = self.client.post(f"/admin/events/booking/{self.booking.pk}/delete/", {"post": "yes"})
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.booked_tickets, 0)

    def test_can_change_total_tickets(self):
        response = self.post_event_form(total_tickets=20)
        self.assertEqual(response.status_code, 302)
        self.event.refresh_from_db()
        self.assertEqual(self.event.total_tickets, 20)
        self.assertEqual(self.event.booked_tickets, 4)

    def test_cannot_lower_total_tickets_below_booked(self):
        response = self.post_event_form(total_tickets=3)
        self.assertEqual(response.status_code, 200)  # пак формата, с грешката
        self.assertContains(response, "4 tickets are already booked.")
        self.event.refresh_from_db()
        self.assertEqual(self.event.total_tickets, 10)


class ConcurrentBookingTests(TransactionTestCase):
    """
    Много потребители в един и същи момент, всеки в собствена нишка (thread).
    Ползваме TransactionTestCase, защото всяка нишка има собствена връзка с базата
    и трябва да вижда данни, които наистина са записани (commit-нати).
    """

    def run_at_the_same_time(self, how_many, work):
        """Пуска work(0), work(1), ... в how_many нишки, които тръгват едновременно."""
        barrier = threading.Barrier(how_many)  # всички нишки тръгват заедно

        def worker(number):
            barrier.wait()
            try:
                return work(number)
            finally:
                connection.close()  # всяка нишка затваря своята връзка с базата

        with ThreadPoolExecutor(max_workers=how_many) as pool:
            return list(pool.map(worker, range(how_many)))

    def test_100_users_10_tickets(self):
        """100 потребители искат по 1 билет за събитие с 10 билета: точно 10 успяват."""
        event = make_event(total_tickets=10)
        users = [User.objects.create_user(username=f"user{i}", password="x") for i in range(100)]

        def book(number):
            try:
                services.reserve_tickets(users[number], event.id, 1)
                return "ok"
            except services.BookingError:
                return "sold out"

        results = self.run_at_the_same_time(100, book)

        self.assertEqual(results.count("ok"), 10)
        self.assertEqual(results.count("sold out"), 90)
        event.refresh_from_db()
        self.assertEqual(event.booked_tickets, 10)
        self.assertEqual(active_tickets(event), 10)

    def test_same_booking_cancelled_10_times_at_once(self):
        """Една резервация се отказва от 10 нишки наведнъж: билетите се връщат само веднъж."""
        event = make_event(total_tickets=10)
        user = User.objects.create_user(username="ivan", password="x")
        reserve(user, event, 2)
        booking = reserve(user, event, 3)

        def cancel(number):
            try:
                services.cancel_booking(user, booking.id)
                return "ok"
            except services.BookingError:
                return "error"

        results = self.run_at_the_same_time(10, cancel)

        self.assertEqual(results.count("ok"), 1)
        event.refresh_from_db()
        self.assertEqual(event.booked_tickets, 2)

    def test_same_idempotency_key_from_10_threads(self):
        """10 нишки пращат един и същи ключ: прави се само една резервация."""
        event = make_event(total_tickets=10)
        user = User.objects.create_user(username="ivan", password="x")
        key = uuid.uuid4()

        def book(number):
            booking, created = services.reserve_tickets(user, event.id, 2, idempotency_key=key)
            return booking.id

        booking_ids = self.run_at_the_same_time(10, book)

        self.assertEqual(len(set(booking_ids)), 1)
        event.refresh_from_db()
        self.assertEqual(event.booked_tickets, 2)

    def test_confirm_and_cancel_at_the_same_time(self):
        """Потвърждения и откази на едни и същи резервации едновременно: броячът остава верен."""
        event = make_event(total_tickets=10)
        user = User.objects.create_user(username="ivan", password="x")
        bookings = [reserve(user, event, 1) for _ in range(10)]

        def confirm_or_cancel(number):
            booking = bookings[number % 10]
            try:
                if number < 10:
                    services.confirm_booking(user, booking.id)
                else:
                    services.cancel_booking(user, booking.id)
            except services.BookingError:
                pass

        self.run_at_the_same_time(20, confirm_or_cancel)

        event.refresh_from_db()
        self.assertEqual(event.booked_tickets, active_tickets(event))

    def test_bookings_and_cancels_at_the_same_time(self):
        """Резервации и откази едновременно: никога над 10 билета и броячът е верен."""
        event = make_event(total_tickets=10)
        user = User.objects.create_user(username="ivan", password="x")
        old_bookings = [reserve(user, event, 1) for _ in range(5)]

        def book_or_cancel(number):
            try:
                if number < 5:
                    services.cancel_booking(user, old_bookings[number].id)
                else:
                    services.reserve_tickets(user, event.id, 1)
            except services.BookingError:
                pass

        self.run_at_the_same_time(15, book_or_cancel)

        event.refresh_from_db()
        self.assertLessEqual(event.booked_tickets, 10)
        self.assertEqual(event.booked_tickets, active_tickets(event))


class WebSocketTests(TransactionTestCase):
    """Браузърът получава новия брой билети през WebSocket."""
    def test_browser_gets_new_ticket_count(self):
        event = make_event(total_tickets=10)
        user = User.objects.create_user(username="ivan", password="x")

        async def scenario():
            communicator = WebsocketCommunicator(application, f"/ws/events/{event.id}/")
            connected, _ = await communicator.connect()
            self.assertTrue(connected)
            await database_sync_to_async(services.reserve_tickets)(user, event.id, 3)
            message = await communicator.receive_json_from(timeout=5)
            await communicator.disconnect()
            return message

        message = async_to_sync(scenario)()
        self.assertEqual(message, {"available_tickets": 7})
