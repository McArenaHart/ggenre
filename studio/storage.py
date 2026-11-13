from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible

@deconstructible
class PrivateStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=getattr(settings, 'STUDIO_STORAGE_ROOT', settings.BASE_DIR / "studio_private"))

    def url(self, name):
        raise ValueError("Studio files require authorized playback.")

    def _save(self, name, content):
        from django.db import transaction
        from .capacity import current_artist, ensure_disk, ensure_artist_capacity
        artist_id = current_artist.get()
        if artist_id is None:
            ensure_disk(self, content.size)
            return super()._save(name, content)
        from .models import StudioStorageAccount, StudioAsset
        with transaction.atomic():
            account, _ = StudioStorageAccount.objects.get_or_create(artist_id=artist_id)
            StudioStorageAccount.objects.select_for_update().get(pk=account.pk)
            ensure_artist_capacity(artist_id, self, content.size)
            saved = super()._save(name, content)
            StudioAsset.objects.create(artist_id=artist_id, name=saved, size=content.size)
            return saved

private_storage = PrivateStorage()
