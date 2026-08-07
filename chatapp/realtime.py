from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import Sum

from users.models import CustomUser, Role

from .models import AdminChatThread, MissionSession


MISSION_REQUEST_QUEUE_STATUSES = [
    MissionSession.Status.REQUESTED,
    MissionSession.Status.MATCHING,
    MissionSession.Status.OPPONENT_PROPOSED,
]


def user_events_group(user_id):
    return f"user_events_{user_id}"


def admin_counts_payload(admin_user):
    unread_count = (
        AdminChatThread.objects.filter(admin=admin_user).aggregate(total=Sum("unread_count"))["total"]
        or 0
    )
    mission_request_count = MissionSession.objects.filter(status__in=MISSION_REQUEST_QUEUE_STATUSES).count()
    return {
        "unread_count": unread_count,
        "mission_request_count": mission_request_count,
        "total_action_count": unread_count + mission_request_count,
    }


def send_user_event(user_id, event_type, payload):
    channel_layer = get_channel_layer()
    if not channel_layer:
        return
    async_to_sync(channel_layer.group_send)(
        user_events_group(user_id),
        {
            "type": "user.event",
            "event": {
                "type": event_type,
                **payload,
            },
        },
    )


def broadcast_admin_counts(admin_user=None):
    admins = [admin_user] if admin_user else CustomUser.objects.filter(role=Role.ADMIN, is_active=True)
    for admin in admins:
        if admin:
            send_user_event(admin.id, "admin_counts", admin_counts_payload(admin))


def broadcast_mission_update(mission):
    if not mission:
        return
    payload = {
        "mission_id": mission.id,
        "status": mission.status,
        "requester_id": mission.requester_id,
        "opponent_id": mission.opponent_id,
    }
    send_user_event(mission.requester_id, "mission_updated", payload)
    if mission.opponent_id:
        send_user_event(mission.opponent_id, "mission_updated", payload)
