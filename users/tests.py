from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from content.models import Comment, Content, LivePerformance, Vote
from chatapp.models import AdminChatThread, MatchRating, PeerChatThread
from chatapp.services import record_match_rating

from .models import Announcement, DismissedAnnouncement, Notification, OTP, Role, VotingTokenPolicy

CustomUser = get_user_model()


class UsersAppTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()
        self.register_url = reverse("register")
        self.login_url = reverse("login")
        self.logout_url = reverse("logout")
        self.dashboard_url = reverse("dashboard")
        self.profile_url = reverse("profile")

        self.admin_data = {
            "username": "admin_user",
            "email": "admin@example.com",
            "password": "adminpass123",
            "role": Role.ADMIN,
            "is_staff": True,
        }
        self.artist_data = {
            "username": "artist_user",
            "email": "artist@example.com",
            "password": "artistpass123",
            "role": Role.ARTIST,
        }
        self.fan_data = {
            "username": "fan_user",
            "email": "fan@example.com",
            "password": "fanpass123",
            "role": Role.FAN,
        }

        self.admin_user = CustomUser.objects.create_user(**self.admin_data)
        self.artist_user = CustomUser.objects.create_user(**self.artist_data)
        self.fan_user = CustomUser.objects.create_user(**self.fan_data)

    def test_register_view(self):
        response = self.client.post(
            self.register_url,
            {
                "username": "new_user",
                "email": "new_user@example.com",
                "password1": "newuserpass123",
                "password2": "newuserpass123",
                "role": Role.FAN,
                "terms_accepted": True,
            },
        )
        self.assertEqual(response.status_code, 302)

        new_user = CustomUser.objects.get(username="new_user")
        self.assertTrue(new_user.is_active)
        self.assertRedirects(response, reverse("login"))

    def test_register_rejects_duplicate_email(self):
        initial_count = CustomUser.objects.count()

        response = self.client.post(
            self.register_url,
            {
                "username": "different_username",
                "email": self.admin_data["email"],  # Already used by setup user
                "password1": "anotherpass123",
                "password2": "anotherpass123",
                "role": Role.FAN,
                "terms_accepted": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unable to register with the provided details.")
        self.assertEqual(CustomUser.objects.count(), initial_count)
        self.assertFalse(CustomUser.objects.filter(username="different_username").exists())

    def test_register_rejects_honeypot_submission(self):
        response = self.client.post(
            self.register_url,
            {
                "username": "new_user_honeypot",
                "email": "new_user_honeypot@example.com",
                "password1": "newuserpass123",
                "password2": "newuserpass123",
                "role": Role.FAN,
                "terms_accepted": True,
                "website": "spam-bot",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CustomUser.objects.filter(username="new_user_honeypot").exists())

    @override_settings(AUTH_REGISTER_MAX_ATTEMPTS=2, AUTH_THROTTLE_WINDOW_SECONDS=60)
    def test_register_rate_limit_blocks_repeated_attempts(self):
        payload = {
            "username": "rate_limit_user",
            "email": "rate_limit_user@example.com",
            "password1": "newuserpass123",
            "password2": "different-password123",
            "role": Role.FAN,
            "terms_accepted": True,
        }

        self.client.post(self.register_url, payload)
        self.client.post(self.register_url, payload)
        response = self.client.post(self.register_url, payload)

        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Too many registration attempts.", status_code=429)

    def test_login_view(self):
        response = self.client.post(
            self.login_url,
            {
                "username": self.admin_user.username,
                "password": self.admin_data["password"],
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_login_keeps_session_persistent_until_logout(self):
        response = self.client.post(
            self.login_url,
            {
                "username": self.admin_user.username,
                "password": self.admin_data["password"],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.client.session.get_expire_at_browser_close())
        self.assertGreaterEqual(
            self.client.session.get_expiry_age(),
            settings.SESSION_COOKIE_AGE - 5,
        )

    @override_settings(AUTH_LOGIN_MAX_ATTEMPTS=2, AUTH_THROTTLE_WINDOW_SECONDS=60)
    def test_login_rate_limit_blocks_repeated_attempts(self):
        payload = {
            "username": self.admin_user.username,
            "password": "wrong-password",
        }

        self.client.post(self.login_url, payload)
        self.client.post(self.login_url, payload)
        response = self.client.post(self.login_url, payload)

        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Too many login attempts.", status_code=429)

    def test_logout_view(self):
        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )
        response = self.client.get(self.logout_url)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_dashboard_redirects_by_role(self):
        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )
        response = self.client.get(self.dashboard_url)
        self.assertRedirects(response, reverse("admin_dashboard"))

        self.client.login(
            username=self.artist_user.username,
            password=self.artist_data["password"],
        )
        response = self.client.get(self.dashboard_url)
        self.assertRedirects(response, reverse("artist_dashboard"))

        self.client.login(
            username=self.fan_user.username,
            password=self.fan_data["password"],
        )
        response = self.client.get(self.dashboard_url)
        self.assertRedirects(response, reverse("fan_dashboard"))

    def test_admin_navigation_links_to_admin_dashboard(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("content_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse("admin_dashboard"))
        self.assertContains(response, "Admin Dashboard")

        self.client.force_login(self.artist_user)
        response = self.client.get(reverse("content_list"))
        self.assertNotContains(response, reverse("admin_dashboard"))

        self.client.force_login(self.fan_user)
        response = self.client.get(reverse("content_list"))
        self.assertNotContains(response, reverse("admin_dashboard"))

    def test_fan_shell_has_floating_admin_chat_widget(self):
        self.client.force_login(self.fan_user)
        response = self.client.get(reverse("content_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin-contact-chat")
        self.assertContains(response, f'data-direct-chat-user="{self.admin_user.id}"')
        self.assertContains(response, 'data-message-retention-ms="86400000"')
        self.assertContains(response, "Contact Admin")

    def test_admin_shell_does_not_show_admin_contact_widget(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("content_list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "admin-contact-chat")
        self.assertContains(response, reverse("chatapp:admin_inbox"))

    def test_admin_dashboard_does_not_show_message_shortcuts(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("chatapp:direct", args=[self.artist_user.id]))
        self.assertNotContains(response, reverse("chatapp:direct", args=[self.fan_user.id]))

    def test_profile_does_not_show_message_shortcut(self):
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("user_profile", args=[self.fan_user.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("chatapp:direct", args=[self.fan_user.id]))

    def test_profile_hides_peer_message_shortcut_until_rating_unlock(self):
        self.client.force_login(self.artist_user)
        response = self.client.get(reverse("user_profile", args=[self.fan_user.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("chatapp:direct", args=[self.fan_user.id]))
        self.assertNotContains(response, reverse("chatapp:rate_user", args=[self.fan_user.id]))
        self.assertNotContains(response, "profile-match-rating")

    def test_profile_hides_peer_message_shortcut_for_rating_unlocked_users(self):
        record_match_rating(self.artist_user, self.fan_user, 8)

        self.client.force_login(self.artist_user)
        response = self.client.get(reverse("user_profile", args=[self.fan_user.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse("chatapp:direct", args=[self.fan_user.id]))
        self.assertNotContains(response, "profile-match-rating")

    def test_artist_list_uses_directory_cards_and_stable_avatars(self):
        self.artist_user.bio = "Independent performer with weekly releases."
        self.artist_user.save(update_fields=["bio"])
        content = Content.objects.create(
            title="Weekly Stage Set",
            artist=self.artist_user,
            is_approved=True,
            is_visible=True,
        )
        Vote.objects.create(
            content=content,
            fan=self.fan_user,
            base_value=8,
            value=8,
            otp_code="123456",
        )
        Comment.objects.create(
            content=content,
            user=self.fan_user,
            text="Strong performance.",
        )

        self.client.force_login(self.fan_user)
        response = self.client.get(reverse("artist_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "artist-directory-card")
        self.assertContains(response, "artist-card-avatar")
        self.assertContains(response, "Independent performer")
        self.assertContains(response, "1 uploads")
        self.assertContains(response, "8.0")
        self.assertContains(response, "Latest upload")
        self.assertContains(response, "--gg-avatar-size: 74px")

    def test_profile_update(self):
        self.client.login(
            username=self.artist_user.username,
            password=self.artist_data["password"],
        )

        valid_image = SimpleUploadedFile(
            "profile.jpg",
            (
                b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
                b"\x00\x00\x00\xFF\xFF\xFF\x21\xF9\x04\x01\x00\x00\x01\x00"
                b"\x2C\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x4C\x01\x00\x3B"
            ),
            content_type="image/jpeg",
        )

        response = self.client.post(
            self.profile_url,
            {
                "username": self.artist_user.username,
                "email": self.artist_user.email,
                "bio": "Updated bio",
                "profile_picture": valid_image,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.artist_user.refresh_from_db()
        self.assertEqual(self.artist_user.bio, "Updated bio")

    def test_access_restrictions(self):
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 302)

        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, 302)

    def test_admin_can_manage_fan_otp_access(self):
        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )

        grant_response = self.client.post(
            reverse("admin_dashboard"),
            {
                "otp_action": "grant",
                "user_id": self.fan_user.id,
                "vote_count": 1,
            },
        )
        self.assertEqual(grant_response.status_code, 302)
        otp = OTP.objects.get(user=self.fan_user)
        self.assertTrue(otp.is_active)
        self.assertEqual(otp.remaining_votes, 1)

        extend_response = self.client.post(
            reverse("admin_dashboard"),
            {
                "otp_action": "extend",
                "user_id": self.fan_user.id,
                "vote_count": 2,
            },
        )
        self.assertEqual(extend_response.status_code, 302)
        otp.refresh_from_db()
        self.assertEqual(otp.remaining_votes, 3)

        cancel_response = self.client.post(
            reverse("admin_dashboard"),
            {
                "otp_action": "cancel",
                "user_id": self.fan_user.id,
                "vote_count": 1,
            },
        )
        self.assertEqual(cancel_response.status_code, 302)
        otp.refresh_from_db()
        self.assertFalse(otp.is_active)
        self.assertEqual(otp.remaining_votes, 0)

        reset_response = self.client.post(
            reverse("admin_dashboard"),
            {
                "otp_action": "reset",
                "user_id": self.fan_user.id,
                "vote_count": 1,
            },
        )
        self.assertEqual(reset_response.status_code, 302)
        otp.refresh_from_db()
        self.assertTrue(otp.is_active)
        self.assertEqual(otp.remaining_votes, 1)

    def test_admin_can_pause_and_resume_voting_tokens(self):
        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )

        pause_response = self.client.post(
            reverse("admin_dashboard"),
            {"token_policy_action": "pause"},
        )

        self.assertEqual(pause_response.status_code, 302)
        policy = VotingTokenPolicy.current()
        self.assertTrue(policy.tokens_paused)
        self.assertEqual(policy.updated_by, self.admin_user)

        resume_response = self.client.post(
            reverse("admin_dashboard"),
            {"token_policy_action": "resume"},
        )

        self.assertEqual(resume_response.status_code, 302)
        policy.refresh_from_db()
        self.assertFalse(policy.tokens_paused)

    def test_admin_can_set_message_retention_policy(self):
        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )

        response = self.client.post(
            reverse("admin_dashboard"),
            {
                "token_policy_action": "message_retention",
                "message_retention_hours": "36",
            },
        )

        self.assertEqual(response.status_code, 302)
        policy = VotingTokenPolicy.current()
        self.assertEqual(policy.message_retention_hours, 36)

        response = self.client.post(
            reverse("admin_dashboard"),
            {
                "token_policy_action": "message_retention",
                "message_retention_hours": "500",
            },
        )

        self.assertEqual(response.status_code, 302)
        policy.refresh_from_db()
        self.assertEqual(policy.message_retention_hours, 168)

    def test_admin_can_bulk_generate_otps_and_deliver_contact_notifications(self):
        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )

        response = self.client.post(
            reverse("admin_dashboard"),
            {
                "bulk_otp_action": "grant",
                "bulk_user_ids": [str(self.fan_user.id), str(self.artist_user.id)],
                "bulk_vote_count": "3",
            },
        )

        self.assertEqual(response.status_code, 302)
        fan_otp = OTP.objects.get(user=self.fan_user)
        artist_otp = OTP.objects.get(user=self.artist_user)
        self.assertEqual(fan_otp.remaining_votes, 3)
        self.assertEqual(artist_otp.remaining_votes, 3)
        self.assertTrue(fan_otp.is_active)
        self.assertTrue(artist_otp.is_active)

        fan_thread = AdminChatThread.objects.get(admin=self.admin_user, user=self.fan_user)
        artist_thread = AdminChatThread.objects.get(admin=self.admin_user, user=self.artist_user)
        self.assertEqual(fan_thread.user_unread_count, 1)
        self.assertEqual(artist_thread.user_unread_count, 1)
        self.assertTrue(
            Notification.objects.filter(
                user=self.fan_user,
                message__contains=fan_otp.otp_code,
            ).exists()
        )

    def test_user_contact_admin_unread_endpoint_returns_database_otp(self):
        otp = OTP.objects.create(
            user=self.fan_user,
            otp_code="987654",
            remaining_votes=2,
            is_active=True,
        )
        AdminChatThread.objects.create(
            admin=self.admin_user,
            user=self.fan_user,
            user_unread_count=2,
        )
        self.client.login(
            username=self.fan_user.username,
            password=self.fan_data["password"],
        )

        response = self.client.get(reverse("chatapp:admin_contact_unread_count"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["unread_count"], 2)
        self.assertEqual(payload["otp"]["code"], otp.otp_code)
        self.assertEqual(payload["otp"]["remaining_votes"], 2)

        mark_read_response = self.client.post(reverse("chatapp:mark_admin_contact_read"))
        self.assertEqual(mark_read_response.status_code, 200)
        thread = AdminChatThread.objects.get(admin=self.admin_user, user=self.fan_user)
        self.assertEqual(thread.user_unread_count, 0)

    def test_admin_can_suspend_and_resume_all_voting(self):
        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )

        suspend_response = self.client.post(
            reverse("admin_dashboard"),
            {"token_policy_action": "suspend_voting"},
        )

        self.assertEqual(suspend_response.status_code, 302)
        policy = VotingTokenPolicy.current()
        self.assertTrue(policy.voting_suspended)
        self.assertEqual(policy.updated_by, self.admin_user)

        resume_response = self.client.post(
            reverse("admin_dashboard"),
            {"token_policy_action": "resume_voting"},
        )

        self.assertEqual(resume_response.status_code, 302)
        policy.refresh_from_db()
        self.assertFalse(policy.voting_suspended)

    def test_admin_dashboard_can_allow_peer_chat(self):
        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )

        response = self.client.post(
            reverse("admin_dashboard"),
            {
                "peer_chat_action": "allow",
                "first_user_id": self.artist_user.id,
                "second_user_id": self.fan_user.id,
            },
        )

        self.assertEqual(response.status_code, 302)
        thread = PeerChatThread.objects.get(
            user_one=min(self.artist_user, self.fan_user, key=lambda user: user.id),
            user_two=max(self.artist_user, self.fan_user, key=lambda user: user.id),
        )
        self.assertTrue(thread.admin_approved)
        self.assertEqual(thread.approved_by, self.admin_user)

        self.client.force_login(self.artist_user)
        direct_response = self.client.get(
            reverse("chatapp:direct", args=[self.fan_user.id])
        )
        self.assertEqual(direct_response.status_code, 200)

    def test_verify_otp_redirects_when_disabled(self):
        pending_user = CustomUser.objects.create_user(
            username="pending_user",
            email="pending@example.com",
            password="pendingpass123",
            role=Role.FAN,
            is_active=False,
        )

        response = self.client.get(reverse("verify_otp", args=[pending_user.id]), follow=True)

        self.assertRedirects(response, reverse("login"))
        self.assertContains(response, "OTP is disabled. Please log in with password.")
        pending_user.refresh_from_db()
        self.assertFalse(pending_user.is_active)

    def test_resend_otp_redirects_when_disabled(self):
        pending_user = CustomUser.objects.create_user(
            username="resend_user",
            email="resend@example.com",
            password="resendpass123",
            role=Role.FAN,
            is_active=False,
        )
        otp = OTP.objects.create(user=pending_user, otp_code="111111")

        response = self.client.get(reverse("resend_otp", args=[pending_user.id]), follow=True)

        self.assertRedirects(response, reverse("login"))
        self.assertContains(response, "OTP is disabled. Please log in with password.")
        otp.refresh_from_db()
        self.assertEqual(otp.otp_code, "111111")

    def test_search_results_show_current_view_count(self):
        content = Content.objects.create(
            title="Metric Search Content",
            description="Searchable content",
            artist=self.artist_user,
            is_approved=True,
        )
        content.viewers.add(self.fan_user)

        response = self.client.get(reverse("search_results"), {"q": "Metric Search"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Metric Search Content")
        self.assertContains(response, "1 views")

    def test_admin_dashboard_content_ranking_uses_current_vote_metrics(self):
        ranked_content = Content.objects.create(
            title="Ranked Content",
            artist=self.artist_user,
            is_approved=True,
        )
        zero_vote_content = Content.objects.create(
            title="Zero Vote Content",
            artist=self.artist_user,
            is_approved=True,
        )
        extra_fan = CustomUser.objects.create_user(
            username="fan_user_two",
            email="fan2@example.com",
            password="fanpass123",
            role=Role.FAN,
        )

        Vote.objects.create(
            content=ranked_content,
            fan=self.fan_user,
            base_value=2,
            value=2,
            otp_code="111111",
            is_badge_vote=False,
        )
        Vote.objects.create(
            content=ranked_content,
            fan=extra_fan,
            base_value=3,
            value=6,
            otp_code="222222",
            is_badge_vote=True,
        )

        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )
        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        ranking = list(response.context["content_ranking"])

        self.assertEqual(ranking[0].pk, ranked_content.pk)
        self.assertEqual(ranking[0].total_points, 8)
        self.assertEqual(ranking[0].total_votes, 2)
        self.assertEqual(ranking[0].badge_votes, 1)

        zero_vote_entry = next(item for item in ranking if item.pk == zero_vote_content.pk)
        self.assertEqual(zero_vote_entry.total_points, 0)
        self.assertEqual(zero_vote_entry.total_votes, 0)
        self.assertEqual(zero_vote_entry.badge_votes, 0)

    def test_admin_dashboard_filters_recent_uploads_by_category(self):
        music_content = Content.objects.create(
            title="Music Upload",
            artist=self.artist_user,
            category="music",
            is_approved=True,
        )
        art_content = Content.objects.create(
            title="Art Upload",
            artist=self.artist_user,
            category="art",
            is_approved=True,
        )

        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )
        response = self.client.get(reverse("admin_dashboard"), {"category": "music"})

        self.assertEqual(response.status_code, 200)
        recent_upload_ids = [content.id for content in response.context["recent_uploads"]]
        self.assertIn(music_content.id, recent_upload_ids)
        self.assertNotIn(art_content.id, recent_upload_ids)

    def test_admin_dashboard_content_actions_render_standard_menu(self):
        Content.objects.create(
            title="Action Menu Upload",
            artist=self.artist_user,
            is_approved=True,
            is_approved_for_voting=True,
        )

        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )
        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "admin-content-table-wrap")
        self.assertContains(response, "admin-actions-menu")
        self.assertContains(response, "admin-actions-toggle")
        self.assertContains(response, "admin-dropdown-scroll")
        self.assertContains(response, "<details", count=1)
        self.assertContains(response, "admin-dropdown-section", count=4)
        self.assertContains(response, "admin-dropdown-action", count=8)
        self.assertNotContains(response, "dropdown-toggle admin-actions-toggle")
        self.assertContains(response, "Approve Voting")
        self.assertContains(response, "Reset Votes & Chats")

    def test_admin_dashboard_voucher_dropdown_does_not_leak_template_code(self):
        LivePerformance.objects.create(
            title="Restricted Showcase",
            artist=self.artist_user,
            start_time=timezone.now(),
            is_restricted=True,
        )

        self.client.login(
            username=self.admin_user.username,
            password=self.admin_data["password"],
        )
        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Restricted Showcase")
        self.assertContains(response, "Restricted")
        self.assertNotContains(response, "&mdash; {{")
        self.assertNotContains(response, "perf.is_restricted")


class CustomUserModelTests(TestCase):
    def test_notify_admin_without_admin_is_noop(self):
        artist = CustomUser.objects.create_user(
            username="artist_without_admin",
            password="artistpass123",
            role=Role.ARTIST,
        )

        artist.notify_admin()

        self.assertEqual(Notification.objects.count(), 0)


class AnnouncementTests(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="testuser",
            password="testpass",
            role=Role.FAN,
        )
        self.admin = CustomUser.objects.create_user(
            username="admin",
            password="adminpass",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.announcement = Announcement.objects.create(
            title="Test",
            message="Test message",
            created_by=self.admin,
        )

    def test_get_announcements(self):
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(reverse("get_announcements"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("announcements", response.json())

    def test_dismiss_announcement(self):
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(
            reverse("dismiss_announcement", args=[self.announcement.id])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            DismissedAnnouncement.objects.filter(
                user=self.user,
                announcement=self.announcement,
            ).exists()
        )
