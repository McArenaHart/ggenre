"""Read configuration locally without deploying or invoking paid compute."""
from django.core.management.base import BaseCommand
from django.conf import settings
from studio.models import StudioMaintenance, AudioJob
from studio.remote_extraction import configuration_errors


class Command(BaseCommand):
    help = 'Check remote extraction configuration without contacting Modal or spending credits.'

    def add_arguments(self, parser):
        parser.add_argument('--list-jobs', action='store_true', help='List up to ten waiting extraction job IDs for selecting the pilot.')
        parser.add_argument('--clear-pause', action='store_true', help='Clear a provider pause only after reviewing credits and any previous uncertain submission.')

    def handle(self, *args, **options):
        if options['list_jobs']:
            ids = list(AudioJob.objects.filter(operation='separate', status='queued').order_by('-pk').values_list('pk', flat=True)[:10])
            self.stdout.write('Waiting extraction job IDs: ' + (', '.join(map(str, ids)) or 'none'))
        if options['clear_pause']:
            StudioMaintenance.objects.filter(pk='remote-extraction-paused').update(last_error='')
            self.stdout.write('Provider pause cleared. This does not reset a previously dispatched job or its billing controls.')
        errors = configuration_errors()
        paused = StudioMaintenance.objects.filter(pk='remote-extraction-paused').exclude(last_error='').first()
        for error in errors:
            self.stdout.write(error)
        if paused:
            self.stdout.write('A provider pause is active: ' + paused.last_error)
        if not errors and not paused:
            scope = 'all artist jobs' if settings.STUDIO_REMOTE_ALLOW_ALL_JOBS else 'one selected job'
            self.stdout.write(f'Configuration is ready for {scope}. No network request was made. Provider billing controls must be verified separately.')
