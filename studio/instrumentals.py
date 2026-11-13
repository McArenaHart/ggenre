import json
import wave
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from .views import artist_only, validate_audio
from .models import Instrumental, Project, Track, Export, ExportAllowance
from .catalog import BEATS
from .composition import validate_config


@artist_only
def library(request):
    items = list(Instrumental.objects.filter(artist=request.user).order_by('-updated_at'))
    exports = {}
    for export in Export.objects.filter(instrumental__artist=request.user).order_by('-created_at', '-pk'):
        exports.setdefault((export.instrumental_id, export.audio.name), export)
    for item in items:
        item.download_export = exports.get((item.pk, item.audio.name))
        item.downloadable = item.download_export and item.download_export.status in ('free', 'approved')
        item.pending_download = item.download_export and item.download_export.status == 'pending'
    allowance, _ = ExportAllowance.objects.get_or_create(artist=request.user)
    return render(request, "studio/instrumentals.html", {"instrumentals": items, 'free_left': allowance.free_remaining, 'unlimited_exports': allowance.unlimited_exports,
        'downloads': Export.objects.filter(instrumental__artist=request.user, status__in=['free', 'approved']).select_related('instrumental').order_by('-created_at'),
        "projects": Project.objects.filter(artist=request.user).exclude(category="acapella").order_by("-updated_at")})


@artist_only
@require_POST
def request_download(request, pk):
    from .exports import request_export
    with transaction.atomic():
        item = get_object_or_404(Instrumental.objects.select_for_update(), pk=pk, artist=request.user)
        if not item.audio:
            messages.error(request, 'Save this instrumental before downloading it.')
            return redirect('studio:instrumentals')
        # Re-downloading the same saved version must not spend another trial.
        export, _ = request_export(request.user, item, request.POST.get('payment_reference', ''))
        if export.status in ('free', 'approved'):
            messages.success(request, 'Your instrumental download is ready. Re-downloading this saved version does not use another trial.')
            from django.urls import reverse
            return redirect(reverse('studio:instrumentals') + f'#download-{item.pk}')
        messages.info(request, 'Your trial downloads are used. This instrumental download is awaiting admin payment approval.')
    return redirect('studio:instrumentals')


@artist_only
def workspace(request, pk=None):
    item = get_object_or_404(Instrumental, pk=pk, artist=request.user) if pk else None
    if item and item.config.get("imported"):
        messages.info(request, "Extracted instrumentals are audio recordings. Use one in a Studio session to trim, mix or process it.")
        return redirect("studio:instrumentals")
    mode = request.GET.get("mode", "full")
    if mode not in ("piano", "bass", "chords", "full", "drums"):
        mode = "full"
    config = item.config if item else {"schema": 1, "mode": mode, "bpm": 90, "bars": 8, "key": 0, "progression": "worship", "preset": "gospel-worship", "notes": {"piano": [], "bass": [], "pad": []}, "drums": {}, "levels": {}}
    if not item:
        config.update(schema=2, bars=32, clips=[], sounds={"pad": "warm-pad"})
    template = "studio/piano.html"
    return render(request, template, {"midi_channels": range(1, 17), "workspace_label": {"piano": "Piano", "bass": "Bass", "chords": "Chords", "drums": "Drums", "full": "Full arrangement"}[config["mode"]], "item": item, "config": config, "presets": BEATS, "keys": ["C", "C♯ / D♭", "D", "D♯ / E♭", "E", "F", "F♯ / G♭", "G", "G♯ / A♭", "A", "A♯ / B♭", "B"]})


@artist_only
@require_POST
def save(request, pk=None):
    with transaction.atomic():
        item = get_object_or_404(Instrumental.objects.select_for_update(), pk=pk, artist=request.user) if pk else Instrumental(artist=request.user)
        if pk and item.config.get("imported"):
            return JsonResponse({"error": "Extracted audio cannot be overwritten by a piano-roll arrangement. Edit a copy in Studio."}, status=400)
        if pk and request.POST.get("revision") != item.updated_at.isoformat():
            return JsonResponse({"error": "This instrumental changed in another tab. Reload the saved version before editing."}, status=409)
        try:
            title = request.POST.get("title", "").strip()
            category = request.POST.get("category")
            if not title or len(title) > 160 or category not in ("gospel", "secular"):
                raise ValueError("Enter a name and select Gospel or Secular.")
            config = validate_config(json.loads(request.POST.get("config", "null")), category)
            audio = validate_audio(request.FILES.get("audio"))
            with wave.open(audio, "rb") as recording:
                duration = recording.getnframes() / recording.getframerate()
            audio.seek(0)
            if abs(duration - config["bars"] * 240 / config["bpm"]) > .03:
                raise ValueError("Audio length does not match the arrangement. Preview and save again.")
        except (ValueError, TypeError, KeyError, ValidationError) as exc:
            return JsonResponse({"error": exc.messages[0] if isinstance(exc, ValidationError) else str(exc)}, status=400)
        item.title, item.category, item.config, item.audio = title, category, config, audio
        item.save()
    return JsonResponse({"ok": True, "id": item.pk, "revision": item.updated_at.isoformat(), "url": f"/studio/instrumentals/{item.pk}/"})


@artist_only
def audio(request, pk):
    item = get_object_or_404(Instrumental, pk=pk, artist=request.user)
    from .audio_delivery import deliver
    return deliver(item.audio, request)


@artist_only
@require_POST
def use(request, pk):
    with transaction.atomic():
        item = get_object_or_404(Instrumental.objects.select_for_update(), pk=pk, artist=request.user)
        if not item.audio:
            messages.error(request, "Save your instrumental before using it in Studio.")
            return redirect("studio:instrumentals")
        target = request.POST.get("project", "")
        if target:
            try:
                target = int(target)
            except ValueError:
                return JsonResponse({"error": "Choose a Studio project."}, status=400)
            project = get_object_or_404(Project.objects.select_for_update(), pk=target, artist=request.user)
            if project.category != item.category or project.tracks.filter(kind="beat").exists() or project.tracks.count() >= 12 or (project.tracks.exists() and project.tempo != item.config["bpm"]):
                messages.error(request, "Choose a matching category and tempo with room for a backing track, or start a new vocal session.")
                return redirect("studio:instrumentals")
        else:
            project = Project.objects.create(artist=request.user, title=item.title[:160], category=item.category, tempo=item.config["bpm"])
        # Saved audio names are immutable. Pin the version without reading or
        # duplicating its WAV; subsequent library edits write a different name.
        Track.objects.create(project=project, name=item.title[:100], kind="backing" if item.config.get("imported") else "beat", audio=item.audio.name, beat_preset=item.config.get("preset", ""), beat_bpm=None if item.config.get("imported") else item.config["bpm"])
        project.tempo = item.config["bpm"]
        project.mix = ""
        project.save()
    messages.success(request, "Saved instrumental copied into your session. You can now record vocals.")
    return redirect("studio:editor", pk=project.pk)


@artist_only
@require_POST
def keyboard_audio(request):
    category = request.POST.get("category", "gospel")
    title = request.POST.get("title", "Keyboard audio session").strip()
    try:
        tempo = int(request.POST.get("tempo", "90"))
        if category not in ("gospel", "secular") or not title or not 40 <= tempo <= 240:
            raise ValueError()
    except ValueError:
        return JsonResponse({"error": "Choose Gospel or Secular, a title and a tempo from 40 to 240 BPM."}, status=400)
    project = Project.objects.create(artist=request.user, title=title[:160], category=category, tempo=tempo)
    return redirect(f"/studio/project/{project.pk}/?input=keyboard")
