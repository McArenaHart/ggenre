"""Optional Modal pilot. Importing/deploying is separate from running Django.

Do not deploy or invoke before verifying the provider's $0 spend limit.
"""
import os
import tempfile
import wave
from pathlib import Path
import modal

app = modal.App('ggenre-extraction-pilot')
accelerator = os.getenv('GGENRE_MODAL_ACCELERATOR', 'cpu').strip().lower()
if accelerator not in ('cpu', 't4'):
    raise ValueError('GGENRE_MODAL_ACCELERATOR must be cpu or t4.')
control_image = modal.Image.debian_slim(python_version='3.11').pip_install('fastapi[standard]').add_local_python_source('remote_workers')
audio_base = modal.Image.debian_slim(python_version='3.11').apt_install('libgomp1')
if accelerator == 'cpu':
    audio_base = audio_base.pip_install('torch==2.8.0', 'torchaudio==2.8.0', index_url='https://download.pytorch.org/whl/cpu')
else:
    audio_base = audio_base.pip_install('torch==2.8.0', 'torchaudio==2.8.0')
audio_image = (audio_base
    .pip_install('demucs==4.0.1', 'numpy>=1.26,<3', 'Django==5.1.4', 'imageio-ffmpeg==0.6.0')
    .env({'STUDIO_EXTRACTION_DEVICE': 'auto', 'STUDIO_EXTRACTION_PROFILE': 'fast', 'STUDIO_EXTRACTION_THREADS': '2' if accelerator == 'cpu' else '1', 'STUDIO_EXTRACTION_WINDOW_SECONDS': '6', 'TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD': '1'})
    .add_local_python_source('studio', 'remote_workers'))


@app.cls(image=audio_image, gpu='T4' if accelerator == 't4' else None, cpu=2 if accelerator == 'cpu' else 1, memory=2048 if accelerator == 'cpu' else 4096, max_containers=1, timeout=600, scaledown_window=2)
class Extractor:
    @modal.enter()
    def load(self):
        import torch
        from demucs.pretrained import get_model
        from studio.separation_options import extraction_options
        self.options = extraction_options(torch.cuda.is_available())
        torch.set_num_threads(self.options['threads'])
        torch.set_num_interop_threads(1)
        self.model = get_model('htdemucs').to(self.options['device']).eval()
        for part in getattr(self.model, 'models', [self.model]):
            part.segment = min(float(part.segment), 2.)

    @modal.method()
    def self_test(self):
        """Operator-only SDK check using generated sound, never artist audio."""
        import time
        import numpy as np
        from studio.separate_audio import stream_backing
        started = time.monotonic()
        rate = self.model.samplerate
        times = np.arange(rate) / rate
        samples = .15 * np.sin(2 * np.pi * 220 * times) + .1 * np.sin(2 * np.pi * 330 * times)
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'synthetic.wav', Path(folder) / 'result.wav'
            with wave.open(str(source), 'wb') as audio:
                audio.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
                audio.writeframes((np.repeat(samples[:, None], 2, axis=1) * 32767).astype('<i2').tobytes())
            stream_backing(source, output, self.model, self.options)
            with wave.open(str(output), 'rb') as audio:
                frames, channels = audio.getnframes(), audio.getnchannels()
                non_silent = bool(np.any(np.frombuffer(audio.readframes(frames), dtype='<i2')))
            if frames != rate or channels != 2 or not non_silent:
                raise ValueError('The synthetic extraction check failed.')
        return {'device': self.options['device'], 'frames': frames, 'channels': channels, 'non_silent': non_silent, 'engine_seconds': round(time.monotonic() - started, 2)}

    @modal.method()
    def extract(self, payload):
        from remote_workers.transfer import validate_payload, active, download, upload
        from studio.separate_audio import stream_backing
        validate_payload(payload, 'https://www.ggenre.com')
        try:
            with tempfile.TemporaryDirectory() as folder:
                source, output = Path(folder) / 'source.wav', Path(folder) / 'backing.wav'
                def check():
                    if not active(payload):
                        raise ValueError('This extraction was cancelled or already completed.')
                check()
                download(payload, source)
                with wave.open(str(source), 'rb') as audio:
                    rate = audio.getframerate()
                    if audio.getsampwidth() != 2 or audio.getnchannels() not in (1, 2) or not 0 < audio.getnframes() / rate <= 360:
                        raise ValueError('Invalid source audio.')
                if rate != self.model.samplerate:
                    from studio.video_render import run_ffmpeg
                    normalized = Path(folder) / 'normalized.wav'
                    run_ffmpeg(['-i', str(source), '-ar', str(self.model.samplerate), '-ac', '2', '-c:a', 'pcm_s16le', str(normalized)])
                    source = normalized
                stream_backing(source, output, self.model, self.options, check=check)
                check()
                upload(payload, output)
                return {'ok': True}
        except Exception:
            try:
                upload(payload)
            except Exception:
                pass
            # Do not log signed transfer tokens or raw callback payloads.
            return {'ok': False}


@app.function(image=control_image, max_containers=1, timeout=30, scaledown_window=2)
@modal.fastapi_endpoint(method='POST', requires_proxy_auth=True)
def submit(payload: dict):
    from remote_workers.transfer import validate_payload, active
    if payload == {'probe': True}:
        return {'ready': True, 'submitted': False, 'accelerator': accelerator}
    try:
        validate_payload(payload, 'https://www.ggenre.com')
    except (ValueError, TypeError, AttributeError):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail='Invalid extraction request.') from None
    if not active(payload):
        return {'accepted': False}
    call = Extractor().extract.spawn(payload)
    return {'accepted': True, 'call_id': call.object_id}
