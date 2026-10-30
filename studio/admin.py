from django.contrib import admin
from .models import Project, Export, ExportAllowance

@admin.register(Export)
class ExportAdmin(admin.ModelAdmin):
    list_display = ("id", "project", "status", "payment_reference", "created_at", "reviewed_by")
    list_filter = ("status",)
    readonly_fields = ("project", "status", "payment_reference", "created_at", "reviewed_by")
    exclude = ("audio",)
    actions = ("approve_payment", "reject_payment")

    def has_add_permission(self, request):
        return False

    @admin.action(description="Verify received payment and approve selected exports")
    def approve_payment(self, request, queryset):
        queryset.filter(status="pending").update(status="approved", reviewed_by=request.user)

    @admin.action(description="Reject selected pending export requests")
    def reject_payment(self, request, queryset):
        queryset.filter(status="pending").update(status="rejected", reviewed_by=request.user)

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("title", "artist", "category", "updated_at")
    readonly_fields = ("artist", "title", "category", "description", "updated_at")
    exclude = ("mix",)

    def has_add_permission(self, request):
        return False


@admin.register(ExportAllowance)
class ExportAllowanceAdmin(admin.ModelAdmin):
    list_display = ("artist", "unlimited_exports", "free_limit", "free_used", "free_remaining")
    search_fields = ("artist__username",)
    readonly_fields = ("artist", "free_remaining")
    actions = ("reset_usage",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Reset selected artists' free export usage to zero", permissions=["change"])
    def reset_usage(self, request, queryset):
        from django.db import transaction
        count = 0
        with transaction.atomic():
            for allowance in queryset.select_for_update():
                previous = allowance.free_used
                allowance.free_used = 0
                allowance.save(update_fields=["free_used"])
                self.log_change(request, allowance, f"Reset free export usage from {previous} to 0; limit unchanged.")
                count += 1
        self.message_user(request, f"Reset usage for {count} artist(s). Export history was preserved.")


from .models import VideoCollaboration

@admin.register(VideoCollaboration)
class VideoCollaborationAdmin(admin.ModelAdmin):
    list_display = ("id", "creator", "source_title", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("creator__username", "source_title")
    readonly_fields = ("id", "creator", "source", "content", "source_title", "credits", "role", "status", "created_at")
    exclude = ("video",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
