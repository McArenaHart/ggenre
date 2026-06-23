from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from users.models import Role

from .forms import LiveStreamAccessForm, LiveStreamForm
from .models import LiveStream, LiveStreamAccess


def stream_list(request):
    streams = LiveStream.objects.select_related("host").exclude(
        status=LiveStream.STATUS_ENDED
    )
    if not request.user.is_authenticated or not request.user.is_admin():
        streams = streams.filter(status=LiveStream.STATUS_LIVE)
    return render(request, "livestream/list.html", {"streams": streams})


@login_required
def create_stream(request):
    if not request.user.is_artist() and not request.user.is_admin():
        messages.error(request, "Only artists can start live streams.")
        return redirect("dashboard")

    if request.method == "POST":
        form = LiveStreamForm(request.POST)
        if form.is_valid():
            stream = form.save(commit=False)
            stream.host = request.user
            stream.save()
            messages.success(request, "Live stream created.")
            return redirect("livestream:room", stream_key=stream.stream_key)
    else:
        form = LiveStreamForm()

    return render(request, "livestream/form.html", {"form": form})


@login_required
def stream_room(request, stream_key):
    stream = get_object_or_404(
        LiveStream.objects.select_related("host"),
        stream_key=stream_key,
    )
    if not stream.can_join(request.user):
        messages.error(request, "You do not have access to this stream.")
        return redirect("livestream:index")

    return render(
        request,
        "livestream/room.html",
        {
            "stream": stream,
            "is_host": request.user == stream.host or request.user.is_admin(),
        },
    )


@login_required
@require_POST
def start_stream(request, stream_key):
    stream = get_object_or_404(LiveStream, stream_key=stream_key)
    if request.user != stream.host and not request.user.is_admin():
        return HttpResponseForbidden()
    stream.start()
    messages.success(request, "Stream is live.")
    return redirect("livestream:room", stream_key=stream.stream_key)


@login_required
@require_POST
def end_stream(request, stream_key):
    stream = get_object_or_404(LiveStream, stream_key=stream_key)
    if request.user != stream.host and not request.user.is_admin():
        return HttpResponseForbidden()
    stream.end()
    messages.success(request, "Stream ended.")
    return redirect("livestream:index")


@login_required
def manage_access(request, stream_key):
    stream = get_object_or_404(LiveStream, stream_key=stream_key)
    if request.user != stream.host and not request.user.is_admin():
        return HttpResponseForbidden()

    form = LiveStreamAccessForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.cleaned_data["user"]
        grant, _ = LiveStreamAccess.objects.get_or_create(
            stream=stream,
            user=user,
            defaults={"granted_by": request.user},
        )
        if not grant.is_active:
            grant.is_active = True
            grant.granted_by = request.user
            grant.save(update_fields=["is_active", "granted_by"])
        messages.success(request, f"Access granted to {user.username}.")
        return redirect("livestream:manage_access", stream_key=stream.stream_key)

    grants = stream.access_grants.select_related("user", "granted_by")
    return render(
        request,
        "livestream/manage_access.html",
        {"stream": stream, "form": form, "grants": grants},
    )


@login_required
@require_POST
def revoke_access(request, stream_key, grant_id):
    stream = get_object_or_404(LiveStream, stream_key=stream_key)
    if request.user != stream.host and not request.user.is_admin():
        return HttpResponseForbidden()

    grant = get_object_or_404(LiveStreamAccess, id=grant_id, stream=stream)
    grant.is_active = False
    grant.save(update_fields=["is_active"])
    messages.success(request, f"Access revoked for {grant.user.username}.")
    return redirect("livestream:manage_access", stream_key=stream.stream_key)
