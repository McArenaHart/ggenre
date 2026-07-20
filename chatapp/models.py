from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

class DirectChatMessage(models.Model):
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_direct_chat_messages",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_direct_chat_messages",
    )
    client_id = models.CharField(max_length=120, blank=True, default="")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["sender", "recipient", "created_at"]),
            models.Index(fields=["recipient", "read_at"]),
            models.Index(fields=["client_id"]),
        ]

    def __str__(self):
        return f"{self.sender} -> {self.recipient}: {self.body[:30]}"


class AdminChatThread(models.Model):
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_chat_threads",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="admin_contact_threads",
    )
    unread_count = models.PositiveIntegerField(default=0)
    user_unread_count = models.PositiveIntegerField(default=0)
    last_contact_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("admin", "user")
        ordering = ["-last_contact_at"]

    def __str__(self):
        return f"{self.user} -> {self.admin} ({self.unread_count} unread)"


class PeerChatThread(models.Model):
    user_one = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="peer_chat_threads_as_user_one",
    )
    user_two = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="peer_chat_threads_as_user_two",
    )
    unread_count_user_one = models.PositiveIntegerField(default=0)
    unread_count_user_two = models.PositiveIntegerField(default=0)
    admin_approved = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_peer_chat_threads",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    unlocked_until = models.DateTimeField(null=True, blank=True)
    last_contact_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("user_one", "user_two")
        ordering = ["-last_contact_at"]

    @classmethod
    def ordered_users(cls, first_user, second_user):
        if first_user.pk < second_user.pk:
            return first_user, second_user
        return second_user, first_user

    @classmethod
    def get_or_create_for_users(cls, first_user, second_user):
        user_one, user_two = cls.ordered_users(first_user, second_user)
        return cls.objects.get_or_create(user_one=user_one, user_two=user_two)

    def other_user(self, user):
        return self.user_two if self.user_one_id == user.id else self.user_one

    def unread_count_for(self, user):
        if self.user_one_id == user.id:
            return self.unread_count_user_one
        return self.unread_count_user_two

    def __str__(self):
        return f"{self.user_one} <-> {self.user_two}"


class MatchRating(models.Model):
    rater = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="given_match_ratings",
    )
    rated = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_match_ratings",
    )
    score = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    source_content = models.ForeignKey(
        "content.Content",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="match_ratings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("rater", "rated")
        constraints = [
            models.CheckConstraint(
                check=~Q(rater=F("rated")),
                name="matchrating_no_self_rating",
            )
        ]

    def __str__(self):
        return f"{self.rater} rated {self.rated} {self.score}/10"
