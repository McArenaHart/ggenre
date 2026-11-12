"""Install the production Studio cleanup service/timer on Ubuntu (run with sudo)."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


def quote(value):
    value = str(value)
    if any(character in value for character in ('\n', '\r', '\x00')):
        raise ValueError('Unit paths must not contain newlines or NUL bytes.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def render_units(project, python, user, hour_utc=1):
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*\$?', user) or not 0 <= hour_utc <= 23:
        raise ValueError('Use an existing Linux service username and a UTC hour from 0 to 23.')
    service = f'''[Unit]
Description=GGenre private Studio audio retention cleanup
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User={user}
WorkingDirectory={quote(project)}
Environment=DJANGO_SETTINGS_MODULE=ggenre.settings
Environment=PYTHONDONTWRITEBYTECODE=1
RuntimeDirectory=ggenre-audio-cleanup
RuntimeDirectoryMode=0700
ExecStart=/usr/bin/flock -n /run/ggenre-audio-cleanup/cleanup.lock {quote(python)} -u manage.py cleanup_studio_audio --apply --orphan-days 7 --job-days 7 --preview-days 30
TimeoutStartSec=1800
Nice=10
CPUQuota=25%
MemoryMax=256M
IOSchedulingClass=idle
UMask=0077
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths={quote(project)}
StandardOutput=journal
StandardError=journal
'''
    timer = f'''[Unit]
Description=Run GGenre audio cleanup every night

[Timer]
OnCalendar=*-*-* {hour_utc:02d}:00:00 UTC
RandomizedDelaySec=15m
Persistent=true
Unit=ggenre-audio-cleanup.service

[Install]
WantedBy=timers.target
'''
    return service, timer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--user', required=True, help='The existing account with access to app settings, database and private storage.')
    parser.add_argument('--hour-utc', type=int, default=1, help='Default 01:00 UTC = 03:00 Africa/Harare, plus up to 15 minutes jitter.')
    parser.add_argument('--preview', action='store_true', help='Print the unit configuration without installing or deleting anything.')
    options = parser.parse_args()
    project = options.project.resolve()
    # Do not resolve the virtualenv Python symlink to the system interpreter.
    python = options.python.absolute()
    service, timer = render_units(project, python, options.user, options.hour_utc)
    if options.preview:
        print(service + '\n' + timer)
        return
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise SystemExit('Run this installer on the Ubuntu server with sudo. Use --preview to inspect its configuration anywhere.')
    import pwd
    pwd.getpwnam(options.user)
    if not (project / 'manage.py').is_file() or not python.is_file() or not os.access(python, os.X_OK):
        raise SystemExit('Check --project and --python; use the application virtualenv Python.')
    # Test the exact service identity/interpreter before touching systemd.
    subprocess.run(['runuser', '-u', options.user, '--', str(python), '-u', 'manage.py', 'cleanup_studio_audio', '--dry-run'], cwd=project, check=True)
    with tempfile.TemporaryDirectory(prefix='ggenre-cleanup-units-') as folder:
        stage = Path(folder)
        for name, content in [('ggenre-audio-cleanup.service', service), ('ggenre-audio-cleanup.timer', timer)]:
            (stage / name).write_text(content, encoding='utf-8')
        subprocess.run(['systemd-analyze', 'verify', str(stage / 'ggenre-audio-cleanup.service'), str(stage / 'ggenre-audio-cleanup.timer')], check=True)
        target = Path('/etc/systemd/system')
        for name in ('ggenre-audio-cleanup.service', 'ggenre-audio-cleanup.timer'):
            path = target / name
            # Fixed target names only; preserve the previous installation for review.
            if path.exists():
                path.with_suffix(path.suffix + '.previous').write_bytes(path.read_bytes())
            path.write_bytes((stage / name).read_bytes())
            path.chmod(0o644)
    subprocess.run(['systemctl', 'daemon-reload'], check=True)
    subprocess.run(['systemctl', 'enable', '--now', 'ggenre-audio-cleanup.timer'], check=True)
    subprocess.run(['systemctl', 'start', 'ggenre-audio-cleanup.service'], check=True, timeout=1860)
    subprocess.run(['systemctl', 'is-enabled', 'ggenre-audio-cleanup.timer'], check=True)
    subprocess.run(['systemctl', 'list-timers', '--all', 'ggenre-audio-cleanup.timer'], check=True)
    print('Automatic audio cleanup installed and its initial run completed. Logs: journalctl -u ggenre-audio-cleanup.service')


if __name__ == '__main__':
    main()
