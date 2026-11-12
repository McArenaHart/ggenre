import re
import time
from datetime import timedelta
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from studio.cleanup import private_file_fields, referenced_names, is_referenced
from studio.models import AudioJob
from studio.storage import private_storage


class Command(BaseCommand):
    help = 'Preview private audio cleanup; --apply expires old processing snapshots and removes unreferenced generated WAVs.'

    def heartbeat(self):
        """The in-app scheduler replaces this hook to renew its database lease."""

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Perform cleanup; without this flag nothing changes.')
        parser.add_argument('--dry-run', action='store_true', help='Explicit preview (the default).')
        parser.add_argument('--orphan-days', type=int, default=7)
        parser.add_argument('--job-days', type=int, default=7, help='Applied/failed task snapshot retention.')
        parser.add_argument('--preview-days', type=int, default=30, help='Unused ready result retention.')

    def handle(self, *args, **options):
        if options['apply'] and options['dry_run']:
            raise CommandError('Choose --apply or --dry-run, not both.')
        if min(options['orphan_days'], options['job_days'], options['preview_days']) < 1:
            raise CommandError('Retention periods must be at least one day.')
        root = Path(private_storage.location).resolve()
        directory = root / 'audio'
        if directory.is_symlink() or directory.resolve().parent != root:
            raise CommandError('Refusing cleanup outside the private audio directory.')
        fields = list(private_file_fields())
        now = timezone.now()
        jobs_expired = 0
        retained_job_names = set()

        # Apply and worker completion also lock/claim these records. Never touch
        # queued or running jobs, and give recently completed results full grace.
        for pk in AudioJob.objects.filter(status__in=['applied', 'failed', 'ready']).values_list('pk', flat=True).iterator():
            self.heartbeat()
            with transaction.atomic():
                job = AudioJob.objects.select_for_update().filter(pk=pk, status__in=['applied', 'failed', 'ready']).first()
                if not job:
                    continue
                names = {str(value) for value in (job.source, job.result) if value}
                if not names:
                    continue
                days = options['preview_days'] if job.status == 'ready' else options['job_days']
                cutoff = now - timedelta(days=days)
                if job.created_at >= cutoff:
                    retained_job_names.update(names)
                    continue
                # Older tasks can have newly produced results after a retry.
                if job.result and private_storage.exists(job.result.name) and private_storage.get_modified_time(job.result.name) >= cutoff:
                    retained_job_names.update(names)
                    continue
                jobs_expired += 1
                if options['apply']:
                    self.heartbeat()
                    job.source = job.result = ''
                    if job.status == 'ready':
                        job.status = 'expired'
                        job.error = 'This temporary result expired. Process the original track again.'
                    job.save(update_fields=['source', 'result', 'status', 'error'])

        references = referenced_names(fields)
        if not options['apply']:
            # Model the planned reference removal without modifying the database.
            other_fields = [(model, field) for model, field in fields if model is not AudioJob]
            references = referenced_names(other_fields) | retained_job_names
            for source, result in AudioJob.objects.exclude(status__in=['applied', 'failed', 'ready']).values_list('source', 'result').iterator():
                references.update(name for name in (source, result) if name)
        cutoff = time.time() - options['orphan_days'] * 86400
        count = total = errors = 0
        if directory.is_dir():
            for path in directory.iterdir():
                self.heartbeat()
                if not re.fullmatch(r'[0-9a-f]{32}(?:_[A-Za-z0-9]{7})?\.wav', path.name):
                    continue
                if path.is_symlink() or path.resolve().parent != directory.resolve():
                    continue
                name = f'audio/{path.name}'
                try:
                    if not path.is_file() or name in references:
                        continue
                    stat = path.stat()
                    if stat.st_mtime >= cutoff:
                        continue
                    if options['apply']:
                        if is_referenced(name, fields):
                            continue
                        self.heartbeat()
                        path.unlink()
                    count += 1
                    total += stat.st_size
                except OSError as exc:
                    errors += 1
                    self.stderr.write(f'Could not clean {name}: {exc}')
        mode = 'Removed' if options['apply'] else 'Would remove'
        self.stdout.write(f'{mode} {count} unreferenced WAV files ({total / 1024 / 1024:.2f} MiB); {jobs_expired} old task snapshots ' + ('expired.' if options['apply'] else 'eligible for expiry.'))
        if errors:
            raise CommandError(f'{errors} files could not be cleaned; see errors above.')
