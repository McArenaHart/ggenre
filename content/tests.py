from datetime import timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from chatapp.models import MatchRating, PeerChatThread
from users.models import Follow, OTP, Role, CustomUser, VotingTokenPolicy

from .forms import ContentUploadForm
from .models import ArtistUploadLimit, Badge, Comment, Content, Genre, LivePerformance, Vote, Voucher


def sample_upload_file(filename="test.mp4", content_type="video/mp4"):
    return SimpleUploadedFile(filename, b"fake-video-content", content_type=content_type)


def sample_image_file(filename="poster.gif", content_type="image/gif"):
    return SimpleUploadedFile(
        filename,
        (
            b"\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00"
            b"\x00\x00\x00\xFF\xFF\xFF\x21\xF9\x04\x01\x00\x00\x01\x00"
            b"\x2C\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02\x4C\x01\x00\x3B"
        ),
        content_type=content_type,
    )


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
        self.assertEqual(self.content.category, "other")

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

    def test_content_detail_tracks_unique_view_on_page_load(self):
        detail_url = reverse("content_detail", args=[self.content.id])

        first_response = self.client.get(detail_url)
        second_response = self.client.get(detail_url)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(self.content.viewers.count(), 1)

        second_viewer = CustomUser.objects.create_user(
            username="fan_viewer",
            password="password",
            role=Role.FAN,
        )
        self.client.logout()
        self.client.login(username="fan_viewer", password="password")
        self.client.get(detail_url)

        self.assertEqual(self.content.viewers.count(), 2)

    def test_content_detail_up_next_prioritizes_same_creator_then_related_creators(self):
        shared_genre = Genre.objects.create(name="Afro Fusion")
        self.content.genre = shared_genre
        self.content.save(update_fields=["genre"])
        self.content.tags.add("featured", "live")

        same_artist_newer = Content.objects.create(
            title="Same Creator One",
            artist=self.user,
            genre=shared_genre,
            file=sample_upload_file(filename="same_creator_1.mp4"),
            is_approved=True,
        )
        same_artist_newer.tags.add("featured")

        same_artist_older = Content.objects.create(
            title="Same Creator Two",
            artist=self.user,
            genre=shared_genre,
            file=sample_upload_file(filename="same_creator_2.mp4"),
            is_approved=True,
        )
        same_artist_older.tags.add("featured")

        related_artist = CustomUser.objects.create_user(
            username="related_artist",
            password="password",
            role=Role.ARTIST,
        )
        related_by_genre = Content.objects.create(
            title="Related Genre Match",
            artist=related_artist,
            genre=shared_genre,
            file=sample_upload_file(filename="related_genre.mp4"),
            is_approved=True,
        )

        tag_artist = CustomUser.objects.create_user(
            username="tag_artist",
            password="password",
            role=Role.ARTIST,
        )
        related_by_tag = Content.objects.create(
            title="Related Tag Match",
            artist=tag_artist,
            file=sample_upload_file(filename="related_tag.mp4"),
            is_approved=True,
        )
        related_by_tag.tags.add("live")

        unrelated_artist = CustomUser.objects.create_user(
            username="unrelated_artist",
            password="password",
            role=Role.ARTIST,
        )
        Content.objects.create(
            title="Unrelated Fallback",
            artist=unrelated_artist,
            file=sample_upload_file(filename="unrelated.mp4"),
            is_approved=True,
        )

        response = self.client.get(reverse("content_detail", args=[self.content.id]))

        self.assertEqual(response.status_code, 200)
        related_ids = [item.id for item in response.context["related_contents"]]
        self.assertEqual(
            related_ids,
            [same_artist_older.id, same_artist_newer.id, related_by_genre.id, related_by_tag.id],
        )

    def test_content_detail_up_next_falls_back_when_same_creator_and_related_are_insufficient(self):
        fallback_artist = CustomUser.objects.create_user(
            username="fallback_artist",
            password="password",
            role=Role.ARTIST,
        )
        fallback_content = Content.objects.create(
            title="Fallback Suggestion",
            artist=fallback_artist,
            file=sample_upload_file(filename="fallback.mp4"),
            is_approved=True,
        )

        response = self.client.get(reverse("content_detail", args=[self.content.id]))

        self.assertEqual(response.status_code, 200)
        related_ids = [item.id for item in response.context["related_contents"]]
        self.assertIn(fallback_content.id, related_ids)

    def test_content_detail_up_next_prioritizes_viewer_follow_signals(self):
        followed_artist = CustomUser.objects.create_user(
            username="followed_artist",
            password="password",
            role=Role.ARTIST,
        )
        followed_content = Content.objects.create(
            title="Followed Artist Pick",
            artist=followed_artist,
            file=sample_upload_file(filename="followed.mp4"),
            is_approved=True,
        )
        same_creator_content = Content.objects.create(
            title="Same Creator Pick",
            artist=self.user,
            file=sample_upload_file(filename="same_creator_pick.mp4"),
            is_approved=True,
        )
        fan = CustomUser.objects.create_user(
            username="personalized_fan",
            password="password",
            role=Role.FAN,
        )
        Follow.objects.create(follower=fan, following=followed_artist)

        self.client.logout()
        self.client.login(username="personalized_fan", password="password")
        response = self.client.get(reverse("content_detail", args=[self.content.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["up_next_personalized"][0].id, followed_content.id)
        self.assertEqual(response.context["related_contents"][0].id, followed_content.id)
        self.assertIn(same_creator_content, response.context["up_next_same_creator"])

    def test_increment_views_endpoint_tracks_unique_authenticated_viewers(self):
        increment_url = reverse("increment_views", args=[self.content.id])

        first_response = self.client.post(increment_url)
        second_response = self.client.post(increment_url)

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(first_response.json()["new_viewers"], 1)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(second_response.json()["new_viewers"], 1)
        self.assertEqual(self.content.viewers.count(), 1)

    def test_home_view_shows_up_to_fifty_featured_items(self):
        base_time = timezone.now()
        latest_content_pk = None

        for index in range(55):
            content = Content.objects.create(
                title=f"Featured Content {index}",
                description="Test",
                artist=self.user,
                file=sample_upload_file(filename=f"featured_{index}.mp4"),
                is_approved=True,
            )
            Content.objects.filter(pk=content.pk).update(
                upload_date=base_time + timedelta(minutes=index)
            )
            if index == 54:
                latest_content_pk = content.pk

        hidden_content = Content.objects.create(
            title="Hidden Content",
            description="Test",
            artist=self.user,
            file=sample_upload_file(filename="hidden.mp4"),
            is_approved=False,
        )
        Content.objects.filter(pk=hidden_content.pk).update(
            upload_date=base_time + timedelta(minutes=56)
        )

        response = self.client.get(reverse("home"))
        featured_contents = response.context["featured_contents"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(featured_contents), 50)
        self.assertEqual(featured_contents[0].pk, latest_content_pk)
        self.assertNotIn(hidden_content, featured_contents)


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

    def test_reset_upload_limit_requires_admin_role(self):
        upload_limit = ArtistUploadLimit.objects.create(
            artist=self.artist_user,
            uploads_used=2,
            upload_limit=5,
        )

        self.client.login(username="fan1", password="password")
        response = self.client.get(reverse("reset_upload_limit", args=[self.artist_user.id]))

        self.assertEqual(response.status_code, 302)
        upload_limit.refresh_from_db()
        self.assertEqual(upload_limit.uploads_used, 2)


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


class MediaDisplayTemplateTest(TestCase):
    def setUp(self):
        self.artist = CustomUser.objects.create_user(
            username="media_artist",
            password="password",
            role=Role.ARTIST,
        )

    def test_uploaded_video_renders_native_controls_with_thumbnail_as_poster(self):
        content = Content.objects.create(
            title="Controlled Video",
            artist=self.artist,
            file=sample_upload_file(filename="clip.mp4", content_type="video/mp4"),
            thumbnail=sample_image_file(),
            is_approved=True,
        )

        html = render_to_string("partials/media_display.html", {"content": content})

        self.assertIn("<video", html)
        self.assertIn("controls", html)
        self.assertIn('controlsList="nodownload"', html)
        self.assertIn("disablePictureInPicture", html)
        self.assertIn('oncontextmenu="return false"', html)
        self.assertIn("poster=", html)
        self.assertIn("<source", html)

    def test_uploaded_audio_renders_native_controls(self):
        content = Content.objects.create(
            title="Controlled Audio",
            artist=self.artist,
            file=sample_upload_file(filename="track.mp3", content_type="audio/mpeg"),
            is_approved=True,
        )

        html = render_to_string("partials/media_display.html", {"content": content})

        self.assertIn("<audio", html)
        self.assertIn("controls", html)
        self.assertIn('controlsList="nodownload"', html)
        self.assertIn('oncontextmenu="return false"', html)
        self.assertIn("<source", html)


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
            is_approved_for_voting=True,
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
        self.assertTrue(Badge.objects.filter(user=self.fan).exists())

    def test_content_rating_accepts_ten_and_records_match_rating(self):
        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 10, "otp_code": "123456", "voter_tag": "top"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        vote = Vote.objects.get(content=self.content, fan=self.fan)
        self.assertEqual(vote.base_value, 10)
        self.assertEqual(response.json()["chat_url"], reverse("chatapp:direct", args=[self.artist.id]))
        self.assertEqual(response.json()["inbox_url"], reverse("chatapp:index"))
        self.assertTrue(
            MatchRating.objects.filter(
                rater=self.fan,
                rated=self.artist,
                score=10,
                source_content=self.content,
            ).exists()
        )
        thread = PeerChatThread.objects.get()
        self.assertGreater(thread.unlocked_until, timezone.now())

        inbox_response = self.client.get(reverse("chatapp:index"))
        self.assertEqual(inbox_response.status_code, 200)
        self.assertContains(inbox_response, self.artist.username)

    def test_content_detail_renders_click_ready_vote_controls(self):
        response = self.client.get(reverse("content_detail", args=[self.content.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'watch-action-row has-vote')
        self.assertContains(response, 'watch-action-buttons')
        self.assertContains(response, 'data-vote-toggle')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, 'data-vote-submit', count=10)
        self.assertNotContains(response, 'onclick="submitDetailVote')
        self.assertNotContains(response, 'onclick="toggleDetailVoting')

    def test_old_vote_can_be_recast_for_same_content_after_one_day(self):
        old_vote = Vote.objects.create(
            content=self.content,
            fan=self.fan,
            base_value=8,
            value=8,
            otp_code="OLD",
            tag="old",
        )
        Vote.objects.filter(pk=old_vote.pk).update(
            timestamp=timezone.now() - timedelta(days=1, minutes=1)
        )

        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 8, "otp_code": "123456", "voter_tag": "new"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        vote = Vote.objects.get(content=self.content, fan=self.fan)
        self.assertEqual(vote.base_value, 8)
        self.assertEqual(vote.tag, "new")
        self.assertGreater(vote.timestamp, timezone.now() - timedelta(minutes=1))

    def test_admin_reset_content_voting_clears_vote_and_temporary_chat(self):
        self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 9, "otp_code": "123456", "voter_tag": "reset"}',
            content_type="application/json",
        )
        self.assertTrue(Vote.objects.filter(content=self.content, fan=self.fan).exists())
        self.assertTrue(MatchRating.objects.filter(source_content=self.content).exists())
        self.assertTrue(PeerChatThread.objects.exists())

        admin = CustomUser.objects.create_user(
            username="vote_admin",
            password="password",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("toggle_content_voting", args=[self.content.id, "reset"])
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Vote.objects.filter(content=self.content).exists())
        self.assertFalse(MatchRating.objects.filter(source_content=self.content).exists())
        self.assertFalse(PeerChatThread.objects.exists())

    def test_calculate_final_ranking_does_not_auto_assign_badge(self):
        from content.views import calculate_final_ranking

        Vote.objects.create(
            content=self.content,
            fan=self.fan,
            base_value=1,
            value=1,
            otp_code="999999",
        )

        ranking = calculate_final_ranking()

        self.assertTrue(ranking.exists())
        self.assertFalse(Badge.objects.filter(user=self.fan).exists())

    def test_vote_rejected_when_otp_has_no_remaining_votes(self):
        self.otp.remaining_votes = 0
        self.otp.save(update_fields=["remaining_votes"])

        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "otp_code": "123456", "voter_tag": "blocked"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Vote.objects.filter(content=self.content, fan=self.fan).exists())

    def test_vote_rejected_without_voter_tag(self):
        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "otp_code": "123456"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.remaining_votes, 1)
        self.assertFalse(Vote.objects.filter(content=self.content, fan=self.fan).exists())

    def test_malformed_vote_payload_returns_400(self):
        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": ',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.remaining_votes, 1)
        self.assertFalse(Vote.objects.filter(content=self.content, fan=self.fan).exists())

    def test_vote_accepts_standard_form_post(self):
        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data={
                "vote_value": "4",
                "otp_code": "123456",
                "voter_tag": "form",
            },
        )

        self.assertEqual(response.status_code, 200)
        vote = Vote.objects.get(content=self.content, fan=self.fan)
        self.assertEqual(vote.base_value, 4)
        self.assertEqual(vote.tag, "form")

    def test_vote_without_otp_when_tokens_are_paused(self):
        policy = VotingTokenPolicy.current()
        policy.tokens_paused = True
        policy.save(update_fields=["tokens_paused", "updated_at"])

        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "voter_tag": "free"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.remaining_votes, 1)
        vote = Vote.objects.get(content=self.content, fan=self.fan)
        self.assertEqual(vote.base_value, 4)
        self.assertEqual(vote.otp_code, "FREE")

    def test_vote_rejected_when_admin_suspends_all_voting(self):
        policy = VotingTokenPolicy.current()
        policy.voting_suspended = True
        policy.save(update_fields=["voting_suspended", "updated_at"])

        detail_response = self.client.get(reverse("content_detail", args=[self.content.id]))
        vote_response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "otp_code": "123456", "voter_tag": "suspended"}',
            content_type="application/json",
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, 'watch-action-row no-vote')
        self.assertNotContains(detail_response, 'data-vote-toggle')
        self.assertEqual(vote_response.status_code, 200)
        self.assertEqual(vote_response.json()["message"], "Voting is suspended by admin")
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.remaining_votes, 1)
        self.assertFalse(Vote.objects.filter(content=self.content, fan=self.fan).exists())

    def test_global_voting_suspension_overrides_paused_tokens_and_free_pass(self):
        policy = VotingTokenPolicy.current()
        policy.tokens_paused = True
        policy.voting_suspended = True
        policy.save(update_fields=["tokens_paused", "voting_suspended", "updated_at"])
        self.fan.has_free_pass = True
        self.fan.save(update_fields=["has_free_pass"])

        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "voter_tag": "blocked"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["message"], "Voting is suspended by admin")
        self.assertFalse(Vote.objects.filter(content=self.content, fan=self.fan).exists())

    def test_paused_tokens_preserve_rank_reuse_rule(self):
        policy = VotingTokenPolicy.current()
        policy.tokens_paused = True
        policy.save(update_fields=["tokens_paused", "updated_at"])
        other_content = Content.objects.create(
            title="Second Vote Target",
            artist=self.artist,
            genre=self.genre,
            file=sample_upload_file(filename="target-two.mp4", content_type="video/mp4"),
            is_approved=True,
            is_approved_for_voting=True,
        )
        Vote.objects.create(
            content=self.content,
            fan=self.fan,
            base_value=4,
            value=4,
            otp_code="FREE",
        )

        response = self.client.post(
            reverse("vote_content", args=[other_content.id]),
            data='{"vote_value": 4, "voter_tag": "free"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Vote.objects.filter(content=other_content, fan=self.fan).exists())

    def test_free_pass_user_can_vote_without_otp(self):
        self.fan.has_free_pass = True
        self.fan.save(update_fields=["has_free_pass"])

        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "voter_tag": "free-pass"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.remaining_votes, 1)
        vote = Vote.objects.get(content=self.content, fan=self.fan)
        self.assertEqual(vote.otp_code, "FREE")

    def test_suspended_user_cannot_vote_even_with_valid_otp(self):
        self.fan.is_suspended_by_admin = True
        self.fan.save(update_fields=["is_suspended_by_admin"])

        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "otp_code": "123456", "voter_tag": "suspended"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("login"))
        self.otp.refresh_from_db()
        self.assertEqual(self.otp.remaining_votes, 1)
        self.assertFalse(Vote.objects.filter(content=self.content, fan=self.fan).exists())

    def test_admin_voting_toggle_hides_button_and_blocks_votes(self):
        admin = CustomUser.objects.create_user(
            username="vote_toggle_admin",
            password="password",
            role=Role.ADMIN,
            is_staff=True,
        )
        self.client.force_login(admin)
        response = self.client.post(
            reverse("toggle_content_voting", args=[self.content.id, "disapprove"])
        )

        self.assertEqual(response.status_code, 302)
        self.content.refresh_from_db()
        self.assertFalse(self.content.is_approved_for_voting)

        self.client.force_login(self.fan)
        detail_response = self.client.get(reverse("content_detail", args=[self.content.id]))
        vote_response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "otp_code": "123456", "voter_tag": "closed"}',
            content_type="application/json",
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, 'watch-action-row no-vote')
        self.assertNotContains(detail_response, 'data-vote-toggle')
        self.assertEqual(vote_response.status_code, 200)
        self.assertFalse(Vote.objects.filter(content=self.content, fan=self.fan).exists())

    def test_vote_rejected_when_content_not_approved_for_voting(self):
        self.content.is_approved_for_voting = False
        self.content.save(update_fields=["is_approved_for_voting"])

        response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "otp_code": "123456", "voter_tag": "closed"}',
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Vote.objects.filter(content=self.content, fan=self.fan).exists())

    def test_pending_content_rejects_detail_comments_and_votes_for_fans(self):
        self.content.is_approved = False
        self.content.save(update_fields=["is_approved"])

        detail_response = self.client.get(reverse("content_detail", args=[self.content.id]))
        comment_response = self.client.post(
            reverse("add_comment", args=[self.content.id]),
            {"text": "Should not post"},
        )
        vote_response = self.client.post(
            reverse("vote_content", args=[self.content.id]),
            data='{"vote_value": 4, "otp_code": "123456"}',
            content_type="application/json",
        )

        self.assertEqual(detail_response.status_code, 302)
        self.assertEqual(comment_response.status_code, 404)
        self.assertEqual(vote_response.status_code, 404)
        self.assertFalse(Comment.objects.filter(content=self.content).exists())
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
