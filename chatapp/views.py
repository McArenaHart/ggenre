from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db.models import Sum
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect, render

from users.models import CustomUser, OTP, Role, VotingTokenPolicy

from .models import AdminChatThread, MatchRating, PeerChatThread
from .services import record_match_rating, users_can_peer_chat


@login_required
def chat_index(request):
    if request.user.is_admin():
        return redirect("chatapp:admin_inbox")

    threads = (
        PeerChatThread.objects.filter(
            Q(user_one=request.user) | Q(user_two=request.user)
        )
        .select_related("user_one", "user_two")
        .order_by("-last_contact_at")
    )
    thread_rows = []
    thread_user_ids = set()
    total_unread = 0
    for thread in threads:
        other_user = thread.other_user(request.user)
        if other_user.is_admin() or other_user.is_suspended_by_admin or not other_user.is_active:
            continue
        if not users_can_peer_chat(request.user, other_user):
            continue
        unread_count = thread.unread_count_for(request.user)
        thread_user_ids.add(other_user.id)
        total_unread += unread_count
        thread_rows.append(
            {
                "thread": thread,
                "user": other_user,
                "unread_count": unread_count,
            }
        )

    incoming_ratings = {
        rating.rater_id: rating
        for rating in MatchRating.objects.filter(
            rater_id__in=thread_user_ids,
            rated=request.user,
        ).select_related("source_content")
    }
    for row in thread_rows:
        row["incoming_rating"] = incoming_ratings.get(row["user"].id)

    return render(
        request,
        "chatapp/list.html",
        {
            "thread_rows": thread_rows,
            "thread_count": len(thread_rows),
            "total_unread": total_unread,
        },
    )


@login_required
def direct_chat(request, user_id):
    other_user = get_object_or_404(
        CustomUser.objects.exclude(id=request.user.id)
        .exclude(is_suspended_by_admin=True)
        .filter(is_active=True),
        id=user_id,
    )

    is_user_contacting_admin = other_user.is_admin() and not request.user.is_admin()
    is_admin_replying_to_user = request.user.is_admin() and not other_user.is_admin()
    is_peer_chat = (
        not request.user.is_admin()
        and not other_user.is_admin()
        and users_can_peer_chat(request.user, other_user)
    )
    if not (is_user_contacting_admin or is_admin_replying_to_user or is_peer_chat):
        return HttpResponseForbidden()

    incoming_rating = None
    if is_peer_chat:
        incoming_rating = (
            MatchRating.objects.filter(rater=other_user, rated=request.user)
            .select_related("source_content")
            .first()
        )

    if request.user.is_admin():
        AdminChatThread.objects.filter(admin=request.user, user=other_user).update(
            unread_count=0
        )
    elif is_user_contacting_admin:
        AdminChatThread.objects.filter(admin=other_user, user=request.user).update(
            user_unread_count=0
        )
    elif is_peer_chat:
        user_one, user_two = PeerChatThread.ordered_users(request.user, other_user)
        thread = PeerChatThread.objects.filter(user_one=user_one, user_two=user_two)
        if request.user.id == user_one.id:
            thread.update(unread_count_user_one=0)
        else:
            thread.update(unread_count_user_two=0)
    return render(
        request,
        "chatapp/direct.html",
        {
            "other_user": other_user,
            "chat_channel": "peer" if is_peer_chat else "admin",
            "incoming_rating": incoming_rating,
            "message_retention_ms": VotingTokenPolicy.message_retention_ms(),
        },
    )


@login_required
@require_POST
def rate_user(request, user_id):
    rated_user = get_object_or_404(
        CustomUser.objects.exclude(id=request.user.id)
        .exclude(role=Role.ADMIN)
        .exclude(is_suspended_by_admin=True)
        .filter(is_active=True),
        id=user_id,
    )
    if request.user.is_admin():
        return HttpResponseForbidden()

    try:
        result = record_match_rating(
            rater=request.user,
            rated=rated_user,
            score=request.POST.get("score"),
        )
    except (TypeError, ValueError):
        messages.error(request, "Choose a rating from 1 to 10.")
        return redirect("user_profile", user_id=rated_user.id)

    if result["matched"]:
        messages.success(
            request,
            (
                f"Rating saved. Private chat with {rated_user.username} "
                "has been unlocked."
            ),
        )
    else:
        messages.info(request, "Rating saved.")
    return redirect("user_profile", user_id=rated_user.id)


@login_required
def admin_inbox(request):
    if not request.user.is_admin():
        return HttpResponseForbidden()

    threads = AdminChatThread.objects.filter(admin=request.user).select_related("user")
    total_unread = threads.aggregate(total=Sum("unread_count"))["total"] or 0
    return render(
        request,
        "chatapp/admin_inbox.html",
        {
            "threads": threads,
            "thread_count": threads.count(),
            "total_unread": total_unread,
        },
    )


@login_required
def admin_unread_count(request):
    if not request.user.is_admin():
        return JsonResponse({"unread_count": 0})

    unread_count = (
        AdminChatThread.objects.filter(admin=request.user).aggregate(
            total=Sum("unread_count")
        )["total"]
        or 0
    )
    return JsonResponse({"unread_count": unread_count})


@login_required
def admin_contact_unread_count(request):
    if request.user.is_admin():
        return JsonResponse({"unread_count": 0, "otp": None})

    admin = (
        CustomUser.objects.filter(role=Role.ADMIN, is_active=True)
        .exclude(is_suspended_by_admin=True)
        .order_by("-is_superuser", "-is_staff", "username")
        .first()
    )
    if not admin:
        return JsonResponse({"unread_count": 0, "otp": None})

    thread = AdminChatThread.objects.filter(admin=admin, user=request.user).first()
    otp = OTP.objects.filter(user=request.user, is_active=True, remaining_votes__gt=0).first()
    return JsonResponse(
        {
            "unread_count": thread.user_unread_count if thread else 0,
            "otp": (
                {
                    "code": otp.otp_code,
                    "remaining_votes": otp.remaining_votes,
                    "updated_at": otp.updated_at.isoformat(),
                }
                if otp
                else None
            ),
        }
    )


@login_required
@require_POST
def mark_admin_contact_read(request):
    if request.user.is_admin():
        return JsonResponse({"status": "ok", "unread_count": 0})

    admin = (
        CustomUser.objects.filter(role=Role.ADMIN, is_active=True)
        .exclude(is_suspended_by_admin=True)
        .order_by("-is_superuser", "-is_staff", "username")
        .first()
    )
    if admin:
        AdminChatThread.objects.filter(admin=admin, user=request.user).update(
            user_unread_count=0
        )
    return JsonResponse({"status": "ok", "unread_count": 0})
