import logging
import subprocess
import time
import threading
from django.db import close_old_connections, connection
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.core.management.base import BaseCommand
from studio.models import AudioJob
from studio.audio_processing import process
from studio.maintenance import AudioMaintenance
from studio.job_control import claim_job, heartbeat, release, JobStopped

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process private Studio audio jobs and run automatic daily cleanup in the same worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Drain queued jobs and exit.")
        parser.add_argument("--retry-interrupted", action="store_true", help="Requeue running jobs; stop all other workers first.")

    def handle(self, *args, **options):
        maintenance = None if options['once'] else AudioMaintenance()
        if options["retry_interrupted"]:
            AudioJob.objects.filter(status="running").update(status="queued")
            from studio.models import StudioMaintenance
            StudioMaintenance.objects.filter(pk='audio-worker').update(lease_until=timezone.now(), lease_token='')
        last_seen = 0
        while True:
            if time.monotonic() - last_seen > 30:
                from studio.models import StudioMaintenance
                guard, _ = StudioMaintenance.objects.get_or_create(key='audio-worker')
                StudioMaintenance.objects.filter(pk=guard.pk).update(last_success_at=timezone.now())
                last_seen = time.monotonic()
            if maintenance:
                maintenance.tick()
            job = claim_job()
            if not job:
                if options["once"]:
                    return
                time.sleep(5)
                continue
            stop = threading.Event()
            lost = threading.Event()
            def renew():
                close_old_connections()
                try:
                    while not stop.wait(10):
                        heartbeat(job)
                except Exception:
                    lost.set()
                finally:
                    close_old_connections()
            def check():
                if lost.is_set():
                    raise JobStopped('Audio task cancelled or worker lease lost')
                heartbeat(job)
            keeper = threading.Thread(target=renew, daemon=True)
            # Externally managed transactions cannot be renewed on a second
            # connection (notably SQLite test transactions). Polling checks
            # still renew extraction ownership on the calling connection.
            threaded = not connection.in_atomic_block
            if threaded:
                keeper.start()
            try:
                from studio.capacity import artist_storage, ensure_artist_capacity
                from studio.storage import private_storage
                with artist_storage(job.track.project.artist_id):
                    ensure_artist_capacity(job.track.project.artist_id, private_storage, job.source.size * 2)
                    process(job, check=check)
            except JobStopped:
                logger.info('Audio job %s stopped after cancellation or lease expiry', job.pk)
            except Exception as exc:
                logger.exception("Studio audio job %s (%s) failed", job.pk, job.operation)
                if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
                    detail = exc.stderr.decode(errors="replace")[-4000:]
                    logger.error("Audio engine output for job %s: %s", job.pk, detail)
                error = exc.messages[0] if isinstance(exc, ValidationError) else 'Processing failed. Try a cleaner recording or ask the administrator to check the audio worker.'
                AudioJob.objects.filter(pk=job.pk, status='running', lease_token=job.lease_token).update(status="failed", finished_at=timezone.now(), error=error[:240])
            finally:
                stop.set()
                if threaded:
                    keeper.join(timeout=5)
                release(job)
