import io
import tempfile
import wave
from datetime import timedelta
from unittest.mock import patch
from urllib.error import HTTPError
from django.core.files.base import ContentFile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from users.models import CustomUser, Role
from .models import AudioJob, Project, Track
from .storage import private_storage
from .job_control import claim_job
from .remote_extraction import extract, token, RemotePaused, configuration_errors
from .test_portable_studio import recording


def result_wav(seconds=1):
    data = io.BytesIO()
    with wave.open(data, 'wb') as audio:
        audio.setparams((2, 2, 44100, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'\x10\x27' * int(seconds * 44100 * 2))
    return data.getvalue()


@override_settings(STUDIO_EXTRACTION_BACKEND='modal')
class RemoteExtractionTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        storage = patch.object(private_storage, 'location', folder.name)
        storage.start()
        self.addCleanup(storage.stop)
        self.artist = CustomUser.objects.create_user(username='remote_artist', role=Role.ARTIST)
        self.project = Project.objects.create(artist=self.artist, title='Remote', category='gospel')
        self.track = Track.objects.create(project=self.project, name='Voice', audio=recording())
        self.job = AudioJob.objects.create(track=self.track, operation='separate', source=self.track.audio.name)
        self.client = Client(enforce_csrf_checks=True)

    def enabled(self, **extra):
        return override_settings(**{
            'STUDIO_REMOTE_EXTRACTION_ENABLED': True, 'STUDIO_REMOTE_BILLING_VERIFIED': True,
            'STUDIO_REMOTE_TEST_JOB_ID': self.job.pk, 'STUDIO_REMOTE_WORKER_URL': 'https://pilot.modal.run',
            'STUDIO_PUBLIC_BASE_URL': 'https://www.ggenre.com', 'STUDIO_REMOTE_PROXY_KEY': 'test-key',
            'STUDIO_REMOTE_PROXY_SECRET': 'test-secret', **extra})

    def running(self):
        self.job = claim_job()
        self.assertIsNotNone(self.job)
        self.job.remote_nonce = 'a' * 32
        self.job.save(update_fields=['remote_nonce'])

    def put(self, signature=None, data=None):
        return self.client.put(reverse('studio:remote_audio', args=[self.job.pk, 'result']), data=result_wav() if data is None else data,
            content_type='audio/wav', HTTP_X_GGENRE_JOB_TOKEN=signature or token(self.job, 'result'))

    def test_disabled_remote_jobs_wait_and_do_not_block_other_tools(self):
        self.assertIsNone(claim_job())
        other = AudioJob.objects.create(track=self.track, operation='denoise', source=self.track.audio.name)
        self.assertEqual(claim_job().pk, other.pk)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'queued')

    def test_only_the_selected_job_can_run(self):
        other = AudioJob.objects.create(track=self.track, operation='separate', source=self.track.audio.name)
        with self.enabled(STUDIO_REMOTE_TEST_JOB_ID=other.pk):
            self.assertEqual(claim_job().pk, other.pk)

    def test_billing_verification_and_credentials_are_required(self):
        with self.enabled(STUDIO_REMOTE_BILLING_VERIFIED=False):
            self.assertIsNone(claim_job())
        with self.enabled(STUDIO_REMOTE_PROXY_SECRET=''):
            self.assertIsNone(claim_job())
        with self.enabled(STUDIO_REMOTE_WORKER_URL='http://example.com'):
            self.assertTrue(configuration_errors())

    def test_callback_requires_scoped_signed_auth_not_a_session(self):
        with self.enabled():
            self.running()
        source_url = reverse('studio:remote_audio', args=[self.job.pk, 'source'])
        self.client.force_login(self.artist)
        self.assertEqual(self.client.get(source_url).status_code, 403)
        self.assertEqual(self.client.get(source_url, HTTP_X_GGENRE_JOB_TOKEN=token(self.job, 'result')).status_code, 403)
        response = self.client.get(source_url, HTTP_X_GGENRE_JOB_TOKEN=token(self.job, 'source'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(b''.join(response.streaming_content)), self.track.audio.size)
        response.close()
        self.assertEqual(self.put().status_code, 200)

    def test_cancelled_and_expired_tokens_cannot_write_results(self):
        with self.enabled():
            self.running()
        with patch('django.core.signing.TimestampSigner.timestamp', return_value='1'):
            expired = token(self.job, 'result')
        self.assertEqual(self.put(expired).status_code, 403)
        AudioJob.objects.filter(pk=self.job.pk).update(status='cancelled')
        self.assertEqual(self.put().status_code, 403)

    def test_remote_result_is_validated_and_duplicate_callback_reuses_file(self):
        with self.enabled():
            self.running()
        self.assertEqual(self.put(data=b'not audio').status_code, 400)
        self.assertEqual(self.put(data=result_wav(.5)).status_code, 400)
        self.assertEqual(self.put().status_code, 200)
        self.job.refresh_from_db()
        name = self.job.result.name
        self.assertEqual(self.put().status_code, 200)
        self.job.refresh_from_db()
        self.assertEqual(self.job.result.name, name)

    def test_end_to_end_transport_saves_result_without_local_model(self):
        with self.enabled():
            self.running()
            def callback(payload):
                self.assertNotIn('test-secret', str(payload))
                response = self.put(payload['tokens']['result'])
                self.assertEqual(response.status_code, 200, response.content)
                return {'accepted': True}
            with patch('studio.remote_extraction.send', side_effect=callback) as send, patch('studio.audio_processing.subprocess.Popen') as local:
                from .audio_processing import process
                process(self.job)
            self.assertEqual(send.call_count, 1)
            local.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, 'ready')

    def test_lost_acknowledgement_does_not_dispatch_a_second_job(self):
        with self.enabled():
            self.running()
            def uncertain(payload):
                self.put(payload['tokens']['result'])
                raise TimeoutError()
            with patch('studio.remote_extraction.send', side_effect=uncertain) as send:
                extract(self.job, lambda: None)
            self.assertEqual(send.call_count, 1)
            AudioJob.objects.filter(pk=self.job.pk).update(status='running')
            self.job.refresh_from_db()
            with patch('studio.remote_extraction.send') as again:
                extract(self.job, lambda: None)
            again.assert_not_called()

    def test_provider_limit_pauses_queue_without_local_fallback(self):
        with self.enabled():
            self.running()
            with patch('studio.remote_extraction.send', side_effect=HTTPError('https://pilot.modal.run', 429, 'limited', {}, None)):
                with self.assertRaises(RemotePaused):
                    extract(self.job, lambda: None)
            self.job.refresh_from_db()
            self.assertEqual(self.job.status, 'queued')
            self.assertIsNone(claim_job())

    def test_remote_failure_is_reported_without_waiting_for_timeout(self):
        with self.enabled():
            self.running()
            self.job.remote_dispatched_at = timezone.now()
            self.job.error = 'Remote worker failed to extract this audio.'
            self.job.save(update_fields=['remote_dispatched_at', 'error'])
            from django.core.exceptions import ValidationError
            with self.assertRaises(ValidationError):
                extract(self.job, lambda: None)

    def test_remote_can_be_offered_without_installed_local_ai_packages(self):
        with patch('studio.audio_processing.available', return_value={'separate': False, 'tune': False, 'denoise': True}):
            from .audio_processing import processing_available
            self.assertTrue(processing_available()['separate'])

    def test_dispatch_uses_proxy_headers_without_following_redirects(self):
        from .remote_extraction import send, NoRedirect
        with self.enabled(), patch('studio.remote_extraction.build_opener') as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = b'{"accepted":true}'
            self.assertTrue(send({'job_id': 1})['accepted'])
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header('Modal-key'), 'test-key')
            self.assertEqual(request.get_header('Modal-secret'), 'test-secret')
            self.assertIsInstance(opener.call_args.args[0], NoRedirect)


class WorkerTransferTests(TestCase):
    def test_worker_rejects_foreign_hosts_and_other_job_paths(self):
        from remote_workers.transfer import validate_payload
        payload = {'job_id': 1, 'tokens': {action: 'x' * 30 for action in ('source', 'result', 'control')}}
        payload.update({action + '_url': f'https://www.ggenre.com/studio/remote-audio/1/{action}/' for action in ('source', 'result', 'control')})
        validate_payload(payload, 'https://www.ggenre.com')
        for url in ['https://evil.example/studio/remote-audio/1/source/', 'https://www.ggenre.com/admin/', 'http://www.ggenre.com/studio/remote-audio/1/source/']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_payload({**payload, 'source_url': url}, 'https://www.ggenre.com')
