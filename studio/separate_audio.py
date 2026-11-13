"""Isolated Demucs process using PCM IO, independent of torchaudio codecs."""
import sys
import os
import wave
import json
import time
import tempfile
from pathlib import Path
import numpy as np
import torch
from demucs.apply import apply_model
from demucs.pretrained import get_model
from .separation_options import extraction_options


def blend_overlap(current, previous):
    """Crossfade adjacent processing windows without changing their length."""
    if previous is not None:
        count = min(previous.shape[1], current.shape[1])
        weight = np.linspace(0, 1, count, dtype=np.float32)
        current[:, :count] = previous[:, :count] * (1 - weight) + current[:, :count] * weight
    return current


def stream_backing(source, output, model, options):
    rate = model.samplerate
    hop, fade = rate * 30, rate
    with wave.open(str(source), 'rb') as audio:
        channels, frames = audio.getnchannels(), audio.getnframes()
        if audio.getframerate() != rate or not frames:
            raise ValueError('The extraction input must be nonempty audio at the model sample rate.')
        # Calculate global normalization in small blocks; no full-song float
        # tensor or full-song four-stem output is retained in memory.
        total = squares = 0.
        while data := audio.readframes(rate * 10):
            mono = np.frombuffer(data, dtype='<i2').reshape(-1, channels).mean(axis=1) / 32768
            total += float(mono.sum())
            squares += float(np.sum(mono * mono))
        mean = total / frames
        std = max(((squares - total * total / frames) / max(1, frames - 1)), 1e-16) ** .5
        pending, peak = None, 1e-8
        with tempfile.TemporaryFile() as spool:
            for start in range(0, frames, hop):
                audio.setpos(start)
                samples = np.frombuffer(audio.readframes(hop + fade), dtype='<i2').reshape(-1, channels).T.astype(np.float32) / 32768
                if channels == 1:
                    samples = np.repeat(samples, 2, axis=0)
                original = torch.from_numpy(np.ascontiguousarray(samples))
                with torch.inference_mode():
                    stems = apply_model(model, ((original - mean) / std)[None], device=options['device'], shifts=options['shifts'], split=True, overlap=options['overlap'], progress=False, num_workers=0, segment=options['segment'])[0]
                    backing = sum(stems[i] * std + mean for i, name in enumerate(model.sources) if name != 'vocals').cpu().numpy()
                del original, stems
                backing = blend_overlap(backing, pending)
                if start + hop < frames:
                    block, pending = backing[:, :hop], backing[:, hop:].copy()
                else:
                    block, pending = backing, None
                if not np.isfinite(block).all():
                    raise ValueError('The extraction produced invalid samples.')
                peak = max(peak, float(np.max(np.abs(block))))
                spool.write(np.ascontiguousarray(block.T, dtype='<f4').tobytes())
            gain = min(1., .98 / peak)
            spool.seek(0)
            with wave.open(str(output), 'wb') as result:
                result.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
                while data := spool.read(rate * 2 * 4):
                    samples = np.frombuffer(data, dtype='<f4') * gain
                    result.writeframesraw((samples * 32767).astype('<i2').tobytes())
    return frames / rate


def separate(source, output):
    started = time.perf_counter()
    # Demucs' official registered checkpoint contains its model class. No user
    # checkpoint path or URL is accepted by this runner.
    os.environ['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD'] = '1'
    options = extraction_options(torch.cuda.is_available())
    torch.set_num_threads(options['threads'])
    model = get_model('htdemucs').to(options['device']).eval()
    if options['segment'] is not None:
        # HTDemucs otherwise pads every short window to its training length.
        # The explicit fast profile trades that context for lower CPU/RAM use.
        for part in getattr(model, 'models', [model]):
            part.segment = min(float(part.segment), options['segment'])
    with wave.open(source, 'rb') as audio:
        rate = audio.getframerate()
    with tempfile.TemporaryDirectory() as folder:
        if rate != model.samplerate:
            from .video_render import run_ffmpeg
            normalized = Path(folder) / 'input.wav'
            run_ffmpeg(['-i', str(source), '-ar', str(model.samplerate), '-ac', '2', '-c:a', 'pcm_s16le', str(normalized)])
            source = str(normalized)
        seconds = stream_backing(source, output, model, options)
    peak_memory = None
    if sys.platform.startswith('linux'):
        import resource
        peak_memory = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    print(json.dumps({'engine': 'htdemucs', **options, 'audio_seconds': round(seconds, 2), 'elapsed_seconds': round(time.perf_counter() - started, 2), 'peak_memory_mib': peak_memory}), flush=True)


if __name__ == '__main__':
    separate(sys.argv[1], sys.argv[2])
