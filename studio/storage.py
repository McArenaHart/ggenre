from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.utils.deconstruct import deconstructible

@deconstructible
class PrivateStorage(FileSystemStorage):
    def __init__(self):
        super().__init__(location=settings.BASE_DIR / "studio_private")

    def url(self, name):
        raise ValueError("Studio files require authorized playback.")

private_storage = PrivateStorage()
