"""Bounded format conversion of an already-authorized, immutable export."""
import tempfile
import uuid
from datetime import timedelta
from pathlib import Path

from django.core.exceptions import ValidationError
from django.http import FileResponse, JsonResponse
from django.utils import timezone

from .models import StudioMaintenance
from .video_render import run_ffmpeg

FORMATS = {
    'mp3': ('audio/mpeg', ['-c:a', 'libmp3lame', '-b:a', '192k']),
    'm4a': ('audio/mp4', ['-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart']),
    'flac': ('audio/flac', ['-c:a', 'flac', '-compression_level', '5']),
    'ogg': ('audio/ogg', ['-c:a', 'libvorbis', '-q:a', '5']),
}


def converted_download(item, extension):
    if extension not in FORMATS:
        return JsonResponse({'error': 'Choose WAV, MP3, M4A, FLAC or OGG.'}, status=400)
    now, token = timezone.now(), uuid.uuid4().hex
    key = 'audio-download-conversion'
    StudioMaintenance.objects.get_or_create(key=key, defaults={'lease_until': now})
    if not StudioMaintenance.objects.filter(pk=key, lease_until__lte=now).update(
        lease_until=now + timedelta(seconds=150), lease_token=token,
    ):
        response = JsonResponse({'error': 'Another download is being prepared. Please try again shortly.'}, status=503)
        response['Retry-After'] = '5'
        return response
    temporary = None
    try:
        temporary = tempfile.TemporaryDirectory(prefix='ggenre-download-')
        mime, codec = FORMATS[extension]
        output = Path(temporary.name) / ('download.' + extension)
        run_ffmpeg(['-protocol_whitelist', 'file,pipe', '-i', item.audio.path,
                    '-map', '0:a:0', '-vn', '-map_metadata', '-1', *codec,
                    '-threads', '1', '-t', '360', '-fs', str(64 * 1024 * 1024), str(output)])
        filename = ('ggenre-instrumental' if item.instrumental_id else 'ggenre-studio') + '.' + extension
        response = FileResponse(output.open('rb'), as_attachment=True, filename=filename, content_type=mime)
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        response._resource_closers.append(temporary.cleanup)
        return response
    except (ValidationError, OSError):
        if temporary:
            temporary.cleanup()
        return JsonResponse({'error': 'Could not prepare this audio format. Try WAV or retry later.'}, status=422)
    finally:
        StudioMaintenance.objects.filter(pk=key, lease_token=token).update(lease_until=timezone.now(), lease_token='')
