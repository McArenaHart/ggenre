from django.contrib import admin
from .models import Content, Vote, Comment, LivePerformance, ArtistUploadLimit

from django.contrib import admin
from .models import Content

class ContentAdmin(admin.ModelAdmin):
    list_display = ('title', 'artist', 'is_approved', 'upload_date')
    list_filter = ('is_approved', 'upload_date')
    search_fields = ('title', 'artist__username')
    actions = ['approve_content', 'disapprove_content']

    def approve_content(self, request, queryset):
        queryset.update(is_approved=True)
    approve_content.short_description = "Approve selected content"

    def disapprove_content(self, request, queryset):
        queryset.update(is_approved=False)
    disapprove_content.short_description = "Disapprove selected content"

admin.site.register(Content, ContentAdmin)

@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ['content', 'fan', 'value', 'timestamp']

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ['content', 'user', 'text', 'timestamp']

@admin.register(LivePerformance)
class LivePerformanceAdmin(admin.ModelAdmin):
    list_display = ['title', 'artist', 'start_time', 'is_active']


@admin.action(description="Reset upload limits for selected artists")
def reset_upload_limit(modeladmin, request, queryset):
    for limit in queryset:
        limit.reset_limit()
        limit.artist.usernotification_set.create(
            message="Your upload limit has been reset. You can now upload content."
        )



@admin.register(ArtistUploadLimit)
class ArtistUploadLimitAdmin(admin.ModelAdmin):
    list_display = ('artist', 'uploads_used', 'upload_limit', 'reset_on_payment')
    actions = ['reset_upload_limit']

    def reset_upload_limit(self, request, queryset):
        """Admin action to manually reset the limit for selected artists."""
        for limit in queryset:
            limit.reset_limit()  # This will reset the uploads_used to 0 and reset reset_on_payment
        self.message_user(request, "Selected artist upload limits have been reset.")
    reset_upload_limit.short_description = "Reset upload limits for selected artists"
