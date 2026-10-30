import io
import os
import tempfile
import time
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


class GuideMaintenanceTests(SimpleTestCase):
    def test_cleanup_only_removes_old_generated_cache_files(self):
        with tempfile.TemporaryDirectory() as directory, override_settings(STUDIO_GUIDE_CACHE_DIR=directory):
            root = Path(directory)
            old = root / ("a" * 64 + ".wav")
            stale_temp = root / ".guide-stale.tmp"
            fresh = root / ("b" * 64 + ".wav")
            source = root / "source.wav"
            for path in (old, stale_temp, fresh, source):
                path.write_bytes(b"test")
            for path in (old, stale_temp, source):
                os.utime(path, (time.time() - 8 * 86400,) * 2)
            output = io.StringIO()
            call_command("cleanup_studio_guides", dry_run=True, stdout=output)
            self.assertIn("2 old generated guides", output.getvalue())
            self.assertTrue(old.exists())
            call_command("cleanup_studio_guides", stdout=io.StringIO())
            self.assertFalse(old.exists())
            self.assertFalse(stale_temp.exists())
            self.assertTrue(fresh.exists())
            self.assertTrue(source.exists())

    def test_cleanup_rejects_invalid_retention(self):
        with self.assertRaises(CommandError):
            call_command("cleanup_studio_guides", days=0)
