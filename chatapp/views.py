import json

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Q
from django.db.models import Sum
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect, render

from users.models import CustomUser, OTP, Role, VotingTokenPolicy

from .models import (
    AdminChatThread,
    AdminDecisionLog,
    DirectChatMessage,
    MatchRating,
    MissionEvidence,
    MissionQueueEntry,
    MissionSession,
    MissionTemplate,
    MissionWinFeed,
    PeerChatThread,
    TokenPurchaseRequest,
)
from .realtime import broadcast_admin_counts, broadcast_mission_update
from .services import (
    accept_mission,
    accept_opponent,
    assign_mission_opponent_by_admin,
    create_token_purchase_request,
    get_admin_contact_user,
    get_mission_policy_settings,
    record_match_rating,
    route_and_start_mission_review,
    set_mission_review_route_mode,
    request_another_mission,
    request_another_opponent,
    request_mission_for_user,
    review_mission_evidence,
    review_token_purchase_request,
    submit_mission_proof,
    users_can_peer_chat,
)


def _presence_snapshot(user_id):
    online_value = cache.get(f"direct_chat_presence:online:{user_id}")
    return {
        "is_online": bool(online_value),
        "last_seen_at": cache.get(f"direct_chat_presence:last_seen:{user_id}"),
    }


def _attach_route_logs(pending_mission_evidence, pending_token_requests):
    mission_ids = [evidence.mission_session_id for evidence in pending_mission_evidence]
    token_request_ids = [token_request.id for token_request in pending_token_requests]

    mission_route_logs = {}
    for route_log in AdminDecisionLog.objects.filter(
        mission_session_id__in=mission_ids,
        action="mission_review_route",
    ).order_by("mission_session_id", "-created_at"):
        mission_route_logs.setdefault(route_log.mission_session_id, route_log)

    token_route_logs = {}
    for route_log in AdminDecisionLog.objects.filter(
        token_purchase_request_id__in=token_request_ids,
        action="token_review_route",
    ).order_by("token_purchase_request_id", "-created_at"):
        token_route_logs.setdefault(route_log.token_purchase_request_id, route_log)

    for evidence in pending_mission_evidence:
        evidence.route_log = mission_route_logs.get(evidence.mission_session_id)
    for token_request in pending_token_requests:
        token_request.route_log = token_route_logs.get(token_request.id)


def _route_matches(route_log, route_filter):
    if route_filter == "all":
        return True
    if route_filter == "unrouted":
        return route_log is None
    if not route_log:
        return False
    return route_log.actor_type == route_filter


def _risk_sort_key(route_log, threshold):
    if not route_log:
        return (0, 0)
    confidence = float(route_log.confidence) if route_log.confidence is not None else 0.0
    if route_log.actor_type == AdminDecisionLog.ActorType.MANUAL:
        return (1, confidence)
    if confidence < threshold:
        return (2, confidence)
    return (3, confidence)


def _admin_mission_return(request):
    next_url = (request.POST.get("next") or "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "chatapp:admin_inbox"


MISSION_MONITOR_STATUSES = [
    MissionSession.Status.REQUESTED,
    MissionSession.Status.MATCHING,
    MissionSession.Status.OPPONENT_PROPOSED,
    MissionSession.Status.MISSION_PROPOSED,
    MissionSession.Status.MISSION_ACTIVE,
    MissionSession.Status.PROOF_SUBMITTED,
    MissionSession.Status.UNDER_REVIEW,
    MissionSession.Status.COOLDOWN_VOTE_REQUIRED,
]

PLAYER_ONGOING_MISSION_STATUSES = [
    MissionSession.Status.REQUESTED,
    MissionSession.Status.MATCHING,
    MissionSession.Status.OPPONENT_PROPOSED,
    MissionSession.Status.MISSION_PROPOSED,
    MissionSession.Status.MISSION_ACTIVE,
    MissionSession.Status.PROOF_SUBMITTED,
    MissionSession.Status.UNDER_REVIEW,
]

MISSION_REQUEST_QUEUE_STATUSES = [
    MissionSession.Status.REQUESTED,
    MissionSession.Status.MATCHING,
    MissionSession.Status.OPPONENT_PROPOSED,
]


def _pending_mission_request_count():
    return MissionSession.objects.filter(status__in=MISSION_REQUEST_QUEUE_STATUSES).count()


def _mission_can_be_removed(mission):
    if mission.status in {
        MissionSession.Status.MISSION_PROPOSED,
        MissionSession.Status.MISSION_ACTIVE,
        MissionSession.Status.PROOF_SUBMITTED,
        MissionSession.Status.UNDER_REVIEW,
        MissionSession.Status.APPROVED,
        MissionSession.Status.COOLDOWN_VOTE_REQUIRED,
    }:
        return False
    approved_evidence_exists = MissionEvidence.objects.filter(
        mission_session=mission,
        review_status=MissionEvidence.ReviewStatus.APPROVED,
    ).exists()
    return not approved_evidence_exists and not hasattr(mission, "win_feed_entry")


def _mission_busy_player_ids():
    busy_statuses = [
        MissionSession.Status.REQUESTED,
        MissionSession.Status.MATCHING,
        MissionSession.Status.OPPONENT_PROPOSED,
        MissionSession.Status.MISSION_PROPOSED,
        MissionSession.Status.MISSION_ACTIVE,
        MissionSession.Status.PROOF_SUBMITTED,
        MissionSession.Status.UNDER_REVIEW,
        MissionSession.Status.COOLDOWN_VOTE_REQUIRED,
    ]
    busy_player_ids = set()
    busy_sessions = MissionSession.objects.filter(status__in=busy_statuses).values_list("requester_id", "opponent_id")
    for requester_id, opponent_id in busy_sessions:
        busy_player_ids.add(requester_id)
        if opponent_id:
            busy_player_ids.add(opponent_id)
    return busy_player_ids


def _online_mission_player_rows(busy_player_ids):
    online_players = []
    candidate_players = CustomUser.objects.exclude(role=Role.ADMIN).exclude(is_suspended_by_admin=True).filter(is_active=True)
    for player in candidate_players:
        if not cache.get(f"direct_chat_presence:online:{player.id}"):
            continue
        online_players.append(
            {
                "user": player,
                "is_busy": player.id in busy_player_ids,
            }
        )
    return online_players


def _build_mission_request_row(mission, current_admin, online_players):
    mission.can_admin_remove = _mission_can_be_removed(mission)
    claimed_by_other = bool(
        mission.assigned_admin_id and mission.assigned_admin_id != current_admin.id
    )
    available_players = []
    unavailable_count = 0
    for player_row in online_players:
        player = player_row["user"]
        is_unavailable = (
            claimed_by_other
            or player_row["is_busy"]
            or player.id == mission.requester_id
        )
        if is_unavailable:
            unavailable_count += 1
            continue
        homepage_wins = MissionWinFeed.objects.filter(
            winner=player,
            homepage_visible=True,
        ).count()
        otp = OTP.objects.filter(user=player).only("remaining_votes").first()
        available_players.append(
            {
                "user": player,
                "badge_level": 1 + (homepage_wins // 3),
                "current_points": otp.remaining_votes if otp else 0,
                "homepage_wins": homepage_wins,
            }
        )
    return {
        "mission": mission,
        "available_players": available_players,
        "available_count": len(available_players),
        "unavailable_count": unavailable_count,
        "claimed_by_other": claimed_by_other,
        "is_claimed": bool(mission.assigned_admin_id),
        "is_claimed_by_current_admin": mission.assigned_admin_id == current_admin.id,
        "match_disabled": claimed_by_other or not available_players,
    }


def _build_pending_mission_rows(current_admin):
    pending_mission_requests = list(
        MissionSession.objects.filter(status__in=MISSION_REQUEST_QUEUE_STATUSES)
        .select_related("requester", "opponent", "mission_template", "assigned_admin")
        .order_by("created_at")[:20]
    )

    online_players = _online_mission_player_rows(_mission_busy_player_ids())
    pending_mission_rows = [
        _build_mission_request_row(mission, current_admin, online_players)
        for mission in pending_mission_requests
    ]
    return pending_mission_requests, pending_mission_rows, online_players


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

    mission_context = None
    token_request_context = None
    if is_user_contacting_admin:
        latest_mission = (
            MissionSession.objects.filter(
                Q(requester=request.user) | Q(opponent=request.user),
                status__in=PLAYER_ONGOING_MISSION_STATUSES,
            )
            .select_related("mission_template", "requester", "opponent")
            .order_by("-created_at")
            .first()
        )
        latest_token_request = (
            TokenPurchaseRequest.objects.filter(requester=request.user)
            .order_by("-created_at")
            .first()
        )
        mission_context = {
            "latest": latest_mission,
        }
        token_request_context = {
            "latest": latest_token_request,
        }

    if is_peer_chat:
        latest_peer_mission = (
            MissionSession.objects.filter(
                Q(requester=request.user, opponent=other_user)
                | Q(requester=other_user, opponent=request.user),
                status__in=PLAYER_ONGOING_MISSION_STATUSES,
            )
            .select_related("mission_template", "requester", "opponent")
            .order_by("-created_at")
            .first()
        )
        mission_context = {
            "latest": latest_peer_mission,
        }

    if is_admin_replying_to_user:
        latest_user_mission = (
            MissionSession.objects.filter(Q(requester=other_user) | Q(opponent=other_user))
            .select_related("mission_template", "opponent", "requester")
            .order_by("-created_at")
            .first()
        )
        mission_request_row = None
        if latest_user_mission and latest_user_mission.status in MISSION_REQUEST_QUEUE_STATUSES:
            mission_request_row = _build_mission_request_row(
                latest_user_mission,
                request.user,
                _online_mission_player_rows(_mission_busy_player_ids()),
            )
        mission_context = {
            "latest_for_user": latest_user_mission,
            "request_row": mission_request_row,
            "pending_evidence_for_user": (
                MissionEvidence.objects.filter(
                    mission_session=latest_user_mission,
                    review_status__in=[
                        MissionEvidence.ReviewStatus.SUBMITTED,
                        MissionEvidence.ReviewStatus.UNDER_REVIEW,
                    ],
                )
                .select_related("submitted_by")
                .order_by("-created_at")
                .first()
                if latest_user_mission
                else None
            ),
        }
        token_request_context = {
            "latest_for_user": (
                TokenPurchaseRequest.objects.filter(requester=other_user)
                .order_by("-created_at")
                .first()
            )
        }

    return render(
        request,
        "chatapp/direct.html",
        {
            "other_user": other_user,
            "chat_channel": "peer" if is_peer_chat else "admin",
            "incoming_rating": incoming_rating,
            "message_retention_ms": VotingTokenPolicy.message_retention_ms(),
            "mission_context": mission_context,
            "token_request_context": token_request_context,
        },
    )


@login_required
def direct_chat_history(request, user_id):
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

    history_items = list(
        DirectChatMessage.objects.filter(
            Q(sender=request.user, recipient=other_user)
            | Q(sender=other_user, recipient=request.user)
        )
        .select_related("sender")
        .order_by("-created_at")[:200]
    )
    history_items.reverse()

    return JsonResponse(
        {
            "presence": _presence_snapshot(other_user.id),
            "messages": [
                {
                    "type": "message",
                    "message_id": item.id,
                    "client_id": item.client_id,
                    "body": item.body,
                    "sender": item.sender.username,
                    "sender_id": item.sender_id,
                    "recipient_id": item.recipient_id,
                    "created_at": item.created_at.isoformat(),
                    "delivery_status": 2
                    if item.read_at
                    else (1 if item.sender_id == request.user.id else 0),
                }
                for item in history_items
            ]
        }
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

    pending_mission_requests, pending_mission_rows, online_players = _build_pending_mission_rows(request.user)
    mission_counts_by_requester = {}
    latest_mission_by_requester = {}
    for mission in pending_mission_requests:
        mission_counts_by_requester[mission.requester_id] = mission_counts_by_requester.get(mission.requester_id, 0) + 1
        latest_mission_by_requester.setdefault(mission.requester_id, mission)

    threads = AdminChatThread.objects.filter(admin=request.user).select_related("user")
    thread_rows = []
    thread_user_ids = set()
    for thread in threads:
        mission_request_count = mission_counts_by_requester.get(thread.user_id, 0)
        thread_user_ids.add(thread.user_id)
        thread_rows.append(
            {
                "user": thread.user,
                "unread_count": thread.unread_count,
                "mission_request_count": mission_request_count,
                "action_count": thread.unread_count + mission_request_count,
                "last_contact_at": thread.last_contact_at,
                "is_mission_only": False,
            }
        )
    for requester_id, mission_request_count in mission_counts_by_requester.items():
        if requester_id in thread_user_ids:
            continue
        mission = latest_mission_by_requester[requester_id]
        thread_rows.append(
            {
                "user": mission.requester,
                "unread_count": 0,
                "mission_request_count": mission_request_count,
                "action_count": mission_request_count,
                "last_contact_at": mission.created_at,
                "is_mission_only": True,
            }
        )
    thread_rows.sort(key=lambda row: row["last_contact_at"], reverse=True)
    total_unread = sum(row["action_count"] for row in thread_rows)
    pending_token_requests = list(TokenPurchaseRequest.objects.filter(
        status__in=[
            TokenPurchaseRequest.Status.SUBMITTED,
            TokenPurchaseRequest.Status.UNDER_REVIEW,
        ]
    ).select_related("requester", "assigned_admin")[:20])
    pending_mission_evidence = list(MissionEvidence.objects.filter(
        review_status__in=[
            MissionEvidence.ReviewStatus.SUBMITTED,
            MissionEvidence.ReviewStatus.UNDER_REVIEW,
        ]
    ).select_related("submitted_by", "mission_session")[:20])
    _attach_route_logs(pending_mission_evidence, pending_token_requests)
    policy = get_mission_policy_settings()
    mode = policy.get("review_route_mode", "manual_only")
    mode_label_map = {
        "alternate": "Alternate",
        "manual_only": "Manual Only",
        "ai_preferred": "AI Preferred",
    }
    active_mission_templates = list(
        MissionTemplate.objects.filter(is_active=True).order_by("title")
    )

    return render(
        request,
        "chatapp/admin_inbox.html",
        {
            "thread_rows": thread_rows,
            "thread_count": len(thread_rows),
            "total_unread": total_unread,
            "pending_token_requests": pending_token_requests,
            "pending_mission_evidence": pending_mission_evidence,
            "pending_mission_requests": pending_mission_requests,
            "pending_mission_rows": pending_mission_rows,
            "online_players": online_players,
            "active_mission_templates": active_mission_templates,
            "policy_review_route_mode": mode,
            "policy_review_route_mode_label": mode_label_map.get(mode, "Alternate"),
        },
    )


@login_required
@require_POST
def admin_assign_mission_opponent(request, mission_id):
    if not request.user.is_admin():
        return HttpResponseForbidden()

    mission = get_object_or_404(
        MissionSession.objects.select_related("requester", "opponent", "mission_template"),
        pk=mission_id,
    )
    if mission.assigned_admin_id and mission.assigned_admin_id != request.user.id:
        messages.error(request, "This mission request is currently claimed by another admin.")
        return redirect(_admin_mission_return(request))

    try:
        opponent_id = int(request.POST.get("opponent_id"))
    except (TypeError, ValueError):
        messages.error(request, "Choose a valid online player.")
        return redirect(_admin_mission_return(request))

    opponent = get_object_or_404(
        CustomUser.objects.exclude(role=Role.ADMIN)
        .exclude(is_suspended_by_admin=True)
        .filter(is_active=True),
        pk=opponent_id,
    )

    selected_template = None
    mission_template_raw = request.POST.get("mission_template_id")
    if mission_template_raw:
        try:
            mission_template_id = int(mission_template_raw)
        except (TypeError, ValueError):
            messages.error(request, "Choose a valid mission template.")
            return redirect(_admin_mission_return(request))
        selected_template = get_object_or_404(
            MissionTemplate.objects.filter(is_active=True),
            pk=mission_template_id,
        )

    if not cache.get(f"direct_chat_presence:online:{opponent.id}"):
        messages.error(request, "Selected player is no longer online.")
        return redirect(_admin_mission_return(request))

    try:
        mission = assign_mission_opponent_by_admin(
            mission=mission,
            admin_user=request.user,
            opponent_user=opponent,
            mission_template=selected_template,
        )
    except (ValueError, PermissionError) as exc:
        messages.error(request, str(exc))
        return redirect(_admin_mission_return(request))

    messages.success(
        request,
        (
            f"Mission #{mission.id} matched: {mission.requester.username} "
            f"vs {opponent.username}."
        ),
    )
    broadcast_mission_update(mission)
    broadcast_admin_counts()
    return redirect(_admin_mission_return(request))


@login_required
@require_POST
def admin_claim_mission_request(request, mission_id):
    if not request.user.is_admin():
        return HttpResponseForbidden()

    mission = get_object_or_404(
        MissionSession.objects.select_related("requester", "assigned_admin"),
        pk=mission_id,
    )
    if mission.status not in {
        MissionSession.Status.REQUESTED,
        MissionSession.Status.MATCHING,
        MissionSession.Status.OPPONENT_PROPOSED,
    }:
        messages.error(request, "Mission request is no longer available for claim.")
        return redirect("chatapp:admin_inbox")

    action = (request.POST.get("action") or "claim").strip().lower()
    if action == "release":
        if mission.assigned_admin_id != request.user.id:
            messages.error(request, "Only the claiming admin can release this mission request.")
            return redirect("chatapp:admin_inbox")
        mission.assigned_admin = None
        mission.assigned_at = None
        mission.save(update_fields=["assigned_admin", "assigned_at", "updated_at"])
        messages.success(request, f"Mission #{mission.id} was released.")
        return redirect("chatapp:admin_inbox")

    if mission.assigned_admin_id and mission.assigned_admin_id != request.user.id:
        messages.error(request, "This mission request is currently claimed by another admin.")
        return redirect("chatapp:admin_inbox")

    mission.assigned_admin = request.user
    mission.assigned_at = timezone.now()
    mission.save(update_fields=["assigned_admin", "assigned_at", "updated_at"])
    messages.success(request, f"Mission #{mission.id} is now assigned to you.")
    return redirect("chatapp:admin_inbox")


@login_required
@require_POST
def admin_mission_control_action(request, mission_id):
    if not request.user.is_admin():
        return HttpResponseForbidden()

    mission = get_object_or_404(
        MissionSession.objects.select_related("requester", "opponent", "winner"),
        pk=mission_id,
    )
    action = (request.POST.get("action") or "").strip().lower()
    note = (request.POST.get("note") or "").strip()

    if action == "cancel":
        if mission.status in {
            MissionSession.Status.APPROVED,
            MissionSession.Status.COOLDOWN_VOTE_REQUIRED,
            MissionSession.Status.CLOSED,
        }:
            messages.error(request, "This mission is already complete and cannot be cancelled.")
            return redirect(_admin_mission_return(request))

        mission.status = MissionSession.Status.CLOSED
        mission.assigned_admin = None
        mission.assigned_at = None
        if not mission.ended_at:
            mission.ended_at = timezone.now()
        mission.save(update_fields=["status", "assigned_admin", "assigned_at", "ended_at", "updated_at"])
        MissionQueueEntry.objects.filter(mission_session=mission).update(
            status=MissionQueueEntry.QueueStatus.CLOSED,
            reason="Cancelled by admin",
            updated_at=timezone.now(),
        )
        MissionEvidence.objects.filter(
            mission_session=mission,
            review_status__in=[
                MissionEvidence.ReviewStatus.SUBMITTED,
                MissionEvidence.ReviewStatus.UNDER_REVIEW,
            ],
        ).update(
            review_status=MissionEvidence.ReviewStatus.REJECTED,
            review_notes=note or "Mission cancelled by admin.",
            reviewed_by=request.user,
            updated_at=timezone.now(),
        )
        AdminDecisionLog.objects.create(
            actor_type=AdminDecisionLog.ActorType.MANUAL,
            actor_user=request.user,
            mission_session=mission,
            action="cancel_mission",
            rationale=note or "Mission cancelled by admin.",
        )
        messages.success(request, f"Mission #{mission.id} was cancelled.")
        return redirect(_admin_mission_return(request))

    if action == "delete":
        if not _mission_can_be_removed(mission):
            messages.error(request, "Only cancelled, rejected, or unused mission records can be removed.")
            return redirect(_admin_mission_return(request))

        mission_id_label = mission.id
        MissionQueueEntry.objects.filter(mission_session=mission).update(
            status=MissionQueueEntry.QueueStatus.CLOSED,
            reason="Mission record removed by admin",
            updated_at=timezone.now(),
        )
        mission.delete()
        AdminDecisionLog.objects.create(
            actor_type=AdminDecisionLog.ActorType.MANUAL,
            actor_user=request.user,
            action="delete_mission",
            rationale=note or f"Mission #{mission_id_label} record removed by admin.",
        )
        messages.success(request, f"Mission #{mission_id_label} was removed.")
        return redirect(_admin_mission_return(request))

    messages.error(request, "Unsupported mission control action.")
    return redirect(_admin_mission_return(request))


@login_required
def admin_review_center(request):
    if not request.user.is_admin():
        return HttpResponseForbidden()

    route_filter = "all"
    sort_mode = (request.GET.get("sort") or "oldest").strip().lower()
    if sort_mode not in {"oldest", "newest", "risk"}:
        sort_mode = "oldest"

    pending_token_requests = list(TokenPurchaseRequest.objects.filter(
        status__in=[
            TokenPurchaseRequest.Status.SUBMITTED,
            TokenPurchaseRequest.Status.UNDER_REVIEW,
        ]
    ).select_related("requester", "assigned_admin").order_by("created_at"))
    pending_mission_evidence = list(MissionEvidence.objects.filter(
        review_status__in=[
            MissionEvidence.ReviewStatus.SUBMITTED,
            MissionEvidence.ReviewStatus.UNDER_REVIEW,
        ]
    ).select_related(
        "submitted_by",
        "mission_session",
        "mission_session__requester",
        "mission_session__opponent",
        "mission_session__mission_template",
    ).order_by("created_at"))
    pending_mission_requests, pending_mission_rows, online_players = _build_pending_mission_rows(request.user)
    monitored_missions = list(
        MissionSession.objects.filter(status__in=MISSION_MONITOR_STATUSES)
        .select_related("requester", "opponent", "winner", "loser", "mission_template", "assigned_admin")
        .order_by("-updated_at")[:50]
    )
    for mission in monitored_missions:
        mission.can_admin_remove = _mission_can_be_removed(mission)

    _attach_route_logs(pending_mission_evidence, pending_token_requests)

    pending_mission_evidence = [
        evidence
        for evidence in pending_mission_evidence
        if _route_matches(evidence.route_log, route_filter)
    ]
    pending_token_requests = [
        token_request
        for token_request in pending_token_requests
        if _route_matches(token_request.route_log, route_filter)
    ]

    policy = get_mission_policy_settings()
    threshold = float(policy.get("ai_confidence_threshold", 0.75))
    if sort_mode == "newest":
        pending_mission_evidence.sort(key=lambda row: row.created_at, reverse=True)
        pending_token_requests.sort(key=lambda row: row.created_at, reverse=True)
    elif sort_mode == "risk":
        pending_mission_evidence.sort(
            key=lambda row: (
                _risk_sort_key(getattr(row, "route_log", None), threshold),
                row.created_at,
            )
        )
        pending_token_requests.sort(
            key=lambda row: (
                _risk_sort_key(getattr(row, "route_log", None), threshold),
                row.created_at,
            )
        )

    return render(
        request,
        "chatapp/admin_review_center.html",
        {
            "pending_token_requests": pending_token_requests,
            "pending_mission_evidence": pending_mission_evidence,
            "pending_mission_requests": pending_mission_requests,
            "pending_mission_rows": pending_mission_rows,
            "monitored_missions": monitored_missions,
            "online_players": online_players,
            "review_route_filter": route_filter,
            "review_sort_mode": sort_mode,
            "policy_review_route_mode": policy.get("review_route_mode", "alternate"),
            "route_mode_is_alternate": policy.get("review_route_mode", "alternate") == "alternate",
            "route_mode_is_manual_only": policy.get("review_route_mode", "alternate") == "manual_only",
            "route_mode_is_ai_preferred": policy.get("review_route_mode", "alternate") == "ai_preferred",
            "filter_route_all": route_filter == "all",
            "filter_route_ai": route_filter == "ai",
            "filter_route_manual": route_filter == "manual",
            "filter_route_unrouted": route_filter == "unrouted",
            "sort_oldest": sort_mode == "oldest",
            "sort_newest": sort_mode == "newest",
            "sort_risk": sort_mode == "risk",
        },
    )


@login_required
@require_POST
def admin_review_route_mode_update(request):
    if not request.user.is_admin():
        return HttpResponseForbidden()

    route_mode = (request.POST.get("route_mode") or "").strip().lower()
    reason = (request.POST.get("reason") or "").strip()
    try:
        set_mission_review_route_mode(route_mode=route_mode, reason=reason)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("chatapp:admin_review_center")

    messages.success(request, f"Mission review route mode updated to {route_mode}.")
    return redirect("chatapp:admin_review_center")


@login_required
@require_POST
def admin_review_bulk_token_action(request):
    if not request.user.is_admin():
        return HttpResponseForbidden()

    action = (request.POST.get("bulk_action") or "").strip().lower()
    if action not in {"approve", "reject"}:
        messages.error(request, "Unsupported bulk action.")
        return redirect("chatapp:admin_review_center")

    request_ids = []
    for raw_id in request.POST.getlist("request_ids"):
        try:
            request_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    request_ids = sorted(set(request_ids))
    if not request_ids:
        messages.error(request, "Select at least one token request for bulk review.")
        return redirect("chatapp:admin_review_center")

    policy = get_mission_policy_settings()
    bulk_limit = int(policy.get("bulk_review_max_items", 10))
    if len(request_ids) > bulk_limit:
        messages.error(request, f"Bulk action limit is {bulk_limit} requests at a time.")
        return redirect("chatapp:admin_review_center")

    expected_confirmation = "BULK_APPROVE" if action == "approve" else "BULK_REJECT"
    confirm_text = (request.POST.get("confirm_text") or "").strip().upper()
    if confirm_text != expected_confirmation:
        messages.error(request, f"Type {expected_confirmation} to confirm bulk {action}.")
        return redirect("chatapp:admin_review_center")

    review_notes = (request.POST.get("review_notes") or "").strip()
    if len(review_notes) < 5:
        messages.error(request, "Bulk review notes must be at least 5 characters.")
        return redirect("chatapp:admin_review_center")

    approved_tokens = request.POST.get("approved_tokens") if action == "approve" else None

    reviewed = 0
    skipped = 0
    pending_requests = TokenPurchaseRequest.objects.filter(
        id__in=request_ids,
        status__in=[
            TokenPurchaseRequest.Status.SUBMITTED,
            TokenPurchaseRequest.Status.UNDER_REVIEW,
        ],
    ).order_by("id")
    for token_request in pending_requests:
        try:
            review_token_purchase_request(
                token_request=token_request,
                admin_user=request.user,
                approved=(action == "approve"),
                approved_tokens=approved_tokens,
                review_notes=review_notes,
            )
            reviewed += 1
        except ValueError:
            skipped += 1

    messages.success(
        request,
        f"Bulk {action} complete. Reviewed {reviewed} request(s); skipped {skipped} request(s).",
    )
    return redirect("chatapp:admin_review_center")


@login_required
@require_POST
def admin_review_mission_action(request, evidence_id):
    if not request.user.is_admin():
        return HttpResponseForbidden()

    evidence = get_object_or_404(
        MissionEvidence.objects.select_related("mission_session", "submitted_by"),
        pk=evidence_id,
    )
    mission = evidence.mission_session
    action = (request.POST.get("action") or "").strip().lower()
    approved = action == "approve"

    if action not in {"approve", "reject"}:
        messages.error(request, "Unsupported mission review action.")
        return redirect("chatapp:admin_review_center")

    try:
        review_mission_evidence(
            mission=mission,
            evidence=evidence,
            admin_user=request.user,
            approved=approved,
            review_notes=request.POST.get("review_notes") or "",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("chatapp:admin_review_center")

    mission.refresh_from_db()
    broadcast_mission_update(mission)
    broadcast_admin_counts()
    messages.success(
        request,
        f"Mission proof #{evidence.id} {'approved' if approved else 'rejected'}.",
    )
    return redirect("chatapp:admin_review_center")


@login_required
@require_POST
def admin_review_token_action(request, request_id):
    if not request.user.is_admin():
        return HttpResponseForbidden()

    token_request = get_object_or_404(TokenPurchaseRequest, pk=request_id)
    action = (request.POST.get("action") or "").strip().lower()
    approved = action == "approve"

    if action not in {"approve", "reject"}:
        messages.error(request, "Unsupported token review action.")
        return redirect("chatapp:admin_review_center")

    try:
        review_token_purchase_request(
            token_request=token_request,
            admin_user=request.user,
            approved=approved,
            approved_tokens=request.POST.get("approved_tokens"),
            review_notes=request.POST.get("review_notes") or "",
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("chatapp:admin_review_center")

    messages.success(
        request,
        f"Token request #{token_request.id} {'approved' if approved else 'rejected'}.",
    )
    return redirect("chatapp:admin_review_center")


@login_required
def mission_center(request):
    if request.user.is_admin():
        mission_filter = Q()
        token_filter = Q()
    else:
        mission_filter = Q(requester=request.user) | Q(opponent=request.user)
        token_filter = Q(requester=request.user)

    mission_sessions = list(
        MissionSession.objects.filter(mission_filter)
        .select_related("requester", "opponent", "winner", "loser", "mission_template")
        .order_by("-created_at")[:80]
    )
    active_mission = None
    if not request.user.is_admin():
        active_mission = next(
            (mission for mission in mission_sessions if mission.status in PLAYER_ONGOING_MISSION_STATUSES),
            None,
        )
    mission_evidence = (
        MissionEvidence.objects.filter(mission_session__in=mission_sessions)
        .select_related("submitted_by", "reviewed_by", "mission_session")
        .order_by("-created_at")[:80]
    )
    token_requests = (
        TokenPurchaseRequest.objects.filter(token_filter)
        .select_related("assigned_admin")
        .order_by("-created_at")[:80]
    )

    return render(
        request,
        "chatapp/mission_center.html",
        {
            "mission_sessions": mission_sessions,
            "mission_evidence": mission_evidence,
            "token_requests": token_requests,
            "active_mission": active_mission,
            "is_admin_mission_overview": request.user.is_admin(),
            "completed_mission_count": sum(
                1
                for mission in mission_sessions
                if mission.status in {
                    MissionSession.Status.CLOSED,
                    MissionSession.Status.APPROVED,
                    MissionSession.Status.REJECTED,
                }
            ),
        },
    )


@login_required
def admin_unread_count(request):
    if not request.user.is_admin():
        return JsonResponse(
            {
                "unread_count": 0,
                "mission_request_count": 0,
                "total_action_count": 0,
            }
        )

    unread_count = (
        AdminChatThread.objects.filter(admin=request.user).aggregate(
            total=Sum("unread_count")
        )["total"]
        or 0
    )
    mission_request_count = _pending_mission_request_count()
    return JsonResponse(
        {
            "unread_count": unread_count,
            "mission_request_count": mission_request_count,
            "total_action_count": unread_count + mission_request_count,
        }
    )


@login_required
def admin_contact_unread_count(request):
    if request.user.is_admin():
        return JsonResponse({"unread_count": 0, "otp": None})

    admin = get_admin_contact_user()
    if not admin:
        return JsonResponse({"unread_count": 0, "otp": None})

    unread_count = (
        AdminChatThread.objects.filter(user=request.user).aggregate(
            total=Sum("user_unread_count")
        )["total"]
        or 0
    )
    otp = OTP.objects.filter(user=request.user, is_active=True, remaining_votes__gt=0).first()
    return JsonResponse(
        {
            "unread_count": unread_count,
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

    AdminChatThread.objects.filter(user=request.user).update(user_unread_count=0)
    return JsonResponse({"status": "ok", "unread_count": 0})


def _mission_payload(mission, viewer=None):
    def _player_snapshot(user):
        if not user:
            return None
        homepage_wins = MissionWinFeed.objects.filter(winner=user, homepage_visible=True).count()
        otp = OTP.objects.filter(user=user).only("remaining_votes").first()
        return {
            "id": user.id,
            "username": user.username,
            "profile_picture_url": user.get_profile_picture(),
            "badge_level": 1 + (homepage_wins // 3),
            "current_points": otp.remaining_votes if otp else 0,
            "homepage_wins": homepage_wins,
        }

    viewer_id = viewer.id if viewer and getattr(viewer, "is_authenticated", False) else None
    viewer_role = ""
    other_player = mission.opponent
    if viewer_id == mission.requester_id:
        viewer_role = "requester"
        other_player = mission.opponent
    elif viewer_id == mission.opponent_id:
        viewer_role = "opponent"
        other_player = mission.requester
    elif viewer and viewer.is_admin():
        viewer_role = "admin"

    requester_instruction = mission.mission_template.instruction_text if mission.mission_template else None
    opponent_instruction = "You are part of a secret mission. Chat naturally and respond to your opponent without knowing their objective."
    viewer_instruction = requester_instruction
    instruction_label = "Your Mission"
    if viewer_role == "opponent":
        viewer_instruction = opponent_instruction
        instruction_label = "Mission Chat"
    elif viewer_role == "admin":
        instruction_label = "Mission"

    return {
        "id": mission.id,
        "status": mission.status,
        "requester_id": mission.requester_id,
        "opponent_id": mission.opponent_id,
        "viewer_id": viewer_id,
        "viewer_role": viewer_role,
        "mission_template_id": mission.mission_template_id,
        "mission_instruction": viewer_instruction,
        "requester_instruction": requester_instruction if viewer_role in {"requester", "admin"} else None,
        "opponent_instruction": opponent_instruction if viewer_role in {"opponent", "admin"} else None,
        "mission_instruction_label": instruction_label,
        "reroll_count": mission.reroll_count,
        "max_rerolls": mission.max_rerolls,
        "winner_id": mission.winner_id,
        "loser_id": mission.loser_id,
        "timer_seconds": mission.timer_seconds,
        "started_at": mission.started_at.isoformat() if mission.started_at else None,
        "ended_at": mission.ended_at.isoformat() if mission.ended_at else None,
        "requester_profile": _player_snapshot(mission.requester),
        "opponent_profile": _player_snapshot(mission.opponent),
        "other_player_profile": _player_snapshot(other_player),
    }


def _parse_json_body(request):
    content_type = request.content_type or ""
    if content_type.startswith("multipart/form-data") or content_type.startswith("application/x-www-form-urlencoded"):
        return {}
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None


def _mission_action_error(message, status=400, code="mission_action_error", error_type="user_action"):
    return JsonResponse(
        {
            "status": "error",
            "message": str(message),
            "error_code": code,
            "error_type": error_type,
        },
        status=status,
    )


@login_required
@require_POST
def mission_request(request):
    try:
        mission = request_mission_for_user(request.user)
    except ValueError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

    broadcast_mission_update(mission)
    broadcast_admin_counts()
    return JsonResponse({"status": "ok", "mission": _mission_payload(mission, request.user)}, status=201)


@login_required
def mission_detail(request, mission_id):
    mission = get_object_or_404(
        MissionSession.objects.select_related("requester", "opponent", "mission_template"),
        pk=mission_id,
    )
    if not request.user.is_admin() and request.user.id not in {
        mission.requester_id,
        mission.opponent_id,
    }:
        return HttpResponseForbidden()
    return JsonResponse({"status": "ok", "mission": _mission_payload(mission, request.user)})


@login_required
def mission_latest(request):
    if request.user.is_admin():
        return JsonResponse({"status": "ok", "mission": None})
    mission = (
        MissionSession.objects.filter(
            Q(requester=request.user) | Q(opponent=request.user),
            status__in=PLAYER_ONGOING_MISSION_STATUSES,
        )
        .select_related("requester", "opponent", "mission_template")
        .order_by("-created_at")
        .first()
    )
    return JsonResponse(
        {
            "status": "ok",
            "mission": _mission_payload(mission, request.user) if mission else None,
        }
    )


@login_required
@require_POST
def mission_action(request, mission_id):
    mission = get_object_or_404(
        MissionSession.objects.select_related("requester", "opponent", "mission_template"),
        pk=mission_id,
    )
    payload = _parse_json_body(request)
    if payload is None:
        return _mission_action_error(
            "Invalid JSON payload.",
            code="invalid_payload",
            error_type="system",
        )

    action = (payload.get("action") or request.POST.get("action") or "").strip().lower()
    message = ""
    try:
        if action == "find_another_opponent":
            mission = request_another_opponent(mission, request.user)
            message = "Looking for another suitable opponent..."
            broadcast_admin_counts()
        elif action == "accept_opponent":
            mission = accept_opponent(mission, request.user)
            message = "Opponent accepted. Your secret mission is ready."
        elif action == "request_another_mission":
            mission = request_another_mission(mission, request.user)
            message = "Fetching another mission from the mission library..."
        elif action == "accept_mission":
            mission = accept_mission(mission, request.user)
            message = "Mission started. Complete your mission before your opponent."
        elif action == "submit_proof":
            explanation = payload.get("explanation") or request.POST.get("explanation") or ""
            evidence = submit_mission_proof(
                mission=mission,
                acting_user=request.user,
                screenshot=request.FILES.get("screenshot"),
                explanation=explanation,
            )
            mission.refresh_from_db()
            broadcast_mission_update(mission)
            broadcast_admin_counts()
            return JsonResponse(
                {
                    "status": "ok",
                    "mission": _mission_payload(mission, request.user),
                    "evidence": {
                        "id": evidence.id,
                        "review_status": evidence.review_status,
                    },
                    "message": "Proof submitted. Admin will review it. You can keep chatting with this opponent from your inbox.",
                }
            )
        elif action == "start_review":
            mission = route_and_start_mission_review(mission, request.user)
            message = "Mission moved to review queue."
        elif action in {"approve_proof", "reject_proof"}:
            if not request.user.is_admin():
                return HttpResponseForbidden()
            evidence_id = payload.get("evidence_id")
            evidence = get_object_or_404(MissionEvidence, pk=evidence_id)
            approved = action == "approve_proof"
            mission = review_mission_evidence(
                mission=mission,
                evidence=evidence,
                admin_user=request.user,
                approved=approved,
                review_notes=(payload.get("review_notes") or ""),
            )
            message = "Victory approved and rewards granted." if approved else "Proof not sufficient. Please upload better evidence."
        else:
            return _mission_action_error(
                "Unsupported mission action.",
                code="unsupported_action",
            )
    except PermissionError as exc:
        return _mission_action_error(
            str(exc),
            status=403,
            code="permission_denied",
            error_type="permission",
        )
    except ValueError as exc:
        message = str(exc)
        code = "mission_rule_not_met"
        if "Chat proof is empty" in message:
            code = "chat_proof_empty"
        elif "Proof can only be submitted" in message:
            code = "proof_not_allowed"
        elif "already have an active mission" in message:
            code = "active_mission_exists"
        return _mission_action_error(message, code=code)

    mission.refresh_from_db()
    broadcast_mission_update(mission)
    return JsonResponse({"status": "ok", "mission": _mission_payload(mission, request.user), "message": message})


@login_required
@require_POST
def token_purchase_create(request):
    payload = _parse_json_body(request)
    if payload is None:
        return JsonResponse({"status": "error", "message": "Invalid JSON payload."}, status=400)

    requested_tokens = payload.get("requested_tokens") or request.POST.get("requested_tokens")
    try:
        token_request = create_token_purchase_request(
            user=request.user,
            requested_tokens=requested_tokens,
            payment_channel=payload.get("payment_channel") or request.POST.get("payment_channel") or "",
            payment_reference=payload.get("payment_reference") or request.POST.get("payment_reference") or "",
            receipt_file=request.FILES.get("receipt_file"),
        )
    except (TypeError, ValueError) as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

    return JsonResponse(
        {
            "status": "ok",
            "token_request": {
                "id": token_request.id,
                "requested_tokens": token_request.requested_tokens,
                "status": token_request.status,
            },
        },
        status=201,
    )


@login_required
@require_POST
def token_purchase_review(request, request_id):
    if not request.user.is_admin():
        return HttpResponseForbidden()

    payload = _parse_json_body(request)
    if payload is None:
        return JsonResponse({"status": "error", "message": "Invalid JSON payload."}, status=400)

    token_request = get_object_or_404(TokenPurchaseRequest, pk=request_id)
    action = (payload.get("action") or "").strip().lower()
    if action not in {"approve", "reject"}:
        return JsonResponse({"status": "error", "message": "Unsupported review action."}, status=400)

    try:
        reviewed = review_token_purchase_request(
            token_request=token_request,
            admin_user=request.user,
            approved=action == "approve",
            approved_tokens=payload.get("approved_tokens"),
            review_notes=payload.get("review_notes") or "",
        )
    except ValueError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

    return JsonResponse(
        {
            "status": "ok",
            "token_request": {
                "id": reviewed.id,
                "status": reviewed.status,
                "approved_tokens": reviewed.approved_tokens,
                "reviewed_at": reviewed.reviewed_at.isoformat() if reviewed.reviewed_at else None,
            },
        }
    )
