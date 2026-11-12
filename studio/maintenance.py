"""Persistent daily cleanup scheduling inside the existing audio worker."""
import logging
import time
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from .models import StudioMaintenance

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=10)


class LeaseLost(RuntimeError):
    pass


def next_cleanup(now):
    hour = getattr(settings, 'STUDIO_CLEANUP_HOUR_UTC', 1)
    if not 0 <= hour <= 23:
        raise ValueError('STUDIO_CLEANUP_HOUR_UTC must be from 0 to 23.')
    from datetime import timezone as dt_timezone
    now = now.astimezone(dt_timezone.utc)
    next_run = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return next_run if next_run > now else next_run + timedelta(days=1)


class AudioMaintenance:
    def __init__(self):
        self.check_after = 0

    def tick(self):
        if not getattr(settings, 'STUDIO_AUTO_CLEANUP_ENABLED', True):
            return
        clock = time.monotonic()
        if clock < self.check_after:
            return
        self.check_after = clock + 60
        try:
            self.run_due()
        except Exception:
            # Maintenance/database failures must not stop vocal processing.
            logger.exception('Automatic Studio cleanup could not run')

    def run_due(self):
        now = timezone.now()
        next_cleanup(now)  # Validate configuration before claiming or deleting.
        StudioMaintenance.objects.get_or_create(key='audio-cleanup', defaults={'next_run_at': now, 'lease_until': now})
        token = uuid.uuid4().hex
        claimed = StudioMaintenance.objects.filter(key='audio-cleanup', next_run_at__lte=now, lease_until__lte=now).update(lease_token=token, lease_until=now + LEASE)
        if not claimed:
            return False
        renew_after = 0

        def heartbeat():
            nonlocal renew_after
            clock = time.monotonic()
            if clock < renew_after:
                return
            current = timezone.now()
            renewed = StudioMaintenance.objects.filter(key='audio-cleanup', lease_token=token, lease_until__gt=current).update(lease_until=current + LEASE)
            if not renewed:
                raise LeaseLost('Cleanup ownership expired or changed; stopping this run.')
            renew_after = clock + 30

        try:
            from .management.commands.cleanup_studio_audio import Command
            command = Command()
            command.heartbeat = heartbeat
            call_command(command, apply=True)
            heartbeat()
            completed = timezone.now()
            updated = StudioMaintenance.objects.filter(key='audio-cleanup', lease_token=token).update(
                next_run_at=next_cleanup(completed), lease_until=completed, lease_token='',
                last_success_at=completed, last_error='')
            if updated:
                logger.info('Automatic Studio audio cleanup completed')
            return bool(updated)
        except Exception as exc:
            failed = timezone.now()
            StudioMaintenance.objects.filter(key='audio-cleanup', lease_token=token).update(
                next_run_at=failed + timedelta(hours=1), lease_until=failed,
                lease_token='', last_error=str(exc)[:1000])
            logger.exception('Automatic Studio cleanup failed; retry scheduled in one hour')
            return False
