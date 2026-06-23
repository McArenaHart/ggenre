# users/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Announcement, Role, TermsAndConditions, VotingTokenPolicy
from django.shortcuts import render
from django.contrib.auth.decorators import login_required, permission_required


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = (
        'username',
        'email',
        'role',
        'is_active',
        'is_staff',
        'has_free_pass',
        'is_suspended_by_admin',
        'subscription_expiry',
        'can_download_content',
    )
    list_editable = ('has_free_pass', 'is_suspended_by_admin', 'can_download_content')
    list_filter = ('role', 'is_active', 'is_staff', 'has_free_pass', 'is_suspended_by_admin')
    search_fields = ('username', 'email', 'role')
    ordering = ('-date_joined',)
    actions = (
        'grant_free_pass',
        'revoke_free_pass',
        'suspend_users',
        'reinstate_users',
    )
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'profile_picture', 'bio')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions', 'can_download_content')}),
        ('Admin Access Controls', {'fields': ('has_free_pass', 'is_suspended_by_admin')}),
        ('Role-specific Info', {'fields': ('role', 'subscription_expiry')}),
    )
    
    add_fieldsets = (
        (None, {'fields': ('username', 'password1', 'password2')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'profile_picture', 'bio')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions', 'can_download_content')}),
        ('Admin Access Controls', {'fields': ('has_free_pass', 'is_suspended_by_admin')}),
        ('Role-specific Info', {'fields': ('role', 'subscription_expiry')}),
    )

    @admin.action(description="Grant free pass to selected users")
    def grant_free_pass(self, request, queryset):
        updated = queryset.exclude(role=Role.ADMIN).update(has_free_pass=True)
        self.message_user(request, f"Granted free pass to {updated} user(s).")

    @admin.action(description="Revoke free pass from selected users")
    def revoke_free_pass(self, request, queryset):
        updated = queryset.exclude(role=Role.ADMIN).update(has_free_pass=False)
        self.message_user(request, f"Revoked free pass from {updated} user(s).")

    @admin.action(description="Suspend selected users")
    def suspend_users(self, request, queryset):
        updated = queryset.exclude(role=Role.ADMIN).update(is_suspended_by_admin=True)
        self.message_user(request, f"Suspended {updated} user(s).")

    @admin.action(description="Reinstate selected users")
    def reinstate_users(self, request, queryset):
        updated = queryset.exclude(role=Role.ADMIN).update(is_suspended_by_admin=False)
        self.message_user(request, f"Reinstated {updated} user(s).")
    
# Register your custom user model in the admin
admin.site.register(CustomUser, CustomUserAdmin)


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_by', 'created_at')


@admin.register(TermsAndConditions)
class TermsAndConditionsAdmin(admin.ModelAdmin):
    list_display = ('version', 'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active',)
    search_fields = ('content', 'version')
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(created_by=request.user)
    
    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser or request.user.is_admin():
            return True
        return False
    
    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser or request.user.is_admin():
            return True
        return False
    
    def save_model(self, request, obj, form, change):
        if obj.is_active:
            # Deactivate all other versions
            TermsAndConditions.objects.exclude(pk=obj.pk).update(is_active=False)
        
        if not obj.pk:  # If creating a new record
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(VotingTokenPolicy)
class VotingTokenPolicyAdmin(admin.ModelAdmin):
    list_display = ('id', 'voting_suspended', 'tokens_paused', 'updated_by', 'updated_at')
    list_editable = ('voting_suspended', 'tokens_paused')
    readonly_fields = ('updated_at',)

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
