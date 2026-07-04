from .models import CustomUser, Role, VotingTokenPolicy


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
            "admin_contact_unread_count": 0,
            "admin_contact_otp": None,
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
            from chatapp.models import AdminChatThread

            unread_count = sum(
                AdminChatThread.objects.filter(admin=user).values_list(
                    "unread_count", flat=True
                )
            )
        except Exception:
            unread_count = 0
        return {
            "admin_contact_user": None,
            "admin_chat_unread_count": unread_count,
            "admin_contact_unread_count": 0,
            "admin_contact_otp": None,
            "peer_chat_unread_count": 0,
            "message_retention_ms": _message_retention_ms(),
        }

    admin_user = (
        CustomUser.objects.filter(role=Role.ADMIN, is_active=True)
        .exclude(is_suspended_by_admin=True)
        .order_by("-is_superuser", "-is_staff", "username")
        .first()
    )
    admin_contact_unread_count = 0
    admin_contact_otp = None
    if admin_user:
        try:
            from chatapp.models import AdminChatThread
            from .models import OTP

            thread = AdminChatThread.objects.filter(admin=admin_user, user=user).first()
            admin_contact_unread_count = thread.user_unread_count if thread else 0
            admin_contact_otp = OTP.objects.filter(
                user=user,
                is_active=True,
                remaining_votes__gt=0,
            ).first()
        except Exception:
            admin_contact_unread_count = 0
            admin_contact_otp = None

    return {
        "admin_contact_user": admin_user,
        "admin_chat_unread_count": 0,
        "admin_contact_unread_count": admin_contact_unread_count,
        "admin_contact_otp": admin_contact_otp,
        "peer_chat_unread_count": peer_unread_count,
        "message_retention_ms": _message_retention_ms(),
    }
