from django.db import connection
from django.apps import apps
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
import tempfile
from channels.db import database_sync_to_async
from channels.routing import URLRouter
from channels.testing import WebsocketCommunicator

from chatapp.routing import websocket_urlpatterns
from content.models import Content, Vote
from users.models import CustomUser, Notification, OTP, Role, VotingTokenPolicy

from .models import (
    AdminChatThread,
    AdminDecisionLog,
    DirectChatMessage,
    MatchRating,
    MissionEvidence,
    MissionQueueEntry,
    MissionReviewControl,
    MissionSession,
    MissionTemplate,
    MissionWinFeed,
    PeerChatThread,
    ReviewAutomationTicket,
    TokenPurchaseRequest,
)
from .services import (
    allow_peer_chat_by_admin,
    record_match_rating,
    revoke_admin_peer_chat,
    users_can_peer_chat,
)
from .realtime import broadcast_admin_counts


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
        self.admin_two = CustomUser.objects.create_user(
            username="chat_admin_two",
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
        listed_usernames = {row["user"].username for row in response.context["thread_rows"]}

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Messages")
        self.assertContains(response, "chat_member")
        self.assertContains(response, reverse("chatapp:direct", args=[self.member.id]))
        self.assertIn("chat_member", listed_usernames)
        self.assertNotIn("chat_admin", listed_usernames)
        self.assertNotIn("chat_suspended", listed_usernames)
        self.assertNotIn("chat_inactive", listed_usernames)
        self.assertNotContains(response, "chat_outsider")
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
        listed_user_ids = {row["user"].id for row in response.context["thread_rows"]}

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.suspended.id, listed_user_ids)
        self.assertNotIn(self.admin.id, listed_user_ids)

    def test_index_redirects_admin_to_inbox(self):
        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:index"))

        self.assertRedirects(response, reverse("chatapp:admin_inbox"))

    def test_direct_chat_page_loads_for_matched_peer_user(self):
        self.create_match(self.owner, self.member)
        policy = VotingTokenPolicy.current()
        policy.message_retention_hours = 12
        policy.save(update_fields=["message_retention_hours", "updated_at"])
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.member.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "chat_member")
        self.assertContains(response, f'data-direct-chat-user="{self.member.id}"')
        self.assertContains(response, 'data-message-retention-ms="43200000"')
        self.assertContains(response, reverse("chatapp:index"))

    def test_direct_chat_history_returns_persisted_messages(self):
        self.create_match(self.owner, self.member)
        cache.set(f"direct_chat_presence:last_seen:{self.owner.id}", "2026-07-20T10:11:12+00:00", timeout=None)
        cache.delete(f"direct_chat_presence:online:{self.owner.id}")
        DirectChatMessage.objects.create(
            sender=self.owner,
            recipient=self.member,
            client_id="history-1",
            body="Stored hello",
        )

        self.client.login(username="chat_member", password="password123")
        response = self.client.get(reverse("chatapp:direct_history", args=[self.owner.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["messages"]), 1)
        self.assertEqual(payload["messages"][0]["body"], "Stored hello")
        self.assertEqual(payload["messages"][0]["client_id"], "history-1")
        self.assertFalse(payload["presence"]["is_online"])
        self.assertEqual(payload["presence"]["last_seen_at"], "2026-07-20T10:11:12+00:00")

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
        self.assertNotContains(response, "{% include")
        self.assertNotContains(response, "row.last_contact_at|date")

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
        MissionSession.objects.create(
            requester=self.outsider,
            status=MissionSession.Status.MATCHING,
        )
        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_unread_count"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread_count"], 5)
        self.assertEqual(response.json()["mission_request_count"], 1)
        self.assertEqual(response.json()["total_action_count"], 6)

    def test_admin_unread_count_endpoint_returns_zero_for_non_admin(self):
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:admin_unread_count"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["unread_count"], 0)

    def test_admin_inbox_lists_mission_requests_as_user_notifications(self):
        AdminChatThread.objects.create(
            admin=self.admin,
            user=self.owner,
            unread_count=2,
        )
        owner_mission = MissionSession.objects.create(
            requester=self.owner,
            status=MissionSession.Status.MATCHING,
        )
        outsider_mission = MissionSession.objects.create(
            requester=self.outsider,
            status=MissionSession.Status.MATCHING,
        )
        self.client.login(username="chat_admin", password="password123")

        response = self.client.get(reverse("chatapp:admin_inbox"))
        rows_by_user = {row["user"].username: row for row in response.context["thread_rows"]}

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_unread"], 4)
        self.assertEqual(rows_by_user["chat_owner"]["unread_count"], 2)
        self.assertEqual(rows_by_user["chat_owner"]["mission_request_count"], 1)
        self.assertEqual(rows_by_user["chat_owner"]["action_count"], 3)
        self.assertEqual(rows_by_user["chat_outsider"]["unread_count"], 0)
        self.assertEqual(rows_by_user["chat_outsider"]["mission_request_count"], 1)
        self.assertEqual(rows_by_user["chat_outsider"]["action_count"], 1)
        self.assertContains(response, f"Mission #{owner_mission.id}")
        self.assertContains(response, f"Mission #{outsider_mission.id}")

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

    def test_direct_chat_to_admin_renders_mission_and_token_request_panels(self):
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.admin.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GGenre Secret Mission")
        self.assertContains(response, "Buy Additional Voting Tokens")
        self.assertContains(response, "data-mission-request-btn")
        self.assertContains(response, "data-token-request-btn")
        self.assertContains(response, "data-mission-instruction")
        self.assertContains(response, "data-mission-action=\"accept_opponent\"")

    def test_admin_direct_chat_renders_simple_mission_control_panel(self):
        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.owner.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Secret Mission Control")
        self.assertContains(response, "The game starts when chat_owner opens admin chat and taps Request Mission.")
        self.assertContains(response, "Back to Inbox")
        self.assertContains(response, "User Tokens")
        self.assertNotContains(response, "Mission ID")
        self.assertNotContains(response, "Evidence ID")
        self.assertNotContains(response, "Token Request ID")

    def test_admin_direct_chat_can_approve_pending_mission_request(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            status=MissionSession.Status.MATCHING,
        )
        cache.set(f"direct_chat_presence:online:{self.member.id}", "1", timeout=60)

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.owner.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Approve mission request")
        self.assertContains(response, "Approve & Match")
        self.assertContains(response, self.member.username)
        self.assertContains(response, reverse("chatapp:admin_assign_mission_opponent", args=[mission.id]))
        self.assertContains(response, f'value="/chat/u/{self.owner.id}/"')

    def test_direct_chat_blocks_suspended_users(self):
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.suspended.id]))

        self.assertEqual(response.status_code, 404)

    def test_chat_message_body_storage_table_is_present(self):
        table_names = connection.introspection.table_names()

        self.assertIn("chatapp_directchatmessage", table_names)

    def test_chatapp_has_active_message_body_model(self):
        model_names = {model.__name__ for model in apps.get_app_config("chatapp").get_models()}

        self.assertIn("DirectChatMessage", model_names)

    def test_admin_inbox_displays_pending_review_queues(self):
        token_request = TokenPurchaseRequest.objects.create(
            requester=self.owner,
            requested_tokens=6,
            status=TokenPurchaseRequest.Status.SUBMITTED,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.PROOF_SUBMITTED,
        )
        evidence = MissionEvidence.objects.create(
            mission_session=mission,
            submitted_by=self.owner,
            review_status=MissionEvidence.ReviewStatus.SUBMITTED,
            explanation="mission proof",
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mission Proof")
        self.assertContains(response, f"#{evidence.id}")
        self.assertContains(response, "Token Requests")
        self.assertContains(response, f"#{token_request.id}")
        self.assertNotContains(response, "{% include")

    def test_admin_inbox_shows_manual_match_queue_with_online_players(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            status=MissionSession.Status.MATCHING,
        )
        cache.set(f"direct_chat_presence:online:{self.member.id}", "1", timeout=60)

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mission Requests")
        self.assertContains(response, f"Mission #{mission.id}")
        self.assertContains(response, "Select online player")
        self.assertContains(response, self.member.username)

    def test_admin_can_assign_online_player_to_mission_request(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            status=MissionSession.Status.MATCHING,
        )
        cache.set(f"direct_chat_presence:online:{self.member.id}", "1", timeout=60)
        MissionTemplate.objects.create(
            title="Admin Queue Mission",
            instruction_text="Introduce yourself and earn trust.",
            is_active=True,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_assign_mission_opponent", args=[mission.id]),
            {"opponent_id": str(self.member.id)},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.opponent, self.member)
        self.assertEqual(mission.status, MissionSession.Status.OPPONENT_PROPOSED)
        self.assertIsNotNone(mission.mission_template)
        self.assertIsNotNone(mission.opponent_mission_template)
        self.assertTrue(
            AdminDecisionLog.objects.filter(
                mission_session=mission,
                action="manual_match_assignment",
            ).exists()
        )
        self.assertTrue(
            AdminChatThread.objects.filter(
                admin=self.admin,
                user=self.owner,
                user_unread_count__gt=0,
            ).exists()
        )
        self.assertTrue(
            AdminChatThread.objects.filter(
                admin=self.admin,
                user=self.member,
                user_unread_count__gt=0,
            ).exists()
        )
        self.assertTrue(
            DirectChatMessage.objects.filter(
                sender=self.admin,
                recipient=self.member,
                body__contains="Opponent found: chat_owner",
            ).exists()
        )

    def test_mission_assignment_uses_visible_admin_contact_thread(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            status=MissionSession.Status.MATCHING,
        )
        cache.set(f"direct_chat_presence:online:{self.member.id}", "1", timeout=60)

        self.client.login(username="chat_admin_two", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_assign_mission_opponent", args=[mission.id]),
            {"opponent_id": str(self.member.id)},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            AdminChatThread.objects.filter(
                admin=self.admin,
                user=self.member,
                user_unread_count__gt=0,
            ).exists()
        )
        self.assertTrue(
            DirectChatMessage.objects.filter(
                sender=self.admin,
                recipient=self.member,
                body__contains="Opponent found: chat_owner",
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.member,
                message__contains="Opponent found: chat_owner",
            ).exists()
        )

    def test_requester_can_accept_opponent_even_when_library_was_empty(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.OPPONENT_PROPOSED,
        )
        MissionTemplate.objects.all().delete()

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "accept_opponent"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.MISSION_PROPOSED)
        self.assertIsNotNone(mission.mission_template)
        self.assertTrue(MissionTemplate.objects.filter(is_active=True).exists())
        self.assertTrue(
            DirectChatMessage.objects.filter(
                sender=self.admin,
                recipient=self.member,
                body__contains="accepted the match",
            ).exists()
        )

        self.client.force_login(self.member)
        unread_response = self.client.get(reverse("chatapp:admin_contact_unread_count"))
        self.assertEqual(unread_response.status_code, 200)
        self.assertGreater(unread_response.json()["unread_count"], 0)

    def test_accept_opponent_seeds_levelled_mission_library(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.OPPONENT_PROPOSED,
        )
        MissionTemplate.objects.all().delete()

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "accept_opponent"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(MissionTemplate.objects.filter(difficulty=1, category="mixed_icebreaker").exists())
        self.assertTrue(MissionTemplate.objects.filter(difficulty=4, category="mixed_chemistry").exists())
        self.assertTrue(MissionTemplate.objects.filter(difficulty=5, category="mixed_mutual_interest").exists())

    def test_mission_timer_scales_with_highest_assigned_difficulty(self):
        green_template = MissionTemplate.objects.create(
            title="Green Timer Mission",
            instruction_text="Start with a simple opener.",
            difficulty=1,
            is_active=True,
        )
        gold_template = MissionTemplate.objects.create(
            title="Gold Timer Mission",
            instruction_text="Keep the conversation going naturally.",
            difficulty=5,
            is_active=True,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            mission_template=green_template,
            opponent_mission_template=gold_template,
            status=MissionSession.Status.MISSION_PROPOSED,
            timer_seconds=120,
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "accept_mission"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.MISSION_ACTIVE)
        self.assertEqual(mission.timer_seconds, 360)

    def test_opponent_cannot_accept_requesters_match(self):
        MissionTemplate.objects.create(
            title="Requester Only",
            instruction_text="Wait for the requester to confirm.",
            is_active=True,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.OPPONENT_PROPOSED,
        )

        self.client.force_login(self.member)
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "accept_opponent"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        mission.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.OPPONENT_PROPOSED)

    def test_admin_can_assign_online_player_with_selected_mission_template(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            status=MissionSession.Status.MATCHING,
        )
        cache.set(f"direct_chat_presence:online:{self.member.id}", "1", timeout=60)
        selected_template = MissionTemplate.objects.create(
            title="Manual Selection Mission",
            instruction_text="Use admin-selected mission template.",
            is_active=True,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_assign_mission_opponent", args=[mission.id]),
            {
                "opponent_id": str(self.member.id),
                "mission_template_id": str(selected_template.id),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.mission_template_id, selected_template.id)
        self.assertEqual(mission.status, MissionSession.Status.OPPONENT_PROPOSED)

    def test_opponent_admin_chat_shows_assigned_mission(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.OPPONENT_PROPOSED,
        )

        self.client.login(username="chat_member", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.admin.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Latest mission #{mission.id}")

    def test_opponent_receives_admin_chat_message_after_match(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            status=MissionSession.Status.MATCHING,
        )
        cache.set(f"direct_chat_presence:online:{self.member.id}", "1", timeout=60)

        self.client.login(username="chat_admin", password="password123")
        self.client.post(
            reverse("chatapp:admin_assign_mission_opponent", args=[mission.id]),
            {"opponent_id": str(self.member.id)},
            follow=True,
        )

        self.client.logout()
        self.client.login(username="chat_member", password="password123")
        response = self.client.get(reverse("chatapp:direct", args=[self.admin.id]))

        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertContains(response, f"Latest mission #{mission.id}")
        self.assertTrue(
            DirectChatMessage.objects.filter(
                sender=self.admin,
                recipient=self.member,
                body__contains="Opponent found: chat_owner",
            ).exists()
        )
        detail_response = self.client.get(reverse("chatapp:mission_detail", args=[mission.id]))
        payload = detail_response.json()["mission"]
        self.assertEqual(payload["viewer_role"], "opponent")
        self.assertEqual(payload["other_player_profile"]["username"], self.owner.username)

    def test_latest_mission_endpoint_discovers_assigned_opponent_mission(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.OPPONENT_PROPOSED,
        )

        self.client.login(username="chat_member", password="password123")
        response = self.client.get(reverse("chatapp:mission_latest"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()["mission"]
        self.assertEqual(payload["id"], mission.id)
        self.assertEqual(payload["viewer_role"], "opponent")
        self.assertEqual(payload["other_player_profile"]["username"], self.owner.username)

    def test_latest_mission_endpoint_ignores_newer_completed_mission(self):
        pending_mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.OPPONENT_PROPOSED,
        )
        MissionSession.objects.create(
            requester=self.owner,
            opponent=self.outsider,
            status=MissionSession.Status.CLOSED,
        )

        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:mission_latest"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()["mission"]
        self.assertEqual(payload["id"], pending_mission.id)
        self.assertEqual(payload["status"], MissionSession.Status.OPPONENT_PROPOSED)
        self.assertEqual(payload["viewer_role"], "requester")

    def test_admin_can_claim_and_release_mission_request(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            status=MissionSession.Status.MATCHING,
        )

        self.client.login(username="chat_admin", password="password123")
        claim_response = self.client.post(
            reverse("chatapp:admin_claim_mission_request", args=[mission.id]),
            {"action": "claim"},
            follow=True,
        )
        self.assertEqual(claim_response.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.assigned_admin, self.admin)
        self.assertIsNotNone(mission.assigned_at)

        release_response = self.client.post(
            reverse("chatapp:admin_claim_mission_request", args=[mission.id]),
            {"action": "release"},
            follow=True,
        )
        self.assertEqual(release_response.status_code, 200)
        mission.refresh_from_db()
        self.assertIsNone(mission.assigned_admin)
        self.assertIsNone(mission.assigned_at)

    def test_other_admin_cannot_assign_claimed_mission_request(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            status=MissionSession.Status.MATCHING,
            assigned_admin=self.admin,
            assigned_at=timezone.now(),
        )
        cache.set(f"direct_chat_presence:online:{self.member.id}", "1", timeout=60)
        MissionTemplate.objects.create(
            title="Claim Lock Mission",
            instruction_text="Respect claim lock.",
            is_active=True,
        )

        self.client.login(username="chat_admin_two", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_assign_mission_opponent", args=[mission.id]),
            {"opponent_id": str(self.member.id)},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertIsNone(mission.opponent_id)
        self.assertEqual(mission.assigned_admin_id, self.admin.id)

    def test_admin_inbox_shows_quick_approve_reject_controls(self):
        token_request = TokenPurchaseRequest.objects.create(
            requester=self.owner,
            requested_tokens=6,
            status=TokenPurchaseRequest.Status.SUBMITTED,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.PROOF_SUBMITTED,
        )
        evidence = MissionEvidence.objects.create(
            mission_session=mission,
            submitted_by=self.owner,
            review_status=MissionEvidence.ReviewStatus.SUBMITTED,
            explanation="mission proof",
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Quick controls are also available below")
        self.assertContains(
            response,
            reverse("chatapp:admin_review_mission_action", args=[evidence.id]),
        )
        self.assertContains(
            response,
            reverse("chatapp:admin_review_token_action", args=[token_request.id]),
        )
        self.assertContains(response, ">Approve<", count=2)
        self.assertContains(response, ">Reject<", count=2)

    def test_admin_inbox_hides_route_labels_for_pending_queues(self):
        token_request = TokenPurchaseRequest.objects.create(
            requester=self.owner,
            requested_tokens=6,
            status=TokenPurchaseRequest.Status.SUBMITTED,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.PROOF_SUBMITTED,
        )
        evidence = MissionEvidence.objects.create(
            mission_session=mission,
            submitted_by=self.owner,
            review_status=MissionEvidence.ReviewStatus.SUBMITTED,
            explanation="mission proof",
        )
        AdminDecisionLog.objects.create(
            actor_type=AdminDecisionLog.ActorType.AI,
            mission_session=mission,
            action="mission_review_route",
            rationale="AI-first route.",
            confidence=0.87,
        )
        AdminDecisionLog.objects.create(
            actor_type=AdminDecisionLog.ActorType.MANUAL,
            actor_user=self.admin,
            token_purchase_request=token_request,
            action="token_review_route",
            rationale="Manual route for token review.",
            confidence=1,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"#{evidence.id}")
        self.assertContains(response, f"#{token_request.id}")
        self.assertNotContains(response, "Route: AI")
        self.assertNotContains(response, "Route: Manual")
        self.assertNotContains(response, "Confidence")

    def test_admin_inbox_hides_review_mode_badge(self):
        MissionReviewControl.objects.create(
            route_mode=MissionReviewControl.RouteMode.MANUAL_ONLY,
            reason="Temporary manual moderation",
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_inbox"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Review Mode")
        self.assertNotContains(response, "Manual Only")

    def test_admin_review_center_is_accessible_to_admin_only(self):
        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:admin_review_center"))
        self.assertEqual(response.status_code, 403)

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_review_center"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Review Center")
        self.assertContains(response, "total mission")
        self.assertContains(response, "Sort queue")
        self.assertContains(response, "Mission timer")
        self.assertContains(response, reverse("chatapp:admin_mission_timer_update"))
        self.assertContains(response, 'name="mission_timer_minutes"')
        self.assertContains(response, "Start Mission")
        self.assertContains(response, "Start Mission Manually")
        self.assertContains(response, reverse("chatapp:admin_start_mission"))
        self.assertContains(response, 'name="requester_id"')
        self.assertContains(response, 'name="opponent_id"')
        self.assertContains(response, "Mission Requests")
        self.assertContains(response, "Mission Proof")
        self.assertContains(response, "Token Requests")

    def test_admin_review_center_replaces_chat_proof_placeholder_with_transcript(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.PROOF_SUBMITTED,
        )
        MissionEvidence.objects.create(
            mission_session=mission,
            submitted_by=self.owner,
            chat_transcript="[2026-08-10 10:00] chat_owner: proof line",
            review_status=MissionEvidence.ReviewStatus.SUBMITTED,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_review_center"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Captured mission chat")
        self.assertContains(response, "proof line")
        self.assertContains(response, "Transcript below")
        self.assertNotContains(response, "chat-review-transcript-inset")
        self.assertNotContains(response, "Chat proof captured")

    def test_admin_can_start_mission_without_player_request(self):
        template = MissionTemplate.objects.create(
            title="Admin Started Mission",
            instruction_text="Start a playful conversation.",
            opponent_instruction_text="Respond naturally.",
            is_active=True,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_start_mission"),
            data={
                "requester_id": self.owner.id,
                "opponent_id": self.member.id,
                "mission_template_id": template.id,
                "next": reverse("chatapp:admin_review_center"),
            },
        )

        self.assertRedirects(response, reverse("chatapp:admin_review_center"))
        mission = MissionSession.objects.get(requester=self.owner, opponent=self.member)
        self.assertEqual(mission.status, MissionSession.Status.OPPONENT_PROPOSED)
        self.assertEqual(mission.mission_template, template)
        self.assertTrue(
            AdminDecisionLog.objects.filter(
                mission_session=mission,
                action="admin_started_mission",
                actor_user=self.admin,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.owner,
                message__contains="Admin started a mission",
            ).exists()
        )
        self.assertTrue(
            MissionQueueEntry.objects.filter(
                user=self.member,
                status=MissionQueueEntry.QueueStatus.MATCHED,
                mission_session=mission,
            ).exists()
        )

    def test_admin_review_center_shows_mission_requests_for_matching(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            status=MissionSession.Status.MATCHING,
        )
        cache.set(f"direct_chat_presence:online:{self.member.id}", "1", timeout=60)

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_review_center"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mission Requests")
        self.assertContains(response, "chat_owner wants a mission")
        self.assertContains(response, f"Mission #{mission.id}")
        self.assertContains(response, "Select online opponent")
        self.assertContains(response, self.member.username)
        self.assertContains(response, "Match Opponent")
        self.assertContains(response, "Cancel")

    def test_admin_review_center_monitors_ongoing_missions(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.MISSION_ACTIVE,
            started_at=timezone.now(),
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_review_center"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mission Monitor")
        self.assertContains(response, f"Mission #{mission.id}: Mission Active")
        self.assertContains(response, "chat_owner")
        self.assertContains(response, "chat_member")
        self.assertContains(response, "Cancel Mission")

    def test_admin_can_cancel_mission_from_control_panel(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.MISSION_ACTIVE,
            started_at=timezone.now(),
        )
        MissionQueueEntry.objects.create(
            user=self.owner,
            status=MissionQueueEntry.QueueStatus.MATCHED,
            mission_session=mission,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_mission_control_action", args=[mission.id]),
            {
                "action": "cancel",
                "note": "User asked to stop.",
                "next": reverse("chatapp:admin_review_center"),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.CLOSED)
        self.assertIsNotNone(mission.ended_at)
        queue_entry = MissionQueueEntry.objects.get(mission_session=mission)
        self.assertEqual(queue_entry.status, MissionQueueEntry.QueueStatus.CLOSED)
        self.assertTrue(
            AdminDecisionLog.objects.filter(
                mission_session=mission,
                action="cancel_mission",
            ).exists()
        )

    def test_admin_can_remove_unused_mission_record(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            status=MissionSession.Status.MATCHING,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_mission_control_action", args=[mission.id]),
            {
                "action": "delete",
                "next": reverse("chatapp:admin_review_center"),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(MissionSession.objects.filter(pk=mission.id).exists())

    def test_admin_cannot_remove_active_mission_record(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.MISSION_ACTIVE,
            started_at=timezone.now(),
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_mission_control_action", args=[mission.id]),
            {
                "action": "delete",
                "next": reverse("chatapp:admin_review_center"),
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(MissionSession.objects.filter(pk=mission.id).exists())

    def test_admin_review_center_hides_route_labels(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.PROOF_SUBMITTED,
        )
        evidence = MissionEvidence.objects.create(
            mission_session=mission,
            submitted_by=self.owner,
            review_status=MissionEvidence.ReviewStatus.SUBMITTED,
            explanation="proof",
        )
        token_request = TokenPurchaseRequest.objects.create(
            requester=self.owner,
            requested_tokens=7,
            status=TokenPurchaseRequest.Status.SUBMITTED,
        )
        AdminDecisionLog.objects.create(
            actor_type=AdminDecisionLog.ActorType.AI,
            mission_session=mission,
            action="mission_review_route",
            rationale="AI-first route.",
            confidence=0.88,
        )
        AdminDecisionLog.objects.create(
            actor_type=AdminDecisionLog.ActorType.MANUAL,
            actor_user=self.admin,
            token_purchase_request=token_request,
            action="token_review_route",
            rationale="Manual route for token review.",
            confidence=1,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_review_center"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Evidence #{evidence.id}")
        self.assertContains(response, f"Request #{token_request.id}")
        self.assertNotContains(response, "Route: AI")
        self.assertNotContains(response, "Route: Manual")
        self.assertNotContains(response, "Confidence")

    def test_admin_review_center_ignores_route_filter(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.PROOF_SUBMITTED,
        )
        evidence = MissionEvidence.objects.create(
            mission_session=mission,
            submitted_by=self.owner,
            review_status=MissionEvidence.ReviewStatus.SUBMITTED,
            explanation="proof",
        )
        token_request = TokenPurchaseRequest.objects.create(
            requester=self.owner,
            requested_tokens=7,
            status=TokenPurchaseRequest.Status.SUBMITTED,
        )
        AdminDecisionLog.objects.create(
            actor_type=AdminDecisionLog.ActorType.AI,
            mission_session=mission,
            action="mission_review_route",
            rationale="AI-first route.",
            confidence=0.88,
        )
        AdminDecisionLog.objects.create(
            actor_type=AdminDecisionLog.ActorType.MANUAL,
            actor_user=self.admin,
            token_purchase_request=token_request,
            action="token_review_route",
            rationale="Manual route for token review.",
            confidence=1,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:admin_review_center"), {"route": "manual"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Evidence #{evidence.id}")
        self.assertContains(response, f"Request #{token_request.id}")

    def test_admin_can_switch_review_route_mode(self):
        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_review_route_mode_update"),
            {
                "route_mode": "manual_only",
                "reason": "Manual moderation shift",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        control = MissionReviewControl.objects.order_by("-updated_at", "-id").first()
        self.assertIsNotNone(control)
        self.assertEqual(control.route_mode, MissionReviewControl.RouteMode.MANUAL_ONLY)
        self.assertContains(response, "Mission review route mode updated to manual_only")

    def test_admin_can_set_global_mission_timer(self):
        pending_mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.MISSION_PROPOSED,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_mission_timer_update"),
            {"mission_timer_minutes": "5"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        control = MissionReviewControl.objects.order_by("-updated_at", "-id").first()
        self.assertIsNotNone(control)
        self.assertEqual(control.mission_timer_seconds, 300)
        pending_mission.refresh_from_db()
        self.assertEqual(pending_mission.timer_seconds, 300)
        self.assertContains(response, "Mission timer set to 5 minute(s).")

    def test_review_routing_stays_manual_only(self):
        manual_mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.PROOF_SUBMITTED,
        )
        MissionEvidence.objects.create(
            mission_session=manual_mission,
            submitted_by=self.owner,
            review_status=MissionEvidence.ReviewStatus.SUBMITTED,
            explanation="proof text",
        )

        self.client.login(username="chat_admin", password="password123")
        self.client.post(
            reverse("chatapp:admin_review_route_mode_update"),
            {"route_mode": "manual_only", "reason": "manual test"},
            follow=True,
        )
        self.client.post(
            reverse("chatapp:mission_action", args=[manual_mission.id]),
            data='{"action": "start_review"}',
            content_type="application/json",
        )
        manual_route = AdminDecisionLog.objects.filter(
            mission_session=manual_mission,
            action="mission_review_route",
        ).first()
        self.assertIsNotNone(manual_route)
        self.assertEqual(manual_route.actor_type, AdminDecisionLog.ActorType.MANUAL)

        second_mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.outsider,
            status=MissionSession.Status.PROOF_SUBMITTED,
        )
        MissionEvidence.objects.create(
            mission_session=second_mission,
            submitted_by=self.owner,
            review_status=MissionEvidence.ReviewStatus.SUBMITTED,
            explanation="proof text",
        )
        self.client.post(
            reverse("chatapp:admin_review_route_mode_update"),
            {"route_mode": "ai_preferred", "reason": "ai test"},
            follow=True,
        )
        self.client.post(
            reverse("chatapp:mission_action", args=[second_mission.id]),
            data='{"action": "start_review"}',
            content_type="application/json",
        )
        second_route = AdminDecisionLog.objects.filter(
            mission_session=second_mission,
            action="mission_review_route",
        ).first()
        self.assertIsNotNone(second_route)
        self.assertEqual(second_route.actor_type, AdminDecisionLog.ActorType.MANUAL)

    def test_admin_review_center_bulk_token_action_requires_confirmation(self):
        token_request = TokenPurchaseRequest.objects.create(
            requester=self.owner,
            requested_tokens=5,
            status=TokenPurchaseRequest.Status.SUBMITTED,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_review_bulk_token_action"),
            {
                "bulk_action": "approve",
                "request_ids": [str(token_request.id)],
                "approved_tokens": "3",
                "review_notes": "ok note",
                "confirm_text": "WRONG",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        token_request.refresh_from_db()
        self.assertEqual(token_request.status, TokenPurchaseRequest.Status.SUBMITTED)

    def test_admin_review_center_bulk_token_approve_updates_multiple_requests(self):
        first = TokenPurchaseRequest.objects.create(
            requester=self.owner,
            requested_tokens=5,
            status=TokenPurchaseRequest.Status.SUBMITTED,
        )
        second = TokenPurchaseRequest.objects.create(
            requester=self.owner,
            requested_tokens=8,
            status=TokenPurchaseRequest.Status.SUBMITTED,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_review_bulk_token_action"),
            {
                "bulk_action": "approve",
                "request_ids": [str(first.id), str(second.id)],
                "approved_tokens": "2",
                "review_notes": "Bulk approved safely",
                "confirm_text": "BULK_APPROVE",
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.status, TokenPurchaseRequest.Status.APPROVED)
        self.assertEqual(second.status, TokenPurchaseRequest.Status.APPROVED)
        self.assertEqual(OTP.objects.get(user=self.owner).remaining_votes, 4)

    def test_admin_review_center_mission_approve_action(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.PROOF_SUBMITTED,
        )
        evidence = MissionEvidence.objects.create(
            mission_session=mission,
            submitted_by=self.owner,
            review_status=MissionEvidence.ReviewStatus.SUBMITTED,
            explanation="proof",
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_review_mission_action", args=[evidence.id]),
            {"action": "approve", "review_notes": "Verified"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        evidence.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.CLOSED)
        self.assertEqual(evidence.review_status, MissionEvidence.ReviewStatus.APPROVED)
        self.assertEqual(OTP.objects.get(user=self.owner).remaining_votes, 2)

    def test_admin_review_center_token_approve_action(self):
        token_request = TokenPurchaseRequest.objects.create(
            requester=self.owner,
            requested_tokens=9,
            status=TokenPurchaseRequest.Status.SUBMITTED,
        )

        self.client.login(username="chat_admin", password="password123")
        response = self.client.post(
            reverse("chatapp:admin_review_token_action", args=[token_request.id]),
            {"action": "approve", "approved_tokens": "5", "review_notes": "Payment checked"},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        token_request.refresh_from_db()
        self.assertEqual(token_request.status, TokenPurchaseRequest.Status.APPROVED)
        self.assertEqual(token_request.approved_tokens, 5)
        self.assertEqual(OTP.objects.get(user=self.owner).remaining_votes, 5)

    def test_mission_center_renders_sidebar_for_admin_and_player(self):
        self.client.login(username="chat_admin", password="password123")
        response = self.client.get(reverse("chatapp:mission_center"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mission navigation")
        self.assertContains(response, "Admin overview")
        self.assertContains(response, reverse("chatapp:admin_review_center"))

        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:mission_center"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "My Mission Center")
        self.assertContains(response, "Mission navigation")

    def test_mission_center_renders_mission_evidence_and_token_history(self):
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.MISSION_ACTIVE,
        )
        evidence = MissionEvidence.objects.create(
            mission_session=mission,
            submitted_by=self.owner,
            review_status=MissionEvidence.ReviewStatus.SUBMITTED,
            explanation="proof note",
        )
        token_request = TokenPurchaseRequest.objects.create(
            requester=self.owner,
            requested_tokens=7,
            status=TokenPurchaseRequest.Status.SUBMITTED,
            payment_channel="bank",
            payment_reference="TX-77",
        )

        self.client.login(username="chat_owner", password="password123")
        response = self.client.get(reverse("chatapp:mission_center"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Mission #{mission.id}")
        self.assertContains(response, f"Evidence #{evidence.id}")
        self.assertContains(response, f"Request #{token_request.id}")
        self.assertContains(response, "proof note")
        self.assertContains(response, "TX-77")
        self.assertContains(response, "Mission navigation")
        self.assertContains(response, "Open Mission Chat")
        self.assertContains(response, reverse("chatapp:direct", args=[self.member.id]))

    def test_mission_request_endpoint_creates_waiting_mission(self):
        self.client.force_login(self.owner)

        response = self.client.post(reverse("chatapp:mission_request"))

        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        mission = MissionSession.objects.get(pk=payload["mission"]["id"])
        self.assertEqual(mission.requester, self.owner)
        self.assertEqual(mission.status, MissionSession.Status.MATCHING)

    def test_mission_action_happy_path_to_approval_grants_bonus_votes(self):
        MissionTemplate.objects.create(
            title="Laugh Mission",
            instruction_text="Make your opponent laugh in two minutes.",
            is_active=True,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.OPPONENT_PROPOSED,
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "accept_opponent"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.MISSION_PROPOSED)
        self.assertIsNotNone(mission.mission_template)
        self.assertIsNotNone(mission.opponent_mission_template)

        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "accept_mission"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.MISSION_ACTIVE)
        expected_timer = 120 + (max(mission.mission_template.difficulty, mission.opponent_mission_template.difficulty) - 1) * 60
        self.assertEqual(mission.timer_seconds, expected_timer)

        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "submit_proof", "explanation": "I won fairly."}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.PROOF_SUBMITTED)
        evidence_id = response.json()["evidence"]["id"]

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "start_review"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.UNDER_REVIEW)
        route_log = AdminDecisionLog.objects.filter(
            mission_session=mission,
            action="mission_review_route",
        ).first()
        self.assertIsNotNone(route_log)
        self.assertEqual(route_log.actor_type, AdminDecisionLog.ActorType.MANUAL)
        self.assertEqual(float(route_log.confidence), 1)
        ticket = ReviewAutomationTicket.objects.filter(mission_session=mission).first()
        self.assertIsNone(ticket)

        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data=f'{{"action": "approve_proof", "evidence_id": {evidence_id}, "review_notes": "Looks valid."}}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.CLOSED)
        self.assertEqual(mission.winner, self.owner)

        winner_otp = OTP.objects.get(user=self.owner)
        self.assertEqual(winner_otp.remaining_votes, 2)
        evidence = MissionEvidence.objects.get(pk=evidence_id)
        self.assertEqual(evidence.review_status, MissionEvidence.ReviewStatus.APPROVED)

    def test_mission_accept_unlocks_direct_chat_thread(self):
        MissionTemplate.objects.create(
            title="Warmup Mission",
            instruction_text="Say hello with style.",
            is_active=True,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.OPPONENT_PROPOSED,
        )

        self.client.force_login(self.owner)
        self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "accept_opponent"}',
            content_type="application/json",
        )
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "accept_mission"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        thread = PeerChatThread.objects.filter(
            user_one=min(self.owner, self.member, key=lambda user: user.id),
            user_two=max(self.owner, self.member, key=lambda user: user.id),
        ).first()
        self.assertIsNotNone(thread)
        self.assertIsNotNone(thread.unlocked_until)
        self.assertGreater(thread.unlocked_until, timezone.now())

    def test_mission_payload_includes_opponent_profile_snapshot(self):
        MissionTemplate.objects.create(
            title="Profile Mission",
            instruction_text="Demo mission.",
            opponent_instruction_text="Respond to the demo mission.",
            is_active=True,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.OPPONENT_PROPOSED,
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "accept_opponent"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("mission", payload)
        self.assertIn("opponent_profile", payload["mission"])
        opponent_profile = payload["mission"]["opponent_profile"]
        self.assertEqual(opponent_profile["username"], self.member.username)
        self.assertIn("badge_level", opponent_profile)
        self.assertIn("current_points", opponent_profile)

    def test_mission_payload_uses_role_specific_instructions(self):
        template = MissionTemplate.objects.create(
            title="Playlist Guess",
            instruction_text="Send three song titles that match your mood.",
            opponent_instruction_text="Pick the song title that fits their mood best and say why.",
            is_active=True,
        )
        opponent_template = MissionTemplate.objects.create(
            title="Question Streak",
            instruction_text="Get your opponent to ask two follow-up questions naturally.",
            is_active=True,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            mission_template=template,
            opponent_mission_template=opponent_template,
            status=MissionSession.Status.MISSION_PROPOSED,
        )

        self.client.force_login(self.owner)
        requester_response = self.client.get(reverse("chatapp:mission_detail", args=[mission.id]))
        self.assertEqual(requester_response.status_code, 200)
        requester_payload = requester_response.json()["mission"]
        self.assertEqual(requester_payload["mission_instruction"], template.instruction_text)
        self.assertEqual(requester_payload["mission_instruction_label"], "Your Mission")

        self.client.force_login(self.member)
        opponent_response = self.client.get(reverse("chatapp:mission_detail", args=[mission.id]))
        self.assertEqual(opponent_response.status_code, 200)
        opponent_payload = opponent_response.json()["mission"]
        self.assertNotEqual(opponent_payload["mission_instruction"], template.instruction_text)
        self.assertNotEqual(opponent_payload["mission_instruction"], template.opponent_instruction_text)
        self.assertIsNone(opponent_payload["requester_instruction"])
        self.assertEqual(opponent_payload["mission_instruction"], opponent_template.instruction_text)
        self.assertEqual(opponent_payload["mission_instruction_label"], "Your Mission")

    def test_peer_chat_renders_active_mission_panel_for_proof_submission(self):
        template = MissionTemplate.objects.create(
            title="Peer Proof Mission",
            instruction_text="Ask your opponent a playful question.",
            opponent_instruction_text="Answer the playful question in this chat.",
            is_active=True,
        )
        MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            mission_template=template,
            status=MissionSession.Status.MISSION_ACTIVE,
            started_at=timezone.now(),
            timer_seconds=120,
        )
        thread, _ = PeerChatThread.get_or_create_for_users(self.owner, self.member)
        thread.unlocked_until = timezone.now() + timedelta(hours=1)
        thread.save(update_fields=["unlocked_until", "updated_at"])

        self.client.force_login(self.member)
        response = self.client.get(reverse("chatapp:direct", args=[self.owner.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Active Mission")
        self.assertContains(response, "data-player-mission-panel")
        self.assertContains(response, "chat-mission-chat-card")
        self.assertContains(response, "Mission Chat")
        self.assertContains(response, "data-mission-action=\"submit_proof\"")
        self.assertContains(response, "After review, you can continue chatting from your inbox.")

    def test_direct_chat_media_upload_creates_shareable_message(self):
        self.create_match(self.owner, self.member)
        upload = SimpleUploadedFile(
            "proof.png",
            b"fake-image-bytes",
            content_type="image/png",
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("chatapp:direct_media_upload", args=[self.member.id]),
            data={"media": upload, "body": "Look at this"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["message"]
        self.assertEqual(payload["media_type"], "image")
        self.assertEqual(payload["media_name"], "proof.png")
        self.assertEqual(payload["body"], "Look at this")
        message = DirectChatMessage.objects.get(pk=payload["message_id"])
        self.assertEqual(message.sender, self.owner)
        self.assertEqual(message.recipient, self.member)
        self.assertTrue(message.media_file)
        thread = PeerChatThread.objects.get(user_one=self.owner, user_two=self.member)
        self.assertEqual(thread.unread_count_for(self.member), 1)
        self.assertTrue(
            Notification.objects.filter(user=self.member, message__contains="media message").exists()
        )

    def test_direct_chat_media_upload_rejects_mismatched_extension(self):
        self.create_match(self.owner, self.member)
        upload = SimpleUploadedFile(
            "proof.exe",
            b"fake-image-bytes",
            content_type="image/png",
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("chatapp:direct_media_upload", args=[self.member.id]),
            data={"media": upload},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(DirectChatMessage.objects.count(), 0)
        self.assertIn("extension", response.json()["message"])

    def test_mission_review_cleans_chat_media_but_keeps_text(self):
        with tempfile.TemporaryDirectory() as media_root:
            with override_settings(MEDIA_ROOT=media_root):
                mission_template = MissionTemplate.objects.create(
                    title="Media Cleanup Mission",
                    instruction_text="Use chat normally.",
                    is_active=True,
                )
                mission = MissionSession.objects.create(
                    requester=self.owner,
                    opponent=self.member,
                    mission_template=mission_template,
                    status=MissionSession.Status.PROOF_SUBMITTED,
                    started_at=timezone.now() - timedelta(minutes=1),
                )
                message = DirectChatMessage.objects.create(
                    sender=self.owner,
                    recipient=self.member,
                    body="This text should stay.",
                    media_file=SimpleUploadedFile(
                        "mission-photo.png",
                        b"temporary-mission-media",
                        content_type="image/png",
                    ),
                    media_type="image",
                    media_name="mission-photo.png",
                )
                media_name = message.media_file.name
                storage = message.media_file.storage
                self.assertTrue(storage.exists(media_name))
                evidence = MissionEvidence.objects.create(
                    mission_session=mission,
                    submitted_by=self.owner,
                    explanation="Proof from chat.",
                    review_status=MissionEvidence.ReviewStatus.SUBMITTED,
                )

                self.client.force_login(self.admin)
                with self.captureOnCommitCallbacks(execute=True):
                    response = self.client.post(
                        reverse("chatapp:mission_action", args=[mission.id]),
                        data=f'{{"action": "approve_proof", "evidence_id": {evidence.id}}}',
                        content_type="application/json",
                    )

                self.assertEqual(response.status_code, 200)
                message.refresh_from_db()
                self.assertEqual(message.body, "This text should stay.")
                self.assertFalse(message.media_file)
                self.assertEqual(message.media_type, "")
                self.assertEqual(message.media_name, "")
                self.assertFalse(storage.exists(media_name))

    def test_mission_submit_proof_supports_multipart_with_screenshot(self):
        MissionTemplate.objects.create(
            title="Screenshot Mission",
            instruction_text="Share visual proof.",
            is_active=True,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.OPPONENT_PROPOSED,
        )

        self.client.force_login(self.owner)
        self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "accept_opponent"}',
            content_type="application/json",
        )
        self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "accept_mission"}',
            content_type="application/json",
        )

        screenshot = SimpleUploadedFile(
            "proof.png",
            b"fake-image-bytes",
            content_type="image/png",
        )
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data={
                "action": "submit_proof",
                "explanation": "Uploading screenshot proof.",
                "screenshot": screenshot,
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("status"), "ok")
        self.assertIn("Proof submitted", payload.get("message", ""))
        evidence = MissionEvidence.objects.get(pk=payload["evidence"]["id"])
        self.assertTrue(bool(evidence.screenshot))

    def test_mission_submit_proof_captures_chat_transcript_without_upload(self):
        MissionTemplate.objects.create(
            title="Chat Proof Mission",
            instruction_text="Get a verifiable chat response.",
            is_active=True,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            mission_template=MissionTemplate.objects.first(),
            status=MissionSession.Status.MISSION_ACTIVE,
            started_at=timezone.now(),
        )
        DirectChatMessage.objects.create(
            sender=self.owner,
            recipient=self.member,
            body="Describe my vibe with one emoji and one word.",
        )
        DirectChatMessage.objects.create(
            sender=self.member,
            recipient=self.owner,
            body="✨ smooth",
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data={"action": "submit_proof", "explanation": ""},
        )

        self.assertEqual(response.status_code, 200)
        evidence = MissionEvidence.objects.get(mission_session=mission)
        self.assertIn("Describe my vibe", evidence.chat_transcript)
        self.assertIn("smooth", evidence.chat_transcript)

    def test_mission_submit_proof_rejects_empty_chat_proof(self):
        mission_template = MissionTemplate.objects.create(
            title="Proof Required Mission",
            instruction_text="Submit something verifiable.",
            is_active=True,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            mission_template=mission_template,
            status=MissionSession.Status.MISSION_ACTIVE,
            started_at=timezone.now(),
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data={"action": "submit_proof", "explanation": ""},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("Chat proof is empty", payload["message"])
        self.assertEqual(payload["error_code"], "chat_proof_empty")
        self.assertEqual(payload["error_type"], "user_action")
        self.assertFalse(MissionEvidence.objects.filter(mission_session=mission).exists())

    def test_mission_multipart_action_does_not_read_raw_body_after_post_stream(self):
        mission_template = MissionTemplate.objects.create(
            title="Multipart Proof Mission",
            instruction_text="Submit something verifiable.",
            is_active=True,
        )
        mission = MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            mission_template=mission_template,
            status=MissionSession.Status.MISSION_ACTIVE,
            started_at=timezone.now(),
        )

        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data={"action": "submit_proof", "explanation": ""},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "chat_proof_empty")

    @override_settings(CHATAPP_MISSION_POLICY={"manual_matchmaking": False, "require_homepage_win_opponent": True})
    def test_mission_matchmaking_can_require_homepage_winner_opponent(self):
        MissionQueueEntry.objects.create(
            user=self.member,
            status=MissionQueueEntry.QueueStatus.WAITING,
            reason="waiting",
        )

        self.client.force_login(self.owner)
        response = self.client.post(reverse("chatapp:mission_request"))

        self.assertEqual(response.status_code, 201)
        mission = MissionSession.objects.get(pk=response.json()["mission"]["id"])
        self.assertEqual(mission.status, MissionSession.Status.MATCHING)
        self.assertIsNone(mission.opponent_id)

        MissionWinFeed.objects.create(
            mission_session=mission,
            winner=self.member,
            homepage_visible=True,
        )
        response_with_winner = self.client.post(
            reverse("chatapp:mission_action", args=[mission.id]),
            data='{"action": "find_another_opponent"}',
            content_type="application/json",
        )

        self.assertEqual(response_with_winner.status_code, 200)
        mission.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.OPPONENT_PROPOSED)
        self.assertEqual(mission.opponent_id, self.member.id)

    def test_loser_can_start_new_mission_after_previous_loss_without_support_vote(self):
        mission = MissionSession.objects.create(
            requester=self.member,
            opponent=self.owner,
            status=MissionSession.Status.COOLDOWN_VOTE_REQUIRED,
            winner=self.member,
            loser=self.owner,
            loser_vote_required=True,
            ended_at=timezone.now(),
        )

        self.client.force_login(self.owner)
        allowed_response = self.client.post(reverse("chatapp:mission_request"))
        self.assertEqual(allowed_response.status_code, 201)
        mission.refresh_from_db()
        self.assertEqual(mission.status, MissionSession.Status.CLOSED)

    @override_settings(CHATAPP_MISSION_POLICY={"manual_matchmaking": False})
    def test_mission_matchmaking_prefers_non_rematch_candidate(self):
        MissionSession.objects.create(
            requester=self.owner,
            opponent=self.member,
            status=MissionSession.Status.CLOSED,
            ended_at=timezone.now() - timedelta(hours=2),
        )
        MissionQueueEntry.objects.create(
            user=self.member,
            status=MissionQueueEntry.QueueStatus.WAITING,
            reason="waiting",
        )
        MissionQueueEntry.objects.create(
            user=self.outsider,
            status=MissionQueueEntry.QueueStatus.WAITING,
            reason="waiting",
        )
        cache.set(f"direct_chat_presence:online:{self.outsider.id}", "1", timeout=60)

        self.client.force_login(self.owner)
        response = self.client.post(reverse("chatapp:mission_request"))

        self.assertEqual(response.status_code, 201)
        mission = MissionSession.objects.get(pk=response.json()["mission"]["id"])
        self.assertEqual(mission.opponent_id, self.outsider.id)

    @override_settings(CHATAPP_MISSION_POLICY={"manual_matchmaking": True})
    def test_mission_request_stays_in_manual_matching_mode_even_when_candidates_wait(self):
        MissionQueueEntry.objects.create(
            user=self.member,
            status=MissionQueueEntry.QueueStatus.WAITING,
            reason="waiting",
        )
        cache.set(f"direct_chat_presence:online:{self.member.id}", "1", timeout=60)

        self.client.force_login(self.owner)
        response = self.client.post(reverse("chatapp:mission_request"))

        self.assertEqual(response.status_code, 201)
        mission = MissionSession.objects.get(pk=response.json()["mission"]["id"])
        self.assertEqual(mission.status, MissionSession.Status.MATCHING)
        self.assertIsNone(mission.opponent_id)

    def test_token_purchase_request_and_manual_admin_review(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("chatapp:token_purchase_create"),
            data='{"requested_tokens": 5, "payment_channel": "bank", "payment_reference": "TXN-100"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 201)
        request_id = response.json()["token_request"]["id"]
        token_request = TokenPurchaseRequest.objects.get(pk=request_id)
        self.assertEqual(token_request.status, TokenPurchaseRequest.Status.SUBMITTED)

        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("chatapp:token_purchase_review", args=[request_id]),
            data='{"action": "approve", "approved_tokens": 4, "review_notes": "Payment confirmed"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        token_request.refresh_from_db()
        self.assertEqual(token_request.status, TokenPurchaseRequest.Status.APPROVED)
        self.assertEqual(token_request.approved_tokens, 4)
        otp = OTP.objects.get(user=self.owner)
        self.assertEqual(otp.remaining_votes, 4)
        route_log = AdminDecisionLog.objects.filter(
            token_purchase_request=token_request,
            action="token_review_route",
        ).first()
        self.assertIsNotNone(route_log)
        self.assertEqual(route_log.actor_type, AdminDecisionLog.ActorType.MANUAL)


class DirectChatWebSocketTests(TestCase):
    async def receive_event(self, communicator, event_type):
        for _ in range(8):
            event = await communicator.receive_json_from()
            if event.get("type") == event_type:
                return event
        self.fail(f"Did not receive event type '{event_type}'")

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
        response = await self.receive_event(communicator, "message")

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
            DirectChatMessage.objects.filter(
                sender=owner,
                recipient=admin,
                body="Hello admin",
            ).exists
        )()
        self.assertEqual(thread.unread_count, 1)
        self.assertTrue(notification_exists)
        self.assertTrue(body_persisted)

        await communicator.disconnect()

    async def test_user_event_socket_receives_admin_count_updates(self):
        owner = await database_sync_to_async(CustomUser.objects.create_user)(
            username="event_owner",
            password="password123",
            role=Role.FAN,
        )
        admin = await database_sync_to_async(CustomUser.objects.create_user)(
            username="event_admin",
            password="password123",
            role=Role.ADMIN,
            is_staff=True,
        )
        await database_sync_to_async(AdminChatThread.objects.create)(
            admin=admin,
            user=owner,
            unread_count=2,
        )

        communicator = WebsocketCommunicator(URLRouter(websocket_urlpatterns), "/ws/events/")
        communicator.scope["user"] = admin
        connected, _ = await communicator.connect()

        self.assertTrue(connected)
        await database_sync_to_async(broadcast_admin_counts)(admin)
        event = await self.receive_event(communicator, "admin_counts")

        self.assertEqual(event["unread_count"], 2)
        self.assertEqual(event["total_action_count"], 2)

        await communicator.disconnect()

    async def test_direct_chat_socket_relays_read_receipts(self):
        owner = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_receipt_owner",
            password="password123",
            role=Role.FAN,
        )
        member = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_receipt_member",
            password="password123",
            role=Role.FAN,
        )
        await database_sync_to_async(record_match_rating)(owner, member, 8)

        owner_socket = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/chat/user/{member.id}/",
        )
        owner_socket.scope["user"] = owner
        member_socket = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/chat/user/{owner.id}/",
        )
        member_socket.scope["user"] = member

        owner_connected, _ = await owner_socket.connect()
        member_connected, _ = await member_socket.connect()

        self.assertTrue(owner_connected)
        self.assertTrue(member_connected)

        await owner_socket.send_json_to(
            {"message": "Receipt test", "client_id": "client-msg-1"}
        )
        owner_echo = await self.receive_event(owner_socket, "message")
        member_message = await self.receive_event(member_socket, "message")

        self.assertEqual(owner_echo["client_id"], "client-msg-1")
        self.assertEqual(member_message["client_id"], "client-msg-1")
        self.assertEqual(member_message["body"], "Receipt test")

        await member_socket.send_json_to(
            {"type": "read", "message_id": "client-msg-1"}
        )
        owner_receipt = await self.receive_event(owner_socket, "receipt")

        self.assertEqual(owner_receipt["type"], "receipt")
        self.assertEqual(owner_receipt["message_id"], "client-msg-1")
        self.assertEqual(owner_receipt["reader_id"], member.id)
        self.assertEqual(owner_receipt["status"], "read")

        await owner_socket.disconnect()
        await member_socket.disconnect()

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
        response = await self.receive_event(communicator, "message")

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
            DirectChatMessage.objects.filter(
                sender=admin,
                recipient=owner,
                body="Your OTP is ready",
            ).exists
        )()
        self.assertEqual(thread.user_unread_count, 1)
        self.assertTrue(notification_exists)
        self.assertTrue(body_persisted)

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
        response = await self.receive_event(communicator, "message")

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
            DirectChatMessage.objects.filter(
                sender=owner,
                recipient=member,
                body="Hello peer",
            ).exists
        )()
        self.assertEqual(thread.unread_count_for(member), 1)
        self.assertTrue(notification_exists)
        self.assertTrue(body_persisted)

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
        response = await self.receive_event(communicator, "message")

        self.assertEqual(response["body"], "Admin allowed hello")
        self.assertEqual(response["sender_id"], owner.id)
        self.assertEqual(response["recipient_id"], member.id)
        thread = await database_sync_to_async(PeerChatThread.get_or_create_for_users)(
            owner,
            member,
        )
        thread = thread[0]
        body_persisted = await database_sync_to_async(
            DirectChatMessage.objects.filter(
                sender=owner,
                recipient=member,
                body="Admin allowed hello",
            ).exists
        )()
        self.assertTrue(thread.admin_approved)
        self.assertEqual(thread.unread_count_for(member), 1)
        self.assertTrue(body_persisted)

        await communicator.disconnect()

    async def test_presence_events_push_online_and_offline_updates(self):
        owner = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_presence_owner",
            password="password123",
            role=Role.FAN,
        )
        member = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_presence_member",
            password="password123",
            role=Role.FAN,
        )
        await database_sync_to_async(record_match_rating)(owner, member, 8)

        owner_socket = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/chat/user/{member.id}/",
        )
        owner_socket.scope["user"] = owner
        member_socket = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/chat/user/{owner.id}/",
        )
        member_socket.scope["user"] = member

        owner_connected, _ = await owner_socket.connect()
        member_connected, _ = await member_socket.connect()

        self.assertTrue(owner_connected)
        self.assertTrue(member_connected)

        online_event = await self.receive_event(owner_socket, "presence")
        self.assertEqual(online_event["user_id"], member.id)
        self.assertTrue(online_event["is_online"])

        await member_socket.disconnect()

        offline_event = await self.receive_event(owner_socket, "presence")
        self.assertEqual(offline_event["user_id"], member.id)
        self.assertFalse(offline_event["is_online"])
        self.assertTrue(offline_event.get("last_seen_at"))

        await owner_socket.disconnect()

    async def test_ping_keeps_socket_active_for_subsequent_messages(self):
        owner = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_ping_owner",
            password="password123",
            role=Role.FAN,
        )
        member = await database_sync_to_async(CustomUser.objects.create_user)(
            username="socket_ping_member",
            password="password123",
            role=Role.FAN,
        )
        await database_sync_to_async(record_match_rating)(owner, member, 8)

        owner_socket = WebsocketCommunicator(
            URLRouter(websocket_urlpatterns),
            f"/ws/chat/user/{member.id}/",
        )
        owner_socket.scope["user"] = owner

        connected, _ = await owner_socket.connect()
        self.assertTrue(connected)

        await owner_socket.send_json_to({"type": "ping"})
        await owner_socket.send_json_to({"message": "Ping then message"})
        response = await self.receive_event(owner_socket, "message")

        self.assertEqual(response["body"], "Ping then message")
        self.assertEqual(response["sender_id"], owner.id)
        self.assertEqual(response["recipient_id"], member.id)

        await owner_socket.disconnect()
