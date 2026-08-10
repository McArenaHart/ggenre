from django.contrib import admin

from .models import (
    AdminChatThread,
    AdminDecisionLog,
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


@admin.register(AdminChatThread)
class AdminChatThreadAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "admin",
        "unread_count",
        "user_unread_count",
        "last_contact_at",
        "updated_at",
    )
    list_filter = ("last_contact_at", "updated_at")
    search_fields = ("user__username", "admin__username")
    readonly_fields = ("created_at", "updated_at")


@admin.register(PeerChatThread)
class PeerChatThreadAdmin(admin.ModelAdmin):
    list_display = (
        "user_one",
        "user_two",
        "admin_approved",
        "approved_by",
        "approved_at",
        "unlocked_until",
        "last_contact_at",
    )
    list_filter = ("admin_approved", "approved_at", "unlocked_until", "last_contact_at")
    search_fields = ("user_one__username", "user_two__username", "approved_by__username")
    readonly_fields = ("created_at", "updated_at", "last_contact_at")


@admin.register(MatchRating)
class MatchRatingAdmin(admin.ModelAdmin):
    list_display = ("rater", "rated", "score", "source_content", "created_at", "updated_at")
    list_filter = ("score", "created_at", "updated_at")
    search_fields = ("rater__username", "rated__username", "source_content__title")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MissionTemplate)
class MissionTemplateAdmin(admin.ModelAdmin):
    list_display = ("title", "category", "difficulty", "is_active", "updated_at")
    list_filter = ("is_active", "category", "difficulty")
    search_fields = ("title", "instruction_text", "category")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MissionSession)
class MissionSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "requester",
        "opponent",
        "status",
        "mission_template",
        "reroll_count",
        "max_rerolls",
        "created_at",
    )
    list_filter = ("status", "loser_vote_required", "created_at", "started_at", "ended_at")
    search_fields = ("requester__username", "opponent__username")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MissionQueueEntry)
class MissionQueueEntryAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "reason", "mission_session", "updated_at")
    list_filter = ("status", "created_at", "updated_at")
    search_fields = ("user__username", "reason")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MissionReviewControl)
class MissionReviewControlAdmin(admin.ModelAdmin):
    list_display = ("id", "route_mode", "mission_timer_seconds", "reason", "updated_at")
    list_filter = ("route_mode", "updated_at")
    search_fields = ("reason",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(MissionEvidence)
class MissionEvidenceAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "mission_session",
        "submitted_by",
        "review_status",
        "reviewed_by",
        "created_at",
    )
    list_filter = ("review_status", "created_at", "updated_at")
    search_fields = ("submitted_by__username", "review_notes", "explanation")
    readonly_fields = ("created_at", "updated_at")


@admin.register(TokenPurchaseRequest)
class TokenPurchaseRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "requester",
        "requested_tokens",
        "approved_tokens",
        "status",
        "assigned_admin",
        "created_at",
    )
    list_filter = ("status", "payment_channel", "created_at", "reviewed_at")
    search_fields = (
        "requester__username",
        "payment_reference",
        "review_notes",
        "assigned_admin__username",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(AdminDecisionLog)
class AdminDecisionLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "actor_type",
        "actor_user",
        "action",
        "mission_session",
        "token_purchase_request",
        "created_at",
    )
    list_filter = ("actor_type", "action", "created_at")
    search_fields = ("action", "rationale", "actor_user__username")
    readonly_fields = ("created_at",)


@admin.register(ReviewAutomationTicket)
class ReviewAutomationTicketAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "mission_session",
        "mission_evidence",
        "route_actor_type",
        "status",
        "created_at",
    )
    list_filter = ("route_actor_type", "status", "created_at")
    search_fields = ("mission_session__id", "mission_evidence__id", "error_message")
    readonly_fields = ("created_at", "updated_at")


@admin.register(MissionWinFeed)
class MissionWinFeedAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "winner",
        "mission_session",
        "homepage_visible",
        "published_at",
    )
    list_filter = ("homepage_visible", "published_at")
    search_fields = ("winner__username",)
    readonly_fields = ("created_at", "updated_at")
