# Event Booking

Django app for booking tickets for events.

- Organizers add events in the Django admin.
- Users reserve tickets on the website or through the REST API. A reservation holds the tickets for 5 minutes, then the user confirms it and gets a QR ticket.
- If an event is sold out, users can join a waiting list.
- The ticket count on the event page updates live (WebSocket).
- Many users can book at the same moment and an event is never overbooked.

Stack: Django, Django REST Framework, PostgreSQL, Redis, Celery, Django Channels, Gunicorn, Docker, Kubernetes.

## Run it

You need Docker Desktop and Python.

```bash
python scripts/make_secrets.py   # once (on Windows: py scripts/make_secrets.py)
docker compose up --build
```

`make_secrets.py` writes `.env` (for Docker Compose) and `k8s/secret.env` (for Kubernetes) with random passwords and prints the admin password. Both files are in `.gitignore`. Only `.env.example`, without passwords, is in git.

| What | URL |
|---|---|
| Website | http://localhost:8000/ |
| API | http://localhost:8000/api/ |
| Admin | http://localhost:8000/admin/ (admin / the password from `make_secrets.py`, also in `.env`) |
| WebSocket | ws://localhost:8001/ws/events/<id>/ |

1. Log in to the admin and add an event.
2. Open the website, register, open the event and click Reserve.
3. Go to My bookings and click Confirm (within 5 minutes). The QR ticket shows up.

Stop with `Ctrl+C`. `docker compose down -v` also deletes the database.

If you ran the app before `.env` existed, the database still has the old password and Django can't connect. Run `docker compose down -v` once (this deletes the local data).

### Without Docker for Django

Postgres and Redis still run in Docker, Django runs on your machine (Windows):

```powershell
docker run -d --name eb-db -p 5432:5432 -e POSTGRES_DB=events -e POSTGRES_USER=events -e POSTGRES_PASSWORD=events postgres:17
docker run -d --name eb-redis -p 6379:6379 redis:7

py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
$env:DEBUG = "1"   # DEBUG is off by default
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

In two more terminals (first activate `.venv` and set `$env:DEBUG = "1"`):

```powershell
celery -A config worker -B --pool=solo --loglevel=info   # --pool=solo is needed on Windows
daphne -p 8001 config.asgi:application
```

## Run on Kubernetes

Docker Desktop: Settings -> Kubernetes -> Enable. Then:

```bash
python scripts/make_secrets.py   # if you haven't yet
kubectl create secret generic event-booking-secret --from-env-file=k8s/secret.env
docker build -t event-booking:latest .
kubectl apply -f k8s/
kubectl get pods
```

Website on http://localhost:30080/ (admin password: in `k8s/secret.env`), WebSocket on port 30081. The pods run with `DEBUG=0` and only answer to the host names in `ALLOWED_HOSTS` in the ConfigMap (`localhost,127.0.0.1`; with minikube, add the IP from `minikube ip`).

| File | What |
|---|---|
| 01-config.yaml | ConfigMap with settings. No passwords: the Secret is made from `k8s/secret.env` |
| 02-postgres.yaml | Postgres with a disk |
| 03-redis.yaml | Redis |
| 04-migrate-job.yaml | runs `migrate` once |
| 05-web.yaml | Django + Gunicorn, 2 pods |
| 06-worker.yaml | Celery worker + scheduler, 1 pod |
| 07-websocket.yaml | daphne for WebSockets, 2 pods |

## API

Login with HTTP Basic (`curl -u user:pass`) or the website session. Errors are `{"detail": "..."}`.

| Method | URL | What |
|---|---|---|
| POST | /api/register/ | `{"username", "password"}` |
| GET | /api/events/ | all events |
| GET | /api/events/<id>/ | one event |
| POST | /api/events/<id>/waitlist/ | join waiting list (only when sold out) `{"tickets": 1}` |
| DELETE | /api/events/<id>/waitlist/ | leave waiting list |
| GET | /api/bookings/ | my bookings |
| POST | /api/bookings/ | reserve `{"event": 1, "tickets": 2}`, optional header `Idempotency-Key: <uuid>` |
| GET | /api/bookings/<id>/ | one booking |
| POST | /api/bookings/<id>/confirm/ | confirm a reservation |
| DELETE | /api/bookings/<id>/ | cancel |
| GET | /api/bookings/<id>/qr/ | QR ticket (PNG), only confirmed |

Booking status: `pending` -> `confirmed`, or `cancelled`, or `expired` (not confirmed in 5 minutes).

```bash
curl -X POST localhost:8000/api/register/ -H "Content-Type: application/json" -d '{"username": "ivan", "password": "secret123"}'
curl -u ivan:secret123 -X POST localhost:8000/api/bookings/ -H "Content-Type: application/json" -H "Idempotency-Key: 3f1c..." -d '{"event": 1, "tickets": 2}'
curl -u ivan:secret123 -X POST localhost:8000/api/bookings/1/confirm/
curl -u ivan:secret123 localhost:8000/api/bookings/1/qr/ -o ticket.png
```

## How it works

**No overselling.** `Event.booked_tickets` is changed with one `UPDATE` that checks and adds in the database (`events/services.py`):

```python
Event.objects.filter(pk=event_id, booked_tickets__lte=F("total_tickets") - tickets) \
             .update(booked_tickets=F("booked_tickets") + tickets)
```

Postgres runs updates on the same row one after another and checks the `WHERE` again each time, so two requests can't both get the last ticket. This works across threads, processes and pods. A `CheckConstraint` (`booked_tickets <= total_tickets`) is the last safety net.

**Reservations.** A booking starts as `pending` with `expires_at = now + 5 min`. A Celery beat task runs every 30 seconds and sets old ones to `expired` and gives the tickets back. Confirm and expire are both conditional updates on the status, so only one of them can win.

**Idempotency.** If the client sends the same `Idempotency-Key` twice (for example a retry after a timeout), it gets the first booking back (200) instead of a second one. A `UniqueConstraint(user, idempotency_key)` makes this safe even when both requests arrive at the same moment.

**Waiting list.** When tickets are freed (cancel or expire), a Celery task gives them to the people on the list, first come first served, as a normal 5 minute reservation.

**Rate limiting.** DRF throttling: 10 bookings per minute per user, plus general limits. The counters are in Redis, so the limit is shared by all pods.

**Live updates.** After every change `services.send_availability()` sends the new count to a Channels group. The event page listens on a WebSocket.

**Admin.** Organizers can view bookings in the admin and delete them (the tickets come back), but can't add or change them, because that would get around the ticket limit. Lowering `total_tickets` below the booked tickets shows a form error.

**Secrets and production settings.** No passwords or keys are in git. `DEBUG` is off unless `DEBUG=1`. Without `SECRET_KEY` the app refuses to start (except with `DEBUG=1`). `ALLOWED_HOSTS` comes from the environment, and a request with any other `Host` gets 400.

**Threads.** Gunicorn runs 2 processes x 4 threads per pod. The tests start up to 100 threads at the same moment (`ThreadPoolExecutor` + `threading.Barrier`).

## Tests

```bash
docker compose run --rm web python manage.py test
```

Concurrency tests (`events/tests.py`, `ConcurrentBookingTests`): 100 users / 10 tickets, the same booking cancelled from 10 threads, the same idempotency key from 10 threads, confirm + cancel at once, bookings + cancels at once. `AdminTests`: the admin can't add or change bookings or lower `total_tickets` below the booked tickets.

Demo against the running app (create an event with 10 tickets first):

```bash
docker compose exec web python scripts/concurrent_booking_demo.py 1 http://localhost:8000 100
```

## Project layout

```
config/            settings, urls, wsgi (Gunicorn), asgi (WebSockets), celery
events/
  models.py        Event, Booking, WaitlistEntry
  services.py      all booking rules + sends the ticket count to the WebSocket
  views.py         API (+ booking rate limit, QR image)
  serializers.py
  tasks.py         Celery tasks
  consumers.py     WebSocket
  admin.py
  tests.py
pages/             website (Django templates)
k8s/               Kubernetes
scripts/           concurrency demo, make_secrets.py
```

To add a new booking rule, change `events/services.py`. The API and the website both use it.
