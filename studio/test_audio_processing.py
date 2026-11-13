import io
import tempfile
import wave
import json
import os
import math
import random
import struct
import importlib.util
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from users.models import CustomUser, Role
from studio.models import Project, Track, AudioJob, Instrumental
from studio.storage import private_storage
from studio.audio_processing import process, options_for


def recording():
    data = io.BytesIO()
    rate = 44100
    noise = random.Random(4)
    x = [int((.2 * math.sin(2 * math.pi * 220 * i / rate) + .02 * noise.gauss(0, 1)) * 32767) for i in range(rate)]
    with wave.open(data, 'wb') as audio:
        audio.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        audio.writeframes(struct.pack('<' + 'h' * len(x), *x))
    return ContentFile(data.getvalue(), name='take.wav')


class AudioProcessingTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.storage = patch.object(private_storage, 'location', self.folder.name)
        self.storage.start()
        self.addCleanup(self.storage.stop)
        self.artist = CustomUser.objects.create_user(username='audio_artist', role=Role.ARTIST)
        self.other = CustomUser.objects.create_user(username='audio_other', role=Role.ARTIST)
        self.client.force_login(self.artist)
        self.project = Project.objects.create(artist=self.artist, title='Sound', category='gospel')
        self.track = Track.objects.create(project=self.project, name='Voice', audio=recording())

    def queue(self, operation='denoise', **options):
        return self.client.post(reverse('studio:audio_queue', args=[self.track.pk]), {'operation': operation, **options})

    def test_auto_master_previews_audio_without_saving_project(self):
        url = reverse('studio:audio_master', args=[self.project.pk])
        original = recording().read()
        response = self.client.post(url, {'audio': ContentFile(original, name='mix.wav')})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'audio/wav')
        mastered = b''.join(response.streaming_content)
        response.close()
        with wave.open(io.BytesIO(mastered), 'rb') as result:
            self.assertEqual(result.getnframes(), 44100)
            self.assertNotEqual(result.readframes(44100), original[44:])
        self.project.refresh_from_db()
        self.assertFalse(self.project.mix)
        self.assertEqual(self.client.post(url).status_code, 400)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(url, {'audio': recording()}).status_code, 404)

    def test_ownership_and_queue_limit(self):
        self.assertEqual(self.queue().status_code, 200)
        self.assertEqual(self.queue().status_code, 200)
        self.assertEqual(self.queue().status_code, 409)
        self.client.force_login(self.other)
        self.assertEqual(self.queue().status_code, 404)
        job = AudioJob.objects.first()
        self.assertEqual(self.client.get(reverse('studio:audio_job', args=[job.pk])).status_code, 404)

    def test_repeated_extraction_requests_reuse_the_active_job(self):
        with patch('studio.audio_processing.available', return_value={'separate': True}):
            first = self.queue('separate', permission='yes')
            second = self.queue('separate', permission='yes')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['id'], second.json()['id'])
        self.assertTrue(second.json()['reused'])
        self.assertEqual(AudioJob.objects.count(), 1)

    def test_noise_processing_preview_and_apply_preserve_source(self):
        job_id = self.queue(strength=10, cutoff=60, hum='50').json()['id']
        job = AudioJob.objects.get(pk=job_id)
        original = self.track.audio.name
        process(job)
        self.assertEqual(job.status, 'ready')
        with job.result.open('rb') as stream, wave.open(stream) as audio:
            self.assertEqual(audio.getnframes(), 44100)
        url = reverse('studio:audio_apply', args=[job.pk])
        self.assertEqual(self.client.post(url, {'revision': 'old'}).status_code, 409)
        self.assertEqual(self.client.post(url, {'revision': self.project.updated_at.isoformat()}).status_code, 200)
        self.track.refresh_from_db()
        self.assertTrue(self.track.muted)
        self.assertEqual(self.track.audio.name, original)
        self.assertEqual(self.project.tracks.count(), 2)
        self.assertEqual(job.source.name, original)
        self.assertEqual(self.project.tracks.exclude(pk=self.track.pk).get().audio.name, job.result.name)
        self.assertEqual(self.client.post(url, {'revision': self.project.updated_at.isoformat()}).status_code, 404)

    def test_invalid_options_and_category_rules(self):
        self.assertEqual(self.queue(strength='nan').status_code, 400)
        self.assertEqual(self.queue('separate').status_code, 400)
        with patch('studio.audio_processing.available', return_value={'separate': False}):
            self.assertEqual(self.queue('separate', permission='yes').status_code, 503)
        self.project.category = 'acapella'
        self.project.save()
        self.assertEqual(self.queue('separate', permission='yes').status_code, 400)
        for category in ['acapella', 'gospel', 'secular']:
            self.project.category = category
            self.project.save()
            AudioJob.objects.all().delete()
            with patch('studio.audio_processing.available', return_value={'tune': True}):
                self.assertEqual(self.queue('tune', key=9, scale='minor').status_code, 200)

    def test_import_conversion_and_malformed_audio(self):
        response = self.client.post(reverse('studio:audio_convert'), {'audio': recording()})
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(self.client.post(reverse('studio:audio_convert'), {'audio': ContentFile(b'bad', name='bad.mp3')}).status_code, 400)

    def test_extracted_library_copy_is_reusable(self):
        job = AudioJob.objects.create(track=self.track, operation='separate', status='ready', source=recording(), result=recording())
        response = self.client.post(reverse('studio:audio_apply', args=[job.pk]), {'revision': self.project.updated_at.isoformat(), 'library': 'yes'})
        self.assertEqual(response.status_code, 200)
        item = Instrumental.objects.get()
        self.assertEqual(item.audio.name, job.result.name)
        response = self.client.post(reverse('studio:instrumental_use', args=[item.pk]))
        self.assertEqual(response.status_code, 302)
        copied = Track.objects.exclude(pk=self.track.pk).get()
        self.assertEqual(copied.kind, 'backing')
        self.assertEqual(copied.audio.name, item.audio.name)

    def test_tuning_targets_requested_scale(self):
        self.assertEqual(options_for('tune', {'key': '2', 'scale': 'minor'})['key'], 2)
        with self.assertRaises(ValueError):
            options_for('tune', {'speed': 'inf'})

    def test_worker_drains_queue_and_records_failures(self):
        from django.core.management import call_command
        job = AudioJob.objects.get(pk=self.queue().json()['id'])
        call_command('process_studio_audio', once=True)
        job.refresh_from_db()
        self.assertEqual(job.status, 'ready')
        job.status = 'running'
        job.save(update_fields=["status"])
        call_command('process_studio_audio', once=True)
        job.refresh_from_db()
        self.assertEqual(job.status, 'running')
        with patch('studio.management.commands.process_studio_audio.process', side_effect=RuntimeError('engine failed')):
            with self.assertLogs('studio.management.commands.process_studio_audio', level='ERROR'):
                call_command('process_studio_audio', once=True, retry_interrupted=True)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        self.assertNotIn('engine failed', job.error)

    def test_real_pitch_correction_preserves_length_and_moves_note(self):
        import importlib.util
        if importlib.util.find_spec('pyworld') is None:
            self.skipTest('Optional pitch engine is not installed')
        import numpy as np
        import pyworld as pw
        from pathlib import Path
        from studio.audio_processing import tune
        rate = 44100
        x = .25 * np.sin(2 * np.pi * 230 * np.arange(rate) / rate)
        source, result = Path(self.folder.name) / 'detuned.wav', Path(self.folder.name) / 'tuned.wav'
        with wave.open(str(source), 'wb') as audio:
            audio.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            audio.writeframes((x * 32767).astype('<i2').tobytes())
        tune(source, result, {'key': 0, 'scale': 'chromatic', 'strength': 1, 'speed': 0})
        with wave.open(str(result), 'rb') as audio:
            self.assertEqual(audio.getnframes(), rate)
            y = np.frombuffer(audio.readframes(rate), dtype='<i2').astype(float) / 32768
        f0, _ = pw.dio(y, rate)
        self.assertAlmostEqual(float(np.median(f0[f0 > 0])), 233.08, delta=2)

    def ready_job(self, operation='denoise'):
        return AudioJob.objects.create(track=self.track, operation=operation, status='ready', source=recording(), result=recording())

    def test_job_endpoints_are_private_artist_only_and_csrf_protected(self):
        job = self.ready_job()
        paths = [reverse(name, args=[job.pk]) for name in ['studio:audio_job', 'studio:audio_job_audio', 'studio:audio_apply']]
        paths.append(reverse('studio:audio_queue', args=[self.track.pk]))
        self.client.force_login(self.other)
        for path in paths:
            self.assertEqual(self.client.post(path).status_code, 404)
        fan = CustomUser.objects.create_user(username='audio_fan', role=Role.FAN)
        self.client.force_login(fan)
        for path in paths:
            self.assertEqual(self.client.post(path).status_code, 403)
        self.client.logout()
        for path in paths:
            self.assertEqual(self.client.post(path).status_code, 302)
        from django.test import Client
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.artist)
        for path in paths[2:]:
            self.assertEqual(protected.post(path).status_code, 403)

    def test_preview_requires_ready_job_and_is_not_publicly_cached(self):
        job = self.ready_job()
        url = reverse('studio:audio_job_audio', args=[job.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['Content-Type'], 'audio/wav')
        self.assertTrue(b''.join(response.streaming_content).startswith(b'RIFF'))
        response.close()
        job.status = 'queued'
        job.save()
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_apply_preserves_timing_gain_and_invalidates_saved_mix(self):
        self.track.offset, self.track.gain = 3.5, .7
        self.track.trim_start, self.track.trim_end = .1, .8
        self.track.save()
        self.project.mix = recording()
        self.project.save()
        job = self.ready_job()
        self.assertEqual(self.client.post(reverse('studio:audio_apply', args=[job.pk]), {'revision': self.project.updated_at.isoformat()}).status_code, 200)
        copied = self.project.tracks.exclude(pk=self.track.pk).get()
        self.assertEqual((copied.offset, copied.gain, copied.trim_start, copied.trim_end), (3.5, .7, .1, .8))
        self.project.refresh_from_db()
        self.assertFalse(self.project.mix)
        self.assertFalse(copied.muted)

    def test_track_limit_rejects_apply_without_spending_result(self):
        for i in range(11):
            Track.objects.create(project=self.project, name=f'Voice {i}', audio=recording())
        job = self.ready_job()
        response = self.client.post(reverse('studio:audio_apply', args=[job.pk]), {'revision': self.project.updated_at.isoformat()})
        self.assertEqual(response.status_code, 409)
        job.refresh_from_db()
        self.track.refresh_from_db()
        self.assertEqual(job.status, 'ready')
        self.assertFalse(self.track.muted)
        self.assertEqual(self.project.tracks.count(), 12)

    def test_processed_preset_is_audio_copy_and_does_not_duplicate_preset(self):
        self.track.kind, self.track.beat_preset, self.track.beat_bpm = 'beat', 'gospel-worship', 80
        self.track.save()
        job = self.ready_job()
        self.assertEqual(self.client.post(reverse('studio:audio_apply', args=[job.pk]), {'revision': self.project.updated_at.isoformat()}).status_code, 200)
        self.assertEqual(self.project.tracks.filter(kind='beat').count(), 1)
        self.assertEqual(self.project.tracks.exclude(pk=self.track.pk).get().kind, 'backing')

    def test_extracted_audio_cannot_open_or_overwrite_piano_roll(self):
        item = Instrumental.objects.create(artist=self.artist, title='Extracted', category='gospel', config={'imported': True, 'bpm': 80}, audio=recording())
        self.assertRedirects(self.client.get(reverse('studio:compose', args=[item.pk])), reverse('studio:instrumentals'))
        self.assertEqual(self.client.post(reverse('studio:compose_save', args=[item.pk])).status_code, 400)
        item.refresh_from_db()
        self.assertTrue(item.config['imported'])

    def test_pending_processing_reconnects_when_project_reopens(self):
        job = self.ready_job('separate')
        response = self.client.get(reverse('studio:editor', args=[self.project.pk]))
        self.assertEqual(response.context['tracks'][0]['audio_job'], job.pk)
        self.assertEqual(response.context['tracks'][0]['audio_operation'], 'separate')

    def test_compressed_imports_convert_to_editable_wav(self):
        from studio.video_render import run_ffmpeg
        source = Path(self.folder.name) / 'input.wav'
        source.write_bytes(recording().read())
        for extension, codec in [('mp3', 'libmp3lame'), ('m4a', 'aac'), ('flac', 'flac'), ('ogg', 'libvorbis')]:
            with self.subTest(extension=extension):
                output = source.with_suffix('.' + extension)
                run_ffmpeg(['-i', str(source), '-c:a', codec, str(output)])
                response = self.client.post(reverse('studio:audio_convert'), {'audio': ContentFile(output.read_bytes(), name=output.name)})
                self.assertEqual(response.status_code, 200)
                with wave.open(io.BytesIO(b''.join(response.streaming_content)), 'rb') as audio:
                    self.assertEqual((audio.getsampwidth(), audio.getframerate(), audio.getnchannels()), (2, 44100, 2))
                    self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), 1, delta=.1)
                response.close()

    def test_original_compressed_files_upload_directly_into_tracks(self):
        from studio.video_render import run_ffmpeg
        from django.db import connection
        source = Path(self.folder.name) / 'direct.wav'
        source.write_bytes(recording().read())
        for extension, codec in [('mp3', 'libmp3lame'), ('m4a', 'aac'), ('flac', 'flac'), ('ogg', 'libvorbis')]:
            with self.subTest(extension=extension):
                encoded = source.with_suffix('.' + extension)
                run_ffmpeg(['-i', str(source), '-c:a', codec, str(encoded)])
                self.project.refresh_from_db()
                # TestCase already wraps the test in a transaction. Conversion
                # must not open another atomic block or lock before FFmpeg runs.
                from studio.audio_import import run_ffmpeg as actual_ffmpeg
                depth = len(connection.atomic_blocks)
                def unlocked_conversion(arguments):
                    self.assertEqual(len(connection.atomic_blocks), depth)
                    return actual_ffmpeg(arguments)
                with patch('studio.audio_import.run_ffmpeg', side_effect=unlocked_conversion):
                    response = self.client.post(reverse('studio:add_track', args=[self.project.pk]), {
                        'audio': ContentFile(encoded.read_bytes(), name=encoded.name),
                        'name': 'Imported ' + extension, 'kind': 'backing', 'offset': '3.5', 'original_file': '1',
                        'revision': self.project.updated_at.isoformat(),
                    })
                self.assertEqual(response.status_code, 200, response.content)
                track = self.project.tracks.get(name='Imported ' + extension)
                self.assertEqual(track.offset, 3.5)
                self.assertEqual(track.kind, 'backing')
                with track.audio.open('rb') as stream, wave.open(stream) as audio:
                    self.assertEqual((audio.getsampwidth(), audio.getframerate(), audio.getnchannels()), (2, 44100, 2))
                    self.assertAlmostEqual(audio.getnframes() / audio.getframerate(), 1, delta=.1)

    def test_original_import_validation_preserves_project_on_failure(self):
        url = reverse('studio:add_track', args=[self.project.pk])
        original_count = self.project.tracks.count()
        response = self.client.post(url, {'audio': ContentFile(b'bad', name='bad.mp3'), 'kind': 'backing'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.project.tracks.count(), original_count)
        with patch('studio.audio_import.normalize_upload') as normalize:
            response = self.client.post(url, {'audio': recording(), 'revision': 'stale'})
            self.assertEqual(response.status_code, 409)
            normalize.assert_not_called()

    def test_low_sample_rate_import_is_normalized_for_vocal_processing(self):
        original = io.BytesIO()
        with wave.open(original, 'wb') as audio:
            audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            audio.writeframes(b'\x00\x00' * 8000)
        response = self.client.post(reverse('studio:add_track', args=[self.project.pk]), {
            'audio': ContentFile(original.getvalue(), name='voice.wav'),
            'original_file': '1', 'kind': 'vocal', 'name': 'Imported low rate',
        })
        self.assertEqual(response.status_code, 200)
        track = self.project.tracks.get(name='Imported low rate')
        with track.audio.open('rb') as stream, wave.open(stream) as audio:
            self.assertEqual(audio.getframerate(), 44100)
            self.assertEqual(audio.getnframes(), 44100)

    def test_overlong_import_is_rejected_instead_of_truncated(self):
        source = io.BytesIO()
        with wave.open(source, 'wb') as audio:
            audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            audio.writeframes(b'\x00\x00' * (8000 * 361))
        response = self.client.post(reverse('studio:audio_convert'), {'audio': ContentFile(source.getvalue(), name='long.wav')})
        self.assertEqual(response.status_code, 400)
        self.assertIn('six minutes', response.json()['error'])

    def test_songs_longer_than_five_minutes_import_without_truncation(self):
        source = io.BytesIO()
        with wave.open(source, 'wb') as audio:
            audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
            audio.writeframes(b'\x00\x00' * (8000 * 333))
        response = self.client.post(reverse('studio:audio_convert'), {'audio': ContentFile(source.getvalue(), name='song.mpeg')})
        self.assertEqual(response.status_code, 200)
        with wave.open(io.BytesIO(b''.join(response.streaming_content)), 'rb') as audio:
            self.assertEqual(audio.getnframes(), 44100 * 333)
        response.close()

    def test_six_minute_audio_limit_accepts_boundary_and_rejects_extra_frame(self):
        from studio.views import validate_audio
        from django.core.exceptions import ValidationError
        for extra in (0, 1):
            source = io.BytesIO()
            with wave.open(source, 'wb') as audio:
                audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\x00\x00' * (8000 * 360 + extra))
            data = ContentFile(source.getvalue(), name='boundary.wav')
            if extra:
                with self.assertRaises(ValidationError):
                    validate_audio(data)
            else:
                self.assertIs(validate_audio(data), data)

    @skipUnless(importlib.util.find_spec('numpy'), 'Optional NumPy is not installed')
    def test_real_noise_reduction_attenuates_hum_and_preserves_voice(self):
        import numpy as np
        rate = 44100
        times = np.arange(rate * 2) / rate
        original = .2 * np.sin(2 * np.pi * 50 * times) + .2 * np.sin(2 * np.pi * 220 * times)
        source = io.BytesIO()
        with wave.open(source, 'wb') as audio:
            audio.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
            audio.writeframes((original * 32767).astype('<i2').tobytes())
        job = AudioJob.objects.create(track=self.track, operation='denoise', options={'cutoff': 20, 'strength': 1, 'hum': '50'}, source=ContentFile(source.getvalue(), name='hum.wav'))
        process(job)
        with job.result.open('rb') as stream, wave.open(stream) as audio:
            result = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2') / 32768
        def amplitude(x, hz):
            x = x[rate // 2:]
            t = np.arange(len(x)) / rate
            return abs(np.mean(x * np.exp(-2j * np.pi * hz * t))) * 2
        self.assertLess(amplitude(result, 50), amplitude(original, 50) * .25)
        self.assertGreater(amplitude(result, 220), amplitude(original, 220) * .6)

    @skipUnless(os.environ.get('STUDIO_TEST_EXTRACTION') == '1', 'Set STUDIO_TEST_EXTRACTION=1 to run real Demucs inference')
    def test_real_extraction_queue_worker_preview_apply_and_resave(self):
        import hashlib
        from django.core.management import call_command
        self.track.kind = 'backing'
        self.track.save()
        with self.track.audio.open('rb') as stream:
            original_hash = hashlib.sha256(stream.read()).hexdigest()
        response = self.queue('separate', permission='yes')
        self.assertEqual(response.status_code, 200)
        job = AudioJob.objects.get(pk=response.json()['id'])
        call_command('process_studio_audio', once=True)
        job.refresh_from_db()
        self.assertEqual(job.status, 'ready', job.error)
        response = self.client.get(reverse('studio:audio_job_audio', args=[job.pk]))
        processed = b''.join(response.streaming_content)
        response.close()
        self.assertTrue(processed.startswith(b'RIFF'))
        response = self.client.post(reverse('studio:audio_apply', args=[job.pk]), {'revision': self.project.updated_at.isoformat()})
        self.assertEqual(response.status_code, 200)
        self.track.refresh_from_db()
        self.assertTrue(self.track.muted)
        with self.track.audio.open('rb') as stream:
            self.assertEqual(hashlib.sha256(stream.read()).hexdigest(), original_hash)
        self.project.refresh_from_db()
        tracks = list(self.project.tracks.values('id', 'gain', 'offset', 'trim_start', 'trim_end', 'muted'))
        response = self.client.post(reverse('studio:save', args=[self.project.pk]), {'revision': self.project.updated_at.isoformat(), 'tracks': json.dumps(tracks), 'audio': ContentFile(processed, name='mix.wav')})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse('studio:export', args=[self.project.pk]))
        self.assertEqual(response.status_code, 302)
        from studio.models import Export
        export = Export.objects.get(project=self.project)
        with export.audio.open('rb') as stream:
            self.assertEqual(stream.read(), processed)

    @skipUnless(importlib.util.find_spec('pyworld'), 'Optional pitch engine is not installed')
    def test_real_vocal_tuning_queue_and_apply_in_every_category(self):
        from django.core.management import call_command
        for category in ['gospel', 'acapella', 'secular']:
            with self.subTest(category=category):
                project = Project.objects.create(artist=self.artist, title='Tune', category=category)
                track = Track.objects.create(project=project, name='Solo', kind='vocal', audio=recording())
                response = self.client.post(reverse('studio:audio_queue', args=[track.pk]), {'operation': 'tune', 'key': 9, 'scale': 'minor', 'strength': .8, 'speed': 40})
                self.assertEqual(response.status_code, 200)
                job = AudioJob.objects.get(pk=response.json()['id'])
                call_command('process_studio_audio', once=True)
                job.refresh_from_db()
                self.assertEqual(job.status, 'ready', job.error)
                self.assertEqual(self.client.post(reverse('studio:audio_apply', args=[job.pk]), {'revision': project.updated_at.isoformat()}).status_code, 200)
                track.refresh_from_db()
                self.assertTrue(track.muted)
                self.assertEqual(project.tracks.exclude(pk=track.pk).get().kind, 'vocal')
