from channels.generic.websocket import AsyncJsonWebsocketConsumer


class EventConsumer(AsyncJsonWebsocketConsumer):
    """ws://.../ws/events/<id>/ - праща {"available_tickets": N} всеки път, когато броят се промени."""

    async def connect(self):
        """Браузърът се свързва: добавяме го в групата на събитието (напр. "event_1")."""
        self.group_name = f"event_{self.scope['url_route']['kwargs']['event_id']}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        """Браузърът затваря страницата: махаме го от групата."""
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def tickets_update(self, message):
        """Вика се за съобщения с type "tickets.update" (от send_availability() в services.py) - препращаме ги на браузъра."""
        await self.send_json({"available_tickets": message["available_tickets"]})
