from django.contrib.auth.models import AbstractUser
from django.db import models
from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.utils.timezone import now

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

    # Additional profile information
    profile_picture = models.ImageField(upload_to='profile_pictures/', null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    subscription_expiry = models.DateField(null=True, blank=True)

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



