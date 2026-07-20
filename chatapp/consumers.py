import json

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import F
from django.utils import timezone

from users.models import Notification, Role

from .models import AdminChatThread, DirectChatMessage, PeerChatThread
from .services import users_can_peer_chat

User = get_user_model()
PRESENCE_TTL_SECONDS = 90
PRESENCE_CONNECTION_TTL_SECONDS = 5 * 60


class DirectChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        self.other_user_id = int(self.scope["url_route"]["kwargs"]["user_id"])

        if not self.user.is_authenticated:
            await self.close(code=4401)
            return
        if getattr(self.user, "is_suspended_by_admin", False):
            await self.close(code=4403)
            return

        self.other_user = await self.get_other_user()
        if not self.other_user or self.other_user.id == self.user.id:
            await self.close(code=4403)
            return

        self.is_user_contacting_admin = self.other_user.has_role(
            Role.ADMIN
        ) and not self.user.has_role(Role.ADMIN)
        self.is_admin_replying_to_user = self.user.has_role(
            Role.ADMIN
        ) and not self.other_user.has_role(Role.ADMIN)
        self.is_peer_chat = (
            not self.user.has_role(Role.ADMIN)
            and not self.other_user.has_role(Role.ADMIN)
            and await self.can_peer_chat()
        )
        if not (
            self.is_user_contacting_admin
            or self.is_admin_replying_to_user
            or self.is_peer_chat
        ):
            await self.close(code=4403)
            return

        user_ids = sorted([self.user.id, self.other_user.id])
        self.group_name = f"direct_chat_{user_ids[0]}_{user_ids[1]}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        became_online = await self.begin_presence_session()
        if became_online:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "direct.presence",
                    "user_id": self.user.id,
                    "is_online": True,
                    "last_seen_at": timezone.now().isoformat(),
                },
            )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            presence_update = await self.end_presence_session()
            if presence_update:
                await self.channel_layer.group_send(
                    self.group_name,
                    {
                        "type": "direct.presence",
                        "user_id": self.user.id,
                        "is_online": False,
                        "last_seen_at": presence_update["last_seen_at"],
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

        if data.get("type") == "ping":
            await self.touch_presence()
            return

        if data.get("type") == "read":
            await self.touch_presence()
            message_id = str(data.get("message_id") or "")[:120]
            if not message_id:
                return
            await self.mark_message_read(message_id)
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "direct.receipt",
                    "message_id": message_id,
                    "reader_id": self.user.id,
                },
            )
            return

        body = (data.get("message") or "").strip()
        if not body:
            return
        await self.touch_presence()

        if self.is_user_contacting_admin:
            await self.record_admin_contact()
        elif self.is_admin_replying_to_user:
            await self.record_admin_reply()
        elif self.is_peer_chat:
            await self.record_peer_contact()

        client_id = str(data.get("client_id") or "")[:120]
        persisted_message = await self.save_direct_message(client_id=client_id, body=body[:2000])

        message = {
            "type": "message",
            "client_id": persisted_message.client_id,
            "message_id": persisted_message.id,
            "body": body[:2000],
            "sender": self.user.username,
            "sender_id": self.user.id,
            "recipient_id": self.other_user.id,
            "created_at": persisted_message.created_at.isoformat(),
        }
        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "direct.message",
                "message": message,
            },
        )

    async def direct_message(self, event):
        await self.send(text_data=json.dumps(event["message"]))

    async def direct_receipt(self, event):
        await self.send(
            text_data=json.dumps(
                {
                    "type": "receipt",
                    "message_id": event["message_id"],
                    "reader_id": event["reader_id"],
                    "status": "read",
                }
            )
        )

    async def direct_presence(self, event):
        if event.get("user_id") == self.user.id:
            return
        await self.send(
            text_data=json.dumps(
                {
                    "type": "presence",
                    "user_id": event.get("user_id"),
                    "is_online": bool(event.get("is_online")),
                    "last_seen_at": event.get("last_seen_at"),
                }
            )
        )

    @sync_to_async
    def get_other_user(self):
        return (
            User.objects.exclude(is_suspended_by_admin=True)
            .filter(is_active=True)
            .filter(id=self.other_user_id)
            .first()
        )

    @sync_to_async
    def can_peer_chat(self):
        return users_can_peer_chat(self.user, self.other_user)

    @sync_to_async
    def record_admin_contact(self):
        thread, created = AdminChatThread.objects.get_or_create(
            admin=self.other_user,
            user=self.user,
            defaults={"unread_count": 1},
        )
        if not created:
            AdminChatThread.objects.filter(pk=thread.pk).update(
                unread_count=F("unread_count") + 1,
                last_contact_at=timezone.now(),
            )
        Notification.objects.create(
            user=self.other_user,
            message=f"{self.user.username} sent you an admin chat message.",
        )

    @sync_to_async
    def record_admin_reply(self):
        thread, created = AdminChatThread.objects.get_or_create(
            admin=self.user,
            user=self.other_user,
            defaults={"user_unread_count": 1, "last_contact_at": timezone.now()},
        )
        if not created:
            AdminChatThread.objects.filter(pk=thread.pk).update(
                user_unread_count=F("user_unread_count") + 1,
                last_contact_at=timezone.now(),
            )
        Notification.objects.create(
            user=self.other_user,
            message=f"Admin sent you a contact message.",
        )

    @sync_to_async
    def record_peer_contact(self):
        thread, created = PeerChatThread.get_or_create_for_users(
            self.user,
            self.other_user,
        )
        update_fields = {"last_contact_at": timezone.now()}
        if self.other_user_id == thread.user_one_id:
            update_fields["unread_count_user_one"] = F("unread_count_user_one") + 1
        else:
            update_fields["unread_count_user_two"] = F("unread_count_user_two") + 1

        if created:
            for field_name, value in update_fields.items():
                setattr(
                    thread,
                    field_name,
                    1 if field_name.startswith("unread") else value,
                )
            thread.save(update_fields=list(update_fields.keys()))
        else:
            PeerChatThread.objects.filter(pk=thread.pk).update(**update_fields)

        Notification.objects.create(
            user=self.other_user,
            message=f"{self.user.username} sent you a message.",
        )

    @sync_to_async
    def save_direct_message(self, client_id, body):
        return DirectChatMessage.objects.create(
            sender=self.user,
            recipient=self.other_user,
            client_id=client_id,
            body=body,
        )

    @sync_to_async
    def mark_message_read(self, message_id):
        DirectChatMessage.objects.filter(
            client_id=message_id,
            sender=self.other_user,
            recipient=self.user,
            read_at__isnull=True,
        ).update(read_at=timezone.now())

    @sync_to_async
    def touch_presence(self):
        self._touch_presence_sync()

    def _touch_presence_sync(self):
        now = timezone.now()
        connection_key = f"direct_chat_presence:connections:{self.user.id}"
        current_connections = int(cache.get(connection_key) or 0)
        if current_connections > 0:
            cache.set(
                connection_key,
                current_connections,
                timeout=PRESENCE_CONNECTION_TTL_SECONDS,
            )
        cache.set(
            f"direct_chat_presence:online:{self.user.id}",
            now.isoformat(),
            timeout=PRESENCE_TTL_SECONDS,
        )
        cache.set(
            f"direct_chat_presence:last_seen:{self.user.id}",
            now.isoformat(),
            timeout=None,
        )

    @sync_to_async
    def begin_presence_session(self):
        connection_key = f"direct_chat_presence:connections:{self.user.id}"
        current_connections = int(cache.get(connection_key) or 0)
        cache.set(
            connection_key,
            current_connections + 1,
            timeout=PRESENCE_CONNECTION_TTL_SECONDS,
        )
        self._touch_presence_sync()
        return current_connections == 0

    @sync_to_async
    def end_presence_session(self):
        connection_key = f"direct_chat_presence:connections:{self.user.id}"
        current_connections = int(cache.get(connection_key) or 0)
        if current_connections <= 1:
            cache.delete(connection_key)
            return self.mark_presence_offline()

        cache.set(
            connection_key,
            current_connections - 1,
            timeout=PRESENCE_CONNECTION_TTL_SECONDS,
        )
        self._touch_presence_sync()
        return None

    def mark_presence_offline(self):
        now = timezone.now().isoformat()
        cache.delete(f"direct_chat_presence:online:{self.user.id}")
        cache.set(f"direct_chat_presence:last_seen:{self.user.id}", now, timeout=None)
        return {"last_seen_at": now}
