from django.test import TestCase
from django.urls import reverse

from users.models import CustomUser, Role

from .models import LiveStream, LiveStreamAccess


class LiveStreamTests(TestCase):
    def setUp(self):
        self.artist = CustomUser.objects.create_user(
            username="live_artist_app",
            password="password123",
            role=Role.ARTIST,
        )
        self.fan = CustomUser.objects.create_user(
            username="live_fan_app",
            password="password123",
            role=Role.FAN,
        )

    def test_artist_can_create_stream(self):
        self.client.login(username="live_artist_app", password="password123")
        response = self.client.post(
            reverse("livestream:create"),
            {
                "title": "Local Live",
                "description": "No third party",
                "is_restricted": "",
                "allow_free_access": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        stream = LiveStream.objects.get(title="Local Live")
        self.assertEqual(stream.host, self.artist)
        self.assertTrue(stream.stream_key)

    def test_restricted_stream_requires_access(self):
        stream = LiveStream.objects.create(
            title="Restricted",
            host=self.artist,
            status=LiveStream.STATUS_LIVE,
            is_restricted=True,
        )

        self.assertFalse(stream.can_join(self.fan))
        LiveStreamAccess.objects.create(stream=stream, user=self.fan, granted_by=self.artist)
        self.assertTrue(stream.can_join(self.fan))

    def test_host_can_start_and_end_stream(self):
        stream = LiveStream.objects.create(title="Lifecycle", host=self.artist)
        self.client.login(username="live_artist_app", password="password123")

        start_response = self.client.post(reverse("livestream:start", args=[stream.stream_key]))
        stream.refresh_from_db()
        self.assertEqual(start_response.status_code, 302)
        self.assertEqual(stream.status, LiveStream.STATUS_LIVE)

        end_response = self.client.post(reverse("livestream:end", args=[stream.stream_key]))
        stream.refresh_from_db()
        self.assertEqual(end_response.status_code, 302)
        self.assertEqual(stream.status, LiveStream.STATUS_ENDED)
