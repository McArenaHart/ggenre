import io
import json
import tempfile
import wave
import os
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from users.models import CustomUser, Role
from .models import AudioJob, AudioJobInput, Project, Track, Export, ExportAllowance, StudioMaintenance
from .storage import private_storage
from .capacity import artist_storage, usage
from .job_control import claim_job, heartbeat, release, JobStopped


def recording(seconds=1):
    data = io.BytesIO()
    with wave.open(data, 'wb') as audio:
        audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x10\x27' * int(8000 * seconds))
    return ContentFile(data.getvalue(), name='take.wav')


class PortableStudioTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        storage = patch.object(private_storage, 'location', folder.name)
        storage.start()
        self.addCleanup(storage.stop)
        self.artist = CustomUser.objects.create_user(username='portable_artist', role=Role.ARTIST)
        self.other = CustomUser.objects.create_user(username='portable_other', role=Role.ARTIST)
        self.client.force_login(self.artist)
        self.project = Project.objects.create(artist=self.artist, title='Portable', category='gospel')
        self.track = Track.objects.create(project=self.project, audio=recording(), name='Voice')

    def settings(self):
        return [{'id': self.track.pk, 'name': 'Voice', 'gain': .5, 'offset': .5, 'trim_start': 0, 'trim_end': 1, 'muted': False}]

    def render_request(self, **extra):
        return self.client.post(reverse('studio:queue_mix', args=[self.project.pk]), {'revision': self.project.updated_at.isoformat(), 'tracks': json.dumps(self.settings()), **extra})

    def test_small_waveform_metadata_does_not_transfer_source(self):
        response = self.client.get(reverse('studio:track_peaks', args=[self.track.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['duration'], 1)
        self.assertLessEqual(len(response.json()['peaks']), 1600)
        self.assertLess(len(response.content), 16000)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('studio:track_peaks', args=[self.track.pk])).status_code, 404)

    def test_private_ranges_are_bounded_and_authorized(self):
        url = reverse('studio:track_audio', args=[self.track.pk])
        for header, length in [('bytes=0-3', 4), ('bytes=-5', 5), ('bytes=16040-', 4)]:
            response = self.client.get(url, HTTP_RANGE=header)
            self.assertEqual(response.status_code, 206)
            self.assertEqual(len(b''.join(response.streaming_content)), length)
            response.close()
        for header in ['bytes=999999-', 'bytes=3-1', 'bytes=0-1,3-4', 'bytes=-0']:
            self.assertEqual(self.client.get(url, HTTP_RANGE=header).status_code, 416)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url, HTTP_RANGE='bytes=0-3').status_code, 404)

    def test_mix_render_snapshot_reused_and_saved_without_browser_wav(self):
        first = self.render_request()
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()['id'], self.render_request().json()['id'])
        with patch('studio.render_mix.shutil.copyfileobj', side_effect=AssertionError('Immutable local inputs must not be copied')):
            call_command('process_studio_audio', once=True)
        job = AudioJob.objects.get(pk=first.json()['id'])
        self.assertEqual(job.status, 'ready', job.error)
        with job.result.open('rb') as stream, wave.open(stream) as audio:
            self.assertEqual(audio.getnframes(), 66150)
            self.assertEqual(audio.getnchannels(), 2)
            audio.setpos(0)
            self.assertEqual(set(audio.readframes(20000)), {0})
        response = self.client.post(reverse('studio:audio_apply', args=[job.pk]), {'revision': self.project.updated_at.isoformat()})
        self.assertEqual(response.status_code, 200, response.content)
        self.project.refresh_from_db()
        self.assertEqual(self.project.mix.name, job.result.name)
        self.track.refresh_from_db()
        self.assertEqual(self.track.offset, .5)

    def test_render_refuses_to_overwrite_newer_project(self):
        job = AudioJob.objects.get(pk=self.render_request().json()['id'])
        call_command('process_studio_audio', once=True)
        self.project.save()
        response = self.client.post(reverse('studio:audio_apply', args=[job.pk]), {'revision': self.project.updated_at.isoformat()})
        self.assertEqual(response.status_code, 409)

    def test_master_runs_in_same_queue_without_a_client_mix_upload(self):
        response = self.render_request(master='yes')
        call_command('process_studio_audio', once=True)
        job = AudioJob.objects.get(pk=response.json()['id'])
        self.assertEqual(job.operation, 'master')
        self.assertEqual(job.status, 'ready', job.error)
        self.project.refresh_from_db()
        self.assertFalse(self.project.mix)
        with job.result.open('rb') as stream, wave.open(stream) as audio:
            self.assertEqual(audio.getnframes(), 66150)

    def test_global_lease_prevents_parallel_model_loading_and_recovers_stale_job(self):
        self.render_request()
        first = claim_job()
        self.assertIsNotNone(first)
        self.assertIsNone(claim_job())
        past = timezone.now() - timedelta(seconds=1)
        StudioMaintenance.objects.filter(pk='audio-worker').update(lease_until=past)
        AudioJob.objects.filter(pk=first.pk).update(lease_until=past)
        recovered = claim_job()
        self.assertEqual(recovered.pk, first.pk)
        self.assertEqual(recovered.attempts, 2)
        with self.assertRaises(JobStopped):
            heartbeat(first)
        release(first)
        self.assertIsNone(claim_job())
        heartbeat(recovered)

    def test_repeated_interruptions_stop_retrying(self):
        self.render_request()
        job = claim_job()
        past = timezone.now() - timedelta(seconds=1)
        StudioMaintenance.objects.filter(pk='audio-worker').update(lease_until=past)
        AudioJob.objects.filter(pk=job.pk).update(lease_until=past, attempts=2)
        self.assertIsNone(claim_job())
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')

    def test_cancel_is_owned_and_stops_lease_renewal(self):
        self.render_request()
        job = claim_job()
        url = reverse('studio:audio_cancel', args=[job.pk])
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url).status_code, 404)
        self.client.force_login(self.artist)
        self.assertEqual(self.client.post(url).status_code, 200)
        with self.assertRaises(JobStopped):
            heartbeat(job)
        release(job)

    def test_completed_extraction_is_reused_without_inference(self):
        existing = AudioJob.objects.create(track=self.track, operation='separate', source=self.track.audio.name, result=recording(), status='applied')
        with patch('studio.audio_processing.available', return_value={'separate': True}):
            response = self.client.post(reverse('studio:audio_queue', args=[self.track.pk]), {'operation': 'separate', 'permission': 'yes'})
        self.assertTrue(response.json()['reused'])
        reused = AudioJob.objects.get(pk=response.json()['id'])
        self.assertEqual(reused.status, 'ready')
        self.assertEqual(reused.result.name, existing.result.name)

    @override_settings(STUDIO_REMOTE_AUDIO_ENGINES=['separate'])
    def test_light_web_can_use_a_checked_worker_but_not_a_stopped_worker(self):
        from .audio_processing import processing_available
        with patch('studio.audio_processing.available', return_value={'separate': False, 'denoise': True, 'tune': False}):
            self.assertFalse(processing_available()['separate'])
            StudioMaintenance.objects.create(key='audio-worker', last_success_at=timezone.now())
            self.assertTrue(processing_available()['separate'])
            StudioMaintenance.objects.filter(pk='audio-worker').update(last_success_at=timezone.now() - timedelta(minutes=2))
            self.assertFalse(processing_available()['separate'])

    def test_same_mix_export_spends_only_one_trial(self):
        self.project.mix = self.track.audio.name
        self.project.save()
        for _ in range(3):
            self.client.post(reverse('studio:export', args=[self.project.pk]))
        self.assertEqual(Export.objects.count(), 1)
        self.assertEqual(ExportAllowance.objects.get(artist=self.artist).free_used, 1)

    def test_lost_upload_response_retry_is_safe_even_with_stale_revision(self):
        url = reverse('studio:add_track', args=[self.project.pk])
        response = self.client.post(url, {'audio': recording(), 'upload_key': 'same-request'})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(url, {'upload_key': 'same-request', 'revision': 'stale'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['reused'])
        self.assertEqual(self.project.tracks.count(), 2)

    def test_removed_track_is_recoverable_and_source_stays_private(self):
        revision = self.project.updated_at.isoformat()
        self.client.post(reverse('studio:delete_track', args=[self.track.pk]), {'revision': revision})
        self.assertFalse(Track.objects.filter(pk=self.track.pk).exists())
        self.assertTrue(private_storage.exists(self.track.audio.name))
        self.assertEqual(self.client.get(reverse('studio:track_audio', args=[self.track.pk])).status_code, 404)
        self.project.refresh_from_db()
        response = self.client.post(reverse('studio:restore_track', args=[self.track.pk]), {'revision': self.project.updated_at.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Track.objects.filter(pk=self.track.pk).exists())

    @override_settings(STUDIO_ARTIST_STORAGE_MIB=.02)
    def test_quota_counts_shared_files_once_and_refuses_new_audio(self):
        Track.objects.create(project=self.project, audio=self.track.audio.name, name='Shared')
        self.assertEqual(usage(self.artist.pk, private_storage), self.track.audio.size)
        with artist_storage(self.artist.pk), self.assertRaises(ValidationError):
            private_storage.save('audio/quota.wav', recording())
        self.assertFalse(Path(private_storage.location, 'audio/quota.wav').exists())

    def test_disk_pressure_refuses_write_before_creating_file(self):
        with patch('studio.capacity.shutil.disk_usage') as disk:
            disk.return_value.free = 0
            with self.assertRaises(ValidationError):
                private_storage.save('audio/full.wav', recording())
        self.assertFalse(private_storage.exists('audio/full.wav'))

    def test_health_requires_admin(self):
        self.assertEqual(self.client.get(reverse('studio:health')).status_code, 403)
        admin = CustomUser.objects.create_user(username='studio_health_admin', role=Role.ADMIN)
        self.client.force_login(admin)
        response = self.client.get(reverse('studio:health'))
        self.assertContains(response, 'Audio worker needs attention')
        self.assertContains(response, 'Available storage')

    def test_trash_cleanup_preserves_exported_file(self):
        Export.objects.create(project=self.project, audio=self.track.audio.name, status='free')
        Track.all_objects.filter(pk=self.track.pk).update(deleted_at=timezone.now() - timedelta(days=8))
        age = (timezone.now() - timedelta(days=10)).timestamp()
        os.utime(self.track.audio.path, (age, age))
        call_command('cleanup_studio_audio', apply=True, stdout=io.StringIO())
        self.assertFalse(Track.all_objects.filter(pk=self.track.pk).exists())
        self.assertTrue(private_storage.exists(Export.objects.get().audio.name))

    def test_expired_render_input_cleanup_matches_preview(self):
        job = AudioJob.objects.create(track=self.track, operation='mix', source=self.track.audio.name, status='failed')
        part = AudioJobInput.objects.create(job=job, audio=recording(), settings={})
        AudioJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=10))
        age = (timezone.now() - timedelta(days=10)).timestamp()
        os.utime(part.audio.path, (age, age))
        output = io.StringIO()
        call_command('cleanup_studio_audio', stdout=output)
        self.assertIn('Would remove 1', output.getvalue())
        call_command('cleanup_studio_audio', apply=True, stdout=io.StringIO())
        self.assertFalse(private_storage.exists(part.audio.name))
        self.assertTrue(private_storage.exists(self.track.audio.name))
