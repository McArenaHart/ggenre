import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from content.models import ArtistUploadLimit, Content
from users.models import CustomUser, Role
from .models import ExportAllowance, VideoCollaboration
from .storage import private_storage
from .tests import wav_upload
from .video_render import extract_audio, inspect_video, render_video, run_ffmpeg


class CollaborationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.original = CustomUser.objects.create_user(username="original_voice", role=Role.ARTIST)
        cls.artist = CustomUser.objects.create_user(username="joining_voice", role=Role.ARTIST)
        cls.fan = CustomUser.objects.create_user(username="listener", role=Role.FAN)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        storage = patch.object(private_storage, "location", self.directory.name)
        storage.start()
        self.addCleanup(storage.stop)
        # The source is a private rendered post, avoiding writes into real media storage.
        parent = VideoCollaboration.objects.create(creator=self.original, source_title="Original", status="published", credits=[{"artist_id": self.original.pk, "username": self.original.username, "role": "Original video"}])
        parent.video.save("source.mp4", SimpleUploadedFile("source.mp4", b"test-video-bytes"))
        self.source = Content.objects.create(artist=self.original, title="Original song", category="video", is_approved=True, allow_collaboration=True)
        parent.content = self.source
        parent.save()
        self.client.force_login(self.artist)
        self.url = reverse("studio:collaborate", args=[self.source.pk])

    def render(self, request_id=None):
        def fake_render(source, vocal, output, *args):
            Path(output).write_bytes(b"combined-mp4")
        with patch("studio.collaborations.render_video", side_effect=fake_render):
            return self.client.post(self.url, {"audio": wav_upload(), "request_id": request_id or uuid.uuid4(), "role": "Bass"})

    def test_opt_in_approval_artist_and_owner_permissions(self):
        self.assertContains(self.client.get(self.url), "Add your voice")
        self.source.allow_collaboration = False
        self.source.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        permission = reverse("studio:collaboration_permission", args=[self.source.pk])
        self.assertEqual(self.client.post(permission, {"allow": "yes"}).status_code, 404)
        self.client.force_login(self.original)
        self.assertEqual(self.client.post(permission, {"allow": "yes"}).status_code, 302)
        self.source.refresh_from_db()
        self.assertTrue(self.source.allow_collaboration)
        self.source.is_approved = False
        self.source.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.force_login(self.fan)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(permission, {"allow": "yes"}).status_code, 403)

    def test_private_preview_publication_credits_and_idempotency(self):
        request_id = uuid.uuid4()
        response = self.render(request_id)
        self.assertEqual(response.status_code, 200)
        item = VideoCollaboration.objects.get(pk=request_id)
        self.assertEqual(item.credits[-1]["username"], self.artist.username)
        self.assertEqual(item.credits[0]["username"], self.original.username)
        self.assertEqual(self.render(request_id).status_code, 200)
        self.assertEqual(VideoCollaboration.objects.filter(creator=self.artist).count(), 1)
        playback = response.json()["preview"]
        stream = self.client.get(playback, HTTP_RANGE="bytes=0-3")
        self.assertEqual(stream.status_code, 206)
        self.assertEqual(b"".join(stream.streaming_content), b"comb")
        stream.close()
        self.client.force_login(self.fan)
        self.assertEqual(self.client.get(playback).status_code, 404)
        self.client.force_login(self.artist)
        publish = response.json()["publish"]
        quota = ArtistUploadLimit.objects.create(artist=self.artist, upload_limit=2)
        self.client.post(publish, {"title": "Our song", "allow_collaboration": "on"})
        item.refresh_from_db()
        self.assertFalse(item.content.is_approved)
        self.assertTrue(item.content.allow_collaboration)
        self.assertEqual(item.content.safe_file_url, playback)
        self.assertTrue(item.content.is_video_file)
        self.client.post(publish, {"title": "Duplicate"})
        quota.refresh_from_db()
        self.assertEqual(quota.uploads_used, 1)
        self.assertFalse(ExportAllowance.objects.filter(artist=self.artist).exists())
        self.client.force_login(self.fan)
        self.assertEqual(self.client.get(playback).status_code, 404)
        item.content.is_approved = True
        item.content.save()
        stream = self.client.get(playback)
        self.assertEqual(stream.status_code, 200)
        stream.close()
        item.content.is_visible = False
        item.content.save()
        self.assertEqual(self.client.get(playback).status_code, 404)

    def test_quota_source_revocation_and_owner_isolation(self):
        response = self.render()
        publish = response.json()["publish"]
        ArtistUploadLimit.objects.create(artist=self.artist, suspended_by_admin=True)
        self.client.post(publish, {"title": "Blocked"})
        item = VideoCollaboration.objects.get(creator=self.artist)
        self.assertIsNone(item.content)
        self.source.allow_collaboration = False
        self.source.save()
        self.assertEqual(self.client.post(publish, {"title": "Closed"}).status_code, 404)
        self.client.force_login(self.original)
        self.assertEqual(self.client.post(publish, {"title": "Wrong owner"}).status_code, 404)

    def test_reject_invalid_audio_processing_overlap_and_ranges(self):
        self.assertEqual(self.client.post(self.url, {"request_id": "bad"}).status_code, 400)
        VideoCollaboration.objects.create(creator=self.artist, source=self.source, source_title="Pending")
        self.assertEqual(self.render().status_code, 409)
        parent = self.source.video_collaboration
        response = self.client.get(reverse("studio:collaboration_source", args=[self.source.pk]), HTTP_RANGE="bytes=9999-")
        self.assertEqual(response.status_code, 416)
        csrf = Client(enforce_csrf_checks=True)
        csrf.force_login(self.artist)
        self.assertEqual(csrf.post(self.url, {}).status_code, 403)

    def test_render_failure_retains_failed_state_without_public_post(self):
        with patch("studio.collaborations.render_video", side_effect=ValidationError("Invalid video")):
            response = self.client.post(self.url, {"audio": wav_upload(), "request_id": uuid.uuid4()})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(VideoCollaboration.objects.get(creator=self.artist).status, "failed")
        self.assertEqual(Content.objects.count(), 1)

    def test_real_ffmpeg_composes_playable_mp4_and_keeps_source(self):
        directory = Path(self.directory.name)
        source, vocal, output = directory / "source.mp4", directory / "voice.wav", directory / "out.mp4"
        run_ffmpeg(["-f", "lavfi", "-i", "color=c=blue:s=160x120:d=1", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source)])
        run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=660:duration=1", "-ac", "1", "-ar", "44100", str(vocal)])
        original = source.read_bytes()
        render_video(source, vocal, output, .8, .6, -50)
        self.assertGreater(output.stat().st_size, 1000)
        self.assertAlmostEqual(inspect_video(output), 1, delta=.1)
        self.assertEqual(source.read_bytes(), original)
        import math, struct, wave
        mixed_audio = directory / "mixed.wav"
        extract_audio(output, mixed_audio)
        with wave.open(str(mixed_audio), "rb") as pcm:
            rate = pcm.getframerate()
            data = pcm.readframes(pcm.getnframes())
            samples = struct.unpack("<" + "h" * (len(data)//2), data)
        section = samples[int(rate*.2):int(rate*.8)]
        for frequency in (440, 660):
            energy = abs(sum(value*complex(math.cos(2*math.pi*frequency*i/rate), math.sin(2*math.pi*frequency*i/rate)) for i,value in enumerate(section)))/len(section)/32768
            self.assertGreater(energy, .015, f"Missing {frequency} Hz contribution")
        with self.assertRaises(ValidationError):
            render_video(source, vocal, output, float("nan"))


    def test_collaboration_chain_and_saved_library_preserve_credits(self):
        response = self.render()
        self.client.post(response.json()["publish"], {"title": "Second voice", "allow_collaboration": "on"})
        first = VideoCollaboration.objects.get(creator=self.artist)
        first.content.is_approved = True
        first.content.save()
        self.assertContains(self.client.get(reverse("content_detail", args=[self.source.pk])), "This song is growing")
        self.assertContains(self.client.get(reverse("studio:collaboration_library")), "Second voice")
        self.client.force_login(self.original)
        self.url = reverse("studio:collaborate", args=[first.content_id])
        response = self.render()
        self.assertEqual(response.status_code, 200)
        newest = VideoCollaboration.objects.filter(creator=self.original, source=first.content).get()
        self.assertEqual([credit["username"] for credit in newest.credits], [self.original.username, self.artist.username, self.original.username])
        self.client.force_login(self.fan)
        self.assertEqual(self.client.get(reverse("studio:collaboration_library")).status_code, 403)

    def test_saved_preview_is_retained_when_source_closes(self):
        response = self.render()
        self.source.allow_collaboration = False
        self.source.save()
        self.assertContains(self.client.get(reverse("studio:collaboration_library")), "private preview is retained")
        stream = self.client.get(response.json()["preview"])
        self.assertEqual(stream.status_code, 200)
        stream.close()


    def test_upload_collaboration_opt_in_is_explicit_and_mp4_only(self):
        from content.forms import ContentUploadForm
        video = SimpleUploadedFile("song.mp4", b"test-video", content_type="video/mp4")
        form = ContentUploadForm({"title": "Song", "tags": "acapella", "allow_collaboration": "on"}, {"file": video})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertTrue(form.cleaned_data["allow_collaboration"])
        audio = SimpleUploadedFile("song.mp3", b"audio", content_type="audio/mpeg")
        form = ContentUploadForm({"title": "Song", "tags": "acapella", "allow_collaboration": "on"}, {"file": audio})
        self.assertFalse(form.is_valid())
        form = ContentUploadForm({"title": "External", "tags": "acapella", "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "allow_collaboration": "on"})
        self.assertFalse(form.is_valid())


    def test_approved_collaboration_shares_main_feed_with_normal_uploads(self):
        response = self.render()
        self.client.post(response.json()["publish"], {"title": "Feed harmony collaboration", "allow_collaboration": "on"})
        item = VideoCollaboration.objects.get(creator=self.artist)
        ordinary = Content.objects.create(artist=self.original, title="Ordinary uploaded video", file="content/ordinary-test.mp4", category="video", is_approved=True)
        feed_url = reverse("content_list")
        self.assertNotContains(self.client.get(feed_url), "Feed harmony collaboration")
        item.content.is_approved = True
        item.content.save()
        response = self.client.get(feed_url)
        ids = [content.pk for content in response.context["featured_contents"]]
        self.assertIn(ordinary.pk, ids)
        self.assertIn(item.content_id, ids)
        self.assertContains(response, "Feed harmony collaboration")
        self.assertContains(response, "Ordinary uploaded video")
        self.assertContains(response, "Vocal collaboration")
        self.assertContains(response, reverse("studio:collaborate", args=[item.content_id]))
        self.assertContains(response, item.content.safe_file_url)
        item.content.is_visible = False
        item.content.save()
        self.assertNotContains(self.client.get(feed_url), "Feed harmony collaboration")

    def test_mobile_pages_include_responsive_styles_and_normal_post_controls(self):
        self.assertContains(self.client.get(reverse("studio:collaboration_library")), "studio-collaboration.css")
        self.assertContains(self.client.get(self.url), 'name="viewport"')
        self.assertContains(self.client.get(self.url), 'id="collab-cancel"')
        self.assertContains(self.client.get(reverse("content_list")), 'class="welcome-collaboration-actions"')


    def test_reference_audio_cache_reuses_bytes_but_rechecks_access(self):
        from django.test import override_settings
        cache = Path(self.directory.name) / "guides"
        audio = wav_upload().read()
        def extract(video, output):
            Path(output).write_bytes(audio)
        url = reverse("studio:collaboration_audio", args=[self.source.pk])
        with override_settings(STUDIO_GUIDE_CACHE_DIR=cache), patch("studio.guide_cache.extract_audio", side_effect=extract) as encoder:
            for _ in range(2):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(b"".join(response.streaming_content), audio)
                response.close()
            self.assertEqual(encoder.call_count, 1)
            self.source.allow_collaboration = False
            self.source.save()
            self.assertEqual(self.client.get(url).status_code, 404)
            self.assertEqual(encoder.call_count, 1)

    def test_reference_cache_invalidates_changed_source_and_falls_back_if_unwritable(self):
        from django.test import override_settings
        cache = Path(self.directory.name) / "guides"
        audio = wav_upload().read()
        url = reverse("studio:collaboration_audio", args=[self.source.pk])
        with override_settings(STUDIO_GUIDE_CACHE_DIR=cache), patch("studio.guide_cache.extract_audio", side_effect=lambda video, output: Path(output).write_bytes(audio)) as encoder:
            response = self.client.get(url)
            response.close()
            field = self.source.video_collaboration.video
            Path(field.path).write_bytes(b"new-source-video-bytes")
            response = self.client.get(url)
            response.close()
            self.assertEqual(encoder.call_count, 2)
        blocked = Path(self.directory.name) / "not-a-directory"
        blocked.write_text("test", encoding="utf-8")
        with override_settings(STUDIO_GUIDE_CACHE_DIR=blocked), patch("studio.guide_cache.extract_audio", side_effect=lambda video, output: Path(output).write_bytes(audio)):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b"".join(response.streaming_content), audio)
            response.close()
