"""Authenticated Modal extraction with optional one-job pilot mode. Never falls back to local AI."""
import json
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import AudioJob, StudioMaintenance

SALT = 'ggenre-remote-audio-v1'
MAX_WAIT = 900


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RemotePaused(Exception):
    pass


def configuration_errors():
    errors = []
    endpoint = urlsplit(settings.STUDIO_REMOTE_WORKER_URL)
    origin = urlsplit(settings.STUDIO_PUBLIC_BASE_URL)
    if settings.STUDIO_EXTRACTION_BACKEND != 'modal':
        errors.append('Choose the modal extraction backend.')
    if not settings.STUDIO_REMOTE_EXTRACTION_ENABLED:
        errors.append('Remote processing is disabled.')
    if not settings.STUDIO_REMOTE_BILLING_VERIFIED:
        errors.append('Verify a provider-enforced zero-charge billing cap before enabling processing.')
    if not settings.STUDIO_REMOTE_ALLOW_ALL_JOBS and settings.STUDIO_REMOTE_TEST_JOB_ID <= 0:
        errors.append('Select exactly one existing extraction job for the pilot.')
    if endpoint.scheme != 'https' or not (endpoint.hostname or '').endswith('.modal.run') or endpoint.username or endpoint.query or endpoint.fragment:
        errors.append('Set the authenticated HTTPS Modal web-function URL.')
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.query or origin.fragment or origin.path not in ('', '/'):
        errors.append('Set the public HTTPS origin of GGenre, without a path.')
    if not settings.STUDIO_REMOTE_PROXY_KEY or not settings.STUDIO_REMOTE_PROXY_SECRET:
        errors.append('Configure Modal proxy authentication securely on the server.')
    return errors


def job_allowed(job):
    return settings.STUDIO_REMOTE_ALLOW_ALL_JOBS or job.pk == settings.STUDIO_REMOTE_TEST_JOB_ID


def configured():
    return not configuration_errors() and not StudioMaintenance.objects.filter(key='remote-extraction-paused').exclude(last_error='').exists()


def token(job, action):
    return signing.dumps({'job': job.pk, 'nonce': job.remote_nonce, 'source': job.source.name, 'action': action}, salt=SALT)


def authorize(request, pk, action):
    try:
        payload = signing.loads(request.headers.get('X-GGenre-Job-Token', ''), salt=SALT, max_age=3600)
    except signing.BadSignature:
        raise PermissionError()
    if not isinstance(payload, dict) or payload.get('job') != pk or payload.get('action') != action or not payload.get('nonce'):
        raise PermissionError()
    return AudioJob.objects.get(pk=pk, remote_nonce=payload['nonce'], source=payload.get('source'), status='running', operation='separate')


def send(payload):
    request = Request(settings.STUDIO_REMOTE_WORKER_URL, data=json.dumps(payload).encode(), method='POST', headers={
        'Content-Type': 'application/json', 'Modal-Key': settings.STUDIO_REMOTE_PROXY_KEY, 'Modal-Secret': settings.STUDIO_REMOTE_PROXY_SECRET})
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        if response.status != 200:
            raise ValidationError('The remote worker did not acknowledge this request.')
        result = json.loads(response.read(8192))
        if not isinstance(result, dict) or result.get('accepted') is not True:
            raise ValidationError('The remote worker refused this request. No local fallback was attempted.')
        return result


@transaction.atomic
def pause(job, message):
    StudioMaintenance.objects.update_or_create(key='remote-extraction-paused', defaults={'last_error': message})
    AudioJob.objects.filter(pk=job.pk, status='running', lease_token=job.lease_token).update(status='queued', error=message)
    return message


def extract(job, check):
    if not configured() or not job_allowed(job):
        raise RemotePaused('Remote extraction is paused. No local processing was attempted.')
    with transaction.atomic():
        current = AudioJob.objects.select_for_update().get(pk=job.pk)
        if current.status != 'running' or current.lease_token != job.lease_token:
            from .job_control import JobStopped
            raise JobStopped('Audio task ownership changed')
        dispatched = current.remote_dispatched_at is not None
        if not dispatched:
            current.remote_nonce = uuid.uuid4().hex
            current.remote_dispatched_at = timezone.now()
            current.save(update_fields=['remote_nonce', 'remote_dispatched_at'])
        job.remote_nonce = current.remote_nonce
    if not dispatched:
        base = settings.STUDIO_PUBLIC_BASE_URL
        payload = {'job_id': job.pk, 'source_url': f'{base}/studio/remote-audio/{job.pk}/source/',
                   'result_url': f'{base}/studio/remote-audio/{job.pk}/result/', 'control_url': f'{base}/studio/remote-audio/{job.pk}/control/',
                   'tokens': {action: token(job, action) for action in ('source', 'result', 'control')}}
        try:
            send(payload)
        except HTTPError as exc:
            if exc.code in (402, 429):
                raise RemotePaused(pause(job, 'Remote allowance or capacity is unavailable. Extraction is paused; no local fallback will run.')) from None
            if exc.code in (401, 403):
                raise ValidationError('Remote worker authentication failed. Ask the administrator to check the connection.') from None
            # A lost acknowledgement may still mean the GPU job started. Wait
            # for its callback instead of dispatching and charging twice.
        except (URLError, TimeoutError, OSError, json.JSONDecodeError):
            pass
    started = time.monotonic()
    while time.monotonic() - started < MAX_WAIT:
        check()
        with transaction.atomic():
            current = AudioJob.objects.select_for_update().get(pk=job.pk)
            if current.status != 'running' or current.lease_token != job.lease_token:
                from .job_control import JobStopped
                raise JobStopped('Remote task cancelled or ownership changed')
            if current.result:
                current.status, current.error, current.finished_at = 'ready', '', timezone.now()
                current.save(update_fields=['status', 'error', 'finished_at'])
                job.result, job.status = current.result, 'ready'
                return
            if current.error.startswith('Remote worker failed'):
                raise ValidationError(current.error)
        time.sleep(3)
    raise RemotePaused(pause(job, 'Remote extraction has not returned a result. Processing is paused for review; the job will not be submitted twice.'))
