import os
from unittest.mock import patch
from django.test import SimpleTestCase
from studio.separation_options import extraction_options


class SeparationOptionsTests(SimpleTestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_auto_selects_gpu_when_available(self):
        self.assertEqual(extraction_options(True)['device'], 'cuda')
        self.assertEqual(extraction_options(False)['device'], 'cpu')

    @patch.dict(os.environ, {'STUDIO_EXTRACTION_DEVICE': 'cpu'}, clear=True)
    def test_cpu_override_is_respected(self):
        self.assertEqual(extraction_options(True)['device'], 'cpu')

    @patch.dict(os.environ, {'STUDIO_EXTRACTION_PROFILE': 'fast', 'STUDIO_EXTRACTION_THREADS': '1'}, clear=True)
    def test_fast_profile_reduces_overlap_without_parallel_job_fanout(self):
        options = extraction_options(False)
        self.assertEqual(options['threads'], 1)
        self.assertEqual(options['shifts'], 0)
        self.assertEqual(options['overlap'], .1)

    @patch.dict(os.environ, {'STUDIO_EXTRACTION_PROFILE': 'balanced'}, clear=True)
    def test_balanced_preserves_previous_quality_settings(self):
        options = extraction_options(False)
        self.assertEqual(options['shifts'], 1)
        self.assertEqual(options['overlap'], .25)

    @patch.dict(os.environ, {}, clear=True)
    def test_cpu_defaults_to_low_memory_profile(self):
        self.assertEqual(extraction_options(False)['profile'], 'fast')
        self.assertEqual(extraction_options(False)['segment'], 2)
        self.assertEqual(extraction_options(True)['profile'], 'balanced')

    def test_invalid_settings_are_rejected(self):
        for settings in [{'STUDIO_EXTRACTION_DEVICE': 'cuda'}, {'STUDIO_EXTRACTION_DEVICE': 'bad'}, {'STUDIO_EXTRACTION_PROFILE': 'bad'}, {'STUDIO_EXTRACTION_THREADS': '0'}, {'STUDIO_EXTRACTION_THREADS': '100'}, {'STUDIO_EXTRACTION_THREADS': 'not-a-number'}]:
            with self.subTest(settings=settings), patch.dict(os.environ, settings, clear=True):
                with self.assertRaises(ValueError):
                    extraction_options(False)

    def test_setup_check_rejects_an_unbounded_benchmark(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        for seconds in (0, 61):
            with self.assertRaises(CommandError):
                call_command('check_studio_audio', seconds=seconds)
