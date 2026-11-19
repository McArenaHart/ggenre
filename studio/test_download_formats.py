import tempfile
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Export, ExportAllowance, Project, StudioMaintenance
from .storage import private_storage
from .tests import wav_upload
from users.models import CustomUser, Role


class DownloadFormatTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        storage = patch.object(private_storage, 'location', folder.name)
        storage.start()
        self.addCleanup(storage.stop)
        self.artist = CustomUser.objects.create_user(username='formats', role=Role.ARTIST)
        self.project = Project.objects.create(artist=self.artist, title='Formats', category='secular', mix=wav_upload(1))
        self.export = Export.objects.create(project=self.project, audio=self.project.mix.name, status='free')
        self.allowance = ExportAllowance.objects.create(artist=self.artist, free_used=1)
        self.client.force_login(self.artist)
        self.url = reverse('studio:download', args=[self.export.pk])

    def test_real_formats_and_repeat_downloads_preserve_trial(self):
        expected = {'mp3': ('audio/mpeg', b'ID3'), 'm4a': ('audio/mp4', b'ftyp'),
                    'flac': ('audio/flac', b'fLaC'), 'ogg': ('audio/ogg', b'OggS')}
        for extension, (mime, signature) in expected.items():
            with self.subTest(extension=extension):
                constructor, folders = tempfile.TemporaryDirectory, []
                def make_folder(*args, **kwargs):
                    folder = constructor(*args, **kwargs)
                    folders.append(folder.name)
                    return folder
                with patch('studio.download_formats.tempfile.TemporaryDirectory', side_effect=make_folder):
                    response = self.client.get(self.url, {'format': extension})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Type'], mime)
                self.assertIn('.' + extension, response['Content-Disposition'])
                data = b''.join(response.streaming_content)
                self.assertIn(signature, data[:32])
                response.close()
                from pathlib import Path
                self.assertFalse(Path(folders[0]).exists())
        self.allowance.refresh_from_db()
        self.assertEqual(self.allowance.free_used, 1)
        self.assertEqual(Export.objects.count(), 1)

    def test_invalid_formats_and_unapproved_exports_never_encode(self):
        with patch('studio.download_formats.run_ffmpeg') as encode:
            self.assertEqual(self.client.get(self.url, {'format': '../mp3'}).status_code, 400)
            self.export.status = 'pending'
            self.export.save()
            self.assertEqual(self.client.get(self.url, {'format': 'mp3'}).status_code, 404)
            encode.assert_not_called()

    def test_other_artist_cannot_convert_private_export(self):
        other = CustomUser.objects.create_user(username='other_formats', role=Role.ARTIST)
        self.client.force_login(other)
        self.assertEqual(self.client.get(self.url, {'format': 'mp3'}).status_code, 404)

    def test_conversion_capacity_returns_retry_instead_of_parallel_work(self):
        StudioMaintenance.objects.create(key='audio-download-conversion', lease_until=timezone.now() + timedelta(seconds=60))
        response = self.client.get(self.url, {'format': 'mp3'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response['Retry-After'], '5')
