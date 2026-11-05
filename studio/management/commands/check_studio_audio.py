"""Download/check the registered extraction model and exercise real inference."""
import tempfile
import wave
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from studio.audio_processing import available, process
from studio.views import validate_audio


class Command(BaseCommand):
    help = "Check extraction dependencies, cache the Demucs model, and separate generated test audio without creating user data."

    def handle(self, *args, **options):
        if not available()['separate']:
            raise CommandError('Install requirements-audio.txt first.')
        import numpy as np
        import torch
        from django.core.files.storage import FileSystemStorage

        # Some networks stall a single large GET while serving byte ranges.
        # Cache the fixed official model with bounded requests and verify the
        # same SHA-256 prefix used by Demucs before making it available.
        cache = Path(torch.hub.get_dir()) / 'checkpoints'
        cache.mkdir(parents=True, exist_ok=True)
        model = cache / '955717e8-8726e21a.th'
        if not model.exists():
            url = 'https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/' + model.name
            self.stdout.write('Downloading and verifying the official extraction model...')
            with urlopen(Request(url, method='HEAD'), timeout=30) as response:
                size = int(response.headers['Content-Length'])
            chunk_size = 4 * 1024 * 1024

            def download(start):
                end = min(size, start + chunk_size) - 1
                request = Request(url, headers={'Range': f'bytes={start}-{end}'})
                with urlopen(request, timeout=45) as response:
                    if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{size}':
                        raise CommandError('Model server did not honor the requested byte range.')
                    data = response.read(end - start + 2)
                    if len(data) != end - start + 1:
                        raise CommandError('Incomplete model download. Run the check again.')
                    return data

            with tempfile.NamedTemporaryFile(dir=cache, suffix='.download', delete=False) as stream:
                temporary = Path(stream.name)
                digest = hashlib.sha256()
                try:
                    with ThreadPoolExecutor(max_workers=4) as executor:
                        for data in executor.map(download, range(0, size, chunk_size)):
                            stream.write(data)
                            digest.update(data)
                    stream.close()
                    if not digest.hexdigest().startswith('8726e21a'):
                        raise CommandError('Model checksum mismatch; downloaded file was discarded.')
                    os.replace(temporary, model)
                finally:
                    stream.close()
                    temporary.unlink(missing_ok=True)
        with model.open('rb') as stream:
            if not hashlib.file_digest(stream, 'sha256').hexdigest().startswith('8726e21a'):
                raise CommandError('Cached extraction model failed checksum verification. Replace it with the official checkpoint before continuing.')

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.wav'
            rate = 44100
            times = np.arange(rate * 3) / rate
            # Deterministic chord, rhythmic transients and a changing melodic tone.
            x = sum(.06 * np.sin(2 * np.pi * hz * times) for hz in (130.81, 164.81, 196))
            x += .1 * np.sin(2 * np.pi * (300 * times + 18 * np.sin(times * 3)))
            x += .04 * np.random.default_rng(42).normal(size=len(times)) * np.exp(-30 * (times % .5))
            with wave.open(str(source), 'wb') as audio:
                audio.setparams((2, 2, rate, 0, 'NONE', 'not compressed'))
                audio.writeframes((np.repeat(x[:, None], 2, axis=1) * 32767).astype('<i2').tobytes())

            # Exercise the same processing function as queued jobs, with temporary
            # storage rather than a real artist or project.
            class Result:
                def save(self, name, content, save=False):
                    self.data = content.read()

            class Job:
                operation = 'separate'
                result = Result()
                source = FileSystemStorage(location=folder).open('source.wav', 'rb')

                def save(self, **kwargs):
                    pass

            job = Job()
            self.stdout.write('Running real Demucs extraction (the first run downloads the model)...')
            try:
                process(job)
                validate_audio(ContentFile(job.result.data, name='result.wav'))
                with wave.open(str(source), 'rb') as original:
                    original_frames = original.getnframes()
                import io
                with wave.open(io.BytesIO(job.result.data), 'rb') as result:
                    if result.getnchannels() != 2 or result.getframerate() != rate or result.getnframes() != original_frames:
                        raise ValueError('Output format or duration differs from input.')
                    samples = np.frombuffer(result.readframes(original_frames), dtype='<i2')
                    if not np.any(samples):
                        raise ValueError('The extracted instrumental is silent.')
                self.stdout.write(self.style.SUCCESS('PASS: real extraction produced a non-silent, three-second stereo PCM WAV. Model is cached.'))
            except Exception as exc:
                if hasattr(exc, 'stderr') and exc.stderr:
                    self.stderr.write(exc.stderr.decode(errors='replace')[-4000:])
                raise CommandError(f'Extraction setup check failed: {exc}') from exc
            finally:
                job.source.close()
