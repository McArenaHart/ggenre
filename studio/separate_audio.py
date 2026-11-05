"""Isolated Demucs process using PCM IO, independent of torchaudio codecs."""
import sys
import os
import wave
from math import gcd
import numpy as np
import torch
from scipy.signal import resample_poly
from demucs.apply import apply_model
from demucs.pretrained import get_model


def separate(source, output):
    # Demucs' official registered checkpoint contains its model class. No user
    # checkpoint path or URL is accepted by this runner.
    os.environ['TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD'] = '1'
    model = get_model('htdemucs').cpu().eval()
    with wave.open(source, 'rb') as audio:
        rate, channels = audio.getframerate(), audio.getnchannels()
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype='<i2').reshape(-1, channels).T.astype(np.float32) / 32768
    if channels == 1:
        samples = np.repeat(samples, 2, axis=0)
    if rate != model.samplerate:
        divisor = gcd(rate, model.samplerate)
        samples = resample_poly(samples, model.samplerate // divisor, rate // divisor, axis=1)
    original = torch.from_numpy(np.ascontiguousarray(samples))
    reference = original.mean(0)
    mean, std = reference.mean(), reference.std().clamp(min=1e-8)
    with torch.no_grad():
        stems = apply_model(model, ((original - mean) / std)[None], device='cpu', shifts=1, split=True, overlap=.25, progress=False, num_workers=0)[0]
        stems = stems * std + mean
        backing = sum(stems[i] for i, name in enumerate(model.sources) if name != 'vocals')
    result = backing.numpy()
    result *= min(1., .98 / max(float(np.max(np.abs(result))), 1e-8))
    with wave.open(output, 'wb') as audio:
        audio.setparams((2, 2, model.samplerate, 0, 'NONE', 'not compressed'))
        audio.writeframes((result.T * 32767).astype('<i2').tobytes())


if __name__ == '__main__':
    separate(sys.argv[1], sys.argv[2])
