import logging
import time
from django.core.management.base import BaseCommand
from studio.models import AudioJob
from studio.audio_processing import process

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process private Studio audio jobs. Run as a supervised background worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Drain queued jobs and exit.")
        parser.add_argument("--retry-interrupted", action="store_true", help="Requeue running jobs; stop all other workers first.")

    def handle(self, *args, **options):
        if options["retry_interrupted"]:
            AudioJob.objects.filter(status="running").update(status="queued")
        while True:
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
            except Exception:
                logger.exception("Studio audio job %s failed", job.pk)
                AudioJob.objects.filter(pk=job.pk).update(status="failed", error="Processing failed. Try a cleaner recording or ask the administrator to check the audio worker.")
