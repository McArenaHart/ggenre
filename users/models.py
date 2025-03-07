from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError



class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=now)

    def __str__(self):
        return f"Notification for {self.user.username}: {self.message}"


# Define roles
class Role:
    ADMIN = 'admin'
    ARTIST = 'artist'
    FAN = 'fan'
    CHOICES = [(ADMIN, 'Admin'), (ARTIST, 'Artist'), (FAN, 'Fan')]

class CustomUser(AbstractUser):
    # Role definition: Each user can have one of the roles - Admin, Artist, or Fan
    role = models.CharField(max_length=10, choices=Role.CHOICES, default=Role.FAN)
    phone_number = models.CharField(max_length=15, unique=True, null=True, blank=True)

    # Additional profile information
    profile_picture = models.ImageField(upload_to='profile_pictures/', null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    subscription_expiry = models.DateField(null=True, blank=True)
    wants_to_participate = models.BooleanField(default=False)

    def notify_admin(self):
        """
        Notify admin when an artist wants to participate.
        """
        if self.is_artist():
            Notification.objects.create(
                user=CustomUser.objects.filter(role=Role.ADMIN).first(),
                message=f"Artist {self.username} wants to participate."
            )


    # Check if the user has a specific role
    def has_role(self, role):
        return self.role == role

    # Specific checks for the artist role
    def is_artist(self):
        return self.role == Role.ARTIST

    def is_admin(self):
        return self.role == Role.ADMIN

    def is_fan(self):
        return self.role == Role.FAN

    # Method to get the profile picture URL
    def get_profile_picture(self):
        if self.profile_picture:
            return self.profile_picture.url
        else:
            return "/static/defaults/profile.png"  # Ensure this path exists

    def __str__(self):
        return self.username


class Follow(models.Model):
    follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='following')
    following = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='followers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('follower', 'following')

    def __str__(self):
        return f"{self.follower.username} follows {self.following.username}"
    


class OTP(models.Model):
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE)
    otp_code = models.CharField(max_length=6)
    remaining_votes = models.IntegerField(default=0)  # ✅ Allow multiple uses
    created_at = models.DateTimeField(auto_now_add=True)


    def use_vote(self):
        """
        Deduct a vote if available.
        """
        if self.remaining_votes > 0:
            self.remaining_votes -= 1
            self.save()
            return True
        return False

    def is_expired(self):
        return now() > self.created_at + timedelta(minutes=5)  # OTP expires in 5 minutes
    
    def clean(self):
        if self.remaining_votes < 0:
            raise ValidationError("Remaining votes cannot be negative")
            
    def __str__(self):
        return f"OTP for {self.user.username} ({self.remaining_votes} votes left)"


class Announcement(models.Model):
    title = models.CharField(max_length=255)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    expires_at = models.DateTimeField(null=True, blank=True)  # Add expiry field

    def is_active(self):
        return self.expires_at is None or self.expires_at > timezone.now()

    def __str__(self):
        return self.title

class DismissedAnnouncement(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE)

    def __str__(self):
        return f"{self.user.username} dismissed {self.announcement.title}"

