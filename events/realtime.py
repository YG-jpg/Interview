import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Event

logger = logging.getLogger(__name__)


def send_availability(event_id):
    """Tell every browser that has this event open how many tickets are left (WebSocket)."""
    try:
        event = Event.objects.get(pk=event_id)
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"event_{event_id}",
            {"type": "tickets.update", "available_tickets": event.available_tickets},
        )
    except Exception:
        # The booking is already saved. A problem with the live update should not break it.
        logger.exception("Could not send availability update for event %s", event_id)
