from django.db import models
from django.conf import settings
import uuid
from django.utils.timezone import now
from django.db.models import Avg, Sum
from taggit.managers import TaggableManager  # For tagging support
from PIL import Image
from datetime import timedelta
from io import BytesIO
from django.core.files.base import ContentFile

def resize_and_crop_thumbnail(image, target_size=(1280, 720)):
    """
    Resize and crop an image to a standard aspect ratio (e.g., 16:9).
    """
    img = Image.open(image)
    width, height = img.size

    # Calculate the target aspect ratio
    target_width, target_height = target_size
    target_ratio = target_width / target_height

    # Crop the image to match the target aspect ratio
    if width / height > target_ratio:
        # Image is wider than the target aspect ratio
        new_width = int(height * target_ratio)
        left = (width - new_width) / 2
        right = left + new_width
        img = img.crop((left, 0, right, height))
    else:
        # Image is taller than the target aspect ratio
        new_height = int(width / target_ratio)
        top = (height - new_height) / 2
        bottom = top + new_height
        img = img.crop((0, top, width, bottom))

    # Resize the image to the target size
    img = img.resize(target_size, Image.ANTIALIAS)

    # Save the image to a BytesIO object
    output = BytesIO()
    img.save(output, format='JPEG', quality=90)
    output.seek(0)

    return ContentFile(output.read(), image.name)

# Usage in your model's save method
def save(self, *args, **kwargs):
    if self.thumbnail:
        self.thumbnail = resize_and_crop_thumbnail(self.thumbnail)
    super().save(*args, **kwargs)


class Genre(models.Model):
    name = models.CharField(max_length=255, unique=True)

class Content(models.Model):
    """
    Model for artist-uploaded content.
    Tracks metadata, approval status, views, and the associated artist.
    """
    CATEGORY_CHOICES = [
        ('music', 'Music'),
        ('video', 'Video'),
        ('art', 'Art'),
        ('fashion', 'Fashion'),
        ('other', 'Other'),
    ]

    title = models.CharField(max_length=255)
    genre = models.ForeignKey(Genre, on_delete=models.CASCADE, related_name="contents", null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    file = models.FileField(upload_to='content/')
    thumbnail = models.ImageField(upload_to='thumbnails/', blank=True, null=True)  # New field
    upload_date = models.DateTimeField(auto_now_add=True)
    artist = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='content'
    )
    is_approved_for_voting = models.BooleanField(default=False)  # New field for voting approval
    is_approved = models.BooleanField(default=False)  # Approval status for admin
    views = models.PositiveIntegerField(default=0)  # Tracks view count
    tags = TaggableManager()  # Tags for content (e.g., music, dance, drama)

    def __str__(self):
        return self.title

    def calculate_popularity(self):
        total_votes = self.votes.aggregate(total=Sum('value'))['total'] or 0
        return self.views + total_votes

    def get_average_vote(self):
        """
        Returns the average vote for the content.
        """
        return self.votes.aggregate(average=Avg('value'))['average'] or 0



class ParticipationRequest(models.Model):
    artist = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    content = models.ForeignKey('Content', on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=[('pending', 'Pending'), ('approved', 'Approved')], default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.artist.username} requested to participate with {self.content.title}"



class Vote(models.Model):
    content = models.ForeignKey(Content, on_delete=models.CASCADE, related_name='votes')
    fan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_votes')
    base_value = models.IntegerField()  # Original vote (1-8)
    value = models.IntegerField()  # base_value * multiplier
    timestamp = models.DateTimeField(auto_now_add=True)
    otp_code = models.CharField(max_length=6)
    tag = models.CharField(max_length=255, blank=True, null=True)
    is_badge_vote = models.BooleanField(default=False)  # New field to track badge votes

    class Meta:
        unique_together = ('content', 'fan')


    def __str__(self):
        return f"{self.fan.username} - {self.base_value} for {self.content.title}"






class Badge(models.Model):
    """
    Represents user badges that increase vote power.
    """
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="badge")
    level = models.IntegerField(default=1)  # Badge levels increase vote weight

    def vote_multiplier(self):
        """
        Returns a multiplier based on badge level.
        Example: Level 1 = x10, Level 2 = x20, etc.
        """
        return 10 * self.level  # Example: Level 1 = x10, Level 2 = x20

    def __str__(self):
        return f"Badge for {self.user.username} (Level {self.level}, x{self.vote_multiplier()})"




class Comment(models.Model):
    """
    Model for comments on content by fans.
    """
    content = models.ForeignKey(Content, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='comments')
    text = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} on {self.content.title}"
    




class LivePerformance(models.Model):
    """
    Model for live performances hosted by artists.
    """

    is_restricted = models.BooleanField(default=False)  # 🔒 Restriction toggle

    title = models.CharField(max_length=255)
    artist = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='live_performances'
    )
    start_time = models.DateTimeField()
    end_time = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    stream_key = models.CharField(
        max_length=255,
        unique=True,
        default=uuid.uuid4  # Generate a unique stream key
    )
    use_camera = models.BooleanField(default=True)  # Toggle for live camera

    def __str__(self):
        return self.title
    


class ArtistUploadLimit(models.Model): 
    artist = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='content_upload_limit'  # Unique related name
    )
    uploads_used = models.PositiveIntegerField(default=0)
    upload_limit = models.PositiveIntegerField(default=20)
    reset_on_payment = models.BooleanField(default=False)
    suspended_by_admin = models.BooleanField(default=False)

    def has_upload_quota(self):
        """
        Check if the user has upload quota, considering admin suspension.
        Artists who are suspended by an admin cannot upload.
        """
        if self.suspended_by_admin:
            return False  # Suspended artists cannot upload
        return self.upload_limit > self.uploads_used  # Check remaining quota

    def reset_limit(self):
        self.uploads_used = 0
        self.save(update_fields=['uploads_used'])

    def __str__(self):
        """
        Return a human-readable representation of the upload limit for an artist.
        Includes the artist's username and the number of uploads they've used.
        """
        return f"{self.artist.username} - {self.uploads_used} uploads used"


class Voucher(models.Model):
    """
    Voucher model to control access to restricted live streams.
    """
    code = models.CharField(max_length=16, unique=True)
    performance = models.ForeignKey(LivePerformance, on_delete=models.CASCADE, related_name='vouchers')
    is_used = models.BooleanField(default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='created_vouchers'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='used_vouchers'
    )
    used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Voucher {self.code} for {self.performance.title}"
