import tempfile
from unittest.mock import patch
from django.db import IntegrityError, transaction
from django.test import TestCase, Client
from django.urls import reverse
from studio.models import Export, ExportAllowance, Instrumental, Project
from studio.storage import private_storage
from studio.tests import wav_upload
from users.models import CustomUser, Role


class InstrumentalDownloadTests(TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        storage = patch.object(private_storage, 'location', folder.name)
        storage.start()
        self.addCleanup(storage.stop)
        self.artist = CustomUser.objects.create_user(username='download_artist', role=Role.ARTIST)
        self.other = CustomUser.objects.create_user(username='download_other', role=Role.ARTIST)
        self.admin = CustomUser.objects.create_user(username='download_admin', role=Role.ADMIN)
        self.client.force_login(self.artist)
        self.item = self.instrumental()

    def instrumental(self):
        return Instrumental.objects.create(artist=self.artist, title='Backing', category='gospel', config={'imported': True, 'bpm': 80}, audio=wav_upload())

    def request(self, item=None):
        return self.client.post(reverse('studio:instrumental_download', args=[(item or self.item).pk]))

    def test_instrumental_before_any_vocals_uses_one_trial(self):
        self.assertFalse(Project.objects.exists())
        self.assertEqual(self.request().status_code, 302)
        allowance = ExportAllowance.objects.get(artist=self.artist)
        self.assertEqual(allowance.free_used, 1)
        self.assertEqual(allowance.free_remaining, 1)
        export = Export.objects.get()
        self.assertEqual(export.instrumental, self.item)
        self.assertIsNone(export.project)
        self.assertEqual(export.audio.name, self.item.audio.name)

    def test_mix_and_instrumental_downloads_share_two_trials(self):
        self.request()
        project = Project.objects.create(artist=self.artist, title='Vocals', category='gospel', mix=wav_upload())
        self.client.post(reverse('studio:export', args=[project.pk]))
        self.request(self.instrumental())
        self.assertEqual(list(Export.objects.order_by('pk').values_list('status', flat=True)), ['free', 'free', 'pending'])
        self.assertEqual(ExportAllowance.objects.get(artist=self.artist).free_used, 2)
        pending = Export.objects.get(status='pending')
        self.assertEqual(self.client.get(reverse('studio:download', args=[pending.pk])).status_code, 404)

    def test_repeat_requests_and_downloads_do_not_use_another_trial(self):
        self.request()
        export = Export.objects.get()
        self.request()
        for _ in range(2):
            response = self.client.get(reverse('studio:download', args=[export.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment', response['Content-Disposition'])
            response.close()
        self.assertEqual(Export.objects.count(), 1)
        self.assertEqual(ExportAllowance.objects.get(artist=self.artist).free_used, 1)

    def test_new_saved_version_counts_again_and_old_download_remains_unchanged(self):
        self.request()
        first = Export.objects.get()
        original = first.audio.name
        self.item.audio = wav_upload(seconds=.2)
        self.item.save()
        self.request()
        first.refresh_from_db()
        self.assertEqual(first.audio.name, original)
        self.assertEqual(Export.objects.count(), 2)
        self.assertEqual(ExportAllowance.objects.get(artist=self.artist).free_used, 2)
        response = self.client.get(reverse('studio:download', args=[first.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_pending_requests_are_reused_and_existing_admin_approval_unlocks_them(self):
        ExportAllowance.objects.create(artist=self.artist, free_limit=0)
        self.request()
        self.request()
        export = Export.objects.get()
        self.assertEqual(export.status, 'pending')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('studio:export_reviews'))
        self.assertContains(response, self.item.title)
        self.assertContains(response, self.artist.username)
        self.client.post(reverse('studio:export_reviews'), {'decision': 'approved', 'export_id': export.pk})
        self.client.force_login(self.artist)
        response = self.client.get(reverse('studio:download', args=[export.pk]))
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_library_shows_shared_allowance_and_download_ready_state(self):
        response = self.client.get(reverse('studio:instrumentals'))
        self.assertContains(response, '2 trial downloads remaining')
        self.assertContains(response, 'uses one trial')
        self.request()
        response = self.client.get(reverse('studio:instrumentals'))
        self.assertContains(response, '1 trial download remaining')
        self.assertContains(response, reverse('studio:download', args=[Export.objects.get().pk]))

    def test_previews_and_using_instrumentals_do_not_consume_trials(self):
        response = self.client.get(reverse('studio:instrumental_audio', args=[self.item.pk]))
        response.close()
        self.client.post(reverse('studio:instrumental_use', args=[self.item.pk]))
        self.assertFalse(Export.objects.exists())
        self.assertFalse(ExportAllowance.objects.filter(artist=self.artist, free_used__gt=0).exists())

    def test_owner_permissions_post_only_and_csrf(self):
        self.request()
        export = Export.objects.get()
        self.client.force_login(self.other)
        self.assertEqual(self.request().status_code, 404)
        self.assertEqual(self.client.get(reverse('studio:download', args=[export.pk])).status_code, 404)
        self.client.force_login(self.artist)
        self.assertEqual(self.client.get(reverse('studio:instrumental_download', args=[self.item.pk])).status_code, 405)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.artist)
        self.assertEqual(protected.post(reverse('studio:instrumental_download', args=[self.item.pk])).status_code, 403)

    def test_unlimited_exports_and_admin_totals_include_instrumentals(self):
        ExportAllowance.objects.create(artist=self.artist, unlimited_exports=True)
        self.request()
        self.assertEqual(ExportAllowance.objects.get(artist=self.artist).free_used, 0)
        self.client.force_login(self.admin)
        response = self.client.get(reverse('studio:export_controls'))
        page = response.context['page']
        artist = next(user for user in page if user.pk == self.artist.pk)
        self.assertEqual(artist.export_total, 1)

    def test_admin_totals_include_mixed_sources_without_duplicate_counts(self):
        self.request()
        project = Project.objects.create(artist=self.artist, title='Mix', category='gospel', mix=wav_upload())
        Export.objects.create(project=project, audio=project.mix.name, status='free')
        Export.objects.create(project=project, audio=project.mix.name, status='pending')
        self.client.force_login(self.admin)
        response = self.client.get(reverse('studio:export_controls'))
        artist = next(user for user in response.context['page'] if user.pk == self.artist.pk)
        self.assertEqual(artist.export_total, 3)
        self.assertEqual(artist.pending_total, 1)

    def test_each_export_has_exactly_one_source(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Export.objects.create(audio=self.item.audio.name, status='free')
