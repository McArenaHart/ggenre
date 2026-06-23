from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from users.models import Notification, Role

from .models import MatchRating, PeerChatThread


CHAT_ACCESS_DURATION = timedelta(days=1)


def users_are_valid_peer_candidates(first_user, second_user):
    if not first_user or not second_user or first_user.id == second_user.id:
        return False
    if first_user.has_role(Role.ADMIN) or second_user.has_role(Role.ADMIN):
        return False
    if not first_user.is_active or not second_user.is_active:
        return False
    if first_user.is_suspended_by_admin or second_user.is_suspended_by_admin:
        return False
    return True


def get_match_score(first_user, second_user):
    if not users_are_valid_peer_candidates(first_user, second_user):
        return None

    first_rating = MatchRating.objects.filter(
        rater=first_user,
        rated=second_user,
    ).values_list("score", flat=True).first()
    second_rating = MatchRating.objects.filter(
        rater=second_user,
        rated=first_user,
    ).values_list("score", flat=True).first()

    if first_rating is not None:
        return first_rating
    return second_rating


def users_can_peer_chat(first_user, second_user):
    if not users_are_valid_peer_candidates(first_user, second_user):
        return False

    user_one, user_two = PeerChatThread.ordered_users(first_user, second_user)
    return PeerChatThread.objects.filter(
        Q(admin_approved=True) | Q(unlocked_until__gt=timezone.now()),
        user_one=user_one,
        user_two=user_two,
    ).exists()


def admin_has_allowed_peer_chat(first_user, second_user):
    if not users_are_valid_peer_candidates(first_user, second_user):
        return False

    user_one, user_two = PeerChatThread.ordered_users(first_user, second_user)
    return PeerChatThread.objects.filter(
        user_one=user_one,
        user_two=user_two,
        admin_approved=True,
    ).exists()


@transaction.atomic
def allow_peer_chat_by_admin(first_user, second_user, admin_user):
    if not admin_user or not admin_user.has_role(Role.ADMIN):
        raise ValueError("Only admins can allow peer chats.")
    if not users_are_valid_peer_candidates(first_user, second_user):
        raise ValueError("These users cannot be allowed to chat.")

    was_allowed = users_can_peer_chat(first_user, second_user)
    thread, _ = PeerChatThread.get_or_create_for_users(first_user, second_user)
    if not thread.admin_approved:
        thread.admin_approved = True
        thread.approved_by = admin_user
        thread.approved_at = timezone.now()
        thread.save(update_fields=["admin_approved", "approved_by", "approved_at", "updated_at"])

    if not was_allowed:
        Notification.objects.bulk_create(
            [
                Notification(
                    user=first_user,
                    message=f"Admin unlocked chat between you and {second_user.username}.",
                ),
                Notification(
                    user=second_user,
                    message=f"Admin unlocked chat between you and {first_user.username}.",
                ),
            ]
        )
    return thread


@transaction.atomic
def revoke_admin_peer_chat(first_user, second_user):
    if not users_are_valid_peer_candidates(first_user, second_user):
        raise ValueError("These users cannot have peer chat access.")

    user_one, user_two = PeerChatThread.ordered_users(first_user, second_user)
    PeerChatThread.objects.filter(user_one=user_one, user_two=user_two).update(
        admin_approved=False,
        approved_by=None,
        approved_at=None,
        updated_at=timezone.now(),
    )


def _active_rating_until(first_user, second_user):
    latest_rating = (
        MatchRating.objects.filter(
            Q(rater=first_user, rated=second_user)
            | Q(rater=second_user, rated=first_user)
        )
        .order_by("-updated_at")
        .first()
    )
    if not latest_rating:
        return None
    return latest_rating.updated_at + CHAT_ACCESS_DURATION


def sync_peer_chat_access(first_user, second_user):
    user_one, user_two = PeerChatThread.ordered_users(first_user, second_user)
    thread = PeerChatThread.objects.filter(user_one=user_one, user_two=user_two).first()
    if not thread:
        return None

    unlocked_until = _active_rating_until(first_user, second_user)
    if thread.admin_approved:
        thread.unlocked_until = unlocked_until
        thread.save(update_fields=["unlocked_until", "updated_at"])
        return thread

    if not unlocked_until or unlocked_until <= timezone.now():
        thread.delete()
        return None

    thread.unlocked_until = unlocked_until
    thread.save(update_fields=["unlocked_until", "updated_at"])
    return thread


@transaction.atomic
def reset_content_rating_chat_access(content):
    ratings = list(
        MatchRating.objects.filter(source_content=content).select_related("rater", "rated")
    )
    affected_pairs = [(rating.rater, rating.rated) for rating in ratings]
    MatchRating.objects.filter(pk__in=[rating.pk for rating in ratings]).delete()

    for first_user, second_user in affected_pairs:
        sync_peer_chat_access(first_user, second_user)

    return len(ratings)


@transaction.atomic
def record_match_rating(rater, rated, score, source_content=None):
    score = int(score)
    if score < 1 or score > 10:
        raise ValueError("Match rating must be between 1 and 10.")
    if not users_are_valid_peer_candidates(rater, rated):
        raise ValueError("These users cannot use peer chat.")

    was_matched = users_can_peer_chat(rater, rated)
    rating, _ = MatchRating.objects.update_or_create(
        rater=rater,
        rated=rated,
        defaults={
            "score": score,
            "source_content": source_content,
        },
    )

    now = timezone.now()
    unlocked_until = now + CHAT_ACCESS_DURATION
    match_score = score
    thread = None
    matched = True
    thread, _ = PeerChatThread.get_or_create_for_users(rater, rated)
    thread.unlocked_until = unlocked_until
    thread.last_contact_at = now
    thread.save(update_fields=["unlocked_until", "last_contact_at", "updated_at"])
    if not was_matched:
        Notification.objects.bulk_create(
            [
                Notification(
                    user=rater,
                    message=(
                        f"Private chat with {rated.username} has been unlocked for 24 hours."
                    ),
                ),
                Notification(
                    user=rated,
                    message=(
                        f"{rater.username} rated you {match_score}/10. "
                        "Private chat has been unlocked for 24 hours."
                    ),
                ),
            ]
        )

    return {
        "rating": rating,
        "matched": matched,
        "match_score": match_score,
        "thread": thread,
    }
