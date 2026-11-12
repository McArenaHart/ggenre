import contextlib
import io
from unittest.mock import patch

from django.test import SimpleTestCase

from scripts.install_audio_cleanup import main, quote, render_units


class CleanupScheduleTests(SimpleTestCase):
    def test_timer_runs_nightly_and_catches_missed_runs_after_reboot(self):
        service, timer = render_units('/home/ggenre/app', '/home/ggenre/venv/bin/python', 'ggenre')
        self.assertIn('OnCalendar=*-*-* 01:00:00 UTC', timer)
        self.assertIn('Persistent=true', timer)
        self.assertIn('WantedBy=timers.target', timer)
        self.assertIn('RandomizedDelaySec=15m', timer)
        self.assertIn('User=ggenre', service)
        self.assertIn('/usr/bin/flock -n ', service)
        self.assertIn('cleanup_studio_audio --apply --orphan-days 7 --job-days 7 --preview-days 30', service)
        self.assertIn('CPUQuota=25%', service)
        self.assertIn('MemoryMax=256M', service)
        self.assertIn('StandardError=journal', service)

    def test_paths_preserve_spaces_and_escape_unit_specifiers(self):
        service, _ = render_units('/srv/my app%/project', '/srv/my app/venv/bin/python', 'ggenre')
        self.assertIn('WorkingDirectory="/srv/my app%%/project"', service)
        self.assertIn('"/srv/my app/venv/bin/python"', service)
        self.assertEqual(quote('a"b'), '"a\\"b"')

    def test_invalid_configuration_cannot_inject_unit_directives(self):
        for user in ['ggenre\nExecStart=bad', 'ggenre root', '../root']:
            with self.assertRaises(ValueError):
                render_units('/srv/app', '/srv/venv/bin/python', user)
        for hour in [-1, 24]:
            with self.assertRaises(ValueError):
                render_units('/srv/app', '/srv/venv/bin/python', 'ggenre', hour)
        with self.assertRaises(ValueError):
            render_units('/srv/app\nExecStart=bad', '/srv/venv/bin/python', 'ggenre')

    def test_preview_does_not_install_services_or_run_cleanup(self):
        with patch('sys.argv', ['install_audio_cleanup.py', '--user', 'ggenre', '--preview']):
            with patch('scripts.install_audio_cleanup.subprocess.run') as run:
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    main()
        run.assert_not_called()
        self.assertIn('OnCalendar=', output.getvalue())
