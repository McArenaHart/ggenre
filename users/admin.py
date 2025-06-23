# users/admin.py
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import CustomUser, Announcement, TermsAndConditions
from django.shortcuts import render
from django.contrib.auth.decorators import login_required, permission_required


class CustomUserAdmin(UserAdmin):
    model = CustomUser
    list_display = ('username', 'email', 'phone_number', 'role', 'is_active', 'is_staff', 'subscription_expiry')
    search_fields = ('username', 'email', 'role')
    ordering = ('-date_joined',)
    
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'profile_picture', 'bio')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Role-specific Info', {'fields': ('role', 'subscription_expiry')}),
    )
    
    add_fieldsets = (
        (None, {'fields': ('username', 'password1', 'password2')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'email', 'profile_picture', 'bio')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Role-specific Info', {'fields': ('role', 'subscription_expiry')}),
    )
    
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
