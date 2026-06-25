from django.db import connection
from django.apps import apps
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from chatapp.routing import websocket_urlpatterns
from users.models import CustomUser, Notification, Role

from .models import AdminChatThread, MatchRating, PeerChatThread
from .services import (
    allow_peer_chat_by_admin,
    record_match_rating,
    revoke_admin_peer_chat,
    users_can_peer_chat,
)


class ChatAppTests(TestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            username="chat_owner",
            password="password123",
            role=Role.FAN,
        )
        self.member = CustomUser.objects.create_user(
            username="chat_member",
            password="password123",
            role=Role.FAN,
        )
        self.outsider = CustomUser.objects.create_user(
            username="chat_outsider",
            password="password123",
            role=Role.FAN,
        )
        self.admin = CustomUser.objects.create_user(
            username="chat_admin",
            password="password123",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.suspended = CustomUser.objects.create_user(
            username="chat_suspended",
            password="password123",
            role=Role.FAN,
            is_suspended_by_admin=True,
        )
        self.inactive = CustomUser.objects.create_user(
            username="chat_inactive",
            password="password123",
            role=Role.FAN,
            is_active=False,
        )

    def create_match(self, first_user, second_user, score=8):
        return record_match_rating(first_user, second_user, score)["thread"]

    def test_index_shows_matched_peer_inbox_for_non_admin(self):
        self.create_match(self.owner, self.member)
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Messages")
        self.assertContains(response, "chat_member")
        self.assertNotContains(response, "chat_outsider")
        self.assertNotContains(response, reverse("chatapp:direct", args=[self.admin.id]))
        self.assertNotContains(response, "chat_suspended")
        self.assertNotContains(response, "chat_inactive")

    def test_artist_inbox_shows_rating_received_from_peer(self):
        self.member.role = Role.ARTIST
        self.member.save(update_fields=["role"])
        self.create_match(self.owner, self.member, score=8)

        self.client.login(username="chat_member", password="password123")
        response = self.client.get(reverse("chatapp:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "chat_owner")
        self.assertContains(response, "Rated you 8/10")
        self.assertContains(response, 'class="chat-rating-pill"')

    def test_index_hides_invalid_existing_peer_threads(self):
        owner_suspended_one, owner_suspended_two = PeerChatThread.ordered_users(
            self.owner,
            self.suspended,
        )
        PeerChatThread.objects.create(
            user_one=owner_suspended_one,
            user_two=owner_suspended_two,
            unread_count_user_one=1,
            unread_count_user_two=1,
        )
        owner_admin_one, owner_admin_two = PeerChatThread.ordered_users(
            self.owner,
            self.admin,
        )
        PeerChatThread.objects.create(
            user_one=owner_admin_one,
            user_two=owner_admin_two,
            unread_count_user_one=1,
            unread_count_user_two=1,
        )

        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:index"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("chatapp:direct", args=[self.suspended.id]))
        self.assertNotContains(response, reverse("chatapp:direct", args=[self.admin.id]))

    def test_index_redirects_admin_to_inbox(self):
        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:index"))

        self.assertRedirects(response, reverse("chatapp:admin_inbox"))

    def test_direct_chat_page_loads_for_matched_peer_user(self):
        self.create_match(self.owner, self.member)
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.member.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "chat_member")
        self.assertContains(response, f'data-direct-chat-user="{self.member.id}"')
        self.assertContains(response, reverse("chatapp:index"))

    def test_artist_direct_chat_shows_rating_received_from_peer(self):
        self.member.role = Role.ARTIST
        self.member.save(update_fields=["role"])
        self.create_match(self.owner, self.member, score=9)

        self.client.login(username="chat_member", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.owner.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rated you 9/10")
        self.assertContains(response, 'class="chat-inline-rating"')

    def test_direct_chat_blocks_unmatched_peer_user(self):
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.member.id]))

        self.assertEqual(response.status_code, 403)

    def test_single_rating_unlocks_peer_chat_and_notifies(self):
        result = record_match_rating(self.owner, self.member, 8)

        self.assertTrue(result["matched"])
        self.assertEqual(result["match_score"], 8)
        self.assertTrue(users_can_peer_chat(self.owner, self.member))
        self.assertGreater(result["thread"].unlocked_until, timezone.now())
        self.assertTrue(
            PeerChatThread.objects.filter(
                user_one=min(self.owner, self.member, key=lambda user: user.id),
                user_two=max(self.owner, self.member, key=lambda user: user.id),
            ).exists()
        )
        self.assertEqual(Notification.objects.filter(user=self.owner).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.member).count(), 1)

    def test_expired_rating_unlock_blocks_peer_chat(self):
        thread = record_match_rating(self.owner, self.member, 8)["thread"]
        thread.unlocked_until = timezone.now() - timedelta(minutes=1)
        thread.save(update_fields=["unlocked_until"])

        self.assertFalse(users_can_peer_chat(self.owner, self.member))

        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.member.id]))

        self.assertEqual(response.status_code, 403)

    def test_admin_can_allow_peer_chat_without_matching_ratings(self):
        thread = allow_peer_chat_by_admin(self.owner, self.member, self.admin)

        self.assertTrue(thread.admin_approved)
        self.assertEqual(thread.approved_by, self.admin)
        self.assertTrue(users_can_peer_chat(self.owner, self.member))
        self.assertEqual(Notification.objects.filter(user=self.owner).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.member).count(), 1)

        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.member.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "chat_member")

    def test_admin_can_revoke_unmatched_peer_chat_override(self):
        allow_peer_chat_by_admin(self.owner, self.member, self.admin)

        revoke_admin_peer_chat(self.owner, self.member)

        self.assertFalse(users_can_peer_chat(self.owner, self.member))
        thread = PeerChatThread.objects.get()
        self.assertFalse(thread.admin_approved)

    def test_different_reciprocal_ratings_keep_peer_chat_unlocked(self):
        first_result = record_match_rating(self.owner, self.member, 8)
        second_result = record_match_rating(self.member, self.owner, 6)

        self.assertTrue(first_result["matched"])
        self.assertTrue(second_result["matched"])
        self.assertTrue(users_can_peer_chat(self.owner, self.member))
        self.assertTrue(PeerChatThread.objects.exists())
        self.assertEqual(Notification.objects.filter(user=self.owner).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.member).count(), 1)

    def test_rating_updates_do_not_duplicate_unlock_notifications(self):
        result = record_match_rating(self.owner, self.member, 8)
        record_match_rating(self.member, self.owner, 6)

        self.assertTrue(result["matched"])
        self.assertEqual(Notification.objects.filter(user=self.owner).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.member).count(), 1)

        record_match_rating(self.owner, self.member, 9)

        self.assertEqual(Notification.objects.filter(user=self.owner).count(), 1)
        self.assertEqual(Notification.objects.filter(user=self.member).count(), 1)

    def test_direct_chat_blocks_self(self):
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.owner.id]))

        self.assertEqual(response.status_code, 404)

    def test_admin_inbox_lists_unread_contact_threads(self):
        AdminChatThread.objects.create(
            admin=self.admin,
            user=self.owner,
            unread_count=2,
        )
        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin Inbox")
        self.assertContains(response, "chat_owner")
        self.assertContains(response, "2")
        self.assertContains(response, reverse("chatapp:direct", args=[self.owner.id]))

    def test_admin_unread_count_endpoint_returns_total(self):
        AdminChatThread.objects.create(
            admin=self.admin,
            user=self.owner,
            unread_count=2,
        )
        AdminChatThread.objects.create(
            admin=self.admin,
            user=self.member,
            unread_count=3,
        )
        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_unread_count"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread_count"], 5)

    def test_admin_unread_count_endpoint_returns_zero_for_non_admin(self):
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:admin_unread_count"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread_count"], 0)

    def test_admin_opening_direct_chat_marks_thread_read(self):
        thread = AdminChatThread.objects.create(
            admin=self.admin,
            user=self.owner,
            unread_count=3,
        )
        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.owner.id]))

        self.assertEqual(response.status_code, 200)
        thread.refresh_from_db()
        self.assertEqual(thread.unread_count, 0)

    def test_peer_opening_direct_chat_marks_thread_read(self):
        thread = self.create_match(self.owner, self.member)
        user_one, user_two = thread.user_one, thread.user_two
        if user_one == self.owner:
            thread.unread_count_user_one = 2
        else:
            thread.unread_count_user_two = 2
        thread.save(
            update_fields=[
                "unread_count_user_one",
                "unread_count_user_two",
            ]
        )
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.member.id]))

        self.assertEqual(response.status_code, 200)
        thread.refresh_from_db()
        self.assertEqual(thread.unread_count_for(self.owner), 0)

    def test_direct_chat_to_admin_does_not_duplicate_floating_admin_widget(self):
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.admin.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-direct-chat-user="{self.admin.id}"', count=1)
        self.assertNotContains(response, 'data-chat-widget="admin-contact"')

    def test_direct_chat_blocks_suspended_users(self):
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.suspended.id]))

        self.assertEqual(response.status_code, 404)

    def test_chat_message_body_storage_table_is_not_present(self):
        table_names = connection.introspection.table_names()

        self.assertNotIn("chatapp_chatmessage", table_names)
        self.assertNotIn("chatapp_chatroom", table_names)

    def test_chatapp_has_no_active_message_body_model(self):
        model_names = {model.__name__ for model in apps.get_app_config("chatapp").get_models()}

        self.assertNotIn("ChatMessage", model_names)
        self.assertNotIn("ChatRoom", model_names)


class DirectChatWebSocketTests(TestCase):
    async def test_direct_chat_socket_echoes_sent_message(self):
        owner = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_owner",
            password="password123",
            role=Role.FAN,
        )
        admin = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_admin",
            password="password123",
            role=Role.ADMIN,
            is_staff=True,
        )

        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/chat/user/{admin.id}/",
        )
        communicator.scope["user"] = owner
        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        await communicator.send_json_to({"message": "Hello admin"})
        response = await communicator.receive_json_from()

        self.assertEqual(response["body"], "Hello admin")
        self.assertEqual(response["sender_id"], owner.id)
        self.assertEqual(response["recipient_id"], admin.id)
        thread = await database_sync_to_async(AdminChatThread.objects.get)(
            admin=admin,
            user=owner,
        )
        notification_exists = await database_sync_to_async(
            Notification.objects.filter(
                user=admin,
                message="socket_owner sent you an admin chat message.",
            ).exists
        )()
        body_persisted = await database_sync_to_async(
            Notification.objects.filter(message__contains="Hello admin").exists
        )()
        self.assertEqual(thread.unread_count, 1)
        self.assertTrue(notification_exists)
        self.assertFalse(body_persisted)

        await communicator.disconnect()

    async def test_admin_reply_socket_increments_user_contact_unread(self):
        owner = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_reply_owner",
            password="password123",
            role=Role.FAN,
        )
        admin = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_reply_admin",
            password="password123",
            role=Role.ADMIN,
            is_staff=True,
        )

        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/chat/user/{owner.id}/",
        )
        communicator.scope["user"] = admin
        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        await communicator.send_json_to({"message": "Your OTP is ready"})
        response = await communicator.receive_json_from()

        self.assertEqual(response["body"], "Your OTP is ready")
        self.assertEqual(response["sender_id"], admin.id)
        self.assertEqual(response["recipient_id"], owner.id)
        thread = await database_sync_to_async(AdminChatThread.objects.get)(
            admin=admin,
            user=owner,
        )
        notification_exists = await database_sync_to_async(
            Notification.objects.filter(
                user=owner,
                message="Admin sent you a contact message.",
            ).exists
        )()
        body_persisted = await database_sync_to_async(
            Notification.objects.filter(message__contains="Your OTP is ready").exists
        )()
        self.assertEqual(thread.user_unread_count, 1)
        self.assertTrue(notification_exists)
        self.assertFalse(body_persisted)

        await communicator.disconnect()

    async def test_direct_chat_socket_blocks_unmatched_peer_thread(self):
        owner = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_user_one",
            password="password123",
            role=Role.FAN,
        )
        member = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_user_two",
            password="password123",
            role=Role.FAN,
        )

        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/chat/user/{member.id}/",
        )
        communicator.scope["user"] = owner
        connected, _ = await communicator.connect()

        self.assertFalse(connected)

    async def test_direct_chat_socket_records_rating_unlocked_peer_thread(self):
        owner = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_matched_one",
            password="password123",
            role=Role.FAN,
        )
        member = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_matched_two",
            password="password123",
            role=Role.FAN,
        )
        await database_sync_to_async(record_match_rating)(owner, member, 8)

        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/chat/user/{member.id}/",
        )
        communicator.scope["user"] = owner
        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        await communicator.send_json_to({"message": "Hello peer"})
        response = await communicator.receive_json_from()

        self.assertEqual(response["body"], "Hello peer")
        self.assertEqual(response["sender_id"], owner.id)
        self.assertEqual(response["recipient_id"], member.id)
        thread = await database_sync_to_async(PeerChatThread.get_or_create_for_users)(
            owner,
            member,
        )
        thread = thread[0]
        notification_exists = await database_sync_to_async(
            Notification.objects.filter(
                user=member,
                message="socket_matched_one sent you a message.",
            ).exists
        )()
        body_persisted = await database_sync_to_async(
            Notification.objects.filter(message__contains="Hello peer").exists
        )()
        self.assertEqual(thread.unread_count_for(member), 1)
        self.assertTrue(notification_exists)
        self.assertFalse(body_persisted)

        await communicator.disconnect()

    async def test_direct_chat_socket_records_admin_allowed_peer_thread(self):
        owner = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_allowed_one",
            password="password123",
            role=Role.FAN,
        )
        member = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_allowed_two",
            password="password123",
            role=Role.FAN,
        )
        admin = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_allowed_admin",
            password="password123",
            role=Role.ADMIN,
            is_staff=True,
        )
        await database_sync_to_async(allow_peer_chat_by_admin)(owner, member, admin)

        communicator = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/chat/user/{member.id}/",
        )
        communicator.scope["user"] = owner
        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        await communicator.send_json_to({"message": "Admin allowed hello"})
        response = await communicator.receive_json_from()

        self.assertEqual(response["body"], "Admin allowed hello")
        self.assertEqual(response["sender_id"], owner.id)
        self.assertEqual(response["recipient_id"], member.id)
        thread = await database_sync_to_async(PeerChatThread.get_or_create_for_users)(
            owner,
            member,
        )
        thread = thread[0]
        body_persisted = await database_sync_to_async(
            Notification.objects.filter(message__contains="Admin allowed hello").exists
        )()
        self.assertTrue(thread.admin_approved)
        self.assertEqual(thread.unread_count_for(member), 1)
        self.assertFalse(body_persisted)

        await communicator.disconnect()
