import io
import os
import tempfile
import time
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from content.models import Content
from users.models import CustomUser, Role
from studio.models import AudioJob, Export, Instrumental, Project, Release, Track
from studio.storage import private_storage


class AudioCleanupTests(TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.patch = patch.object(private_storage, 'location', self.folder.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.root = Path(self.folder.name)
        (self.root / 'audio').mkdir()
        self.artist = CustomUser.objects.create_user(username='cleanup_artist', role=Role.ARTIST)
        self.project = Project.objects.create(artist=self.artist, title='Keep', category='gospel')
        self.track = Track.objects.create(project=self.project, name='Voice', audio=self.file())

    def file(self, days=45):
        name = f'audio/{uuid.uuid4().hex}.wav'
        path = self.root / name
        path.write_bytes(b'private recording')
        stamp = time.time() - days * 86400
        os.utime(path, (stamp, stamp))
        return name

    def exists(self, name):
        return (self.root / name).exists()

    def cleanup(self, **options):
        output = io.StringIO()
        call_command('cleanup_studio_audio', stdout=output, **options)
        return output.getvalue()

    def job(self, status, days=45, source=None, result=None):
        job = AudioJob.objects.create(track=self.track, operation='denoise', status=status,
                                      source=source or self.file(), result=result or self.file())
        AudioJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=days))
        job.refresh_from_db()
        return job

    def test_default_preview_never_changes_files_or_database(self):
        orphan = self.file()
        job = self.job('ready')
        output = self.cleanup()
        self.assertIn('Would remove 3', output)
        self.assertTrue(self.exists(orphan))
        job.refresh_from_db()
        self.assertEqual(job.status, 'ready')
        self.assertTrue(job.source)

    def test_removes_old_orphans_but_keeps_recent_or_unknown_files(self):
        old, recent = self.file(), self.file(days=1)
        unknown = self.root / 'audio' / 'manual-recording.wav'
        unknown.write_bytes(b'keep')
        video = self.root / 'collaborations'
        video.mkdir()
        (video / 'keep.mp4').write_bytes(b'keep')
        self.assertIn('Removed 1', self.cleanup(apply=True))
        self.assertFalse(self.exists(old))
        self.assertTrue(self.exists(recent))
        self.assertTrue(unknown.exists())
        self.assertTrue((video / 'keep.mp4').exists())
        self.assertTrue(self.exists(self.track.audio.name))

    def test_protects_every_reference_and_shared_export_release_snapshot(self):
        mix, exported, released, library = [self.file() for _ in range(4)]
        self.project.mix = mix
        self.project.save()
        Export.objects.create(project=self.project, audio=exported, status='free')
        content = Content.objects.create(artist=self.artist, title='Published', category='music')
        Release.objects.create(project=self.project, content=content, audio=released)
        Instrumental.objects.create(artist=self.artist, title='Saved backing', category='gospel', audio=library)
        self.cleanup(apply=True)
        for name in (mix, exported, released, library, self.track.audio.name):
            self.assertTrue(self.exists(name), name)
        # Re-saving a project cannot remove an older exported mix.
        self.project.mix = exported
        self.project.save()
        self.project.mix = ''
        self.project.save()
        self.cleanup(apply=True)
        self.assertTrue(self.exists(exported))

    def test_old_running_and_queued_jobs_are_never_expired(self):
        for status in ['running', 'queued']:
            job = self.job(status)
            self.cleanup(apply=True)
            job.refresh_from_db()
            self.assertEqual(job.status, status)
            self.assertTrue(self.exists(job.source.name))
            self.assertTrue(self.exists(job.result.name))

    def test_ready_results_expire_after_30_days_and_can_be_regenerated(self):
        job = self.job('ready')
        source, result = job.source.name, job.result.name
        self.cleanup(apply=True)
        job.refresh_from_db()
        self.assertEqual(job.status, 'expired')
        self.assertIn('Process the original', job.error)
        self.assertFalse(job.result)
        self.assertFalse(self.exists(source))
        self.assertFalse(self.exists(result))
        self.assertTrue(self.exists(self.track.audio.name))

    def test_used_results_and_originals_survive_expiring_job_references(self):
        job = self.job('applied', source=self.track.audio.name)
        name = job.result.name
        Track.objects.create(project=self.project, name='Processed', audio=name)
        self.cleanup(apply=True)
        job.refresh_from_db()
        self.assertFalse(job.source)
        self.assertFalse(job.result)
        self.assertTrue(self.exists(name))
        self.assertTrue(self.exists(self.track.audio.name))

    def test_unused_failed_task_files_expire_after_seven_days(self):
        job = self.job('failed', days=10)
        names = [job.source.name, job.result.name]
        self.cleanup(apply=True)
        job.refresh_from_db()
        self.assertEqual(job.status, 'failed')
        for name in names:
            self.assertFalse(self.exists(name))
        self.assertFalse(job.source)

    def test_new_jobs_and_recently_retried_results_keep_their_grace(self):
        recent = self.job('ready', days=3)
        retried = self.job('ready', result=self.file(days=1))
        self.cleanup(apply=True)
        for job in (recent, retried):
            job.refresh_from_db()
            self.assertEqual(job.status, 'ready')
            self.assertTrue(self.exists(job.result.name))

    def test_preview_protects_files_shared_by_expiring_and_active_jobs(self):
        old = self.job('applied')
        self.job('queued', source=old.source.name, result=old.result.name)
        self.assertIn('Would remove 0', self.cleanup())
        self.assertIn('Removed 0', self.cleanup(apply=True))

    def test_deleted_track_file_becomes_reclaimable(self):
        name = self.track.audio.name
        self.track.delete()
        self.cleanup(apply=True)
        self.assertFalse(self.exists(name))

    def test_in_app_schedule_reclaims_orphans_and_preserves_active_audio(self):
        from studio.maintenance import AudioMaintenance
        from studio.models import StudioMaintenance
        orphan = self.file()
        self.assertTrue(AudioMaintenance().run_due())
        self.assertFalse(self.exists(orphan))
        self.assertTrue(self.exists(self.track.audio.name))
        self.assertIsNotNone(StudioMaintenance.objects.get().last_success_at)
        self.assertFalse(AudioMaintenance().run_due())

    def test_final_reference_recheck_protects_newly_referenced_files(self):
        name = self.file()
        with patch('studio.management.commands.cleanup_studio_audio.is_referenced', return_value=True):
            self.cleanup(apply=True)
        self.assertTrue(self.exists(name))

    def test_invalid_retention_is_rejected_without_mutation(self):
        for options in ({'orphan_days': 0}, {'job_days': -1}, {'preview_days': 0}, {'apply': True, 'dry_run': True}):
            with self.assertRaises(CommandError):
                self.cleanup(**options)

    def test_symlinked_audio_directory_is_rejected_before_any_mutation(self):
        name = self.file()
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaises(CommandError):
                self.cleanup(apply=True)
        self.assertTrue(self.exists(name))

    def test_symlinked_file_is_skipped_even_when_its_name_is_generated(self):
        name = self.file()
        original = Path.is_symlink
        def is_link(path):
            return str(path) == str(self.root / name) or original(path)
        with patch.object(Path, 'is_symlink', is_link):
            self.cleanup(apply=True)
        self.assertTrue(self.exists(name))

    def test_symlink_cannot_delete_an_external_file(self):
        with tempfile.TemporaryDirectory() as external:
            target = Path(external) / 'outside.wav'
            target.write_bytes(b'keep')
            link = self.root / 'audio' / f'{uuid.uuid4().hex}.wav'
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest('Symlink creation is unavailable on this Windows account')
            self.cleanup(apply=True)
            self.assertTrue(target.exists())
