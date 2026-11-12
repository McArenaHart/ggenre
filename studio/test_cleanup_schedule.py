from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from studio.maintenance import AudioMaintenance, LeaseLost, next_cleanup
from studio.models import StudioMaintenance


class CleanupScheduleTests(TestCase):
    def test_next_run_moves_to_next_day_after_scheduled_hour(self):
        before = datetime(2026, 11, 12, 0, 15, tzinfo=dt_timezone.utc)
        self.assertEqual(next_cleanup(before), before.replace(hour=1, minute=0))
        at = before.replace(hour=1, minute=0)
        self.assertEqual(next_cleanup(at), at + timedelta(days=1))

    def test_first_worker_runs_and_other_workers_do_not_repeat(self):
        with patch('studio.maintenance.call_command') as cleanup:
            self.assertTrue(AudioMaintenance().run_due())
            self.assertFalse(AudioMaintenance().run_due())
        cleanup.assert_called_once()
        self.assertTrue(cleanup.call_args.kwargs['apply'])
        state = StudioMaintenance.objects.get()
        self.assertIsNotNone(state.last_success_at)
        self.assertGreater(state.next_run_at, timezone.now())
        self.assertEqual(state.lease_token, '')

    def test_missed_run_is_caught_up_after_restart(self):
        yesterday = timezone.now() - timedelta(days=1)
        StudioMaintenance.objects.create(key='audio-cleanup', next_run_at=yesterday, lease_until=yesterday)
        with patch('studio.maintenance.call_command') as cleanup:
            self.assertTrue(AudioMaintenance().run_due())
        cleanup.assert_called_once()

    def test_active_lease_prevents_another_worker_running(self):
        now = timezone.now()
        StudioMaintenance.objects.create(key='audio-cleanup', next_run_at=now - timedelta(days=1), lease_until=now + timedelta(minutes=5), lease_token='other-worker')
        with patch('studio.maintenance.call_command') as cleanup:
            self.assertFalse(AudioMaintenance().run_due())
        cleanup.assert_not_called()

    def test_expired_lease_can_be_reclaimed(self):
        past = timezone.now() - timedelta(hours=1)
        StudioMaintenance.objects.create(key='audio-cleanup', next_run_at=past, lease_until=past, lease_token='dead-worker')
        with patch('studio.maintenance.call_command'):
            self.assertTrue(AudioMaintenance().run_due())

    def test_failure_retries_later_without_crashing_audio_worker(self):
        with patch('studio.maintenance.call_command', side_effect=RuntimeError('disk unavailable')):
            with self.assertLogs('studio.maintenance', level='ERROR'):
                self.assertFalse(AudioMaintenance().run_due())
        state = StudioMaintenance.objects.get()
        self.assertIn('disk unavailable', state.last_error)
        self.assertIsNone(state.last_success_at)
        self.assertGreater(state.next_run_at, timezone.now() + timedelta(minutes=59))
        self.assertEqual(state.lease_token, '')

    def test_heartbeat_renews_lease_and_stale_owner_cannot_continue(self):
        def execute(command, **kwargs):
            command.heartbeat()
            self.assertGreater(StudioMaintenance.objects.get().lease_until, timezone.now() + timedelta(minutes=9))
        with patch('studio.maintenance.call_command', side_effect=execute):
            self.assertTrue(AudioMaintenance().run_due())
        StudioMaintenance.objects.update(next_run_at=timezone.now() - timedelta(days=1))
        def stale(command, **kwargs):
            StudioMaintenance.objects.update(lease_token='new-owner')
            with self.assertRaises(LeaseLost):
                command.heartbeat()
            raise LeaseLost('stale')
        with patch('studio.maintenance.call_command', side_effect=stale):
            with self.assertLogs('studio.maintenance', level='ERROR'):
                self.assertFalse(AudioMaintenance().run_due())
        self.assertEqual(StudioMaintenance.objects.get().lease_token, 'new-owner')

    def test_database_error_does_not_kill_the_audio_loop(self):
        with patch.object(AudioMaintenance, 'run_due', side_effect=RuntimeError('database offline')):
            with self.assertLogs('studio.maintenance', level='ERROR'):
                AudioMaintenance().tick()

    def test_checks_are_throttled(self):
        scheduler = AudioMaintenance()
        with patch('studio.maintenance.time.monotonic', return_value=100):
            with patch.object(scheduler, 'run_due') as run:
                scheduler.tick()
                scheduler.tick()
        run.assert_called_once()

    @override_settings(STUDIO_AUTO_CLEANUP_ENABLED=False)
    def test_disabled_schedule_uses_no_database_queries(self):
        with self.assertNumQueries(0):
            AudioMaintenance().tick()

    @override_settings(STUDIO_CLEANUP_HOUR_UTC=25)
    def test_invalid_hour_cannot_run_cleanup(self):
        with patch('studio.maintenance.call_command') as run:
            with self.assertRaises(ValueError):
                AudioMaintenance().run_due()
        run.assert_not_called()
        self.assertFalse(StudioMaintenance.objects.exists())

    def test_worker_checks_schedule_but_batch_mode_does_not(self):
        with patch('studio.management.commands.process_studio_audio.AudioMaintenance') as scheduler:
            with patch('studio.management.commands.process_studio_audio.time.sleep', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    call_command('process_studio_audio')
            scheduler.return_value.tick.assert_called_once()
        with patch('studio.management.commands.process_studio_audio.AudioMaintenance') as scheduler:
            call_command('process_studio_audio', once=True)
            scheduler.assert_not_called()
