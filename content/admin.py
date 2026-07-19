from django.contrib import admin
from .models import Content, Vote, Comment, LivePerformance, ArtistUploadLimit
from django.contrib import admin
from .models import Content, Badge, ParticipationRequest
from users.models import OTP
from .models import Voucher

class ContentAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'artist',
        'is_approved',
        'is_visible',
        'is_approved_for_voting',
        'upload_date',
        'genre',
    )
    list_editable = ('is_approved', 'is_visible', 'is_approved_for_voting')
    list_filter = ('is_approved', 'is_visible', 'is_approved_for_voting', 'upload_date', 'genre')
    search_fields = ('title', 'artist__username')
    actions = [
        'approve_content',
        'disapprove_content',
        'show_content',
        'hide_content',
        'approve_voting',
        'disapprove_voting',
    ]

    def approve_content(self, request, queryset):
        queryset.update(is_approved=True)
    approve_content.short_description = "Approve selected content"

    def disapprove_content(self, request, queryset):
        queryset.update(is_approved=False)
    disapprove_content.short_description = "Disapprove selected content"

    def show_content(self, request, queryset):
        queryset.update(is_visible=True)
    show_content.short_description = "Show selected content"

    def hide_content(self, request, queryset):
        queryset.update(is_visible=False)
    hide_content.short_description = "Hide selected content"

    def approve_voting(self, request, queryset):
        queryset.update(is_approved_for_voting=True)
    approve_voting.short_description = "Approve selected content for voting"

    def disapprove_voting(self, request, queryset):
        queryset.update(is_approved_for_voting=False)
    disapprove_voting.short_description = "Disapprove selected content for voting"

admin.site.register(Content, ContentAdmin)

@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ['content', 'user', 'text', 'timestamp']

@admin.register(LivePerformance)
class LivePerformanceAdmin(admin.ModelAdmin):
    list_display = ['title', 'artist', 'start_time', 'is_active', 'is_restricted']
    list_editable = ['is_active', 'is_restricted']
    list_filter = ['is_active', 'is_restricted', 'start_time']


@admin.action(description="Reset upload limits for selected artists")
def reset_upload_limit(modeladmin, request, queryset):
    for limit in queryset:
        limit.reset_limit()
        limit.artist.usernotification_set.create(
            message="Your upload limit has been reset. You can now upload content."
        )



@admin.register(ArtistUploadLimit)
class ArtistUploadLimitAdmin(admin.ModelAdmin):
    list_display = ('artist', 'uploads_used', 'upload_limit', 'suspended_by_admin')
    list_editable = ('upload_limit', 'suspended_by_admin')
    list_filter = ('suspended_by_admin',)
    actions = ['reset_upload_limit', 'suspend_uploads', 'reinstate_uploads']

    def reset_upload_limit(self, request, queryset):
        """Admin action to manually reset the limit for selected artists."""
        for limit in queryset:
            limit.reset_limit()  # This will reset the uploads_used to 0 and reset reset_on_payment
        self.message_user(request, "Selected artist upload limits have been reset.")
    reset_upload_limit.short_description = "Reset upload limits for selected artists"

    def suspend_uploads(self, request, queryset):
        queryset.update(suspended_by_admin=True)
        self.message_user(request, "Selected artist upload limits have been suspended.")
    suspend_uploads.short_description = "Suspend uploads for selected artists"

    def reinstate_uploads(self, request, queryset):
        queryset.update(suspended_by_admin=False)
        self.message_user(request, "Selected artist upload limits have been reinstated.")
    reinstate_uploads.short_description = "Reinstate uploads for selected artists"



@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ('content', 'fan', 'value', 'is_badge_vote', 'timestamp', 'otp_code', 'tag')
    list_filter = ('timestamp', 'is_badge_vote')

@admin.register(OTP)
class OTPAdmin(admin.ModelAdmin):
    list_display = ('user', 'otp_code', 'remaining_votes', 'created_at')

@admin.register(ParticipationRequest)
class ParticipationRequestAdmin(admin.ModelAdmin):
    list_display = ('artist', 'content', 'status', 'created_at')

@admin.register(Badge)
class BadgeAdmin(admin.ModelAdmin):
    list_display = ('user', 'level')

@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = ['code', 'performance', 'is_used', 'created_by', 'used_by']
    search_fields = ['code', 'performance__title']
    list_filter = ['is_used', 'created_at']
