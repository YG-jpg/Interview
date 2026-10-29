# Ползва се само за WebSocket (пуска се с daphne). Нормалният HTTP минава през Gunicorn (wsgi.py).
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_app = get_asgi_application()

# Тези импорти са след get_asgi_application(), защото Django трябва първо да се зареди.
from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from django.urls import path  # noqa: E402

from events.consumers import EventConsumer  # noqa: E402

# Разпределя връзките по вид: http -> Django, websocket -> EventConsumer.
# Браузърът се свързва с ws://localhost:8001/ws/events/<id>/, за да получава броя на билетите на живо.
application = ProtocolTypeRouter({
    "http": django_app,
    "websocket": URLRouter([
        path("ws/events/<int:event_id>/", EventConsumer.as_asgi()),
    ]),
})
