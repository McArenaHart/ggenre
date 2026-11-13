"""Portable disk admission and per-artist accounting for private assets."""
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import shutil
import tempfile
from django.conf import settings
from django.core.exceptions import ValidationError

current_artist = ContextVar('studio_storage_artist', default=None)


@contextmanager
def artist_storage(artist_id):
    token = current_artist.set(artist_id)
    try:
        yield
    finally:
        current_artist.reset(token)


def ensure_disk(storage, additional=0):
    root = Path(storage.location)
    root.mkdir(parents=True, exist_ok=True)
    minimum = max(0, settings.STUDIO_MIN_FREE_MIB) * 1024 * 1024
    if shutil.disk_usage(root).free < minimum + additional:
        raise ValidationError('Studio storage is nearly full. Please try later or contact support. Your saved audio is safe.')
    if shutil.disk_usage(tempfile.gettempdir()).free < minimum + additional:
        raise ValidationError('Studio temporary storage is nearly full. Please try later or contact support.')


def usage(artist_id, storage):
    from .models import Project, Track, AudioJob, Instrumental, Export, Release, VideoCollaboration, StudioAsset
    from django.db.models import Q
    names = set()
    for query, fields in [
        (Project.objects.filter(artist_id=artist_id), ['mix']),
        (Track.all_objects.filter(project__artist_id=artist_id), ['audio']),
        (AudioJob.objects.filter(track__project__artist_id=artist_id), ['source', 'result']),
        (Instrumental.objects.filter(artist_id=artist_id), ['audio', 'source_audio']),
        (Export.objects.filter(Q(project__artist_id=artist_id) | Q(instrumental__artist_id=artist_id)), ['audio']),
        (Release.objects.filter(content__artist_id=artist_id), ['audio']),
        (VideoCollaboration.objects.filter(creator_id=artist_id), ['video']),
    ]:
        for values in query.values_list(*fields).iterator():
            names.update(value for value in values if value)
    assets = dict(StudioAsset.objects.filter(artist_id=artist_id).values_list('name', 'size'))
    names.update(assets)
    total = 0
    for name in names:
        try:
            # Missing files and cleaned orphan ledger entries do not consume quota.
            if storage.exists(name):
                total += assets[name] if name in assets else storage.size(name)
        except OSError:
            continue
    return total


def ensure_artist_capacity(artist_id, storage, additional):
    ensure_disk(storage, additional)
    limit = max(0, settings.STUDIO_ARTIST_STORAGE_MIB) * 1024 * 1024
    if limit and usage(artist_id, storage) + additional > limit:
        raise ValidationError('Your Studio storage limit has been reached. Remove unused audio or contact support before adding more.')
