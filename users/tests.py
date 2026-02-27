from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .models import Announcement, DismissedAnnouncement, OTP, Role

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
