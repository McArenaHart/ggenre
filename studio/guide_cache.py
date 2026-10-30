"""Reusable private audio guides; access is still checked by the calling view."""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from django.conf import settings

from .video_render import copy_source, extract_audio


def cache_directory():
    return Path(getattr(settings, "STUDIO_GUIDE_CACHE_DIR", settings.BASE_DIR / "studio_private" / "guide_cache"))


def _cache_path(source):
    field = source.video_collaboration.video if hasattr(source, "video_collaboration") else source.file
    if not field:
        return None
    try:
        fingerprint = [str(field.storage.location), field.name, field.size, field.storage.get_modified_time(field.name).isoformat()]
        key = hashlib.sha256(json.dumps(fingerprint).encode()).hexdigest()
        directory = cache_directory()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return directory / (key + ".wav")
    except (OSError, AttributeError, NotImplementedError, ValueError):
        # Unsupported storage metadata or a read-only cache must not break recording.
        return None


def open_guide(source):
    path = _cache_path(source)
    try:
        if path and path.stat().st_size > 44:
            return path.open("rb")
    except OSError:
        pass
    with tempfile.TemporaryDirectory(prefix="ggenre-guide-") as directory:
        video, audio = Path(directory) / "source.mp4", Path(directory) / "guide.wav"
        copy_source(source, video)
        extract_audio(video, audio)
        if path:
            staging = None
            try:
                with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".guide-", suffix=".tmp", delete=False) as target, audio.open("rb") as result:
                    staging = Path(target.name)
                    shutil.copyfileobj(result, target)
                os.replace(staging, path)
                return path.open("rb")
            except OSError:
                pass
            finally:
                if staging:
                    try:
                        staging.unlink(missing_ok=True)
                    except OSError:
                        pass
        stream = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
        with audio.open("rb") as result:
            shutil.copyfileobj(result, stream)
        stream.seek(0)
        return stream
