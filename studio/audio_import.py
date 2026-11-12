"""Normalize local audio uploads once, on the server, before taking DB locks."""
import tempfile
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

from .limits import MAX_AUDIO_BYTES, MAX_AUDIO_SECONDS
from .video_render import run_ffmpeg


def normalize_upload(upload, *, force_conversion=False):
    from .views import validate_audio

    if not upload or upload.size > MAX_AUDIO_BYTES:
        raise ValidationError('Choose an audio file under 64 MB.')
    # Recorded takes and generated beats are already PCM; avoid transcoding them.
    if not force_conversion:
        try:
            return validate_audio(upload)
        except ValidationError:
            upload.seek(0)
    try:
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'input', Path(folder) / 'output.wav'
            with source.open('wb') as stream:
                for chunk in upload.chunks():
                    stream.write(chunk)
            # One extra second detects overlong files instead of truncating them.
            # Exclude playlists and remote protocols; only decode uploaded media.
            run_ffmpeg(['-protocol_whitelist', 'file,pipe', '-format_whitelist',
                        'wav,mp3,mov,flac,ogg,aac,matroska,webm,aiff',
                        '-i', str(source), '-map', '0:a:0', '-vn',
                        '-t', str(MAX_AUDIO_SECONDS + 1), '-ac', '2', '-ar', '44100',
                        '-c:a', 'pcm_s16le', str(output)])
            return validate_audio(ContentFile(output.read_bytes(), name='import.wav'))
    except ValidationError as exc:
        raise ValidationError('Could not import this audio. Use an unprotected MP3, WAV, M4A, FLAC or OGG file up to six minutes.') from exc
