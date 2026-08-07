from django.db.models import Q, Sum

from .models import CustomUser, Role, VotingTokenPolicy


ONGOING_MISSION_STATUSES = [
    "requested",
    "matching",
    "opponent_proposed",
    "mission_proposed",
    "mission_active",
    "proof_submitted",
    "under_review",
]


def _message_retention_ms():
    try:
        return VotingTokenPolicy.message_retention_ms()
    except Exception:
        return 24 * 60 * 60 * 1000


def admin_contact(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "admin_contact_user": None,
            "admin_chat_unread_count": 0,
            "admin_mission_request_count": 0,
            "admin_contact_unread_count": 0,
            "admin_contact_otp": None,
            "admin_contact_latest_mission": None,
            "admin_contact_mission_chat_user": None,
            "admin_contact_mission_chat_unread_count": 0,
            "peer_chat_unread_count": 0,
            "message_retention_ms": _message_retention_ms(),
        }

    peer_unread_count = 0
    if not user.has_role(Role.ADMIN):
        try:
            from chatapp.models import PeerChatThread
            from chatapp.services import users_can_peer_chat

            one_threads = (
                PeerChatThread.objects.filter(
                    user_one=user,
                    user_two__is_active=True,
                    user_two__is_suspended_by_admin=False,
                )
                .exclude(user_two__role=Role.ADMIN)
            )
            two_threads = (
                PeerChatThread.objects.filter(
                    user_two=user,
                    user_one__is_active=True,
                    user_one__is_suspended_by_admin=False,
                )
                .exclude(user_one__role=Role.ADMIN)
            )
            peer_unread_count = sum(
                thread.unread_count_user_one
                for thread in one_threads.select_related("user_two")
                if users_can_peer_chat(user, thread.user_two)
            ) + sum(
                thread.unread_count_user_two
                for thread in two_threads.select_related("user_one")
                if users_can_peer_chat(user, thread.user_one)
            )
        except Exception:
            peer_unread_count = 0

    if user.has_role(Role.ADMIN):
        try:
            from chatapp.models import AdminChatThread, MissionSession

            unread_count = sum(
                AdminChatThread.objects.filter(admin=user).values_list(
                    "unread_count", flat=True
                )
            )
            mission_request_count = MissionSession.objects.filter(
                status__in=["requested", "matching", "opponent_proposed"]
            ).count()
        except Exception:
            unread_count = 0
            mission_request_count = 0
        return {
            "admin_contact_user": None,
            "admin_chat_unread_count": unread_count + mission_request_count,
            "admin_mission_request_count": mission_request_count,
            "admin_contact_unread_count": 0,
            "admin_contact_otp": None,
            "admin_contact_latest_mission": None,
            "admin_contact_mission_chat_user": None,
            "admin_contact_mission_chat_unread_count": 0,
            "peer_chat_unread_count": 0,
            "message_retention_ms": _message_retention_ms(),
        }

    admin_user = None
    try:
        from chatapp.services import get_admin_contact_user

        admin_user = get_admin_contact_user()
    except Exception:
        admin_user = (
            CustomUser.objects.filter(role=Role.ADMIN, is_active=True)
            .exclude(is_suspended_by_admin=True)
            .order_by("-is_superuser", "-is_staff", "username")
            .first()
        )
    admin_contact_unread_count = 0
    admin_contact_otp = None
    admin_contact_latest_mission = None
    admin_contact_mission_chat_user = None
    admin_contact_mission_chat_unread_count = 0
    if admin_user:
        try:
            from chatapp.models import AdminChatThread, MissionSession, PeerChatThread
            from chatapp.services import users_can_peer_chat
            from .models import OTP

            admin_contact_unread_count = (
                AdminChatThread.objects.filter(user=user).aggregate(
                    total=Sum("user_unread_count")
                )["total"]
                or 0
            )
            admin_contact_otp = OTP.objects.filter(
                user=user,
                is_active=True,
                remaining_votes__gt=0,
            ).first()
            admin_contact_latest_mission = (
                MissionSession.objects.filter(
                    Q(requester=user) | Q(opponent=user),
                    status__in=ONGOING_MISSION_STATUSES,
                )
                .select_related("mission_template", "requester", "opponent")
                .order_by("-created_at")
                .first()
            )
            if admin_contact_latest_mission and admin_contact_latest_mission.opponent_id:
                other_player = (
                    admin_contact_latest_mission.opponent
                    if admin_contact_latest_mission.requester_id == user.id
                    else admin_contact_latest_mission.requester
                )
                if other_player:
                    admin_contact_mission_chat_user = other_player
                    if users_can_peer_chat(user, other_player):
                        user_one, user_two = PeerChatThread.ordered_users(user, other_player)
                        thread = PeerChatThread.objects.filter(user_one=user_one, user_two=user_two).first()
                        admin_contact_mission_chat_unread_count = thread.unread_count_for(user) if thread else 0
        except Exception:
            admin_contact_unread_count = 0
            admin_contact_otp = None
            admin_contact_latest_mission = None
            admin_contact_mission_chat_user = None
            admin_contact_mission_chat_unread_count = 0

    return {
        "admin_contact_user": admin_user,
        "admin_chat_unread_count": 0,
        "admin_mission_request_count": 0,
        "admin_contact_unread_count": admin_contact_unread_count,
        "admin_contact_otp": admin_contact_otp,
        "admin_contact_latest_mission": admin_contact_latest_mission,
        "admin_contact_mission_chat_user": admin_contact_mission_chat_user,
        "admin_contact_mission_chat_unread_count": admin_contact_mission_chat_unread_count,
        "peer_chat_unread_count": peer_unread_count,
        "message_retention_ms": _message_retention_ms(),
    }
