from django.contrib import admin

from .models import AdminChatThread, MatchRating, PeerChatThread


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
