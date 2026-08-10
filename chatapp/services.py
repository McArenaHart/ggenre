from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone
from datetime import timedelta

from content.models import Vote
from users.models import Notification, OTP, Role

from .models import (
    AdminChatThread,
    AdminDecisionLog,
    DirectChatMessage,
    MatchRating,
    MissionEvidence,
    MissionQueueEntry,
    MissionReviewControl,
    MissionSession,
    MissionTemplate,
    MissionWinFeed,
    PeerChatThread,
    ReviewAutomationTicket,
    TokenPurchaseRequest,
)


CHAT_ACCESS_DURATION = timedelta(days=1)
MISSION_AI_REVIEW_CONFIDENCE_THRESHOLD = 0.75
MISSION_MATCH_REMATCH_COOLDOWN_HOURS = 12
MISSION_DEFAULT_TIMER_SECONDS = 120
MISSION_DIFFICULTY_TIMER_STEP_SECONDS = 60
MISSION_MAX_TIMER_SECONDS = 3600


def _mission_policy_settings():
    def _as_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return default

    defaults = {
        "review_route_mode": "manual_only",
        "ai_confidence_threshold": MISSION_AI_REVIEW_CONFIDENCE_THRESHOLD,
        "prefer_online_opponent": True,
        "require_homepage_win_opponent": False,
        "manual_matchmaking": True,
        "rematch_cooldown_hours": MISSION_MATCH_REMATCH_COOLDOWN_HOURS,
        "bulk_review_max_items": 10,
        "mission_timer_seconds": MISSION_DEFAULT_TIMER_SECONDS,
    }
    configured = getattr(settings, "CHATAPP_MISSION_POLICY", {}) or {}
    policy = {**defaults, **configured}

    runtime_control = MissionReviewControl.objects.order_by("-updated_at", "-id").first()
    if runtime_control and runtime_control.route_mode:
        policy["review_route_mode"] = runtime_control.route_mode
        policy["mission_timer_seconds"] = runtime_control.mission_timer_seconds

    # Mission review is deliberately manual-only for now.
    policy["review_route_mode"] = "manual_only"
    try:
        policy["ai_confidence_threshold"] = float(policy.get("ai_confidence_threshold", 0.75))
    except (TypeError, ValueError):
        policy["ai_confidence_threshold"] = 0.75
    try:
        policy["rematch_cooldown_hours"] = max(0, int(policy.get("rematch_cooldown_hours", 12)))
    except (TypeError, ValueError):
        policy["rematch_cooldown_hours"] = 12
    try:
        policy["bulk_review_max_items"] = max(1, int(policy.get("bulk_review_max_items", 10)))
    except (TypeError, ValueError):
        policy["bulk_review_max_items"] = 10
    try:
        policy["mission_timer_seconds"] = max(60, min(int(policy.get("mission_timer_seconds", MISSION_DEFAULT_TIMER_SECONDS)), 3600))
    except (TypeError, ValueError):
        policy["mission_timer_seconds"] = MISSION_DEFAULT_TIMER_SECONDS
    policy["prefer_online_opponent"] = _as_bool(policy.get("prefer_online_opponent", True), default=True)
    policy["require_homepage_win_opponent"] = _as_bool(
        policy.get("require_homepage_win_opponent", False),
        default=False,
    )
    policy["manual_matchmaking"] = _as_bool(
        policy.get("manual_matchmaking", True),
        default=True,
    )
    return policy


def get_mission_policy_settings():
    return _mission_policy_settings()


def set_mission_review_route_mode(route_mode, reason=""):
    normalized = str(route_mode or "").strip().lower()
    if normalized != MissionReviewControl.RouteMode.MANUAL_ONLY:
        raise ValueError("Mission review is manual-only for now.")

    control = MissionReviewControl.objects.order_by("-updated_at", "-id").first()
    if not control:
        control = MissionReviewControl.objects.create(route_mode=normalized, reason=(reason or "")[:255])
        return control

    control.route_mode = normalized
    control.reason = (reason or "")[:255]
    control.save(update_fields=["route_mode", "reason", "updated_at"])
    return control


def set_mission_timer_seconds(timer_seconds, admin_user=None):
    try:
        normalized = max(60, min(int(timer_seconds), 3600))
    except (TypeError, ValueError):
        raise ValueError("Choose a valid mission timer.")

    control = MissionReviewControl.objects.order_by("-updated_at", "-id").first()
    if not control:
        control = MissionReviewControl.objects.create(
            route_mode=MissionReviewControl.RouteMode.MANUAL_ONLY,
            mission_timer_seconds=normalized,
            reason="Mission timer updated by admin.",
        )
    else:
        control.mission_timer_seconds = normalized
        control.save(update_fields=["mission_timer_seconds", "updated_at"])

    MissionSession.objects.filter(
        status__in=[
            MissionSession.Status.REQUESTED,
            MissionSession.Status.MATCHING,
            MissionSession.Status.OPPONENT_PROPOSED,
            MissionSession.Status.MISSION_PROPOSED,
        ],
        started_at__isnull=True,
    ).update(timer_seconds=normalized, updated_at=timezone.now())
    return control


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


MISSION_ACTIVE_STATUSES = {
    MissionSession.Status.REQUESTED,
    MissionSession.Status.MATCHING,
    MissionSession.Status.OPPONENT_PROPOSED,
    MissionSession.Status.MISSION_PROPOSED,
    MissionSession.Status.MISSION_ACTIVE,
    MissionSession.Status.PROOF_SUBMITTED,
    MissionSession.Status.UNDER_REVIEW,
}


def _validate_mission_player(user):
    if not user or user.has_role(Role.ADMIN):
        raise ValueError("Only non-admin players can join missions.")
    if not user.is_active or user.is_suspended_by_admin:
        raise ValueError("Suspended or inactive players cannot join missions.")


def _mission_visible_to_user(mission, user):
    if not user:
        return False
    if user.has_role(Role.ADMIN):
        return True
    return mission.requester_id == user.id or mission.opponent_id == user.id


def _available_player_queryset(exclude_user_id):
    return (
        MissionQueueEntry.objects.filter(status=MissionQueueEntry.QueueStatus.WAITING)
        .exclude(user_id=exclude_user_id)
        .select_related("user")
        .order_by("created_at")
    )


def _user_gender_value(user):
    # Gender is optional in this codebase; if absent, treat as unspecified.
    value = getattr(user, "gender", None)
    if value is None:
        return ""
    return str(value).strip().lower()


def _mission_pair_pool(first_user, second_user):
    first_gender = _user_gender_value(first_user)
    second_gender = _user_gender_value(second_user)
    girl_values = {"girl", "female", "woman", "f"}
    boy_values = {"boy", "male", "man", "m"}
    if first_gender in girl_values and second_gender in girl_values:
        return "girl_girl"
    if first_gender in boy_values and second_gender in boy_values:
        return "boy_boy"
    if (
        (first_gender in girl_values and second_gender in boy_values)
        or (first_gender in boy_values and second_gender in girl_values)
    ):
        return "boy_girl"
    return "mixed"


def _users_are_gender_compatible(first_user, second_user):
    first_gender = _user_gender_value(first_user)
    second_gender = _user_gender_value(second_user)
    if not first_gender or not second_gender:
        return True
    return first_gender != second_gender


def _find_available_opponent(requester):
    policy = _mission_policy_settings()
    rematch_cutoff = timezone.now() - timedelta(hours=policy["rematch_cooldown_hours"])
    available = []
    for queue_entry in _available_player_queryset(exclude_user_id=requester.id):
        candidate = queue_entry.user
        if not candidate or not users_are_valid_peer_candidates(requester, candidate):
            continue
        if not _users_are_gender_compatible(requester, candidate):
            continue
        recently_matched = MissionSession.objects.filter(
            Q(requester=requester, opponent=candidate) | Q(requester=candidate, opponent=requester),
            ended_at__gte=rematch_cutoff,
            status__in=[
                MissionSession.Status.APPROVED,
                MissionSession.Status.COOLDOWN_VOTE_REQUIRED,
                MissionSession.Status.CLOSED,
                MissionSession.Status.REJECTED,
            ],
        ).exists()
        is_online = bool(cache.get(f"direct_chat_presence:online:{candidate.id}"))
        has_homepage_win = MissionWinFeed.objects.filter(
            winner=candidate,
            homepage_visible=True,
        ).exists()
        if policy["require_homepage_win_opponent"] and not has_homepage_win:
            continue
        available.append(
            {
                "queue_entry": queue_entry,
                "recently_matched": recently_matched,
                "is_online": is_online,
                "has_homepage_win": has_homepage_win,
            }
        )

    if not available:
        return None

    candidate_pool = available
    candidate_pool.sort(
        key=lambda item: (
            0 if not item["recently_matched"] else 1,
            0 if (policy["prefer_online_opponent"] and item["is_online"]) else 1,
            0 if item["has_homepage_win"] else 1,
            item["queue_entry"].created_at,
        )
    )
    return candidate_pool[0]["queue_entry"]


def _assign_opponent_or_keep_matching(mission):
    queue_entry = _find_available_opponent(mission.requester)
    if not queue_entry:
        mission.status = MissionSession.Status.MATCHING
        mission.opponent = None
        mission.save(update_fields=["status", "opponent", "updated_at"])
        return mission

    mission.opponent = queue_entry.user
    mission.status = MissionSession.Status.OPPONENT_PROPOSED
    mission.save(update_fields=["opponent", "status", "updated_at"])
    MissionQueueEntry.objects.filter(pk=queue_entry.pk).update(
        status=MissionQueueEntry.QueueStatus.MATCHED,
        reason=f"Paired for mission #{mission.pk}",
        mission_session=mission,
        updated_at=timezone.now(),
    )
    return mission


def _legacy_default_mission_templates_unused():
    legacy_defaults = [
        (
            "Level 1: Emoji Vibe Check",
            "Get your opponent to describe your vibe using exactly one emoji and one word.",
            "Describe your opponent's vibe using exactly one emoji and one word.",
            "level_1_warmup",
            1,
        ),
        (
            "Level 1: Playlist Guess",
            "Send three song titles that match your mood and get your opponent to pick the one that fits you best.",
            "Your opponent will send three song titles. Pick the one that fits their mood best and briefly say why.",
            "level_1_warmup",
            1,
        ),
        (
            "Level 1: Two Truths And A Spark",
            "Share two true facts and one playful lie about yourself. Get your opponent to guess the lie.",
            "Your opponent will share two truths and one playful lie. Guess which one is the lie.",
            "level_1_warmup",
            1,
        ),
        (
            "Level 2: Secret Word",
            "Get your opponent to naturally say the word 'smooth' in chat.",
            "Chat naturally with your opponent. If the conversation fits, use the word 'smooth'.",
            "level_2_playful",
            2,
        ),
        (
            "Level 2: Compliment Catch",
            "Get your opponent to give you one genuine compliment without directly asking for a compliment.",
            "Give your opponent one genuine, respectful compliment if they earn it in the conversation.",
            "level_2_playful",
            2,
        ),
        (
            "Level 2: Would You Rather",
            "Ask a playful would-you-rather question and get your opponent to explain their choice.",
            "Answer your opponent's would-you-rather question and explain your choice.",
            "level_2_playful",
            2,
        ),
        (
            "Level 3: Reverse Pickup Line",
            "Get your opponent to send their funniest harmless pickup line.",
            "Send your funniest harmless pickup line when your opponent invites you to.",
            "level_3_flirty",
            3,
        ),
        (
            "Level 3: Guess My Type",
            "Describe your type with three respectful hints and get your opponent to guess one trait.",
            "Read your opponent's three respectful hints and guess one trait of their type.",
            "level_3_flirty",
            3,
        ),
        (
            "Level 3: Emoji Chemistry",
            "Use only emojis to describe an ideal first hangout and get your opponent to guess it.",
            "Your opponent will use only emojis to describe an ideal first hangout. Guess what they mean.",
            "level_3_flirty",
            3,
        ),
        (
            "Level 4: Flirty Riddle",
            "Send a playful riddle about your personality and get your opponent to solve it.",
            "Solve your opponent's playful personality riddle.",
            "level_4_confident",
            4,
        ),
        (
            "Level 4: Rate The Vibe",
            "Get your opponent to rate the conversation vibe from 1 to 10 and explain the score.",
            "Rate the conversation vibe from 1 to 10 and explain your score respectfully.",
            "level_4_confident",
            4,
        ),
        (
            "Level 5: Bold But Respectful",
            "Get your opponent to say what makes a conversation attractive to them, while keeping it respectful.",
            "Share what makes a conversation attractive to you, while keeping it respectful.",
            "level_5_bold",
            5,
        ),
    ]
    pool_defaults = []

    def add(pool, level, title, instruction):
        level_labels = {1: "Green", 2: "Blue", 3: "Purple", 4: "Gold"}
        points = {1: 5, 2: 10, 3: 20, 4: 50}
        pool_defaults.append(
            (
                f"{level_labels[level]}: {title}",
                instruction,
                "Chat naturally and respond honestly. Keep it respectful and comfortable.",
                f"{pool}_level_{level}",
                level,
            )
        )

    for pool in ["girl_girl", "mixed"]:
        add(pool, 1, "Really?", 'Get your opponent to naturally say "Really?"')
        add(pool, 1, "Laugh Line", "Make your opponent laugh.")
        add(pool, 1, "Heart Emoji", "Get your opponent to use ❤️.")
        add(pool, 1, "Name Drop", "Get your opponent to say your name.")
        add(pool, 1, "Three Emojis", "Get your opponent to send three emojis.")
        add(pool, 2, "Movie Pick", "Get your opponent to recommend a movie.")
        add(pool, 2, "Favourite Colour", "Get your opponent to tell you their favourite colour.")
        add(pool, 2, "Good Compliment", "Get your opponent to give you a respectful compliment.")
        add(pool, 2, "Dream Trip", "Get your opponent to tell you their dream destination.")
        add(pool, 3, "Advice Moment", "Get your opponent to give you one useful piece of advice.")
        add(pool, 3, "Secret Talent", "Get your opponent to tell you a secret talent.")
        add(pool, 3, "Keep It Going", "Keep the conversation going for 20 total messages.")

    for pool in ["boy_boy", "mixed"]:
        add(pool, 1, "Bro Moment", 'Get your opponent to naturally say "Bro."')
        add(pool, 1, "No Way", 'Get your opponent to say "No way!"')
        add(pool, 1, "Fire Emoji", "Get your opponent to use 🔥.")
        add(pool, 1, "Music Mention", "Get your opponent to mention music.")
        add(pool, 2, "Team Talk", "Get your opponent to recommend a football team.")
        add(pool, 2, "Favourite Car", "Get your opponent to tell you their favourite car.")
        add(pool, 2, "Business Mention", "Get your opponent to mention business.")
        add(pool, 2, "Three Questions", "Get your opponent to ask three questions.")
        add(pool, 3, "Dream Business", "Get your opponent to tell you their dream business.")
        add(pool, 3, "Big Win", "Get your opponent to tell you their biggest achievement.")
        add(pool, 3, "Team Logic", "Get your opponent to explain why they support their team.")
        add(pool, 3, "Keep It Going", "Keep the conversation going for 25 total messages.")

    for pool in ["boy_girl", "mixed"]:
        add(pool, 1, "Yes", 'Get your opponent to naturally say "Yes."')
        add(pool, 1, "Really?", 'Get your opponent to naturally say "Really?"')
        add(pool, 1, "Smile Emoji", "Get your opponent to use 😊.")
        add(pool, 1, "What You Do", "Get your opponent to ask what you do.")
        add(pool, 1, "Interesting", 'Get your opponent to say "Interesting."')
        add(pool, 2, "Know More", "Get your opponent to ask to know more about you.")
        add(pool, 2, "Favourite Food", "Get your opponent to mention their favourite food.")
        add(pool, 2, "Favourite Artist", "Get your opponent to tell you their favourite artist.")
        add(pool, 2, "Hobbies", "Get your opponent to ask what hobbies you have.")
        add(pool, 2, "Dream Holiday", "Get your opponent to tell you their dream holiday.")
        add(pool, 2, "Voice Note", "Get your opponent to send a voice note or short audio message.")
        add(pool, 3, "Enjoyed Chatting", "Get your opponent to say they enjoyed chatting with you.")
        add(pool, 3, "Profile Thought", "Get your opponent to tell you what they first thought about your profile.")
        add(pool, 3, "Later Here", "Get your opponent to invite you to continue the conversation later in this app.")
        add(pool, 3, "Follow Ups", "Get your opponent to ask two natural follow-up questions.")
        add(pool, 3, "Online Again", "Get your opponent to ask when you'll be online again.")
        add(pool, 4, "Legendary Flow", "Keep the conversation going for 30 total messages while staying respectful.")

    return legacy_defaults + pool_defaults


def _default_mission_templates():
    defaults = []
    level_labels = {
        1: ("Green", "icebreaker"),
        2: ("Blue", "discovery"),
        3: ("Purple", "connection"),
        4: ("Orange", "chemistry"),
        5: ("Gold", "mutual_interest"),
    }
    opponent_instruction = "Chat naturally and respond honestly. Keep it respectful and comfortable."

    def add(level, title, instruction):
        label, slug = level_labels[level]
        defaults.append(
            (
                f"{label}: {title}",
                instruction,
                opponent_instruction,
                f"mixed_{slug}",
                level,
            )
        )

    green = [
        ("Make Them Laugh", "Get your opponent to show amusement with a laugh, haha, lol, or a laughing emoji."),
        ("One Question", "Get your opponent to ask one question about you."),
        ("Something In Common", "Discover one harmless thing you both like."),
        ("Song Recommendation", "Get your opponent to recommend one song."),
        ("Three Emojis", "Get your opponent to describe the current vibe with three emojis."),
        ("Guess Something", "Get your opponent to make a playful guess about you."),
        ("Friendly Disagreement", "Get your opponent to disagree lightly and explain why."),
        ("Favourite Snack", "Get your opponent talking about a snack or food they could eat often."),
        ("Today In One Word", "Get your opponent to describe their day in one word."),
        ("Warm Reaction", "Get a warm reaction to something you share, such as nice, aww, smile, or a friendly emoji."),
        ("Quick Recommendation", "Get your opponent to recommend anything they currently enjoy."),
        ("Playful Surprise", "Share something light that makes your opponent respond with surprise or curiosity."),
        ("Your Turn", 'Get your opponent to ask "what about you?" or return a question back to you.'),
        ("Mini Opinion", "Get your opponent to share an opinion on a light topic."),
        ("Vibe Emoji", "Get your opponent to describe your vibe using one emoji and one word."),
        ("Would You Rather", "Ask a playful would-you-rather question and get your opponent to explain their choice."),
        ("Really Moment", 'Get your opponent to naturally say "really" or show the same kind of surprised reaction.'),
    ]
    blue = [
        ("Favourite Artist", "Get your opponent to tell you one artist they enjoy."),
        ("Ideal Weekend", "Get your opponent to describe their ideal weekend."),
        ("Dream Destination", "Get your opponent to name a dream place they would like to visit, without asking for private addresses."),
        ("Hidden Hobby", "Get your opponent to mention a hobby people might not guess from their profile."),
        ("Something To Learn", "Get your opponent to name something they would like to learn."),
        ("Current Obsession", "Get your opponent to talk about something they are currently into."),
        ("Childhood Favourite", "Get your opponent to mention a childhood favourite show, song, game, or snack."),
        ("Bucket List", "Get your opponent to share one harmless thing on their bucket list."),
        ("Unexpected Opinion", "Get your opponent to share a light opinion that might surprise people."),
        ("Movie Pick", "Get your opponent to recommend a movie or series."),
        ("Playlist Guess", "Send three song titles that match your mood and get your opponent to pick the one that fits you best."),
        ("Know More", "Get your opponent to ask to know more about something you shared."),
        ("Food Recommendation", "Get your opponent to recommend a meal, snack, or restaurant type they enjoy."),
        ("Hobbies", "Get your opponent to ask what hobbies you have."),
        ("Two Truths And A Spark", "Share two true facts and one playful lie about yourself, then get your opponent to guess the lie."),
        ("First Follow Up", "Get your opponent to ask a follow-up question about something you shared."),
        ("Swap Stories", "Get your opponent to trade a short story with you."),
        ("Voice Note Invite", "Get your opponent to voluntarily send a short voice note or audio message inside the app."),
    ]
    purple = [
        ("Two Follow Ups", "Get your opponent to ask two natural follow-up questions."),
        ("Remember That", "Get your opponent to remember and mention something you said earlier in the chat."),
        ("Inside Joke", "Create a tiny inside joke and get your opponent to refer back to it."),
        ("Secret Talent", "Get your opponent to tell you a talent or skill people may not know about."),
        ("Proud Moment", "Get your opponent to tell you something they are proud of."),
        ("Unexpected Connection", "Find a surprising thing you both relate to."),
        ("Ask To Hear More", "Get your opponent to ask you to continue or explain a story."),
        ("Callback", "Get your opponent to bring back an earlier topic without you prompting it directly."),
        ("Change My Mind", "Get your opponent to explain a light preference strongly enough that it could change your mind."),
        ("Story Exchange", "Get your opponent to share a short personal story after you share one first."),
        ("Three Questions", "Get your opponent to ask three questions across the conversation."),
        ("Advice Moment", "Get your opponent to give one useful, harmless piece of advice."),
        ("Big Win", "Get your opponent to tell you about a personal achievement."),
        ("Dream Project", "Get your opponent to describe a project, career goal, or business idea they would like to build."),
        ("Keep It Going 20", "Keep the conversation going for at least 20 total messages while staying natural."),
        ("Respectful Debate", "Start a light debate and get your opponent to explain their side without the chat turning tense."),
        ("Best Version", "Get your opponent to describe what a good year would look like for them."),
    ]
    orange = [
        ("Good Compliment", "Get your opponent to give you one genuine, respectful compliment without directly asking for it."),
        ("Profile Thought", "Get your opponent to tell you what they first thought about your profile."),
        ("Personality Compliment", "Get your opponent to compliment something about your personality or conversation style."),
        ("Nickname", "Get your opponent to give you a playful, respectful nickname."),
        ("Made You Smile", "Get your opponent to say or clearly show that something you said made them smile."),
        ("Something About You", "Get your opponent to tell you one thing they find interesting about you."),
        ("Perfect Hangout", "Get your opponent to describe a harmless ideal hangout, keeping it inside normal conversation."),
        ("One Thing", "Get your opponent to name one thing they would want to know before deciding someone's vibe."),
        ("Curious About You", "Get your opponent to say they are curious about something about you."),
        ("Chemistry Check", "Get your opponent to rate the conversation vibe from 1 to 10 and explain the score respectfully."),
        ("Playful Tease", "Get your opponent to lightly tease you in a friendly, respectful way."),
        ("You Seem Fun", "Get your opponent to say you seem fun, interesting, or easy to talk to."),
        ("Guess My Type", "Describe your type with three respectful personality hints and get your opponent to guess one trait."),
        ("Rate The Vibe", "Get your opponent to rate the chat vibe and explain what influenced the score."),
        ("Emoji Chemistry", "Use only emojis to describe an ideal first hangout and get your opponent to guess it."),
        ("Bold But Respectful", "Get your opponent to say what makes a conversation attractive to them, while keeping it respectful."),
    ]
    gold = [
        ("Later Here", "Get your opponent to invite you to continue the conversation later in this app."),
        ("Online Again", "Get your opponent to ask when you will be online again."),
        ("Round Two", "Get your opponent to suggest playing or chatting again after this mission."),
        ("Next Conversation", "Get your opponent to name a topic they want to continue next time."),
        ("We Should Keep Talking", "Get your opponent to say they want to keep talking in the app."),
        ("Bring Back The Joke", "Get your opponent to revive an inside joke later in the conversation."),
        ("Dont Go Yet", "Get your opponent to ask you to stay in the conversation a little longer."),
        ("Remember Me", "Get your opponent to mention something they will remember about you from this chat."),
        ("Legendary Flow", "Keep the conversation going for at least 30 total messages while staying respectful and natural."),
        ("Enjoyed Chatting", "Get your opponent to say they enjoyed chatting with you."),
        ("Continue The Thread", "Get your opponent to suggest continuing from this exact topic later in the app."),
    ]

    for level, missions in [
        (1, green),
        (2, blue),
        (3, purple),
        (4, orange),
        (5, gold),
    ]:
        for title, instruction in missions:
            add(level, title, instruction)

    return defaults


def ensure_default_mission_templates():
    default_titles = set()
    for title, instruction, opponent_instruction, category, difficulty in _default_mission_templates():
        default_titles.add(title)
        MissionTemplate.objects.update_or_create(
            title=title,
            defaults={
                "instruction_text": instruction,
                "opponent_instruction_text": opponent_instruction,
                "category": category,
                "difficulty": difficulty,
                "is_active": True,
            },
        )
    legacy_seed_filter = (
        Q(category__startswith="level_")
        | Q(category__startswith="mixed_level_")
        | Q(category__startswith="girl_girl_level_")
        | Q(category__startswith="boy_boy_level_")
        | Q(category__startswith="boy_girl_level_")
    )
    MissionTemplate.objects.filter(legacy_seed_filter).exclude(title__in=default_titles).update(is_active=False)


def _mission_pool_filter(pool):
    pool_filter = Q(category__startswith="mixed_")
    if pool:
        pool_filter |= Q(category__startswith=f"{pool}_")
    return pool_filter


def _pick_random_mission_template(pool=None, max_difficulty=None):
    ensure_default_mission_templates()
    queryset = MissionTemplate.objects.filter(is_active=True)
    if pool:
        pooled = queryset.filter(_mission_pool_filter(pool))
        if pooled.exists():
            queryset = pooled
    if max_difficulty:
        queryset = queryset.filter(difficulty__lte=max_difficulty)
    return queryset.order_by("?").first()


def _pick_mission_templates_for_players(first_user, second_user, selected_template=None):
    pool = _mission_pair_pool(first_user, second_user)
    requester_template = selected_template or _pick_random_mission_template(pool=pool)
    opponent_template = _pick_random_mission_template(pool=pool)
    if requester_template and opponent_template and requester_template.id == opponent_template.id:
        alternate = (
            MissionTemplate.objects.filter(is_active=True)
            .filter(_mission_pool_filter(pool))
            .exclude(pk=requester_template.pk)
            .order_by("?")
            .first()
        )
        if alternate:
            opponent_template = alternate
    return requester_template, opponent_template


def _mission_session_difficulty(mission):
    difficulties = []
    if mission.mission_template_id:
        difficulties.append(mission.mission_template.difficulty or 1)
    if mission.opponent_mission_template_id:
        difficulties.append(mission.opponent_mission_template.difficulty or 1)
    return max(difficulties or [1])


def _mission_timer_seconds_for_session(mission):
    base_seconds = _mission_policy_settings()["mission_timer_seconds"]
    difficulty = _mission_session_difficulty(mission)
    scaled_seconds = base_seconds + max(0, difficulty - 1) * MISSION_DIFFICULTY_TIMER_STEP_SECONDS
    return max(60, min(scaled_seconds, MISSION_MAX_TIMER_SECONDS))


def get_admin_contact_user():
    return (
        get_user_model()
        .objects.filter(role=Role.ADMIN, is_active=True)
        .exclude(is_suspended_by_admin=True)
        .order_by("-is_superuser", "-is_staff", "username")
        .first()
    )


def _send_admin_mission_message(admin_user, player, body):
    if not admin_user or not player:
        return
    DirectChatMessage.objects.create(
        sender=admin_user,
        recipient=player,
        body=body,
    )
    thread, created = AdminChatThread.objects.get_or_create(
        admin=admin_user,
        user=player,
        defaults={
            "user_unread_count": 1,
            "last_contact_at": timezone.now(),
        },
    )
    if not created:
        AdminChatThread.objects.filter(pk=thread.pk).update(
            user_unread_count=F("user_unread_count") + 1,
            last_contact_at=timezone.now(),
        )


def _mission_admin_sender(preferred_admin=None):
    return get_admin_contact_user() or (
        preferred_admin if preferred_admin and preferred_admin.has_role(Role.ADMIN) else None
    )


def _next_mission_route_actor_type():
    return AdminDecisionLog.ActorType.MANUAL


def _determine_mission_review_route(mission, evidence):
    return {
        "actor_type": AdminDecisionLog.ActorType.MANUAL,
        "confidence": 1,
        "rationale": "Mission proof is queued for manual admin verification.",
    }


@transaction.atomic
def route_and_start_mission_review(mission, acting_user):
    evidence = (
        MissionEvidence.objects.filter(
            mission_session=mission,
            review_status__in=[
                MissionEvidence.ReviewStatus.SUBMITTED,
                MissionEvidence.ReviewStatus.UNDER_REVIEW,
            ],
        )
        .order_by("-created_at")
        .first()
    )
    route = _determine_mission_review_route(mission, evidence)
    AdminDecisionLog.objects.create(
        actor_type=route["actor_type"],
        actor_user=acting_user if route["actor_type"] == AdminDecisionLog.ActorType.MANUAL else None,
        mission_session=mission,
        action="mission_review_route",
        rationale=route["rationale"],
        confidence=route["confidence"],
    )

    return move_mission_to_review(
        mission=mission,
        acting_user=acting_user,
        actor_type=route["actor_type"],
    )


def _eligible_for_new_mission(user):
    active_session_exists = MissionSession.objects.filter(
        Q(requester=user) | Q(opponent=user),
        status__in=MISSION_ACTIVE_STATUSES,
    ).exists()
    return not active_session_exists


def _loser_support_vote_exists(mission):
    if not mission.loser_id or not mission.winner_id:
        return True

    votes = Vote.objects.filter(
        fan_id=mission.loser_id,
        content__artist_id=mission.winner_id,
    )
    if mission.ended_at:
        votes = votes.filter(timestamp__gte=mission.ended_at)
    return votes.exists()


def _enforce_loser_support_rule(user):
    MissionSession.objects.filter(
        loser=user,
        loser_vote_required=True,
        status__in=[
            MissionSession.Status.APPROVED,
            MissionSession.Status.COOLDOWN_VOTE_REQUIRED,
        ],
    ).exclude(winner__isnull=True).update(
        status=MissionSession.Status.CLOSED,
        updated_at=timezone.now(),
    )


@transaction.atomic
def request_mission_for_user(user):
    _validate_mission_player(user)
    _enforce_loser_support_rule(user)
    if not _eligible_for_new_mission(user):
        raise ValueError("You already have an active mission.")

    mission = MissionSession.objects.create(
        requester=user,
        status=MissionSession.Status.REQUESTED,
    )
    MissionQueueEntry.objects.update_or_create(
        user=user,
        defaults={
            "status": MissionQueueEntry.QueueStatus.WAITING,
            "reason": "Waiting for mission opponent",
            "mission_session": mission,
        },
    )
    mission.status = MissionSession.Status.MATCHING
    mission.save(update_fields=["status", "updated_at"])
    if _mission_policy_settings().get("manual_matchmaking", True):
        return mission
    return _assign_opponent_or_keep_matching(mission)


@transaction.atomic
def create_admin_started_mission(admin_user, requester_user, opponent_user, mission_template=None):
    if not admin_user or not admin_user.has_role(Role.ADMIN):
        raise PermissionError("Only admins can start missions.")
    _validate_mission_player(requester_user)
    _validate_mission_player(opponent_user)
    if requester_user.id == opponent_user.id:
        raise ValueError("Choose two different players.")
    if not users_are_valid_peer_candidates(requester_user, opponent_user):
        raise ValueError("Selected players are not eligible for mission matchmaking.")
    if not _users_are_gender_compatible(requester_user, opponent_user):
        raise ValueError("Selected players are not suitable for this mission match.")
    _enforce_loser_support_rule(requester_user)
    _enforce_loser_support_rule(opponent_user)
    if not _eligible_for_new_mission(requester_user):
        raise ValueError("The first selected player already has an active mission.")
    if not _eligible_for_new_mission(opponent_user):
        raise ValueError("The opponent already has an active mission.")

    mission = MissionSession.objects.create(
        requester=requester_user,
        opponent=opponent_user,
        status=MissionSession.Status.OPPONENT_PROPOSED,
    )
    requester_template, opponent_template = _pick_mission_templates_for_players(
        requester_user,
        opponent_user,
        selected_template=mission_template,
    )
    mission.mission_template = requester_template
    mission.opponent_mission_template = opponent_template
    mission.save(update_fields=["mission_template", "opponent_mission_template", "updated_at"])
    MissionQueueEntry.objects.update_or_create(
        user=requester_user,
        defaults={
            "status": MissionQueueEntry.QueueStatus.MATCHED,
            "reason": f"Started by admin for mission #{mission.pk}",
            "mission_session": mission,
        },
    )
    MissionQueueEntry.objects.update_or_create(
        user=opponent_user,
        defaults={
            "status": MissionQueueEntry.QueueStatus.MATCHED,
            "reason": f"Started by admin for mission #{mission.pk}",
            "mission_session": mission,
        },
    )
    AdminDecisionLog.objects.create(
        actor_type=AdminDecisionLog.ActorType.MANUAL,
        actor_user=admin_user,
        mission_session=mission,
        action="admin_started_mission",
        rationale="Admin manually started a mission without a player request.",
        confidence=1,
    )
    Notification.objects.bulk_create(
        [
            Notification(
                user=requester_user,
                message=(
                    f"Admin started a mission with {opponent_user.username}. "
                    "Open the Mission panel to accept or request another opponent."
                ),
            ),
            Notification(
                user=opponent_user,
                message=(
                    f"Admin started a mission with {requester_user.username}. "
                    "Open the Mission panel to review the match."
                ),
            ),
        ]
    )
    contact_admin = _mission_admin_sender(admin_user)
    _send_admin_mission_message(
        contact_admin,
        requester_user,
        (
            f"Admin started a mission with {opponent_user.username}. "
            "Open this Mission panel to accept the opponent or request another match."
        ),
    )
    _send_admin_mission_message(
        contact_admin,
        opponent_user,
        (
            f"Admin started a mission with {requester_user.username}. "
            "Open this Mission panel to review the match."
        ),
    )
    return mission


@transaction.atomic
def request_another_opponent(mission, acting_user):
    if not _mission_visible_to_user(mission, acting_user):
        raise PermissionError("You cannot update this mission.")
    if mission.requester_id != acting_user.id:
        raise PermissionError("Only the player who requested this mission can change the opponent.")
    if mission.status not in {
        MissionSession.Status.MATCHING,
        MissionSession.Status.OPPONENT_PROPOSED,
    }:
        raise ValueError("Opponent can only be changed before mission acceptance.")

    mission.opponent = None
    mission.status = MissionSession.Status.MATCHING
    mission.save(update_fields=["opponent", "status", "updated_at"])
    if _mission_policy_settings().get("manual_matchmaking", True):
        return mission
    return _assign_opponent_or_keep_matching(mission)


@transaction.atomic
def accept_opponent(mission, acting_user):
    if not _mission_visible_to_user(mission, acting_user):
        raise PermissionError("You cannot update this mission.")
    if mission.requester_id != acting_user.id:
        raise PermissionError("Only the player who requested this mission can accept the opponent.")
    if mission.status != MissionSession.Status.OPPONENT_PROPOSED:
        raise ValueError("Opponent can only be accepted when one is proposed.")
    if not mission.opponent:
        raise ValueError("No opponent is currently assigned.")

    selected_template, opponent_template = _pick_mission_templates_for_players(
        mission.requester,
        mission.opponent,
        selected_template=mission.mission_template,
    )
    if not selected_template:
        raise ValueError("No active mission template is available.")

    mission.mission_template = selected_template
    mission.opponent_mission_template = opponent_template
    mission.status = MissionSession.Status.MISSION_PROPOSED
    mission.save(update_fields=["mission_template", "opponent_mission_template", "status", "updated_at"])
    admin_user = _mission_admin_sender(mission.assigned_admin)
    _send_admin_mission_message(
        admin_user,
        mission.requester,
        "Opponent accepted. Your secret mission is ready in the Mission panel.",
    )
    _send_admin_mission_message(
        admin_user,
        mission.opponent,
        (
            f"{mission.requester.username} accepted the match. "
            "Your secret mission is ready in the Mission panel."
        ),
    )
    return mission


@transaction.atomic
def request_another_mission(mission, acting_user):
    if not _mission_visible_to_user(mission, acting_user):
        raise PermissionError("You cannot update this mission.")
    if mission.requester_id != acting_user.id:
        raise PermissionError("Only the player who requested this mission can change the mission.")
    if mission.status != MissionSession.Status.MISSION_PROPOSED:
        raise ValueError("Mission can only be changed before mission start.")
    if mission.reroll_count >= mission.max_rerolls:
        raise ValueError("Mission reroll limit reached.")

    selected_template, opponent_template = _pick_mission_templates_for_players(mission.requester, mission.opponent)
    if not selected_template:
        raise ValueError("No active mission template is available.")

    mission.mission_template = selected_template
    mission.opponent_mission_template = opponent_template
    mission.reroll_count = mission.reroll_count + 1
    mission.save(update_fields=["mission_template", "opponent_mission_template", "reroll_count", "updated_at"])
    return mission


@transaction.atomic
def assign_mission_opponent_by_admin(mission, admin_user, opponent_user, mission_template=None):
    if not admin_user or not admin_user.has_role(Role.ADMIN):
        raise PermissionError("Only admins can assign mission opponents.")
    if mission.status not in {
        MissionSession.Status.REQUESTED,
        MissionSession.Status.MATCHING,
        MissionSession.Status.OPPONENT_PROPOSED,
    }:
        raise ValueError("Mission is not waiting for opponent assignment.")
    if not users_are_valid_peer_candidates(mission.requester, opponent_user):
        raise ValueError("Selected opponent is not eligible for mission matchmaking.")
    if not _users_are_gender_compatible(mission.requester, opponent_user):
        raise ValueError("Selected opponent is not suitable for this mission match.")
    if mission.assigned_admin_id and mission.assigned_admin_id != admin_user.id:
        raise ValueError("This mission request is currently claimed by another admin.")

    if mission.opponent_id != opponent_user.id and not _eligible_for_new_mission(opponent_user):
        raise ValueError("Selected opponent already has an active mission.")

    mission.opponent = opponent_user
    requester_template, opponent_template = _pick_mission_templates_for_players(
        mission.requester,
        opponent_user,
        selected_template=mission_template,
    )
    if requester_template:
        mission.mission_template = requester_template
    if opponent_template:
        mission.opponent_mission_template = opponent_template
    mission.status = MissionSession.Status.OPPONENT_PROPOSED
    mission.assigned_admin = None
    mission.assigned_at = None
    mission.save(
        update_fields=[
            "opponent",
            "mission_template",
            "opponent_mission_template",
            "status",
            "assigned_admin",
            "assigned_at",
            "updated_at",
        ]
    )

    MissionQueueEntry.objects.update_or_create(
        user=mission.requester,
        defaults={
            "status": MissionQueueEntry.QueueStatus.MATCHED,
            "reason": f"Matched by admin for mission #{mission.pk}",
            "mission_session": mission,
        },
    )
    MissionQueueEntry.objects.update_or_create(
        user=opponent_user,
        defaults={
            "status": MissionQueueEntry.QueueStatus.MATCHED,
            "reason": f"Matched by admin for mission #{mission.pk}",
            "mission_session": mission,
        },
    )

    AdminDecisionLog.objects.create(
        actor_type=AdminDecisionLog.ActorType.MANUAL,
        actor_user=admin_user,
        mission_session=mission,
        action="manual_match_assignment",
        rationale="Admin manually selected an online opponent for mission matchmaking.",
        confidence=1,
    )

    Notification.objects.bulk_create(
        [
            Notification(
                user=mission.requester,
                message=(
                    f"Opponent found: {opponent_user.username}. "
                    "Open admin chat to accept or request another opponent."
                ),
            ),
            Notification(
                user=opponent_user,
                message=(
                    f"Opponent found: {mission.requester.username}. "
                    "Open admin chat to accept or request another opponent."
                ),
            ),
        ]
    )
    contact_admin = _mission_admin_sender(admin_user)
    _send_admin_mission_message(
        contact_admin,
        mission.requester,
        (
            f"Opponent found: {opponent_user.username}. "
            "Open this Mission panel to accept the opponent or request another match."
        ),
    )
    _send_admin_mission_message(
        contact_admin,
        opponent_user,
        (
            f"Opponent found: {mission.requester.username}. "
            "Open this Mission panel to accept the opponent or request another match."
        ),
    )
    return mission


@transaction.atomic
def accept_mission(mission, acting_user):
    if not _mission_visible_to_user(mission, acting_user):
        raise PermissionError("You cannot update this mission.")
    if mission.requester_id != acting_user.id:
        raise PermissionError("Only the player who requested this mission can start it.")
    if mission.status != MissionSession.Status.MISSION_PROPOSED:
        raise ValueError("Mission can only be accepted when proposed.")
    if not mission.mission_template_id or not mission.opponent_id:
        raise ValueError("Mission setup is incomplete.")

    mission.status = MissionSession.Status.MISSION_ACTIVE
    mission.started_at = timezone.now()
    mission.timer_seconds = _mission_timer_seconds_for_session(mission)
    mission.save(update_fields=["status", "started_at", "timer_seconds", "updated_at"])

    # Mission start should unlock direct chat for the matched pair.
    user_one, user_two = PeerChatThread.ordered_users(mission.requester, mission.opponent)
    thread, _ = PeerChatThread.objects.get_or_create(user_one=user_one, user_two=user_two)
    thread.unlocked_until = timezone.now() + CHAT_ACCESS_DURATION
    thread.last_contact_at = timezone.now()
    thread.save(update_fields=["unlocked_until", "last_contact_at", "updated_at"])
    admin_user = _mission_admin_sender(mission.assigned_admin)
    _send_admin_mission_message(
        admin_user,
        mission.requester,
        f"Mission started. You can now chat with {mission.opponent.username}.",
    )
    _send_admin_mission_message(
        admin_user,
        mission.opponent,
        f"Mission started. You can now chat with {mission.requester.username}.",
    )
    return mission


def _mission_chat_transcript(mission):
    if not mission.requester_id or not mission.opponent_id:
        return ""

    messages = DirectChatMessage.objects.filter(
        Q(sender=mission.requester, recipient=mission.opponent)
        | Q(sender=mission.opponent, recipient=mission.requester)
    ).select_related("sender").order_by("created_at")

    if mission.started_at:
        messages = messages.filter(created_at__gte=mission.started_at)

    rows = []
    for message in messages[:80]:
        timestamp = timezone.localtime(message.created_at).strftime("%Y-%m-%d %H:%M")
        rows.append(f"[{timestamp}] {message.sender.username}: {message.body}")

    return "\n".join(rows)


def cleanup_mission_chat_media(mission):
    if not mission.requester_id or not mission.opponent_id:
        return 0

    lower_bound = mission.started_at or mission.created_at
    upper_bound = mission.ended_at or timezone.now()
    messages = (
        DirectChatMessage.objects.filter(
            Q(sender=mission.requester, recipient=mission.opponent)
            | Q(sender=mission.opponent, recipient=mission.requester)
        )
        .exclude(media_file="")
        .filter(media_file__isnull=False, created_at__gte=lower_bound, created_at__lte=upper_bound)
    )

    cleaned = 0
    for message in messages.iterator():
        if not message.media_file:
            continue
        message.media_file.delete(save=False)
        message.media_file = None
        message.media_type = ""
        message.media_name = ""
        message.save(update_fields=["media_file", "media_type", "media_name"])
        cleaned += 1
    return cleaned


@transaction.atomic
def submit_mission_proof(mission, acting_user, screenshot=None, explanation=""):
    if not _mission_visible_to_user(mission, acting_user):
        raise PermissionError("You cannot submit proof for this mission.")
    if mission.status != MissionSession.Status.MISSION_ACTIVE:
        raise ValueError("Proof can only be submitted while mission is active.")
    explanation = (explanation or "").strip()
    chat_transcript = _mission_chat_transcript(mission)
    if not chat_transcript and not screenshot and not explanation:
        raise ValueError("Chat proof is empty. Send mission messages first or add a note before submitting proof.")

    evidence = MissionEvidence.objects.create(
        mission_session=mission,
        submitted_by=acting_user,
        screenshot=screenshot,
        explanation=explanation,
        chat_transcript=chat_transcript,
        review_status=MissionEvidence.ReviewStatus.SUBMITTED,
    )
    mission.status = MissionSession.Status.PROOF_SUBMITTED
    mission.save(update_fields=["status", "updated_at"])
    return evidence


@transaction.atomic
def move_mission_to_review(mission, acting_user, actor_type=AdminDecisionLog.ActorType.AI):
    if not acting_user.has_role(Role.ADMIN):
        raise PermissionError("Only admins can start mission review.")
    if mission.status not in {
        MissionSession.Status.PROOF_SUBMITTED,
        MissionSession.Status.UNDER_REVIEW,
    }:
        raise ValueError("Mission is not ready for review.")

    mission.status = MissionSession.Status.UNDER_REVIEW
    mission.save(update_fields=["status", "updated_at"])
    AdminDecisionLog.objects.create(
        actor_type=actor_type,
        actor_user=acting_user if actor_type == AdminDecisionLog.ActorType.MANUAL else None,
        mission_session=mission,
        action="review_started",
        rationale="Mission proof submitted and queued for verification.",
    )
    MissionEvidence.objects.filter(
        mission_session=mission,
        review_status=MissionEvidence.ReviewStatus.SUBMITTED,
    ).update(review_status=MissionEvidence.ReviewStatus.UNDER_REVIEW, updated_at=timezone.now())
    return mission


@transaction.atomic
def review_mission_evidence(
    mission,
    evidence,
    admin_user,
    approved,
    review_notes="",
    actor_type=AdminDecisionLog.ActorType.MANUAL,
):
    if not admin_user.has_role(Role.ADMIN):
        raise PermissionError("Only admins can review mission evidence.")
    if evidence.mission_session_id != mission.id:
        raise ValueError("Evidence does not belong to this mission.")
    if mission.status not in {
        MissionSession.Status.PROOF_SUBMITTED,
        MissionSession.Status.UNDER_REVIEW,
    }:
        raise ValueError("Mission is not in a reviewable state.")

    evidence.reviewed_by = admin_user
    evidence.review_notes = review_notes or ""
    if approved:
        evidence.review_status = MissionEvidence.ReviewStatus.APPROVED
        mission.winner = evidence.submitted_by
        mission.loser = mission.opponent if mission.requester_id == evidence.submitted_by_id else mission.requester
        mission.status = MissionSession.Status.CLOSED
        mission.ended_at = timezone.now()
        mission.save(update_fields=["winner", "loser", "status", "ended_at", "updated_at"])
        evidence.save(update_fields=["reviewed_by", "review_notes", "review_status", "updated_at"])
        transaction.on_commit(lambda: cleanup_mission_chat_media(mission))
        MissionWinFeed.objects.update_or_create(
            mission_session=mission,
            defaults={
                "winner": evidence.submitted_by,
                "approved_evidence": evidence,
                "homepage_visible": True,
                "published_at": timezone.now(),
            },
        )
        grant_mission_bonus_votes(user=evidence.submitted_by, admin_user=admin_user, votes=2)
    else:
        evidence.review_status = MissionEvidence.ReviewStatus.REJECTED
        mission.status = MissionSession.Status.REJECTED
        if not mission.ended_at:
            mission.ended_at = timezone.now()
        mission.save(update_fields=["status", "ended_at", "updated_at"])
        evidence.save(update_fields=["reviewed_by", "review_notes", "review_status", "updated_at"])
        transaction.on_commit(lambda: cleanup_mission_chat_media(mission))

    AdminDecisionLog.objects.create(
        actor_type=actor_type,
        actor_user=admin_user if actor_type == AdminDecisionLog.ActorType.MANUAL else None,
        mission_session=mission,
        action="approve_proof" if approved else "reject_proof",
        rationale=review_notes or "",
    )
    return mission


@transaction.atomic
def grant_mission_bonus_votes(user, admin_user, votes=2):
    if not admin_user or not admin_user.has_role(Role.ADMIN):
        raise ValueError("Only admins can grant mission bonus votes.")

    otp, _ = OTP.objects.get_or_create(
        user=user,
        defaults={
            "otp_code": "000000",
            "remaining_votes": 0,
            "is_active": True,
        },
    )
    # Keep OTP semantics unchanged: extend adds votes and preserves current code.
    otp.grant_votes(votes=max(1, int(votes or 1)))

    thread, created = AdminChatThread.objects.get_or_create(
        admin=admin_user,
        user=user,
        defaults={"user_unread_count": 1, "last_contact_at": timezone.now()},
    )
    if not created:
        AdminChatThread.objects.filter(pk=thread.pk).update(
            user_unread_count=F("user_unread_count") + 1,
            last_contact_at=timezone.now(),
        )
    Notification.objects.create(
        user=user,
        message=(
            f"Mission reward approved: +{max(1, int(votes or 1))} voting token(s). "
            f"Current balance: {otp.remaining_votes}."
        ),
    )
    return otp


@transaction.atomic
def create_token_purchase_request(user, requested_tokens, payment_channel="", payment_reference="", receipt_file=None):
    _validate_mission_player(user)
    requested_tokens = int(requested_tokens)
    if requested_tokens <= 0:
        raise ValueError("Requested tokens must be greater than zero.")

    return TokenPurchaseRequest.objects.create(
        requester=user,
        requested_tokens=requested_tokens,
        payment_channel=(payment_channel or "")[:40],
        payment_reference=(payment_reference or "")[:120],
        receipt_file=receipt_file,
        status=TokenPurchaseRequest.Status.SUBMITTED,
    )


@transaction.atomic
def review_token_purchase_request(
    token_request,
    admin_user,
    approved,
    approved_tokens=None,
    review_notes="",
    actor_type=AdminDecisionLog.ActorType.MANUAL,
):
    if not admin_user.has_role(Role.ADMIN):
        raise PermissionError("Only admins can review token purchases.")
    if token_request.status in {
        TokenPurchaseRequest.Status.APPROVED,
        TokenPurchaseRequest.Status.REJECTED,
        TokenPurchaseRequest.Status.CANCELLED,
    }:
        raise ValueError("This token request is already closed.")

    AdminDecisionLog.objects.create(
        actor_type=AdminDecisionLog.ActorType.MANUAL,
        actor_user=admin_user,
        token_purchase_request=token_request,
        action="token_review_route",
        rationale="Token purchase requests are always routed to manual review.",
        confidence=1,
    )

    token_request.assigned_admin = admin_user
    token_request.review_notes = review_notes or ""
    token_request.reviewed_at = timezone.now()

    if approved:
        grant_count = int(approved_tokens or token_request.requested_tokens)
        if grant_count <= 0:
            raise ValueError("Approved tokens must be greater than zero.")
        grant_mission_bonus_votes(token_request.requester, admin_user, votes=grant_count)
        token_request.status = TokenPurchaseRequest.Status.APPROVED
        token_request.approved_tokens = grant_count
    else:
        token_request.status = TokenPurchaseRequest.Status.REJECTED
        token_request.approved_tokens = 0

    token_request.save(
        update_fields=[
            "assigned_admin",
            "status",
            "approved_tokens",
            "review_notes",
            "reviewed_at",
            "updated_at",
        ]
    )
    AdminDecisionLog.objects.create(
        actor_type=actor_type,
        actor_user=admin_user if actor_type == AdminDecisionLog.ActorType.MANUAL else None,
        token_purchase_request=token_request,
        action="approve_token_purchase" if approved else "reject_token_purchase",
        rationale=review_notes or "",
    )
    return token_request
