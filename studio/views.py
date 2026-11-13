import math
import wave
from functools import wraps
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F, Q
from django.http import FileResponse, HttpResponseForbidden, JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from content.models import Content, ArtistUploadLimit
from content.views import can_view_content
from .models import Project, Track, ExportAllowance, Export, Release
from .limits import MAX_AUDIO_SECONDS, MAX_AUDIO_BYTES
from .catalog import PROFILES, profile_for, beats_for, REFERENCE_NOTES


def artist_only(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_artist():
            return HttpResponseForbidden("Studio is available to artists.")
        from .capacity import artist_storage
        try:
            with artist_storage(request.user.pk):
                response = view(request, *args, **kwargs)
        except ValidationError as exc:
            response = JsonResponse({'error': exc.messages[0]}, status=409)
        response["Cache-Control"] = "private, no-store"
        return response
    return wrapped


def owned(request, pk):
    return get_object_or_404(Project, pk=pk, artist=request.user)


def validate_audio(upload):
    if not upload or upload.size > MAX_AUDIO_BYTES:
        raise ValidationError("Choose a WAV recording under 64 MB.")
    try:
        with wave.open(upload, "rb") as audio:
            if audio.getnchannels() not in (1, 2) or audio.getsampwidth() != 2 or not 8000 <= audio.getframerate() <= 96000 or not 0 < audio.getnframes() / audio.getframerate() <= MAX_AUDIO_SECONDS:
                raise ValueError()
            remaining = audio.getnframes()
            while remaining:
                count = min(remaining, 16384)
                if len(audio.readframes(count)) != count * audio.getnchannels() * 2:
                    raise ValueError()
                remaining -= count
    except (wave.Error, EOFError, ValueError):
        raise ValidationError("Use a valid 16-bit PCM WAV recording up to six minutes.")
    finally:
        upload.seek(0)
    return upload


def parse_track_settings(project, raw):
    import json
    settings = json.loads(raw)
    tracks = {track.pk: track for track in project.tracks.all()}
    if not isinstance(settings, list) or len(settings) != len(tracks) or {item["id"] for item in settings} != set(tracks):
        raise ValueError()
    for item in settings:
        track = tracks[item["id"]]
        if "name" in item:
            name = item["name"]
            if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
                raise ValueError()
            track.name = name.strip()
        for key, maximum in [("gain", 2), ("offset", MAX_AUDIO_SECONDS), ("trim_start", MAX_AUDIO_SECONDS), ("trim_end", MAX_AUDIO_SECONDS)]:
            value = float(item[key])
            if not math.isfinite(value) or not 0 <= value <= maximum:
                raise ValueError()
            setattr(track, key, value)
        if not isinstance(item["muted"], bool):
            raise ValueError()
        track.muted = item["muted"]
    return tracks.values()


@artist_only
def index(request):
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        category = request.POST.get("category")
        if title and len(title) <= 160 and category in dict(Project.TYPES):
            project = Project.objects.create(artist=request.user, title=title, category=category, tempo=profile_for(category)["tempo"])
            return redirect("studio:editor", pk=project.pk)
        messages.error(request, "Enter a title and select a project type.")
    allowance, _ = ExportAllowance.objects.get_or_create(artist=request.user)
    return render(request, "studio/index.html", {"projects": Project.objects.filter(artist=request.user).order_by("-updated_at"), "types": Project.TYPES, "profiles": PROFILES, "type_options": [{"value": value, **profile_for(value)} for value, _ in Project.TYPES], "unlimited_exports": allowance.unlimited_exports, "free_left": allowance.free_remaining})


@artist_only
def editor(request, pk):
    project = owned(request, pk)
    project.pending_render = project.tracks.filter(audio_jobs__operation__in=['mix', 'master'], audio_jobs__status__in=['queued', 'running', 'ready']).values_list('audio_jobs__pk', flat=True).order_by('-audio_jobs__pk').first()
    project.removed_tracks = list(Track.all_objects.filter(project=project, deleted_at__isnull=False).values('id', 'name'))
    from .capacity import usage
    from .storage import private_storage
    from django.conf import settings
    project.storage_used = round(usage(request.user.pk, private_storage) / 1024 / 1024, 1)
    project.storage_limit = settings.STUDIO_ARTIST_STORAGE_MIB
    allowance, _ = ExportAllowance.objects.get_or_create(artist=request.user)
    tracks = [{"id": t.pk, "name": t.name, "url": f"/studio/track/{t.pk}/audio/", "gain": t.gain, "offset": t.offset, "trim_start": t.trim_start, "trim_end": t.trim_end, "muted": t.muted, "kind": t.kind} for t in project.tracks.all()]
    from .models import AudioJob
    for track in tracks:
        job = AudioJob.objects.filter(track_id=track["id"], operation__in=['denoise', 'tune', 'separate'], status__in=["queued", "running", "ready"]).order_by("-pk").first()
        if job:
            track.update(audio_job=job.pk, audio_operation=job.operation)
    return render(request, "studio/editor.html", {"unlimited_exports": allowance.unlimited_exports, "free_left": allowance.free_remaining, "project": project, "revision": project.updated_at.isoformat(), "profile": profile_for(project.category), "reference_notes": REFERENCE_NOTES, "beats": beats_for(project.category), "has_beat": project.tracks.filter(kind="beat").exists(), "tracks": tracks, "exports": Export.objects.filter(project=project).order_by("-created_at"), "releases": Release.objects.filter(project=project).select_related("content")})


@artist_only
@require_POST
def add_track(request, pk):
    project = owned(request, pk)
    upload_key = request.POST.get('upload_key', '')[:64] or None
    if upload_key and Track.all_objects.filter(project=project, upload_key=upload_key).exists():
        return JsonResponse({'ok': True, 'reused': True})
    # Convert compressed imports before locking the project. Recheck revision,
    # quota and edits inside the transaction after conversion completes.
    if request.POST.get("revision") and request.POST["revision"] != project.updated_at.isoformat():
        return JsonResponse({"error": "This project changed in another tab. Reopen it before uploading."}, status=409)
    if project.tracks.count() >= 12:
        return JsonResponse({"error": "Maximum 12 tracks per project."}, status=400)
    try:
        from .audio_import import normalize_upload
        audio = normalize_upload(request.FILES.get("audio"), force_conversion=request.POST.get("original_file") == "1")
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)
    with transaction.atomic():
        project = Project.objects.select_for_update().get(pk=project.pk)
        if upload_key and Track.all_objects.filter(project=project, upload_key=upload_key).exists():
            return JsonResponse({'ok': True, 'reused': True})
        if request.POST.get("revision") and request.POST["revision"] != project.updated_at.isoformat():
            return JsonResponse({"error": "This project changed in another tab. Your local work is retained; reopen the latest project before saving."}, status=409)
        kind = request.POST.get("kind", "vocal")
        if kind not in {"vocal", "backing", "beat"}:
            return JsonResponse({"error": "Unknown track type."}, status=400)
        if project.category == "acapella" and kind != "vocal":
            return JsonResponse({"error": "Acapella projects are vocal-only. Add a voice or vocal-percussion recording."}, status=400)
        preset_id, beat_bpm = "", None
        if kind == "beat":
            preset_id = request.POST.get("beat_preset", "")
            if not any(beat["id"] == preset_id for beat in beats_for(project.category)):
                return JsonResponse({"error": "Choose a rhythm preset for this project type."}, status=400)
            if project.tracks.filter(kind="beat").exists():
                return JsonResponse({"error": "Remove the current Studio beat before adding a different one."}, status=409)
            try:
                beat_bpm = int(request.POST.get("beat_bpm", ""))
                if not 40 <= beat_bpm <= 240:
                    raise ValueError()
            except ValueError:
                return JsonResponse({"error": "Choose a beat tempo from 40 to 240 BPM."}, status=400)
        try:
            tempo = beat_bpm if beat_bpm is not None else int(request.POST.get("tempo", project.tempo))
            if not 40 <= tempo <= 240 or (kind != "beat" and project.tracks.filter(kind="beat").exists() and tempo != project.tempo):
                raise ValueError()
        except ValueError:
            return JsonResponse({"error": "Use a tempo from 40 to 240 BPM. An existing Studio beat keeps its original tempo."}, status=400)
        if project.tracks.count() >= 12:
            return JsonResponse({"error": "Maximum 12 tracks per project."}, status=400)
        try:
            offset = float(request.POST.get("offset", 0))
            with wave.open(audio, "rb") as recording:
                duration = recording.getnframes() / recording.getframerate()
            audio.seek(0)
            if not math.isfinite(offset) or offset < 0 or offset + duration > MAX_AUDIO_SECONDS + .001:
                raise ValueError()
            edits = parse_track_settings(project, request.POST["tracks"]) if "tracks" in request.POST else []
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            return JsonResponse({"error": exc.messages[0] if isinstance(exc, ValidationError) else "Invalid track settings or recording position. Keep the take within six minutes."}, status=400)
        for track in edits:
            track.save()
        Track.objects.create(project=project, name=request.POST.get("name", "Vocal")[:100], audio=audio, offset=offset, kind=kind, beat_preset=preset_id, beat_bpm=beat_bpm, upload_key=upload_key)
        project.tempo = tempo
        project.mix = ""
        project.save()
    return JsonResponse({"ok": True})


@artist_only
@require_POST
def delete_track(request, pk):
    track = get_object_or_404(Track, pk=pk, project__artist=request.user)
    with transaction.atomic():
        project = Project.objects.select_for_update().get(pk=track.project_id)
        if request.POST.get("revision") and request.POST["revision"] != project.updated_at.isoformat():
            return JsonResponse({"error": "This project changed in another tab. Reopen it before deleting a voice."}, status=409)
        try:
            edits = parse_track_settings(project, request.POST["tracks"]) if "tracks" in request.POST else []
        except (ValueError, KeyError, TypeError):
            return JsonResponse({"error": "Invalid track settings. Your saved project was not changed."}, status=400)
        for edited in edits:
            if edited.pk != track.pk:
                edited.save()
        from django.utils import timezone
        track.deleted_at = timezone.now()
        track.save(update_fields=['deleted_at'])
        track.audio_jobs.filter(status__in=['queued', 'running']).update(status='cancelled', finished_at=timezone.now(), error='Track removed. Restore it before processing again.')
        project.mix = ""
        project.save()
    return JsonResponse({"ok": True})


@artist_only
@require_POST
def restore_track(request, pk):
    track = get_object_or_404(Track.all_objects, pk=pk, project__artist=request.user, deleted_at__isnull=False)
    with transaction.atomic():
        project = Project.objects.select_for_update().get(pk=track.project_id)
        if request.POST.get('revision') != project.updated_at.isoformat():
            return JsonResponse({'error': 'Project changed. Reload before restoring.'}, status=409)
        if project.tracks.count() >= 12 or (track.kind == 'beat' and project.tracks.filter(kind='beat').exists()):
            return JsonResponse({'error': 'Make room for this track before restoring it.'}, status=409)
        track.deleted_at = None
        track.save(update_fields=['deleted_at'])
        project.mix = ''
        project.save()
    return JsonResponse({'ok': True})


@artist_only
@require_POST
def save(request, pk):
    try:
        with transaction.atomic():
            project = get_object_or_404(Project.objects.select_for_update(), pk=pk, artist=request.user)
            if request.POST.get("revision") and request.POST["revision"] != project.updated_at.isoformat():
                return JsonResponse({"error": "This project changed in another tab. Your local work is retained; reopen the latest project before saving."}, status=409)
            tempo = int(request.POST.get("tempo", project.tempo))
            if not 40 <= tempo <= 240 or (project.tracks.filter(kind="beat").exists() and tempo != project.tempo):
                raise ValueError()
            audio = validate_audio(request.FILES.get("audio"))
            tracks = parse_track_settings(project, request.POST.get("tracks", "[]"))
            for track in tracks:
                track.save()
            project.tempo = tempo
            project.mix = audio
            project.save()
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        return JsonResponse({"error": exc.messages[0] if isinstance(exc, ValidationError) else "Check voice names, timing settings and tempo."}, status=400)
    return JsonResponse({"ok": True, "revision": project.updated_at.isoformat()})


@artist_only
def track_audio(request, pk):
    track = get_object_or_404(Track, pk=pk, project__artist=request.user)
    return audio_response(track.audio, request=request)


def audio_response(audio, attachment=False, filename=None, request=None):
    from .audio_delivery import deliver
    return deliver(audio, request, attachment, filename)


@artist_only
@require_POST
def publish(request, pk):
    with transaction.atomic():
        project = get_object_or_404(Project.objects.select_for_update(), pk=pk, artist=request.user)
        if not project.mix:
            messages.error(request, "Save a mix before publishing.")
        else:
            quota = ArtistUploadLimit.objects.select_for_update().filter(artist=request.user).first()
            if quota and not quota.has_upload_quota():
                messages.error(request, "Your content upload allowance is unavailable. Contact admin.")
            else:
                content = Content.objects.create(artist=request.user, title=project.title, description=f"Recorded in GGenre Studio · {project.get_category_display()}", category="music")
                Release.objects.create(project=project, content=content, audio=project.mix.name)
                if quota:
                    quota.uploads_used = F("uploads_used") + 1
                    quota.save(update_fields=["uploads_used"])
                messages.success(request, "Sent to GGenre content for admin review. Publishing does not use an export.")
    return redirect("studio:editor", pk=pk)


@artist_only
@require_POST
def export(request, pk):
    with transaction.atomic():
        project = get_object_or_404(Project.objects.select_for_update(), pk=pk, artist=request.user)
        if not project.mix:
            messages.error(request, "Save a mix before exporting.")
        else:
            from .exports import request_export
            item, created = request_export(request.user, project, request.POST.get('payment_reference', ''))
            messages.success(request, 'Your download is ready. Re-downloading this saved version does not use another trial.' if item.status in ('free', 'approved') else 'Export requested. Admin must verify payment before download.')
    return redirect("studio:editor", pk=pk)


@artist_only
def download(request, pk):
    item = get_object_or_404(Export.objects.filter(Q(project__artist=request.user) | Q(instrumental__artist=request.user)), pk=pk, status__in=["free", "approved"])
    return audio_response(item.audio, True, "ggenre-instrumental.wav" if item.instrumental_id else "ggenre-studio.wav")


@login_required
def play(request, pk):
    release = get_object_or_404(Release.objects.select_related("content"), pk=pk)
    if not can_view_content(request.user, release.content):
        raise Http404()
    return audio_response(release.audio)


@login_required
def export_reviews(request):
    if not request.user.is_admin() and not request.user.is_superuser:
        return HttpResponseForbidden("Admin access required.")
    if request.method == "POST":
        status = request.POST.get("decision")
        export_id = request.POST.get("export_id", "")
        if status in {"approved", "rejected"} and export_id.isdecimal():
            updated = Export.objects.filter(pk=export_id, status="pending").update(status=status, reviewed_by=request.user)
            messages.success(request, "Export request reviewed." if updated else "This request has already been reviewed.")
        return redirect("studio:export_reviews")
    return render(request, "studio/export_reviews.html", {"exports": Export.objects.filter(status="pending").select_related("project__artist", "instrumental__artist").order_by("created_at")})


@login_required
def export_controls(request):
    if not request.user.is_admin() and not request.user.is_superuser:
        return HttpResponseForbidden("Admin access required.")
    from django import forms
    from django.contrib.admin.models import LogEntry, CHANGE
    from django.contrib.contenttypes.models import ContentType
    from django.contrib.auth import get_user_model
    from django.core.paginator import Paginator
    from django.db.models import Count, Q

    class AllowanceForm(forms.Form):
        artist_id = forms.IntegerField(min_value=1)
        free_limit = forms.IntegerField(min_value=0, max_value=1000000)
        free_used = forms.IntegerField(min_value=0, max_value=1000000)
        previous_limit = forms.IntegerField(min_value=0)
        previous_used = forms.IntegerField(min_value=0)
        unlimited_exports = forms.BooleanField(required=False)
        previous_unlimited = forms.BooleanField(required=False)
        reason = forms.CharField(max_length=240)
        action = forms.ChoiceField(choices=[("save", "Save"), ("reset", "Reset")])

    if request.method == "POST":
        form = AllowanceForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Changes not saved. Enter whole numbers from 0 to 1,000,000 and a reason (up to 240 characters).")
        else:
            data = form.cleaned_data
            with transaction.atomic():
                artist = get_object_or_404(get_user_model(), pk=data["artist_id"], role="artist")
                allowance, _ = ExportAllowance.objects.get_or_create(artist=artist)
                allowance = ExportAllowance.objects.select_for_update().get(pk=allowance.pk)
                before = (allowance.free_limit, allowance.free_used, allowance.unlimited_exports)
                if before != (data["previous_limit"], data["previous_used"], data["previous_unlimited"]):
                    messages.error(request, "Usage or limits changed since this page opened. Review the refreshed values and try again.")
                else:
                    if data["action"] == "reset":
                        allowance.free_used = 0
                    else:
                        allowance.free_limit, allowance.free_used = data["free_limit"], data["free_used"]
                        allowance.unlimited_exports = data["unlimited_exports"]
                    allowance.save(update_fields=["free_limit", "free_used", "unlimited_exports"])
                    LogEntry.objects.log_actions(user_id=request.user.pk, queryset=ExportAllowance.objects.filter(pk=allowance.pk), action_flag=CHANGE, change_message=f"Limit: {before[0]} to {allowance.free_limit}; used: {before[1]} to {allowance.free_used}; unlimited exports: {'on' if before[2] else 'off'} to {'on' if allowance.unlimited_exports else 'off'}. Reason: {data['reason']}")
                    messages.success(request, f"Export allowance updated for {artist.username}. Export history and payment decisions were preserved.")
        return redirect("studio:export_controls")
    query = request.GET.get("q", "").strip()[:150]
    artists = get_user_model().objects.filter(role="artist").select_related("exportallowance").annotate(export_total=Count("project__export", distinct=True) + Count("instrumental__export", distinct=True), pending_total=Count("project__export", filter=Q(project__export__status="pending"), distinct=True) + Count("instrumental__export", filter=Q(instrumental__export__status="pending"), distinct=True)).order_by("username")
    if query:
        artists = artists.filter(username__icontains=query)
    page = Paginator(artists, 25).get_page(request.GET.get("page"))
    for artist in page:
        try:
            allowance = artist.exportallowance
        except ExportAllowance.DoesNotExist:
            allowance = ExportAllowance(artist=artist)
        artist.studio_allowance = allowance
    history = LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(ExportAllowance)).select_related("user").order_by("-action_time")[:20]
    return render(request, "studio/export_controls.html", {"page": page, "query": query, "history": history})
