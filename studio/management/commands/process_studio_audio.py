import logging
import subprocess
import time
from django.core.management.base import BaseCommand
from studio.models import AudioJob
from studio.audio_processing import process
from studio.maintenance import AudioMaintenance

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
        while True:
            if maintenance:
                maintenance.tick()
            job = AudioJob.objects.filter(status="queued").order_by("pk").first()
            if not job:
                if options["once"]:
                    return
                time.sleep(2)
                continue
            if not AudioJob.objects.filter(pk=job.pk, status="queued").update(status="running"):
                continue
            try:
                process(job)
            except Exception as exc:
                logger.exception("Studio audio job %s (%s) failed", job.pk, job.operation)
                if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
                    detail = exc.stderr.decode(errors="replace")[-4000:]
                    logger.error("Audio engine output for job %s: %s", job.pk, detail)
                AudioJob.objects.filter(pk=job.pk).update(status="failed", error="Processing failed. Try a cleaner recording or ask the administrator to check the audio worker.")
