import io
import json
import struct
import tempfile
import wave
from unittest.mock import patch

from django.core.files.base import ContentFile
from django.test import TestCase, Client
from django.urls import reverse

from studio.extract_arrangement import plan_ranges, render_arrangement
from studio.models import AudioJob, Instrumental, Project, Track
from studio.storage import private_storage
from users.models import CustomUser, Role


def source_wav():
    data = io.BytesIO()
    with wave.open(data, 'wb') as audio:
        audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b''.join(struct.pack('<h', level) * 8000 for level in [10000, 20000, 30000]))
    return ContentFile(data.getvalue(), name='source.wav')


class ExtractArrangementTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        storage = patch.object(private_storage, 'location', folder.name)
        storage.start()
        self.addCleanup(storage.stop)
        self.artist = CustomUser.objects.create_user(username='arranger', role=Role.ARTIST)
        self.other = CustomUser.objects.create_user(username='outsider', role=Role.ARTIST)
        self.client.force_login(self.artist)
        self.project = Project.objects.create(artist=self.artist, title='Song', category='gospel')
        self.track = Track.objects.create(project=self.project, name='Song', kind='backing', audio=source_wav())
        self.job = AudioJob.objects.create(track=self.track, operation='separate', status='ready', source=self.track.audio.name, result=source_wav())
        self.config = {'crossfade_ms': 20, 'sections': [{'start': 0, 'end': .5, 'gain': 1}, {'start': 1, 'end': 1.5, 'gain': .5}, {'start': 2, 'end': 2.5, 'gain': .25}]}

    def save_job(self):
        return self.client.post(reverse('studio:arrange_job_save', args=[self.job.pk]), {'title': 'Joined', 'config': json.dumps(self.config)})

    def test_real_render_joins_all_three_ranges_without_inserted_silence(self):
        with self.job.result.open('rb') as source:
            original = source.read()
        result = render_arrangement(self.job.result, self.config)
        with wave.open(result, 'rb') as audio:
            self.assertEqual(audio.getnframes(), 12000 - 320)
            samples = struct.unpack('<' + 'h' * audio.getnframes(), audio.readframes(audio.getnframes()))
        self.assertTrue(all(value >= 7400 for value in samples), 'No zero-filled gaps or fade-to-silence at joins')
        self.assertAlmostEqual(samples[100], 10000, delta=2)
        self.assertAlmostEqual(samples[-100], 7500, delta=2)
        with self.job.result.open('rb') as source:
            self.assertEqual(source.read(), original)

    def test_direct_join_preserves_sum_of_section_lengths(self):
        self.config['crossfade_ms'] = 0
        result = render_arrangement(self.job.result, self.config)
        with wave.open(result, 'rb') as audio:
            self.assertEqual(audio.getnframes(), 12000)

    def test_save_from_extraction_pins_source_and_does_not_rerun_separation(self):
        with patch('studio.audio_processing.process') as separation:
            response = self.save_job()
        self.assertEqual(response.status_code, 200, response.content)
        separation.assert_not_called()
        item = Instrumental.objects.get()
        self.assertEqual(item.source_audio.name, self.job.result.name)
        self.assertNotEqual(item.audio.name, item.source_audio.name)
        self.assertEqual(item.config['arrangement'], self.config)
        self.assertEqual(item.config['bpm'], self.project.tempo)
        self.assertEqual(self.client.get(response.json()['url']).status_code, 200)
        source_response = self.client.get(reverse('studio:arrange_source', args=[item.pk]))
        self.assertEqual(source_response.status_code, 200)
        source_response.close()

    def test_reediting_updates_copy_but_preserves_source_and_saved_track_snapshots(self):
        self.assertEqual(self.save_job().status_code, 200)
        item = Instrumental.objects.get()
        old_audio, source = item.audio.name, item.source_audio.name
        Track.objects.create(project=self.project, name='Previous version', audio=old_audio)
        self.config['sections'][1]['end'] = 1.75
        response = self.client.post(reverse('studio:arrange_save', args=[item.pk]), {'title': 'Updated', 'revision': item.updated_at.isoformat(), 'config': json.dumps(self.config)})
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(Instrumental.objects.count(), 1)
        self.assertNotEqual(item.audio.name, old_audio)
        self.assertEqual(item.source_audio.name, source)
        self.assertTrue(private_storage.exists(old_audio))

    def test_saved_library_extract_gets_an_arranged_copy(self):
        original = Instrumental.objects.create(artist=self.artist, title='Original', category='gospel', config={'imported': True, 'bpm': 80}, audio=self.job.result.name)
        response = self.client.post(reverse('studio:arrange_save', args=[original.pk]), {'title': 'Copy', 'revision': original.updated_at.isoformat(), 'config': json.dumps(self.config)})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Instrumental.objects.count(), 2)
        original.refresh_from_db()
        self.assertEqual(original.audio.name, self.job.result.name)

    def test_stale_saves_and_bad_ranges_do_not_change_library(self):
        self.save_job()
        item = Instrumental.objects.get()
        with patch('studio.extract_arrangement.render_arrangement') as render:
            response = self.client.post(reverse('studio:arrange_save', args=[item.pk]), {'title': 'Stale', 'revision': 'old', 'config': json.dumps(self.config)})
        self.assertEqual(response.status_code, 409)
        render.assert_not_called()
        for start, end in [(-1, 1), (0, 9), (1, 1), ('nan', 2)]:
            self.config['sections'][0].update(start=start, end=end)
            self.assertEqual(self.save_job().status_code, 400)
        self.assertEqual(Instrumental.objects.count(), 1)

    def test_owner_isolation_artist_access_and_post_csrf(self):
        self.save_job()
        item = Instrumental.objects.get()
        urls = [reverse('studio:arrange_job', args=[self.job.pk]), reverse('studio:arrange', args=[item.pk]), reverse('studio:arrange_source', args=[item.pk])]
        self.client.force_login(self.other)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.save_job().status_code, 404)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.artist)
        self.assertEqual(protected.post(reverse('studio:arrange_job_save', args=[self.job.pk])).status_code, 403)

    def test_only_ready_extracted_audio_is_editable(self):
        self.job.status = 'expired'
        self.job.save()
        self.assertEqual(self.client.get(reverse('studio:arrange_job', args=[self.job.pk])).status_code, 404)
        self.assertEqual(self.save_job().status_code, 404)

    def test_arranged_source_survives_temporary_job_expiry(self):
        import os
        import time
        from datetime import timedelta
        from django.utils import timezone
        from django.core.management import call_command
        self.save_job()
        item = Instrumental.objects.get()
        source = item.source_audio.name
        old = time.time() - 45 * 86400
        os.utime(private_storage.path(source), (old, old))
        AudioJob.objects.filter(pk=self.job.pk).update(created_at=timezone.now() - timedelta(days=45))
        call_command('cleanup_studio_audio', apply=True)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'expired')
        self.assertTrue(private_storage.exists(source))
        self.assertEqual(self.client.get(reverse('studio:arrange', args=[item.pk])).status_code, 200)

    def test_joined_instrumental_is_used_as_a_single_backing_track(self):
        self.save_job()
        item = Instrumental.objects.get()
        response = self.client.post(reverse('studio:instrumental_use', args=[item.pk]))
        self.assertEqual(response.status_code, 302)
        track = Track.objects.exclude(project=self.project).get()
        self.assertEqual(track.kind, 'backing')
        with track.audio.open('rb') as stream, wave.open(stream, 'rb') as audio:
            self.assertEqual(audio.getnframes(), 11680)

    def test_short_parts_cap_crossfade_and_invalid_plans_are_rejected(self):
        parts, fades, length = plan_ranges({'crossfade_ms': 500, 'sections': [{'start': 0, 'end': .1, 'gain': 1}] * 3}, 8000, 24000)
        self.assertEqual(fades, [400, 400])
        self.assertEqual(length, 1600)
        for config in [None, {'sections': []}, {'sections': self.config['sections'], 'crossfade_ms': float('inf')}, {'sections': [{'start': 0, 'end': 360, 'gain': 1}] * 3}]:
            with self.assertRaises((ValueError, TypeError)):
                plan_ranges(config, 8000, 8000 * 360)
