from django.core.management.base import BaseCommand
from content.models import ArtistUploadLimit
from django.utils import timezone

class Command(BaseCommand):
    help = 'Resets the upload limits for all artists daily'

    def handle(self, *args, **kwargs):
        # Reset uploads_used for all artists
        ArtistUploadLimit.objects.all().update(uploads_used=0)
        self.stdout.write(self.style.SUCCESS('Successfully reset upload limits'))