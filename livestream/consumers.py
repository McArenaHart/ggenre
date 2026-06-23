import json

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from .models import LiveStream


class LiveStreamSignalConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.stream_key = self.scope["url_route"]["kwargs"]["stream_key"]
        self.user = self.scope["user"]
        self.stream = await self.get_stream()

        if not self.stream or not await self.can_join():
            await self.close(code=4403)
            return

        self.group_name = f"livestream_{self.stream_key}"
        self.peer_id = f"user-{self.user.id}-{id(self)}"
        self.is_host = await self.user_is_host()

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "peer.event",
                "event": "host_joined" if self.is_host else "viewer_joined",
                "peer_id": self.peer_id,
                "username": self.user.username,
                "sender": self.channel_name,
            },
        )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "peer.event",
                    "event": "peer_left",
                    "peer_id": getattr(self, "peer_id", ""),
                    "username": self.user.username if self.user.is_authenticated else "",
                    "sender": self.channel_name,
                },
            )
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data:
            return
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        event = data.get("event")
        if event == "chat_message":
            body = (data.get("message") or "").strip()
            if not body:
                return
            payload = {
                "body": body[:2000],
                "sender": self.user.username,
                "sender_id": self.user.id,
            }
        elif event in {"viewer_ready", "offer", "answer", "ice_candidate"}:
            payload = data.get("payload")
        else:
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "peer.event",
                "event": event,
                "peer_id": self.peer_id,
                "target": data.get("target"),
                "payload": payload,
                "username": self.user.username,
                "sender": self.channel_name,
            },
        )

    async def peer_event(self, event):
        if event.get("sender") == self.channel_name and event.get("event") != "chat_message":
            return
        target = event.get("target")
        if target and target != self.peer_id:
            return
        await self.send(
            text_data=json.dumps(
                {
                    "event": event["event"],
                    "peer_id": event.get("peer_id"),
                    "username": event.get("username"),
                    "payload": event.get("payload"),
                }
            )
        )

    @sync_to_async
    def get_stream(self):
        return LiveStream.objects.filter(stream_key=self.stream_key).select_related("host").first()

    @sync_to_async
    def can_join(self):
        return self.stream.can_join(self.user)

    @sync_to_async
    def user_is_host(self):
        return self.user == self.stream.host or self.user.is_admin()
