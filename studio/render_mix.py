"""Render immutable mixer snapshots with bounded-memory FFmpeg filters."""
import shutil
import wave
from pathlib import Path
from django.core.exceptions import ValidationError
from .video_render import run_ffmpeg


def render(job, folder, output, check):
    arguments, filters, labels = [], [], []
    for index, part in enumerate(job.inputs.all()):
        check()
        try:
            source = Path(part.audio.path)
        except NotImplementedError:
            source = Path(folder) / f'track-{index}.wav'
            with part.audio.open('rb') as stream, source.open('wb') as target:
                shutil.copyfileobj(stream, target, 1024 * 1024)
        settings = part.settings
        with wave.open(str(source), 'rb') as audio:
            duration = audio.getnframes() / audio.getframerate()
        start, end = settings['trim_start'], settings['trim_end'] or duration
        if not 0 <= start < end <= duration + .02 or settings['offset'] + end - start > 360.001:
            raise ValidationError('Check track trim and position. Keep the mix within six minutes.')
        arguments += ['-i', str(source)]
        label = f'p{index}'
        filters.append(f'[{index}:a]atrim=start={start}:end={min(end, duration)},asetpts=PTS-STARTPTS,aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={settings["gain"]},adelay={round(settings["offset"] * 44100)}S:all=1[{label}]')
        labels.append(f'[{label}]')
    if not labels:
        raise ValidationError('Add or unmute at least one track.')
    tail = 'alimiter=limit=0.98:level=0:latency=1'
    if job.operation == 'master':
        tail = 'highpass=f=25,acompressor=threshold=0.125:ratio=2:attack=20:release=150,loudnorm=I=-14:TP=-1.5:LRA=11'
    filters.append(''.join(labels) + f'amix=inputs={len(labels)}:normalize=0:duration=longest:dropout_transition=0,{tail}[mix]')
    run_ffmpeg([*arguments, '-filter_complex_threads', '1', '-filter_complex', ';'.join(filters), '-map', '[mix]', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', '-threads', '1', str(output)], timeout=600)
    check()
