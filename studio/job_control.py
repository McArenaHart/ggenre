"""Database leases serialize costly work even when multiple workers start."""
import uuid
from datetime import timedelta
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from .models import AudioJob, StudioMaintenance


class JobStopped(Exception):
    pass


def deadline():
    return timezone.now() + timedelta(seconds=max(30, settings.STUDIO_JOB_LEASE_SECONDS))


@transaction.atomic
def claim_job():
    now = timezone.now()
    guard, _ = StudioMaintenance.objects.get_or_create(key='audio-worker', defaults={'lease_until': now})
    token = uuid.uuid4().hex
    if not StudioMaintenance.objects.filter(pk=guard.pk, lease_until__lte=now).update(lease_until=deadline(), lease_token=token):
        return None
    stale = AudioJob.objects.filter(status='running', lease_until__lte=now)
    stale.filter(attempts__gte=settings.STUDIO_JOB_MAX_ATTEMPTS).update(status='failed', finished_at=now, error='Processing was interrupted repeatedly. Please try again.', lease_token='')
    stale.filter(attempts__lt=settings.STUDIO_JOB_MAX_ATTEMPTS).update(status='queued', lease_token='', error='')
    job = AudioJob.objects.select_for_update().filter(status='queued').order_by('pk').first()
    if not job:
        StudioMaintenance.objects.filter(pk=guard.pk, lease_token=token).update(lease_until=now, lease_token='')
        return None
    AudioJob.objects.filter(pk=job.pk, status='queued').update(status='running', lease_token=token, lease_until=deadline(), started_at=now, finished_at=None, attempts=F('attempts') + 1)
    job.refresh_from_db()
    return job


def heartbeat(job):
    token = job.lease_token
    if not StudioMaintenance.objects.filter(pk='audio-worker', lease_token=token).update(lease_until=deadline(), last_success_at=timezone.now()):
        raise JobStopped('Worker lease lost')
    if not AudioJob.objects.filter(pk=job.pk, status='running', lease_token=token).update(lease_until=deadline()):
        raise JobStopped('Audio task cancelled')


def release(job):
    StudioMaintenance.objects.filter(pk='audio-worker', lease_token=job.lease_token).update(lease_until=timezone.now(), lease_token='')
