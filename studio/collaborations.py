import tempfile
import uuid
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files import File
from django.db import transaction
from django.db.models import F
from django.http import FileResponse, Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods

from content.models import ArtistUploadLimit, Content
from content.views import can_view_content
from .models import VideoCollaboration
from .views import artist_only, validate_audio
from .video_render import copy_source, render_video
from .guide_cache import open_guide

ROLES = ("Harmony", "Lead", "Bass", "Beatbox", "Choir", "Other vocal")


def joinable(content):
    return content.allow_collaboration and content.is_approved and content.is_visible and content.collaboration_supported


def source_for(pk, lock=False):
    queryset = Content.objects.select_for_update() if lock else Content.objects.select_related("artist", "video_collaboration")
    source = get_object_or_404(queryset, pk=pk)
    if not joinable(source):
        raise Http404("This video is not open for collaboration.")
    return source


@artist_only
@require_POST
def permission(request, pk):
    with transaction.atomic():
        source = get_object_or_404(Content.objects.select_for_update(), pk=pk, artist=request.user)
        if not source.collaboration_supported:
            raise Http404()
        source.allow_collaboration = request.POST.get("allow") == "yes"
        source.save(update_fields=["allow_collaboration"])
    messages.success(request, "This video is open to vocal collaborations." if source.allow_collaboration else "New collaborations are closed. Existing collaborated posts remain unchanged.")
    return redirect("content_detail", content_id=pk)


@artist_only
@require_http_methods(["GET", "POST"])
def workspace(request, pk):
    source = source_for(pk)
    if request.method == "GET":
        return render(request, "studio/collaborate.html", {"source": source, "roles": ROLES, "request_id": str(uuid.uuid4()), "drafts": VideoCollaboration.objects.filter(creator=request.user, source=source, status="ready").order_by("-created_at")[:5]})
    try:
        request_id = uuid.UUID(request.POST.get("request_id", ""))
        voice = validate_audio(request.FILES.get("audio"))
        role = request.POST.get("role", "Harmony")
        if role not in ROLES:
            raise ValidationError("Choose a vocal part.")
        original_gain = float(request.POST.get("original_gain", 1))
        vocal_gain = float(request.POST.get("vocal_gain", 1))
        shift_ms = float(request.POST.get("shift_ms", 0))
        parent = getattr(source, "video_collaboration", None)
        credits = list(parent.credits) if parent else [{"artist_id": source.artist_id, "username": source.artist.username, "role": "Original video"}]
        if len(credits) >= 32:
            raise ValidationError("This collaboration has reached its 32-part limit. Start a new song to continue.")
        credits.append({"artist_id": request.user.pk, "username": request.user.username, "role": role})
        with transaction.atomic():
            from django.utils import timezone
            from datetime import timedelta
            get_user_model().objects.select_for_update().get(pk=request.user.pk)
            if VideoCollaboration.objects.filter(creator=request.user, status="processing", created_at__gte=timezone.now()-timedelta(minutes=5)).exclude(pk=request_id).exists():
                return JsonResponse({"error": "Your previous video is still processing. Wait before creating another preview."}, status=409)
            item, created = VideoCollaboration.objects.get_or_create(pk=request_id, defaults={"creator": request.user, "source": source, "source_title": source.title, "credits": credits, "role": role})
            if not created:
                if item.creator_id != request.user.pk or item.source_id != source.pk:
                    raise Http404()
                if item.status in {"ready", "published"}:
                    return JsonResponse({"preview": reverse("studio:collaboration_play", args=[item.pk]), "publish": reverse("studio:collaboration_publish", args=[item.pk])})
                return JsonResponse({"error": "This take is processing or failed. Start a new preview to retry."}, status=409)
        try:
            with tempfile.TemporaryDirectory(prefix="ggenre-collab-") as directory:
                directory = Path(directory)
                video_path, voice_path, output = directory / "source.mp4", directory / "vocal.wav", directory / "collaboration.mp4"
                copy_source(source, video_path)
                with voice_path.open("wb") as target:
                    for chunk in voice.chunks():
                        target.write(chunk)
                render_video(video_path, voice_path, output, original_gain, vocal_gain, shift_ms)
                with output.open("rb") as stream:
                    item.video.save(f"{item.pk}.mp4", File(stream), save=False)
                item.status = "ready"
                item.save(update_fields=["video", "status"])
        except Exception:
            item.status = "failed"
            item.save(update_fields=["status"])
            raise
        return JsonResponse({"preview": reverse("studio:collaboration_play", args=[item.pk]), "publish": reverse("studio:collaboration_publish", args=[item.pk])})
    except (ValidationError, ValueError, TypeError) as exc:
        return JsonResponse({"error": exc.messages[0] if isinstance(exc, ValidationError) else "Check the recording and mix settings."}, status=400)


def video_response(request, field):
    """Private MP4 playback with a bounded single-range response for seeking."""
    size = field.size
    range_header = request.headers.get("Range", "")
    if range_header:
        import re
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
        try:
            if not match or not any(match.groups()):
                raise ValueError()
            first, last = match.groups()
            start = int(first) if first else max(0, size - int(last))
            end = min(size - 1, int(last) if first and last else size - 1)
            if not 0 <= start <= end < size:
                raise ValueError()
        except ValueError:
            response = JsonResponse({"error": "Invalid video range."}, status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        stream = field.open("rb")
        stream.seek(start)
        def chunks():
            remaining = end - start + 1
            try:
                while remaining:
                    chunk = stream.read(min(65536, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
            finally:
                stream.close()
        response = StreamingHttpResponse(chunks(), status=206, content_type="video/mp4")
        response._resource_closers.append(stream.close)
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = end - start + 1
    else:
        response = FileResponse(field.open("rb"), content_type="video/mp4")
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@artist_only
def source_video(request, pk):
    source = source_for(pk)
    field = source.video_collaboration.video if hasattr(source, "video_collaboration") else source.file
    return video_response(request, field)


@artist_only
def source_audio(request, pk):
    source = source_for(pk)
    try:
        stream = open_guide(source)
        response = FileResponse(stream, content_type="audio/wav")
        response["Cache-Control"] = "private, no-store"
        return response
    except ValidationError as exc:
        return JsonResponse({"error": exc.messages[0]}, status=400)


@login_required
def play(request, pk):
    item = get_object_or_404(VideoCollaboration.objects.select_related("content"), pk=pk, status__in=["ready", "published"])
    if item.content_id:
        if not can_view_content(request.user, item.content):
            raise Http404()
    elif item.creator_id != request.user.pk:
        raise Http404()
    return video_response(request, item.video)


@artist_only
@require_POST
def publish(request, pk):
    with transaction.atomic():
        item = get_object_or_404(VideoCollaboration.objects.select_for_update(), pk=pk, creator=request.user, status__in=["ready", "published"])
        if item.status == "published":
            if not item.content_id:
                raise Http404()
            return redirect("content_detail", content_id=item.content_id)
        source = source_for(item.source_id, lock=True)
        # Serialize publishing with other uploads from this artist, including the no-quota-row case.
        get_user_model().objects.select_for_update().get(pk=request.user.pk)
        quota = ArtistUploadLimit.objects.select_for_update().filter(artist=request.user).first()
        if quota and not quota.has_upload_quota():
            messages.error(request, "Your upload allowance is unavailable. Contact admin; your preview is retained.")
            return redirect("studio:collaborate", pk=source.pk)
        title = request.POST.get("title", "").strip()
        if not title or len(title) > 255:
            return JsonResponse({"error": "Enter a title up to 255 characters."}, status=400)
        content = Content.objects.create(artist=request.user, title=title, category="video", genre=source.genre, description=request.POST.get("description", "")[:2000], allow_collaboration=request.POST.get("allow_collaboration") == "on")
        item.content, item.status = content, "published"
        item.save(update_fields=["content", "status"])
        if quota:
            quota.uploads_used = F("uploads_used") + 1
            quota.save(update_fields=["uploads_used"])
    messages.success(request, "Collaboration submitted for review. Your vocal joins the original video; all contributors are credited.")
    return redirect("content_detail", content_id=content.pk)


@artist_only
def library(request):
    from django.core.paginator import Paginator
    items = VideoCollaboration.objects.filter(creator=request.user).select_related("source", "content").order_by("-created_at")
    return render(request, "studio/collaboration_library.html", {"page": Paginator(items, 12).get_page(request.GET.get("page"))})
