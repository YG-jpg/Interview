# Event Booking

A small Django app for booking event tickets.

- **Organizers** use the Django admin to create, edit and delete events and see how many tickets are booked.
- **Users** use the website or the REST API to see events, book tickets, see and cancel their bookings.
- **Bookings are thread-safe**: many users (threads, processes, pods) can book the last tickets at the same time and an event is never overbooked.

Stack: Python 3.13, Django 5.2, Django REST Framework, PostgreSQL 17, Gunicorn (threads), Docker, Kubernetes.

## Run with Docker Compose (easiest)

```bash
docker compose up --build
```

- Website: http://localhost:8000/
- API: http://localhost:8000/api/
- Admin: http://localhost:8000/admin/ (`admin` / `admin`)

## Run on Kubernetes

Manifests for a local cluster (Docker Desktop Kubernetes, minikube or kind).

```bash
docker build -t event-booking:latest .
# minikube: minikube image load event-booking:latest   |   kind: kind load docker-image event-booking:latest
kubectl apply -f k8s/
kubectl get pods        # wait until web pods are READY 1/1
```

Open http://localhost:30080/ (minikube: `minikube service web --url`).

| File | What it creates |
|---|---|
| `k8s/01-secret.yaml` | DB password, Django secret key, admin user |
| `k8s/02-postgres.yaml` | Postgres Deployment + disk (PVC) + Service `postgres` |
| `k8s/03-migrate-job.yaml` | One-time Job: `migrate` + create admin user |
| `k8s/04-web.yaml` | Django Deployment (2 replicas) + NodePort Service on 30080 |

## API

Auth: HTTP Basic (`-u username:password`) or the website login session. Errors look like `{"detail": "..."}`.

| Method | URL | Body | Success | Errors |
|---|---|---|---|---|
| POST | `/api/register/` | `{"username", "password"}` | 201 | 400 |
| GET | `/api/events/` | | 200 | 401 |
| GET | `/api/events/<id>/` | | 200 | 401, 404 |
| GET | `/api/bookings/` | | 200 (only my bookings) | 401 |
| POST | `/api/bookings/` | `{"event": 1, "tickets": 2}` | 201 | 400 (sold out, past event, bad input), 401 |
| GET | `/api/bookings/<id>/` | | 200 | 401, 404 |
| DELETE | `/api/bookings/<id>/` | | 204 | 401, 404 |

```bash
curl -X POST http://localhost:8000/api/register/ -H "Content-Type: application/json" -d '{"username": "ivan", "password": "secret123"}'
curl -u ivan:secret123 http://localhost:8000/api/events/
curl -u ivan:secret123 -X POST http://localhost:8000/api/bookings/ -H "Content-Type: application/json" -d '{"event": 1, "tickets": 2}'
curl -u ivan:secret123 http://localhost:8000/api/bookings/
curl -u ivan:secret123 -X DELETE http://localhost:8000/api/bookings/1/
```

On Windows PowerShell use `curl.exe` instead of `curl`.

## Concurrency

All booking rules are in [`events/services.py`](events/services.py). `book_tickets()` runs inside `transaction.atomic()` and locks the event row with `select_for_update()`. A second request for the same event waits until the first one commits, then sees the new ticket count. The lock lives in PostgreSQL, so it works across threads, Gunicorn processes and Kubernetes pods. A Python `threading.Lock` would only protect one process.

The server runs Gunicorn with `--workers 2 --threads 4`, so every pod handles 8 requests at the same time.

Proof:
- `events/tests.py` → `ConcurrentBookingTests`: 20 threads book 1 ticket each for an event with 5 tickets. Exactly 5 succeed. A second test mixes bookings and cancels in parallel threads.
- `scripts/concurrent_booking_demo.py`: 30 real HTTP clients in a `ThreadPoolExecutor` book the same event against the running app.

```bash
docker compose exec web python scripts/concurrent_booking_demo.py 1 http://localhost:8000 30
# Successful bookings (201): 10
# Rejected, sold out (400):  20
# Event now: 10 of 10 booked
# OK: no overbooking.
```

## Tests

```bash
docker compose run --rm web python manage.py test
```

24 tests: API, website pages, and the threaded concurrency tests (they need PostgreSQL, so they run in Docker).

## Project layout

```
config/                 settings, root URLs, WSGI
events/                 the API app
  models.py             Event, Booking
  services.py           booking rules + locking (used by API and website)
  serializers.py        JSON in/out
  views.py              API endpoints (function-based views)
  urls.py               /api/... routes
  admin.py              organizer admin panel
  tests.py              API + concurrency tests
pages/                  the website (Django templates)
  views.py, forms.py, urls.py, templates/, tests.py
k8s/                    Kubernetes manifests
scripts/                concurrent booking demo
Dockerfile, docker-compose.yml
```

## Adding a new feature

1. A new rule about bookings → add it to `events/services.py` (both API and website get it).
2. A new field → `models.py`, then `python manage.py makemigrations`, then add it to the serializer.
3. A new endpoint → a function in `views.py` + a line in `urls.py` + a test in `tests.py`.
