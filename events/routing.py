from django.urls import path

from . import consumers

websocket_urlpatterns = [
    path("ws/events/<int:event_id>/", consumers.EventConsumer.as_asgi()),
]
