"""
Demo: many users try to book the same event at the same moment.

Each user runs in its own thread and sends a real HTTP request to the API.
At the end we check that the event was not overbooked.

Usage (the app must be running):
    python scripts/concurrent_booking_demo.py <event_id> [base_url] [users]
Example:
    python scripts/concurrent_booking_demo.py 1 http://localhost:8000 30
"""
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests


def create_user(base_url):
    username = "demo_" + uuid.uuid4().hex[:8]
    password = "secret123"
    response = requests.post(f"{base_url}/api/register/", json={"username": username, "password": password})
    response.raise_for_status()
    return (username, password)


def book_one_ticket(base_url, event_id, auth):
    response = requests.post(f"{base_url}/api/bookings/", json={"event": event_id, "tickets": 1}, auth=auth)
    return response.status_code


def main():
    event_id = int(sys.argv[1])
    base_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
    users_count = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    users = [create_user(base_url) for _ in range(users_count)]

    # All users book at the same time, each one in its own thread.
    with ThreadPoolExecutor(max_workers=users_count) as pool:
        futures = [pool.submit(book_one_ticket, base_url, event_id, auth) for auth in users]
        results = [future.result() for future in futures]

    print(f"Successful bookings (201): {results.count(201)}")
    print(f"Rejected, sold out (400):  {results.count(400)}")

    event = requests.get(f"{base_url}/api/events/{event_id}/", auth=users[0]).json()
    print(f"Event now: {event['booked_tickets']} of {event['total_tickets']} booked")

    if event["booked_tickets"] > event["total_tickets"]:
        print("ERROR: overbooked!")
        sys.exit(1)
    print("OK: no overbooking.")


if __name__ == "__main__":
    main()
