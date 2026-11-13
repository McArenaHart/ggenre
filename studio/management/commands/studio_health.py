import json
from django.core.management.base import BaseCommand
from studio.health import report


class Command(BaseCommand):
    help = 'Report audio queue, worker heartbeat, cleanup and available storage as JSON.'

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(report(), indent=2))
