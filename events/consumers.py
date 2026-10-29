from channels.generic.websocket import AsyncJsonWebsocketConsumer


class EventConsumer(AsyncJsonWebsocketConsumer):
    """ws://.../ws/events/<id>/ - sends {"available_tickets": N} every time it changes."""

    async def connect(self):
        self.group_name = f"event_{self.scope['url_route']['kwargs']['event_id']}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def tickets_update(self, message):
        await self.send_json({"available_tickets": message["available_tickets"]})
