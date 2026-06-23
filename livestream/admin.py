from django.contrib import admin

from .models import LiveStream, LiveStreamAccess


@admin.register(LiveStream)
class LiveStreamAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "host",
        "status",
        "is_restricted",
        "allow_free_access",
        "scheduled_for",
        "started_at",
        "ended_at",
    )
    list_editable = ("status", "is_restricted", "allow_free_access")
    list_filter = ("status", "is_restricted", "allow_free_access", "scheduled_for")
    search_fields = ("title", "host__username", "stream_key")
    readonly_fields = ("stream_key", "created_at", "started_at", "ended_at")
    actions = ("mark_live", "mark_ended", "restrict_streams", "open_streams")

    @admin.action(description="Mark selected streams live")
    def mark_live(self, request, queryset):
        for stream in queryset:
            stream.start()
        self.message_user(request, f"Marked {queryset.count()} stream(s) live.")

    @admin.action(description="Mark selected streams ended")
    def mark_ended(self, request, queryset):
        for stream in queryset:
            stream.end()
        self.message_user(request, f"Marked {queryset.count()} stream(s) ended.")

    @admin.action(description="Restrict selected streams")
    def restrict_streams(self, request, queryset):
        queryset.update(is_restricted=True)
        self.message_user(request, f"Restricted {queryset.count()} stream(s).")

    @admin.action(description="Open selected streams")
    def open_streams(self, request, queryset):
        queryset.update(is_restricted=False)
        self.message_user(request, f"Opened {queryset.count()} stream(s).")


@admin.register(LiveStreamAccess)
class LiveStreamAccessAdmin(admin.ModelAdmin):
    list_display = ("stream", "user", "is_active", "granted_by", "created_at")
    list_editable = ("is_active",)
    list_filter = ("is_active", "created_at")
    search_fields = ("stream__title", "user__username", "granted_by__username")
