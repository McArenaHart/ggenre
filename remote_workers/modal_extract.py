"""Optional Modal pilot. Importing/deploying is separate from running Django.

Do not deploy or invoke before verifying the provider's $0 spend limit.
"""
import tempfile
import wave
from pathlib import Path
import modal

app = modal.App('ggenre-extraction-pilot')
control_image = modal.Image.debian_slim(python_version='3.11').pip_install('fastapi[standard]').add_local_python_source('remote_workers')
audio_image = (modal.Image.debian_slim(python_version='3.11')
    .apt_install('libgomp1', 'ffmpeg')
    .pip_install('torch==2.8.0', 'torchaudio==2.8.0', 'demucs==4.0.1', 'numpy>=1.26,<3', 'Django==5.1.4', 'imageio-ffmpeg==0.6.0')
    .env({'STUDIO_EXTRACTION_DEVICE': 'cuda', 'STUDIO_EXTRACTION_PROFILE': 'fast', 'STUDIO_EXTRACTION_THREADS': '1', 'STUDIO_EXTRACTION_WINDOW_SECONDS': '6', 'TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD': '1'})
    .add_local_python_source('studio', 'remote_workers'))


@app.cls(image=audio_image, gpu='T4', cpu=1, memory=4096, max_containers=1, timeout=600, scaledown_window=2)
class Extractor:
    @modal.enter()
    def load(self):
        import torch
        from demucs.pretrained import get_model
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        self.model = get_model('htdemucs').to('cuda').eval()
        for part in getattr(self.model, 'models', [self.model]):
            part.segment = min(float(part.segment), 2.)

    @modal.method()
    def extract(self, payload):
        from remote_workers.transfer import validate_payload, active, download, upload
        from studio.separate_audio import stream_backing
        from studio.separation_options import extraction_options
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
                stream_backing(source, output, self.model, extraction_options(True), check=check)
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
    validate_payload(payload, 'https://www.ggenre.com')
    if not active(payload):
        return {'accepted': False}
    call = Extractor().extract.spawn(payload)
    return {'accepted': True, 'call_id': call.object_id}
