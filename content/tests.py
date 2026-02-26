from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from users.models import OTP, Role, CustomUser

from .forms import ContentUploadForm
from .models import ArtistUploadLimit, Content, Genre, LivePerformance, Vote, Voucher


def sample_upload_file(filename="test.mp4", content_type="video/mp4"):
    return SimpleUploadedFile(filename, b"fake-video-content", content_type=content_type)


class ContentModelTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="artist1",
            password="password",
            role=Role.ARTIST,
        )
        self.content = Content.objects.create(
            title="Test Content",
            description="Test",
            artist=self.user,
            file=sample_upload_file(),
            is_approved=True,
        )
        self.content.tags.add("test")

    def test_content_creation(self):
        self.assertEqual(self.content.title, "Test Content")
        self.assertEqual(self.content.artist.username, "artist1")

    def test_upload_limit(self):
        upload_limit = ArtistUploadLimit.objects.create(
            artist=self.user,
            uploads_used=0,
            upload_limit=5,
        )
        self.assertTrue(upload_limit.has_upload_quota())


class ContentViewTest(TestCase):
    def setUp(self):
        self.user = CustomUser.objects.create_user(
            username="artist1",
            password="password",
            role=Role.ARTIST,
        )
        self.content = Content.objects.create(
            title="Test Content",
            description="Test",
            artist=self.user,
            file=sample_upload_file(),
            is_approved=True,
        )
        self.content.tags.add("test")
        self.client.login(username="artist1", password="password")

    def test_upload_content_view(self):
        response = self.client.get(reverse("upload_content"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "content/upload.html")

    def test_list_content_view(self):
        response = self.client.get(reverse("content_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Content")


class ContentFormTest(TestCase):
    def test_valid_form(self):
        form = ContentUploadForm(
            data={
                "title": "Test Content",
                "description": "Test Description",
                "tags": "test,tag",
            },
            files={"file": sample_upload_file()},
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_invalid_form(self):
        form = ContentUploadForm(
            data={
                "title": "",
                "description": "Test Description",
                "tags": "test,tag",
            },
            files={"file": sample_upload_file()},
        )
        self.assertFalse(form.is_valid())
        self.assertIn("title", form.errors)

    def test_valid_form_with_youtube_link(self):
        form = ContentUploadForm(
            data={
                "title": "YouTube Content",
                "description": "Embedded video",
                "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "tags": "music,video",
            }
        )
        self.assertTrue(form.is_valid(), form.errors.as_json())

    def test_invalid_form_with_file_and_youtube_link(self):
        form = ContentUploadForm(
            data={
                "title": "Mixed source",
                "description": "Should fail",
                "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "tags": "test",
            },
            files={"file": sample_upload_file()},
        )
        self.assertFalse(form.is_valid())


class YouTubeEmbedModelTest(TestCase):
    def test_extracts_embed_url_from_watch_link(self):
        user = CustomUser.objects.create_user(
            username="artist_embed",
            password="password",
            role=Role.ARTIST,
        )
        content = Content.objects.create(
            title="Embedded",
            artist=user,
            youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            is_approved=True,
        )
        self.assertEqual(
            content.youtube_embed_url,
            "https://www.youtube.com/embed/dQw4w9WgXcQ",
        )


class AuthenticationTest(TestCase):
    def setUp(self):
        self.artist_user = CustomUser.objects.create_user(
            username="artist1",
            password="password",
            role=Role.ARTIST,
        )
        self.fan_user = CustomUser.objects.create_user(
            username="fan1",
            password="password",
            role=Role.FAN,
        )

    def test_redirects_if_not_logged_in(self):
        response = self.client.get(reverse("upload_content"))
        self.assertRedirects(response, "/users/login/?next=/content/upload/")

    def test_upload_content_permission_for_artist(self):
        self.client.login(username="artist1", password="password")
        response = self.client.get(reverse("upload_content"))
        self.assertEqual(response.status_code, 200)

    def test_upload_content_redirects_for_fan(self):
        self.client.login(username="fan1", password="password")
        response = self.client.get(reverse("upload_content"))
        self.assertEqual(response.status_code, 302)


class AudioThumbnailFallbackTest(TestCase):
    def setUp(self):
        self.artist = CustomUser.objects.create_user(
            username="audio_artist",
            password="password",
            role=Role.ARTIST,
        )

    def test_audio_content_uses_default_thumbnail_when_missing(self):
        content = Content.objects.create(
            title="Audio Track",
            artist=self.artist,
            file=sample_upload_file(filename="track.mp3", content_type="audio/mpeg"),
            is_approved=True,
        )

        self.assertTrue(content.is_audio_file)
        self.assertIsNone(content.safe_thumbnail_url)
        self.assertIn("img/audio-default-thumbnail.svg", content.audio_thumbnail_url)

    def test_audio_default_thumbnail_renders_in_content_list(self):
        Content.objects.create(
            title="Audio Card",
            artist=self.artist,
            file=sample_upload_file(filename="card.mp3", content_type="audio/mpeg"),
            is_approved=True,
        )

        response = self.client.get(reverse("content_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "img/audio-default-thumbnail.svg")


class ContentUploadFlowTest(TestCase):
    def setUp(self):
        self.artist = CustomUser.objects.create_user(
            username="upload_artist",
            password="password",
            role=Role.ARTIST,
        )
        self.genre = Genre.objects.create(name="Test Genre")
        self.limit = ArtistUploadLimit.objects.create(
            artist=self.artist,
            uploads_used=0,
            upload_limit=3,
        )

    def test_artist_upload_increments_usage_and_creates_content(self):
        self.client.login(username="upload_artist", password="password")
        response = self.client.post(
            reverse("upload_content"),
            data={
                "title": "Fresh Upload",
                "description": "Upload flow check",
                "genre": self.genre.id,
                "tags": "test,upload",
                "file": sample_upload_file(filename="fresh.mp4", content_type="video/mp4"),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Content.objects.filter(title="Fresh Upload", artist=self.artist).exists())
        self.limit.refresh_from_db()
        self.assertEqual(self.limit.uploads_used, 1)


class VotingFlowTest(TestCase):
    def setUp(self):
        self.artist = CustomUser.objects.create_user(
            username="vote_artist",
            password="password",
            role=Role.ARTIST,
        )
        self.fan = CustomUser.objects.create_user(
            username="vote_fan",
            password="password",
            role=Role.FAN,
        )
        self.genre = Genre.objects.create(name="Voting Genre")
        self.content = Content.objects.create(
            title="Vote Target",
            artist=self.artist,
            genre=self.genre,
            file=sample_upload_file(filename="target.mp4", content_type="video/mp4"),
            is_approved=True,
        )
        self.otp = OTP.objects.create(
            user=self.fan,
            otp_code="123456",
            remaining_votes=1,
            is_active=True,
        )
        self.client.login(username="vote_fan", password="password")

    def test_vote_consumes_otp_and_persists_vote(self):
        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "otp_code": "123456", "voter_tag": "smoke"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.remaining_votes, 0)
        vote = Vote.objects.get(content=self.content, fan=self.fan)
        self.assertEqual(vote.base_value, 4)

    def test_vote_rejected_when_otp_has_no_remaining_votes(self):
        self.otp.remaining_votes = 0
        self.otp.save(update_fields=["remaining_votes"])

        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "otp_code": "123456"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Vote.objects.filter(content=self.content, fan=self.fan).exists())


class LiveStreamVoucherFlowTest(TestCase):
    def setUp(self):
        self.artist = CustomUser.objects.create_user(
            username="live_artist",
            password="password",
            role=Role.ARTIST,
        )
        self.fan = CustomUser.objects.create_user(
            username="live_fan",
            password="password",
            role=Role.FAN,
        )

    def test_artist_can_start_restricted_stream_and_fan_needs_voucher(self):
        self.client.login(username="live_artist", password="password")
        start_response = self.client.post(
            reverse("start_live_stream"),
            data={
                "title": "Restricted Live",
                "restrict_access": "on",
            },
        )
        self.assertEqual(start_response.status_code, 302)

        performance = LivePerformance.objects.get(title="Restricted Live")
        self.assertTrue(performance.is_restricted)
        self.client.logout()

        self.client.login(username="live_fan", password="password")
        room_response = self.client.get(reverse("live_stream_room", args=[performance.stream_key]))
        self.assertEqual(room_response.status_code, 302)
        self.assertIn(reverse("voucher_entry", args=[performance.stream_key]), room_response.url)

        voucher = Voucher.objects.create(code="654321", performance=performance, created_by=self.artist)
        room_with_voucher = self.client.get(
            f"{reverse('live_stream_room', args=[performance.stream_key])}?voucher={voucher.code}"
        )
        self.assertEqual(room_with_voucher.status_code, 200)
        voucher.refresh_from_db()
        self.assertTrue(voucher.is_used)
        self.assertEqual(voucher.used_by, self.fan)
