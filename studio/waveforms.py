"""Small waveform envelopes; never decode a song to float32 in the browser."""
from array import array
import sys
import wave
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from .models import Track
from .views import artist_only


def envelope(field, bins=1600):
    key = 'studio-peaks-v1:' + field.name
    result = cache.get(key)
    if result is not None:
        return result
    with field.open('rb') as stream, wave.open(stream) as audio:
        frames, channels, rate = audio.getnframes(), audio.getnchannels(), audio.getframerate()
        peaks = []
        count = min(bins, frames)
        for index in range(count):
            start, end = index * frames // count, (index + 1) * frames // count
            remaining, peak = end - start, 0
            while remaining:
                size = min(16384, remaining)
                samples = array('h', audio.readframes(size))
                if sys.byteorder != 'little':
                    samples.byteswap()
                peak = max(peak, max((abs(value) for value in samples), default=0))
                remaining -= size
            peaks.append(round(peak / 32768, 4))
        result = {'duration': frames / rate, 'peaks': peaks}
    cache.set(key, result, 86400)
    return result


@artist_only
def track_peaks(request, pk):
    track = get_object_or_404(Track, pk=pk, project__artist=request.user)
    return JsonResponse(envelope(track.audio))
