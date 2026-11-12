"""Private, bounded offline audio processing; heavy engines load only in workers."""
import importlib.util
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from .models import AudioJob, Project, Track, Instrumental
from .limits import MAX_AUDIO_SECONDS, MAX_AUDIO_BYTES
from .views import artist_only, owned, validate_audio
from .video_render import run_ffmpeg


def available():
    def installed(*packages):
        return all(importlib.util.find_spec(package) is not None for package in packages)
    return {"denoise": True, "tune": installed("numpy", "scipy", "pyworld"),
            "separate": installed("numpy", "scipy", "torch", "torchaudio", "demucs")}


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
        if not available()[operation]:
            return JsonResponse({"error": "This audio engine is not installed on the server. See Studio audio setup."}, status=503)
        with transaction.atomic():
            # The queue allowance is per artist, including simultaneous requests
            # from different projects/tabs.
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            Project.objects.select_for_update().get(pk=track.project_id)
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
                         "url": f"/studio/audio-jobs/{job.pk}/audio/" if job.result else None})


@artist_only
def job_audio(request, pk):
    job = get_object_or_404(AudioJob, pk=pk, track__project__artist=request.user, status="ready")
    return FileResponse(job.result.open("rb"), content_type="audio/wav")


@artist_only
@require_POST
def apply(request, pk):
    with transaction.atomic():
        job = get_object_or_404(AudioJob.objects.select_for_update(), pk=pk, track__project__artist=request.user, status="ready")
        project = Project.objects.select_for_update().get(pk=job.track.project_id)
        if request.POST.get("revision") != project.updated_at.isoformat():
            return JsonResponse({"error": "Project changed. Reload before applying this result."}, status=409)
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


def process(job):
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        source, output = root / "input.wav", root / "output.wav"
        with job.source.open("rb") as stream:
            source.write_bytes(stream.read())
        if job.operation == "denoise":
            o = job.options
            filters = [f"highpass=f={o['cutoff']}", f"afftdn=nr={o['strength']}:tn=1"]
            if o["hum"] != "off":
                filters += [f"equalizer=f={int(o['hum']) * n}:t=q:w=20:g=-18" for n in (1, 2, 3)]
            run_ffmpeg(["-i", str(source), "-af", ",".join(filters), "-c:a", "pcm_s16le", str(output)])
        elif job.operation == "tune":
            tune(source, output, job.options)
        else:
            subprocess.run([sys.executable, "-m", "studio.separate_audio", str(source), str(output)],
                cwd=settings.BASE_DIR, check=True, capture_output=True, timeout=1800, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        result = ContentFile(output.read_bytes(), name="processed.wav")
        validate_audio(result)
        job.result.save("processed.wav", result, save=False)
        job.status, job.error = "ready", ""
        job.save(update_fields=["result", "status", "error"])
