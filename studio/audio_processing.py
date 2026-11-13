"""Private, bounded offline audio processing; heavy engines load only in workers."""
import importlib.util
import math
import logging
import subprocess
import sys
import time
import tempfile
import shutil
from pathlib import Path

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files import File
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST
from django.utils import timezone

from .models import AudioJob, AudioJobInput, Project, Track, Instrumental
from .limits import MAX_AUDIO_SECONDS, MAX_AUDIO_BYTES
from .views import artist_only, owned, validate_audio
from .video_render import run_ffmpeg

logger = logging.getLogger(__name__)


def available():
    def installed(*packages):
        return all(importlib.util.find_spec(package) is not None for package in packages)
    return {"denoise": True, "tune": installed("numpy", "scipy", "pyworld"),
            "separate": installed("numpy", "scipy", "torch", "torchaudio", "demucs")}


def processing_available():
    engines = dict(available())
    remote = set(settings.STUDIO_REMOTE_AUDIO_ENGINES) & {'tune', 'separate', 'denoise'}
    if remote:
        from datetime import timedelta
        from .models import StudioMaintenance
        if StudioMaintenance.objects.filter(pk='audio-worker', last_success_at__gte=timezone.now() - timedelta(seconds=90)).exists():
            engines.update({engine: True for engine in remote})
    return engines


def options_for(operation, raw):
    if operation == "denoise":
        strength = float(raw.get("strength", 10))
        cutoff = float(raw.get("cutoff", 60))
        hum = str(raw.get("hum", "off"))
        if not math.isfinite(strength) or not 1 <= strength <= 24 or not math.isfinite(cutoff) or not 20 <= cutoff <= 150 or hum not in ("off", "50", "60"):
            raise ValueError("Check noise reduction, rumble cutoff and hum frequency.")
        return {"strength": strength, "cutoff": cutoff, "hum": hum}
    if operation == "tune":
        key, scale = int(raw.get("key", 0)), raw.get("scale", "major")
        strength, speed = float(raw.get("strength", .65)), float(raw.get("speed", 80))
        if not 0 <= key <= 11 or scale not in ("major", "minor", "chromatic") or not math.isfinite(strength) or not 0 <= strength <= 1 or not math.isfinite(speed) or not 0 <= speed <= 300:
            raise ValueError("Check musical key, scale, strength and retune speed.")
        return {"key": key, "scale": scale, "strength": strength, "speed": speed}
    if operation == "separate":
        if raw.get("permission") != "yes":
            raise ValueError("Confirm you have permission to reuse this recording.")
        return {}
    raise ValueError("Choose an audio tool.")


@artist_only
@require_POST
def convert(request):
    try:
        from .audio_import import normalize_upload
        return FileResponse(normalize_upload(request.FILES.get("audio"), force_conversion=True), content_type="audio/wav")
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)


@artist_only
@require_POST
def master(request, pk):
    owned(request, pk)
    try:
        audio = validate_audio(request.FILES.get("audio"))
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)

    try:
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / "mix.wav", Path(folder) / "master.wav"
            with source.open("wb") as stream:
                for chunk in audio.chunks():
                    stream.write(chunk)
            filters = "highpass=f=25,acompressor=threshold=0.125:ratio=2:attack=20:release=150,loudnorm=I=-14:TP=-1.5:LRA=11"
            run_ffmpeg(["-f", "wav", "-i", str(source), "-af", filters, "-ar", "44100", "-c:a", "pcm_s16le", str(output)])
            result = validate_audio(ContentFile(output.read_bytes(), name="master.wav"))
            return FileResponse(result, content_type="audio/wav")
    except ValidationError:
        return JsonResponse({"error": "Auto Master could not process this mix. Try again."}, status=422)


@artist_only
@require_POST
def queue(request, pk):
    track = get_object_or_404(Track, pk=pk, project__artist=request.user)
    try:
        operation = request.POST.get("operation")
        options = options_for(operation, request.POST)
        if operation == "tune" and track.kind != "vocal":
            raise ValueError("Pitch correction needs an individual vocal track.")
        if operation == "separate" and track.project.category == "acapella":
            raise ValueError("Use a Gospel or Secular project for instrumental extraction.")
        if not processing_available()[operation]:
            return JsonResponse({"error": "This audio engine is not installed on the server. See Studio audio setup."}, status=503)
        with transaction.atomic():
            # The queue allowance is per artist, including simultaneous requests
            # from different projects/tabs.
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            Project.objects.select_for_update().get(pk=track.project_id)
            if operation == 'separate':
                pending = AudioJob.objects.filter(track=track, operation='separate', source=track.audio.name, status__in=['queued', 'running', 'ready', 'applied']).exclude(result='', status__in=['ready', 'applied']).order_by('-pk').first()
                if pending:
                    if pending.status not in ('ready', 'applied') or pending.result.storage.exists(pending.result.name):
                        if pending.status == 'applied':
                            pending = AudioJob.objects.create(track=track, operation='separate', source=track.audio.name, result=pending.result.name, status='ready')
                        return JsonResponse({'id': pending.pk, 'status': pending.status, 'reused': True})
            if AudioJob.objects.filter(track__project__artist=request.user, status__in=["queued", "running"]).count() >= 2:
                return JsonResponse({"error": "Two audio tasks are already pending. Wait for them to finish."}, status=409)
            # Studio files have immutable UUID names: pin the existing source
            # instead of storing another full WAV for every processing request.
            job = AudioJob.objects.create(track=track, operation=operation, options=options, source=track.audio.name)
        return JsonResponse({"id": job.pk, "status": job.status})
    except (ValueError, TypeError, OverflowError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)


@artist_only
def job_status(request, pk):
    job = get_object_or_404(AudioJob, pk=pk, track__project__artist=request.user)
    return JsonResponse({"id": job.pk, "status": job.status, "error": job.error,
                         "queue_position": AudioJob.objects.filter(status='queued', pk__lte=job.pk).count() if job.status == 'queued' else None,
                         "url": f"/studio/audio-jobs/{job.pk}/audio/" if job.result else None})


@artist_only
@require_POST
def cancel(request, pk):
    job = get_object_or_404(AudioJob, pk=pk, track__project__artist=request.user)
    AudioJob.objects.filter(pk=job.pk, status__in=['queued', 'running']).update(status='cancelled', finished_at=timezone.now(), error='Cancelled. You can start another task.')
    return JsonResponse({'ok': True})


@artist_only
@require_POST
def queue_mix(request, pk):
    from .views import parse_track_settings
    with transaction.atomic():
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        project = get_object_or_404(Project.objects.select_for_update(), pk=pk, artist=request.user)
        try:
            if request.POST.get('revision') != project.updated_at.isoformat():
                return JsonResponse({'error': 'Project changed. Reload before saving this mix.'}, status=409)
            tempo = int(request.POST.get('tempo', project.tempo))
            if not 40 <= tempo <= 240 or (project.tracks.filter(kind='beat').exists() and tempo != project.tempo):
                raise ValueError()
            edits = list(parse_track_settings(project, request.POST.get('tracks', '[]')))
            active = [track for track in edits if not track.muted]
            if not active:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            return JsonResponse({'error': 'Check tempo and timing, and unmute at least one track.'}, status=400)
        operation = 'master' if request.POST.get('master') == 'yes' else 'mix'
        snapshot = {'revision': project.updated_at.isoformat(), 'tempo': tempo, 'tracks': [{key: getattr(track, key) for key in ('id', 'name', 'gain', 'offset', 'trim_start', 'trim_end', 'muted')} for track in edits]}
        existing = AudioJob.objects.filter(track__project=project, operation=operation, options=snapshot, status__in=['queued', 'running', 'ready']).first()
        if existing:
            return JsonResponse({'id': existing.pk, 'status': existing.status, 'reused': True})
        if AudioJob.objects.filter(track__project__artist=request.user, status__in=['queued', 'running']).count() >= 2:
            return JsonResponse({'error': 'Two audio tasks are pending. Wait or cancel one before saving.'}, status=409)
        job = AudioJob.objects.create(track=active[0], operation=operation, options=snapshot, source=active[0].audio.name)
        AudioJobInput.objects.bulk_create([AudioJobInput(job=job, audio=track.audio.name, settings={key: getattr(track, key) for key in ('gain', 'offset', 'trim_start', 'trim_end')}) for track in active])
    return JsonResponse({'id': job.pk, 'status': job.status})


@artist_only
def job_audio(request, pk):
    job = get_object_or_404(AudioJob, pk=pk, track__project__artist=request.user, status="ready")
    from .audio_delivery import deliver
    return deliver(job.result, request)


@artist_only
@require_POST
def apply(request, pk):
    with transaction.atomic():
        job = get_object_or_404(AudioJob.objects.select_for_update(), pk=pk, track__project__artist=request.user, status="ready")
        project = Project.objects.select_for_update().get(pk=job.track.project_id)
        if request.POST.get("revision") != project.updated_at.isoformat():
            return JsonResponse({"error": "Project changed. Reload before applying this result."}, status=409)
        if job.operation in ('mix', 'master'):
            from .views import parse_track_settings
            import json
            if job.options['revision'] != project.updated_at.isoformat():
                return JsonResponse({'error': 'Project changed while rendering. Save the latest version again.'}, status=409)
            for track in parse_track_settings(project, json.dumps(job.options['tracks'])):
                track.save()
            project.tempo = job.options['tempo']
            project.mix = job.result.name
            project.save()
            job.status = 'applied'
            job.save(update_fields=['status'])
            return JsonResponse({'ok': True, 'revision': project.updated_at.isoformat()})
        if request.POST.get("library") == "yes":
            if job.operation != "separate":
                return JsonResponse({"error": "Only extracted instrumentals belong in this library."}, status=400)
            Instrumental.objects.create(artist=request.user, title=(job.track.name + " instrumental")[:160], category=project.category,
                config={"imported": True, "bpm": project.tempo}, audio=job.result.name)
        else:
            if project.tracks.count() >= 12:
                return JsonResponse({"error": "Make room for a processed track first (maximum 12)."}, status=409)
            old = job.track
            Track.objects.create(project=project, name=(old.name + " · " + job.operation)[:100],
                kind="backing" if job.operation == "separate" or old.kind == "beat" else old.kind,
                audio=job.result.name, gain=old.gain,
                offset=old.offset, trim_start=old.trim_start, trim_end=old.trim_end)
            old.muted = True
            old.save(update_fields=["muted"])
            project.mix = ""
            project.save()
        job.status = "applied"
        job.save(update_fields=["status"])
    return JsonResponse({"ok": True})


def tune(source, output, options):
    import numpy as np
    import pyworld as pw
    import wave
    from scipy.ndimage import uniform_filter1d
    with wave.open(str(source), "rb") as audio:
        rate, channels = audio.getframerate(), audio.getnchannels()
        samples = np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").reshape(-1, channels).mean(axis=1) / 32768.
    samples = np.ascontiguousarray(samples, dtype=np.float64)
    if rate < 16000:
        raise ValueError("Pitch correction requires at least 16 kHz audio. Re-import this recording.")
    # Process short independent chunks to bound WORLD spectral-envelope memory.
    rendered = []
    for start in range(0, len(samples), rate * 10):
        x = np.ascontiguousarray(samples[max(0, start - rate // 10):min(len(samples), start + rate * 10 + rate // 10)])
        f0, times = pw.dio(x, rate, f0_floor=50, f0_ceil=1100)
        f0 = pw.stonemask(x, f0, times, rate)
        voiced = f0 > 0
        midi = 69 + 12 * np.log2(np.maximum(f0, 1) / 440)
        intervals = {"major": [0, 2, 4, 5, 7, 9, 11], "minor": [0, 2, 3, 5, 7, 8, 10], "chromatic": list(range(12))}[options["scale"]]
        allowed = np.array([n for n in range(-12, 152) if (n - options["key"]) % 12 in intervals])
        target = allowed[np.abs(midi[:, None] - allowed).argmin(axis=1)]
        correction = np.where(voiced, (target - midi) * options["strength"], 0)
        window = max(1, round(options["speed"] / 5))
        weights = uniform_filter1d(voiced.astype(float), size=window)
        correction = uniform_filter1d(correction, size=window) / np.maximum(weights, 1e-9)
        corrected = f0 * 2 ** (correction / 12)
        sp, ap = pw.cheaptrick(x, f0, times, rate), pw.d4c(x, f0, times, rate)
        y = pw.synthesize(corrected, sp, ap, rate)
        left = min(start, rate // 10)
        length = min(rate * 10, len(samples) - start)
        rendered.append(np.pad(y, (0, max(0, left + length - len(y))))[left:left + length])
    result = np.concatenate(rendered)
    if not np.isfinite(result).all():
        raise ValueError("This recording could not be tuned. Try a cleaner solo vocal.")
    peak = np.max(np.abs(result))
    if peak > .98:
        result *= .98 / peak
    with wave.open(str(output), "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes((np.clip(result, -1, 1) * 32767).astype("<i2").tobytes())


def process(job, check=None):
    check = check or (lambda: None)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        source, output = root / "input.wav", root / "output.wav"
        try:
            source = Path(job.source.path)
        except (AttributeError, NotImplementedError):
            with job.source.open('rb') as stream, source.open('wb') as target:
                shutil.copyfileobj(stream, target, length=1024 * 1024)
        check()
        if job.operation in ('mix', 'master'):
            from .render_mix import render
            render(job, root, output, check)
        elif job.operation == "denoise":
            o = job.options
            filters = [f"highpass=f={o['cutoff']}", f"afftdn=nr={o['strength']}:tn=1"]
            if o["hum"] != "off":
                filters += [f"equalizer=f={int(o['hum']) * n}:t=q:w=20:g=-18" for n in (1, 2, 3)]
            run_ffmpeg(["-i", str(source), "-af", ",".join(filters), "-c:a", "pcm_s16le", str(output)])
        elif job.operation == "tune":
            tune(source, output, job.options)
        else:
            started = time.perf_counter()
            with subprocess.Popen([sys.executable, "-m", "studio.separate_audio", str(source), str(output)],
                cwd=settings.BASE_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as child:
                try:
                    while True:
                        check()
                        if time.perf_counter() - started > 1800:
                            raise subprocess.TimeoutExpired(child.args, 1800)
                        try:
                            stdout, stderr = child.communicate(timeout=3)
                            break
                        except subprocess.TimeoutExpired:
                            continue
                    if child.returncode:
                        raise subprocess.CalledProcessError(child.returncode, child.args, stdout, stderr)
                    if stdout:
                        logger.info('Extraction completed in %.2f seconds: %s', time.perf_counter() - started, stdout.decode(errors='replace')[-2000:].strip())
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.communicate()
        check()
        with output.open('rb') as stream:
            result = File(stream, name='processed.wav')
            validate_audio(result)
            job.result.save('processed.wav', result, save=False)
        if not isinstance(job, AudioJob):
            job.status, job.error = 'ready', ''
            job.save()
            return
        with transaction.atomic():
            current = AudioJob.objects.select_for_update().get(pk=job.pk)
            if job.lease_token and (current.status != 'running' or current.lease_token != job.lease_token):
                from .job_control import JobStopped
                raise JobStopped('Audio task no longer belongs to this worker')
            job.status, job.error, job.finished_at = 'ready', '', timezone.now()
            job.save(update_fields=['result', 'status', 'error', 'finished_at'])
