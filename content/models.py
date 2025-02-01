from django.db import models
from django.conf import settings
import uuid
from django.db.models import Avg
from taggit.managers import TaggableManager  # For tagging support
from PIL import Image
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


class Content(models.Model):
    """
    Model for artist-uploaded content.
    Tracks metadata, approval status, views, and the associated artist.
    """
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    file = models.FileField(upload_to='content/')
    thumbnail = models.ImageField(upload_to='thumbnails/', blank=True, null=True)  # New field
    upload_date = models.DateTimeField(auto_now_add=True)
    artist = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='content'
    )
    is_approved = models.BooleanField(default=False)  # Approval status for admin
    views = models.PositiveIntegerField(default=0)  # Tracks view count
    tags = TaggableManager()  # Tags for content (e.g., music, dance, drama)

    def __str__(self):
        return self.title

    def calculate_popularity(self):
        """
        Calculates content popularity based on views and votes.
        Popularity can be customized as a weighted score.
        """
        avg_vote = self.votes.aggregate(average=Avg('value'))['average'] or 0
        return self.views + avg_vote * 10  # Example: 1 vote counts as 10 views

    def get_average_vote(self):
        """
        Returns the average vote for the content.
        """
        return self.votes.aggregate(average=Avg('value'))['average'] or 0


class Vote(models.Model):
    """
    Model for fan votes on content.
    """
    content = models.ForeignKey(Content, on_delete=models.CASCADE, related_name='votes')
    fan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_votes')
    value = models.IntegerField()  # e.g., 1-5 ranking
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('content', 'fan')  # Prevent duplicate votes by the same fan

    def __str__(self):
        return f"{self.fan.username} - {self.value} for {self.content.title}"


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
    upload_limit = models.PositiveIntegerField(default=10)
    reset_on_payment = models.BooleanField(default=False)
    suspended_by_admin = models.BooleanField(default=False)

    def has_upload_quota(self):
        """Check if the user has upload quota, considering admin suspension."""
        if self.suspended_by_admin:
            return False  # Suspended artists cannot upload
        return self.upload_limit > self.uploads_used  # Check remaining quota

    def reset_limit(self):
        """Reset the upload limit manually."""
        self.uploads_used = 0
        self.reset_on_payment = False
        self.save()

    def __str__(self):
        return f"{self.artist.username} - {self.uploads_used} uploads used"

    
class ArtistSubscription(models.Model):
    fan = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='artist_subscriptions')  # Updated related_name
    artist = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='subscribed_artists')  # Updated related_name
    subscribed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.fan.username} subscribed to {self.artist.username}"


