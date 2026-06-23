import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone


class LiveStream(models.Model):
    STATUS_SCHEDULED = "scheduled"
    STATUS_LIVE = "live"
    STATUS_ENDED = "ended"
    STATUS_CHOICES = [
        (STATUS_SCHEDULED, "Scheduled"),
        (STATUS_LIVE, "Live"),
        (STATUS_ENDED, "Ended"),
    ]

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    host = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="hosted_livestreams",
    )
    stream_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_SCHEDULED)
    is_restricted = models.BooleanField(default=False)
    allow_free_access = models.BooleanField(default=False)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_live(self):
        return self.status == self.STATUS_LIVE

    def start(self):
        self.status = self.STATUS_LIVE
        self.started_at = self.started_at or timezone.now()
        self.ended_at = None
        self.save(update_fields=["status", "started_at", "ended_at"])

    def end(self):
        self.status = self.STATUS_ENDED
        self.ended_at = timezone.now()
        self.save(update_fields=["status", "ended_at"])

    def can_join(self, user):
        if not user.is_authenticated:
            return False
        if user == self.host or user.is_admin():
            return True
        if not self.is_live:
            return False
        if not self.is_restricted:
            return True
        return (
            self.allow_free_access
            or user.has_free_pass
            or self.access_grants.filter(user=user, is_active=True).exists()
        )


class LiveStreamAccess(models.Model):
    stream = models.ForeignKey(LiveStream, on_delete=models.CASCADE, related_name="access_grants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="livestream_access_grants",
    )
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_livestream_access",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("stream", "user")
        ordering = ["-created_at"]

    def __str__(self):
        status = "active" if self.is_active else "revoked"
        return f"{self.user.username} access to {self.stream.title} ({status})"
