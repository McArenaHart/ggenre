import io
import tempfile
import wave
from unittest.mock import patch
from django.contrib.admin.sites import AdminSite
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from users.models import CustomUser, Role
from content.models import ArtistUploadLimit, Comment, Content
from .admin import ExportAdmin
from .models import Project, Track, Export, ExportAllowance, Release
from .storage import private_storage


def wav_upload(seconds=.1):
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * int(8000 * seconds))
    return SimpleUploadedFile("take.wav", data.getvalue(), content_type="audio/wav")


class StudioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.artist = CustomUser.objects.create_user(username="studio_artist", password="password", role=Role.ARTIST)
        cls.other = CustomUser.objects.create_user(username="other_artist", role=Role.ARTIST)
        cls.fan = CustomUser.objects.create_user(username="studio_fan", role=Role.FAN)
        cls.admin = CustomUser.objects.create_superuser(username="studio_admin", password="password", role=Role.ADMIN)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.storage_patch = patch.object(private_storage, "location", self.directory.name)
        self.storage_patch.start()
        self.addCleanup(self.directory.cleanup)
        self.addCleanup(self.storage_patch.stop)
        self.client.force_login(self.artist)
        self.project = Project.objects.create(artist=self.artist, title="Harmony", category="gospel", mix=wav_upload())

    def url(self, name, pk=None):
        return reverse("studio:" + name, args=[self.project.pk if pk is None else pk])

    def test_artist_only_and_owner_isolation(self):
        self.assertContains(self.client.get(reverse("studio:index")), "GGenre Studio")
        self.assertContains(self.client.get(self.url("editor")), "Harmony")
        self.client.force_login(self.fan)
        self.assertEqual(self.client.get(reverse("studio:index")).status_code, 403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url("editor")).status_code, 404)
        self.assertEqual(self.client.post(self.url("export")).status_code, 404)

    def test_first_two_exports_free_then_payment_approval(self):
        for _ in range(3):
            self.assertEqual(self.client.post(self.url("export"), {"payment_reference": "receipt123"}).status_code, 302)
        exports = list(Export.objects.order_by("pk"))
        self.assertEqual([e.status for e in exports], ["free", "free", "pending"])
        self.assertEqual(ExportAllowance.objects.get(artist=self.artist).free_used, 2)
        for _ in range(2):
            response = self.client.get(self.url("download", exports[0].pk))
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response["Content-Disposition"])
            response.close()
        self.assertEqual(self.client.get(self.url("download", exports[2].pk)).status_code, 404)
        self.client.post(self.url("export"))
        self.assertEqual(Export.objects.count(), 3)
        request = type("Request", (), {"user": self.admin})()
        ExportAdmin(Export, AdminSite()).approve_payment(request, Export.objects.filter(pk=exports[2].pk))
        exports[2].refresh_from_db()
        self.assertEqual(exports[2].reviewed_by, self.admin)
        response = self.client.get(self.url("download", exports[2].pk))
        self.assertEqual(response.status_code, 200)
        response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url("download", exports[0].pk)).status_code, 404)

    def test_publication_preserves_moderation_and_private_tracks(self):
        self.client.post(self.url("publish"))
        release = Release.objects.get()
        self.assertFalse(release.content.is_approved)
        self.assertEqual(release.content.category, "music")
        self.assertTrue(release.content.is_audio_file)
        self.assertEqual(release.content.safe_file_url, self.url("play", release.pk))
        self.assertEqual(Export.objects.count(), 0)
        self.client.force_login(self.fan)
        self.assertEqual(self.client.get(self.url("play", release.pk)).status_code, 404)
        release.content.is_approved = True
        release.content.save()
        response = self.client.get(self.url("play", release.pk))
        self.assertEqual(response.status_code, 200)
        self.assertIn("inline", response["Content-Disposition"])
        response.close()
        self.assertContains(self.client.get(reverse("content_detail", args=[release.content_id])), "audio/wav")
        self.assertEqual(self.client.post(reverse("add_comment", args=[release.content_id]), {"text": "Great harmony!"}).status_code, 200)
        self.assertTrue(Comment.objects.filter(content=release.content).exists())

    def test_publish_obeys_upload_quota(self):
        ArtistUploadLimit.objects.create(artist=self.artist, uploads_used=1, upload_limit=1)
        self.client.post(self.url("publish"))
        self.assertEqual(Release.objects.count(), 0)

    def test_invalid_audio_and_track_ownership(self):
        response = self.client.post(self.url("add_track"), {"audio": SimpleUploadedFile("bad.wav", b"not audio")})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(self.url("add_track"), {"audio": wav_upload(), "name": "Harmony"})
        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertFalse(self.project.mix)
        track = Track.objects.get()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url("track_audio", track.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url("delete_track", track.pk)).status_code, 404)

    def test_saved_mix_snapshot_and_no_export_without_mix(self):
        import json
        track = Track.objects.create(project=self.project, name="Lead", audio=wav_upload())
        self.client.post(self.url("publish"))
        old_path = Release.objects.get().audio.name
        settings = [{"id": track.pk, "gain": 0.5, "offset": 0, "trim_start": 0, "trim_end": 0, "muted": False}]
        response = self.client.post(self.url("save"), {"audio": wav_upload(), "tracks": json.dumps(settings)})
        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertNotEqual(self.project.mix.name, old_path)
        self.assertTrue(private_storage.exists(old_path))
        settings[0]["gain"] = -1
        self.assertEqual(self.client.post(self.url("save"), {"audio": wav_upload(), "tracks": json.dumps(settings)}).status_code, 400)
        self.project.mix = ""
        self.project.save()
        self.client.post(self.url("export"))
        self.assertEqual(Export.objects.count(), 0)

    def test_state_changes_require_post(self):
        for action in ("save", "publish", "export", "add_track"):
            self.assertEqual(self.client.get(self.url(action)).status_code, 405)

    def test_admin_review_access_and_decision(self):
        item = Export.objects.create(project=self.project, audio=self.project.mix.name, status="pending")
        url = reverse("studio:export_reviews")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), "Harmony")
        self.client.post(url, {"export_id": item.pk, "decision": "approved"})
        item.refresh_from_db()
        self.assertEqual(item.status, "approved")
        self.assertEqual(item.reviewed_by, self.admin)

    def test_overdub_keeps_position_and_existing_edits(self):
        import json
        track = Track.objects.create(project=self.project, name="Beat", audio=wav_upload())
        settings = [{"id": track.pk, "gain": 0.4, "offset": 2, "trim_start": 0, "trim_end": 0, "muted": False}]
        response = self.client.post(self.url("add_track"), {"audio": wav_upload(), "name": "Harmony", "offset": "30.25", "tracks": json.dumps(settings)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.project.tracks.get(name="Harmony").offset, 30.25)
        track.refresh_from_db()
        self.assertEqual(track.gain, 0.4)
        self.assertEqual(track.offset, 2)
        self.project.refresh_from_db()
        self.assertFalse(self.project.mix)

    def test_overdub_rejects_invalid_position_without_changing_saved_mix(self):
        original_mix = self.project.mix.name
        for offset in ("NaN", "-1", "300", "infinity"):
            response = self.client.post(self.url("add_track"), {"audio": wav_upload(), "offset": offset})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.project.tracks.count(), 0)
        self.project.refresh_from_db()
        self.assertEqual(self.project.mix.name, original_mix)

    def test_overdub_rejects_edits_to_another_projects_tracks(self):
        import json
        other_project = Project.objects.create(artist=self.other, title="Private", category="acapella")
        track = Track.objects.create(project=other_project, name="Private vocal", audio=wav_upload())
        edits = [{"id": track.pk, "gain": 0.1, "offset": 0, "trim_start": 0, "trim_end": 0, "muted": False}]
        response = self.client.post(self.url("add_track"), {"audio": wav_upload(), "tracks": json.dumps(edits)})
        self.assertEqual(response.status_code, 400)
        track.refresh_from_db()
        self.assertEqual(track.gain, 1)
        self.assertEqual(self.project.tracks.count(), 0)

    def test_deleting_track_preserves_other_unsaved_track_edits(self):
        import json
        keep = Track.objects.create(project=self.project, name="Beat", audio=wav_upload())
        remove = Track.objects.create(project=self.project, name="Vocal", audio=wav_upload())
        edits = [{"id": item.pk, "gain": .3, "offset": 2, "trim_start": 0, "trim_end": 0, "muted": False} for item in (keep, remove)]
        response = self.client.post(self.url("delete_track", remove.pk), {"tracks": json.dumps(edits)})
        self.assertEqual(response.status_code, 200)
        keep.refresh_from_db()
        self.assertEqual(keep.gain, .3)
        self.assertEqual(keep.offset, 2)
        self.assertFalse(Track.objects.filter(pk=remove.pk).exists())

    def test_editor_and_saved_mix_use_consistent_revision_tokens(self):
        import json
        response = self.client.get(self.url("editor"))
        self.assertEqual(response.context["revision"], self.project.updated_at.isoformat())
        response = self.client.post(self.url("save"), {"audio": wav_upload(), "tracks": json.dumps([])})
        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(response.json()["revision"], self.project.updated_at.isoformat())
        self.assertEqual(self.client.get(self.url("editor")).context["revision"], response.json()["revision"])

    def test_project_types_get_different_default_tempos_and_workflows(self):
        from .catalog import PROFILES
        for category, profile in PROFILES.items():
            response = self.client.post(reverse("studio:index"), {"title": category + " session", "category": category})
            self.assertEqual(response.status_code, 302)
            project = Project.objects.get(title=category + " session")
            self.assertEqual(project.tempo, profile["tempo"])
            self.assertEqual(project.workflow_label, profile["label"])
        response = self.client.get(reverse("studio:index"))
        self.assertContains(response, "studio-picker.js")
        self.assertContains(response, "Circular / Secular")

    def test_acapella_has_voice_tools_without_beat_controls(self):
        project = Project.objects.create(artist=self.artist, title="Voices", category="acapella")
        response = self.client.get(self.url("editor", project.pk))
        self.assertContains(response, "Vocal percussion")
        self.assertContains(response, "Voices are your instruments")
        self.assertNotContains(response, 'id="beat-preset"')
        for kind in ("beat", "backing"):
            response = self.client.post(self.url("add_track", project.pk), {"kind": kind, "audio": wav_upload(), "beat_preset": "gospel-worship", "beat_bpm": "72"})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(project.tracks.count(), 0)
        response = self.client.post(self.url("add_track", project.pk), {"kind": "vocal", "audio": wav_upload(), "name": "Bass voice", "tempo": "110"})
        self.assertEqual(response.status_code, 200)
        project.refresh_from_db()
        self.assertEqual(project.tempo, 110)
        self.assertEqual(project.tracks.get().kind, "vocal")

    def test_categories_only_offer_their_own_beats(self):
        from .catalog import beats_for
        self.assertEqual(beats_for("acapella"), [])
        for category in ("gospel", "secular"):
            self.assertEqual(len(beats_for(category)), 3)
            self.assertTrue(all(beat["category"] == category for beat in beats_for(category)))
        response = self.client.post(self.url("add_track"), {"kind": "beat", "audio": wav_upload(), "beat_preset": "secular-hiphop", "beat_bpm": "92"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.project.tracks.count(), 0)

    def test_beat_addition_sets_tempo_and_does_not_use_exports(self):
        response = self.client.post(self.url("add_track"), {"kind": "beat", "audio": wav_upload(), "name": "Worship", "beat_preset": "gospel-worship", "beat_bpm": "72"})
        self.assertEqual(response.status_code, 200)
        self.project.refresh_from_db()
        self.assertEqual(self.project.tempo, 72)
        beat = self.project.tracks.get()
        self.assertEqual((beat.kind, beat.beat_preset, beat.beat_bpm), ("beat", "gospel-worship", 72))
        self.assertFalse(self.project.mix)
        self.assertEqual(Export.objects.count(), 0)
        self.assertEqual(Content.objects.count(), 0)
        self.assertEqual(self.client.post(self.url("add_track"), {"kind": "beat", "audio": wav_upload(), "beat_preset": "gospel-praise", "beat_bpm": "112"}).status_code, 409)
        self.assertContains(self.client.get(self.url("editor")), "readonly")

    def test_existing_beat_tempo_cannot_be_silently_changed(self):
        import json
        self.project.tempo = 72
        self.project.save()
        track = Track.objects.create(project=self.project, name="Worship", audio=wav_upload(), kind="beat", beat_preset="gospel-worship", beat_bpm=72)
        settings = [{"id": track.pk, "gain": 1, "offset": 0, "trim_start": 0, "trim_end": 0, "muted": False}]
        self.assertEqual(self.client.post(self.url("save"), {"audio": wav_upload(), "tracks": json.dumps(settings), "tempo": "100"}).status_code, 400)
        self.assertEqual(self.client.post(self.url("add_track"), {"audio": wav_upload(), "tempo": "100"}).status_code, 400)
        self.assertEqual(self.client.post(self.url("save"), {"audio": wav_upload(), "tracks": json.dumps(settings), "tempo": "72"}).status_code, 200)

    def test_invalid_beat_metadata_keeps_existing_mix(self):
        original = self.project.mix.name
        for bpm in ("0", "241", "bad"):
            response = self.client.post(self.url("add_track"), {"kind": "beat", "audio": wav_upload(), "beat_preset": "gospel-worship", "beat_bpm": bpm})
            self.assertEqual(response.status_code, 400)
        self.project.refresh_from_db()
        self.assertEqual(self.project.mix.name, original)
        self.assertEqual(self.project.tracks.count(), 0)


    def test_acapella_voice_rename_and_stale_edit_protection(self):
        import json
        self.project.category = "acapella"
        self.project.save()
        track = Track.objects.create(project=self.project, name="Alto", audio=wav_upload(), kind="vocal")
        revision = self.project.updated_at.isoformat()
        edits = [{"id": track.pk, "name": "Alto harmony", "gain": 0.8, "offset": 0, "trim_start": 0, "trim_end": 0, "muted": False}]
        response = self.client.post(self.url("save"), {"audio": wav_upload(), "tracks": json.dumps(edits), "tempo": 90, "revision": revision})
        self.assertEqual(response.status_code, 200)
        track.refresh_from_db()
        self.assertEqual(track.name, "Alto harmony")
        self.assertEqual(self.client.post(self.url("save"), {"audio": wav_upload(), "tracks": json.dumps(edits), "revision": revision}).status_code, 409)
        self.assertEqual(self.client.post(self.url("add_track"), {"audio": wav_upload(), "revision": revision}).status_code, 409)
        self.assertEqual(self.client.post(self.url("delete_track", track.pk), {"revision": revision}).status_code, 409)
        edits[0]["name"] = " "
        self.assertEqual(self.client.post(self.url("save"), {"audio": wav_upload(), "tracks": json.dumps(edits)}).status_code, 400)
        track.refresh_from_db()
        self.assertEqual(track.name, "Alto harmony")
        page = self.client.get(self.url("editor"))
        self.assertContains(page, 'id="reference-pitch"')
        self.assertNotContains(page, 'id="beat-preset"')

    def test_instrumental_controls_are_available_only_for_backing_categories(self):
        for category in ("gospel", "secular", "acapella"):
            self.project.category = category
            self.project.save()
            page = self.client.get(self.url("editor"))
            if category == "acapella":
                self.assertNotContains(page, 'id="backing-mode"')
            else:
                for control in ("backing-mode", "backing-key", "backing-progression"):
                    self.assertContains(page, 'id="' + control + '"')
                self.assertContains(page, "Piano only")
                self.assertContains(page, "Bass only")
                self.assertContains(page, "Synth chords only")


    def composition_config(self):
        return {"schema": 1, "mode": "full", "bpm": 240, "bars": 4, "key": 0, "progression": "major", "preset": "gospel-worship", "notes": {"piano": [{"step": 0, "midi": 60, "length": 4}]}, "levels": {"bass": .5}}

    def save_composition(self, config=None, pk=None, revision=""):
        import json
        endpoint = reverse("studio:compose_save", args=[pk]) if pk else reverse("studio:compose_save_new")
        return self.client.post(endpoint, {"title": "Original beat", "category": "gospel", "config": json.dumps(config or self.composition_config()), "audio": wav_upload(4), "revision": revision})

    def test_instrumental_save_reopen_and_vocal_session_snapshot(self):
        from .models import Instrumental
        response = self.save_composition()
        self.assertEqual(response.status_code, 200)
        item = Instrumental.objects.get()
        self.assertEqual(item.config["notes"]["piano"][0]["midi"], 60)
        self.assertContains(self.client.get(reverse("studio:compose", args=[item.pk])), "Original beat")
        self.assertContains(self.client.get(reverse("studio:instrumentals")), "Original beat")
        response = self.client.post(reverse("studio:instrumental_use", args=[item.pk]))
        project = Project.objects.exclude(pk=self.project.pk).get()
        self.assertRedirects(response, self.url("editor", project.pk))
        track = project.tracks.get()
        self.assertEqual((track.kind, track.beat_bpm, project.tempo), ("beat", 240, 240))
        self.assertNotEqual(track.audio.name, item.audio.name)
        with track.audio.open("rb") as source:
            copied = source.read()
        with item.audio.open("rb") as source:
            self.assertEqual(copied, source.read())
        original_revision = item.updated_at.isoformat()
        config = item.config.copy()
        config["key"] = 5
        self.assertEqual(self.save_composition(config, item.pk, original_revision).status_code, 200)
        self.assertEqual(self.save_composition(config, item.pk, original_revision).status_code, 409)
        track.refresh_from_db()
        with track.audio.open("rb") as source:
            self.assertEqual(source.read(), copied)
        self.assertEqual(track.project.tracks.count(), 1)

    def test_instrumental_invalid_patterns_and_audio_are_rejected(self):
        from .models import Instrumental
        for changes in ({"bpm": 0}, {"mode": "unknown"}, {"key": 12}, {"notes": {"piano": [{"step": 63, "midi": 60, "length": 4}]}}, {"drums": {"kick": [64]}}, {"levels": {"piano": 2}}, {"bars": 8}):
            config = self.composition_config()
            config.update(changes)
            self.assertEqual(self.save_composition(config).status_code, 400)
        self.assertFalse(Instrumental.objects.exists())

    def test_instrumentals_are_private_and_artist_only(self):
        from .models import Instrumental
        self.save_composition()
        item = Instrumental.objects.get()
        response = self.client.get(reverse("studio:instrumental_audio", args=[item.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("studio:compose", args=[item.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("studio:instrumental_audio", args=[item.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("studio:instrumental_use", args=[item.pk])).status_code, 404)
        self.client.force_login(self.fan)
        self.assertEqual(self.client.get(reverse("studio:instrumentals")).status_code, 403)
        self.assertEqual(self.save_composition().status_code, 403)

    def test_reusing_instrumental_preserves_acapella_and_existing_backings(self):
        from .models import Instrumental
        self.save_composition()
        item = Instrumental.objects.get()
        self.project.category = "acapella"
        self.project.save()
        self.client.post(reverse("studio:instrumental_use", args=[item.pk]), {"project": self.project.pk})
        self.assertFalse(self.project.tracks.exists())
        self.project.category = "gospel"
        self.project.save()
        self.client.post(reverse("studio:instrumental_use", args=[item.pk]), {"project": self.project.pk})
        self.assertEqual(self.project.tracks.count(), 1)
        self.client.post(reverse("studio:instrumental_use", args=[item.pk]), {"project": self.project.pk})
        self.assertEqual(self.project.tracks.count(), 1)

    def test_new_instrumental_workspaces_start_with_empty_patterns(self):
        for mode in ("piano", "bass", "chords", "full", "drums"):
            page = self.client.get(reverse("studio:compose_new"), {"mode": mode})
            self.assertEqual(page.status_code, 200)
            self.assertEqual(page.context["config"]["notes"], {"piano": [], "bass": [], "pad": []})
            self.assertEqual(page.context["config"]["drums"], {})
            if mode == "piano":
                self.assertEqual(page.context["config"]["bars"], 32)
                self.assertContains(page, "Piano roll")

    def test_piano_song_sections_save_longer_than_a_minute_and_reopen(self):
        import json
        from .models import Instrumental
        config = {"schema": 2, "mode": "piano", "bpm": 240, "bars": 68, "key": 0, "preset": "gospel-worship", "levels": {"piano": .8}, "clips": [{"id": "verse", "name": "Verse", "start": 0, "bars": 8, "notes": [{"step": 0, "midi": 60, "length": 4}]}, {"id": "chorus", "name": "Chorus", "start": 60, "bars": 8, "notes": [{"step": 0, "midi": 64, "length": 8}]}]}
        response = self.client.post(reverse("studio:compose_save_new"), {"title": "Full piano song", "category": "gospel", "config": json.dumps(config), "audio": wav_upload(68)})
        self.assertEqual(response.status_code, 200)
        item = Instrumental.objects.get()
        self.assertEqual(item.config["bars"], 68)
        self.assertEqual(len(item.config["clips"]), 2)
        page = self.client.get(reverse("studio:compose", args=[item.pk]))
        self.assertContains(page, 'id="piano-keyboard"')
        self.assertContains(page, 'id="piano-play-song"')
        self.assertNotContains(page, 'id="composer-grid"')
        response = self.client.post(reverse("studio:instrumental_use", args=[item.pk]))
        project = Project.objects.exclude(pk=self.project.pk).get()
        self.assertRedirects(response, self.url("editor", project.pk))
        self.assertEqual(project.tracks.get().beat_bpm, 240)

    def test_piano_song_validation_rejects_overlap_and_preserves_limits(self):
        from .composition import validate_config
        base = {"schema": 2, "mode": "piano", "bpm": 90, "bars": 8, "key": 0, "preset": "gospel-worship", "levels": {}, "clips": [{"id": "verse", "name": "Verse", "start": 0, "bars": 8, "notes": []}]}
        self.assertEqual(validate_config(base, "gospel")["clips"][0]["name"], "Verse")
        import copy
        for mutate in (lambda c: c.update(bars=200), lambda c: c["clips"].append({**c["clips"][0], "id": "other"}), lambda c: c["clips"][0]["notes"].append({"step": 127, "midi": 60, "length": 2}), lambda c: c["clips"][0].update(bars=33)):
            config = copy.deepcopy(base)
            mutate(config)
            with self.assertRaises(ValueError):
                validate_config(config, "gospel")

    def test_all_library_workspaces_share_song_tools_and_start_blank(self):
        for mode in ("piano", "bass", "chords", "drums", "full"):
            page = self.client.get(reverse("studio:compose_new"), {"mode": mode})
            self.assertEqual(page.context["config"]["schema"], 2)
            self.assertEqual(page.context["config"]["clips"], [])
            self.assertEqual(page.context["config"]["bars"], 32)
            for control in ("workspace-idea", "workspace-fill", "workspace-undo", "piano-copy-notes", "piano-play-song"):
                self.assertContains(page, 'id="' + control + '"')

    def test_full_arrangement_saves_independent_simultaneous_layers(self):
        import json
        from .models import Instrumental
        from .composition import validate_config
        parts = [("piano", 60, 4), ("bass", 36, 4), ("pad", 48, 16), ("drums", 24, 1)]
        config = {"schema": 2, "mode": "full", "bpm": 240, "bars": 4, "key": 0, "preset": "gospel-worship", "levels": {"bass": .6}, "clips": [{"id": part, "name": part, "instrument": part, "start": 0, "bars": 4, "notes": [{"step": 0, "midi": midi, "length": length}]} for part, midi, length in parts]}
        response = self.client.post(reverse("studio:compose_save_new"), {"title": "Full arrangement", "category": "gospel", "config": json.dumps(config), "audio": wav_upload(4)})
        self.assertEqual(response.status_code, 200)
        item = Instrumental.objects.get()
        self.assertEqual({c["instrument"] for c in item.config["clips"]}, {"piano", "bass", "pad", "drums"})
        invalid = dict(config, mode="bass")
        with self.assertRaises(ValueError):
            validate_config(invalid, "gospel")
        invalid = dict(config, clips=[config["clips"][-1] | {"notes": [{"step": 0, "midi": 60, "length": 1}]}])
        with self.assertRaises(ValueError):
            validate_config(invalid, "gospel")

    def test_keyboard_audio_entry_creates_artist_session_without_bypassing_acapella(self):
        endpoint = reverse("studio:keyboard_audio")
        response = self.client.post(endpoint, {"title": "Keyboard test", "category": "secular", "tempo": "100"})
        project = Project.objects.get(title="Keyboard test")
        self.assertEqual(project.artist, self.artist)
        self.assertEqual(project.tempo, 100)
        self.assertEqual(response.url, self.url("editor", project.pk) + "?input=keyboard")
        self.assertFalse(project.tracks.exists())
        self.assertEqual(self.client.post(endpoint, {"category": "acapella", "title": "Invalid", "tempo": "90"}).status_code, 400)
        self.assertEqual(self.client.get(endpoint).status_code, 405)
        self.client.force_login(self.fan)
        self.assertEqual(self.client.post(endpoint).status_code, 403)

    def test_midi_and_audio_setup_controls_render_without_requesting_devices(self):
        page = self.client.get(reverse("studio:compose_new"), {"mode": "piano"})
        for control in ("workspace-midi-connect", "workspace-midi-device", "workspace-midi-panic", "keyboard-audio-form"):
            self.assertContains(page, 'id="' + control + '"')
        page = self.client.get(self.url("editor"))
        self.assertContains(page, 'id="studio-audio-device"')
        self.assertContains(page, 'value="keyboard"')
        self.project.category = "acapella"
        self.project.save()
        self.assertNotContains(self.client.get(self.url("editor")), 'value="keyboard"')

    def test_sound_palette_and_toms_persist_with_instrumental(self):
        import json
        from .models import Instrumental
        config = {"schema": 2, "mode": "full", "bpm": 240, "bars": 4, "key": 0, "preset": "gospel-worship", "levels": {}, "sounds": {"piano": "electric-piano", "bass": "sub-bass", "pad": "warm-pad"}, "clips": [{"id": "warm", "name": "Worship pad", "instrument": "pad", "start": 0, "bars": 4, "notes": [{"step": 0, "midi": 48, "length": 16}]}, {"id": "toms", "name": "Tom fill", "instrument": "drums", "start": 0, "bars": 4, "notes": [{"step": i + 12, "midi": midi, "length": 1} for i, midi in enumerate((34, 33, 32))]}]}
        response = self.client.post(reverse("studio:compose_save_new"), {"title": "Warm pad and toms", "category": "gospel", "config": json.dumps(config), "audio": wav_upload(4)})
        self.assertEqual(response.status_code, 200)
        item = Instrumental.objects.get()
        self.assertEqual(item.config["sounds"], config["sounds"])
        self.assertEqual([n["midi"] for n in item.config["clips"][1]["notes"]], [34, 33, 32])
        page = self.client.get(reverse("studio:compose", args=[item.pk]))
        self.assertContains(page, 'id="workspace-sound"')
        self.assertContains(page, 'id="workspace-add-tom-fill"')
        from .composition import validate_config
        with self.assertRaises(ValueError):
            validate_config(config | {"sounds": {"bass": "warm-pad"}}, "gospel")
        with self.assertRaises(ValueError):
            validate_config(config | {"sounds": {"pad": "unknown"}}, "gospel")

    def test_new_gospel_workspaces_include_warm_pad_default_without_sample_notes(self):
        page = self.client.get(reverse("studio:compose_new"), {"mode": "chords"})
        self.assertEqual(page.context["config"]["sounds"]["pad"], "warm-pad")
        self.assertEqual(page.context["config"]["clips"], [])


    def test_admin_export_controls_save_reset_and_audit(self):
        from django.contrib.admin.models import LogEntry
        allowance = ExportAllowance.objects.create(artist=self.artist, free_used=2)
        existing = Export.objects.create(project=self.project, audio=self.project.mix.name, status="free")
        url = reverse("studio:export_controls")
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {}).status_code, 403)
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(url), "studio_artist")
        data = {"artist_id": self.artist.pk, "free_limit": 5, "free_used": 2, "previous_limit": 2, "previous_used": 2, "reason": "Pilot artist grant", "action": "save"}
        self.assertRedirects(self.client.post(url, data), url)
        allowance.refresh_from_db()
        self.assertEqual((allowance.free_limit, allowance.free_remaining), (5, 3))
        self.assertTrue(LogEntry.objects.filter(user=self.admin, change_message__contains="Pilot artist grant").exists())
        data.update(action="reset", previous_limit=5, free_limit=99, reason="Restart pilot")
        self.client.post(url, data)
        allowance.refresh_from_db()
        self.assertEqual((allowance.free_limit, allowance.free_used), (5, 0))
        existing.refresh_from_db()
        self.assertEqual(existing.status, "free")
        self.client.force_login(self.artist)
        self.assertContains(self.client.get(reverse("studio:index")), "5 free exports")
        self.assertContains(self.client.get(self.url("editor")), "5 free exports remaining")

    def test_admin_export_controls_reject_invalid_stale_and_fan_targets(self):
        allowance = ExportAllowance.objects.create(artist=self.artist, free_used=1)
        self.client.force_login(self.admin)
        url = reverse("studio:export_controls")
        data = {"artist_id": self.artist.pk, "free_limit": -1, "free_used": 0, "previous_limit": 2, "previous_used": 1, "reason": "Correction", "action": "save"}
        self.client.post(url, data)
        allowance.refresh_from_db()
        self.assertEqual((allowance.free_limit, allowance.free_used), (2, 1))
        data.update(free_limit=8, previous_used=0)
        self.client.post(url, data)
        allowance.refresh_from_db()
        self.assertEqual(allowance.free_limit, 2)
        data.update(previous_used=1, reason="")
        self.client.post(url, data)
        allowance.refresh_from_db()
        self.assertEqual(allowance.free_limit, 2)
        data.update(reason="Wrong account", artist_id=self.fan.pk)
        self.assertEqual(self.client.post(url, data).status_code, 404)
        self.assertFalse(ExportAllowance.objects.filter(artist=self.fan).exists())

    def test_configured_export_limits_zero_and_reset_take_effect(self):
        allowance = ExportAllowance.objects.create(artist=self.artist, free_limit=0)
        self.client.post(self.url("export"))
        self.assertEqual(Export.objects.get().status, "pending")
        self.assertEqual(ExportAllowance.objects.get(pk=allowance.pk).free_used, 0)
        allowance.free_limit = 3
        allowance.save()
        for _ in range(4):
            self.client.post(self.url("export"))
        self.assertEqual(Export.objects.filter(status="free").count(), 3)
        allowance.refresh_from_db()
        self.assertEqual(allowance.free_used, 3)
        allowance.free_used = 0
        allowance.save()
        self.client.post(self.url("export"))
        self.assertEqual(Export.objects.filter(status="free").count(), 4)

    def test_export_controls_csrf_and_search(self):
        from django.test import Client
        locked = Client(enforce_csrf_checks=True)
        locked.force_login(self.admin)
        self.assertEqual(locked.post(reverse("studio:export_controls"), {}).status_code, 403)
        self.client.force_login(self.admin)
        response = self.client.get(reverse("studio:export_controls"), {"q": "studio_artist"})
        self.assertContains(response, "studio_artist")
        self.assertNotContains(response, "other_artist")


    def test_django_admin_usage_reset_keeps_limit_and_logs(self):
        from django.contrib.admin.models import LogEntry
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage
        from .admin import ExportAllowanceAdmin
        allowance = ExportAllowance.objects.create(artist=self.artist, free_limit=6, free_used=4)
        request = RequestFactory().post("/admin/studio/exportallowance/")
        request.user = self.admin
        request.session = {}
        request._messages = FallbackStorage(request)
        model_admin = ExportAllowanceAdmin(ExportAllowance, AdminSite())
        model_admin.reset_usage(request, ExportAllowance.objects.filter(pk=allowance.pk))
        allowance.refresh_from_db()
        self.assertEqual((allowance.free_limit, allowance.free_used), (6, 0))
        self.assertTrue(LogEntry.objects.filter(object_id=str(allowance.pk), change_message__contains="Reset free export usage").exists())
        self.assertFalse(model_admin.has_delete_permission(request, allowance))
        self.assertFalse(model_admin.has_add_permission(request))


    def test_unlimited_exports_pause_usage_and_resume_existing_limit(self):
        allowance = ExportAllowance.objects.create(artist=self.artist, free_limit=2, free_used=2, unlimited_exports=True)
        for _ in range(4):
            self.client.post(self.url("export"))
        self.assertEqual(Export.objects.filter(status="free").count(), 4)
        allowance.refresh_from_db()
        self.assertEqual(allowance.free_used, 2)
        self.assertContains(self.client.get(reverse("studio:index")), "Unlimited exports")
        self.assertContains(self.client.get(self.url("editor")), "No payment approval is needed")
        allowance.unlimited_exports = False
        allowance.save()
        self.client.post(self.url("export"))
        self.assertEqual(Export.objects.filter(status="pending").count(), 1)
        response = self.client.get(self.url("download", Export.objects.filter(status="free").first().pk))
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_admin_unlimited_toggle_is_audited_and_stale_safe(self):
        from django.contrib.admin.models import LogEntry
        allowance = ExportAllowance.objects.create(artist=self.artist, free_used=2)
        pending = Export.objects.create(project=self.project, audio=self.project.mix.name, status="pending")
        self.client.force_login(self.admin)
        url = reverse("studio:export_controls")
        data = {"artist_id": self.artist.pk, "free_limit": 2, "free_used": 2, "previous_limit": 2, "previous_used": 2, "previous_unlimited": "false", "unlimited_exports": "on", "reason": "Suspend limits during pilot", "action": "save"}
        self.client.post(url, data)
        allowance.refresh_from_db()
        self.assertTrue(allowance.unlimited_exports)
        self.assertTrue(LogEntry.objects.filter(change_message__contains="unlimited exports: off to on").exists())
        pending.refresh_from_db()
        self.assertEqual(pending.status, "pending")
        data.pop("unlimited_exports")
        self.client.post(url, data)
        allowance.refresh_from_db()
        self.assertTrue(allowance.unlimited_exports)
        data["previous_unlimited"] = "true"
        self.client.post(url, data)
        allowance.refresh_from_db()
        self.assertFalse(allowance.unlimited_exports)
        self.assertEqual(allowance.free_used, 2)
        response = self.client.get(url)
        self.assertContains(response, "<summary>Admin change history</summary>", html=True)
