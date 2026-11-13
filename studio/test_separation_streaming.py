import importlib.util
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch
from django.test import SimpleTestCase


@skipUnless(all(importlib.util.find_spec(name) for name in ['numpy', 'torch', 'demucs']), 'Optional extraction dependencies are not installed')
class StreamingSeparationTests(SimpleTestCase):
    def test_long_audio_is_processed_in_bounded_windows_without_losing_samples(self):
        import numpy as np
        import torch
        from studio.separate_audio import stream_backing
        rate, length = 100, 6120
        samples = (.2 * np.sin(2 * np.pi * 5 * np.arange(length) / rate) * 32767).astype('<i2')
        model = SimpleNamespace(samplerate=rate, sources=['vocals', 'drums', 'bass', 'other'])
        windows = []
        def identity(model, mix, **kwargs):
            windows.append(mix.shape[-1])
            zero = torch.zeros_like(mix[0])
            return torch.stack([zero, mix[0], zero, zero])[None]
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'source.wav', Path(folder) / 'result.wav'
            with wave.open(str(source), 'wb') as audio:
                audio.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
                audio.writeframes(samples.tobytes())
            with patch('studio.separate_audio.apply_model', side_effect=identity):
                seconds = stream_backing(source, output, model, {'device': 'cpu', 'shifts': 0, 'overlap': .1, 'segment': 2})
            with wave.open(str(output), 'rb') as audio:
                self.assertEqual(audio.getnframes(), length)
                self.assertEqual(audio.getnchannels(), 2)
                result = np.frombuffer(audio.readframes(length), dtype='<i2').reshape(-1, 2)
            self.assertEqual(seconds, length / rate)
            self.assertEqual(len(windows), 11)
            self.assertLessEqual(max(windows), rate * 7)
            np.testing.assert_allclose(result[:, 0], samples, atol=2)
            np.testing.assert_array_equal(result[:, 0], result[:, 1])

    def test_overlap_crossfade_keeps_length_and_smoothly_changes_windows(self):
        import numpy as np
        from studio.separate_audio import blend_overlap
        result = blend_overlap(np.ones((2, 10), dtype=np.float32), np.zeros((2, 4), dtype=np.float32))
        self.assertEqual(result.shape, (2, 10))
        self.assertEqual(result[0, 0], 0)
        self.assertEqual(result[0, 3], 1)
        self.assertTrue(np.all(np.diff(result[0]) >= 0))
