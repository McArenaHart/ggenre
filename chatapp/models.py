from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone


class MissionTemplate(models.Model):
    title = models.CharField(max_length=120)
    instruction_text = models.TextField()
    opponent_instruction_text = models.TextField(blank=True, default="")
    category = models.CharField(max_length=50, blank=True, default="")
    difficulty = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class MissionSession(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        MATCHING = "matching", "Matching"
        OPPONENT_PROPOSED = "opponent_proposed", "Opponent Proposed"
        MISSION_PROPOSED = "mission_proposed", "Mission Proposed"
        MISSION_ACTIVE = "mission_active", "Mission Active"
        PROOF_SUBMITTED = "proof_submitted", "Proof Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        COOLDOWN_VOTE_REQUIRED = "cooldown_vote_required", "Cooldown Vote Required"
        CLOSED = "closed", "Closed"

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="requested_mission_sessions",
    )
    opponent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="opponent_mission_sessions",
        null=True,
        blank=True,
    )
    mission_template = models.ForeignKey(
        "MissionTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sessions",
    )
    opponent_mission_template = models.ForeignKey(
        "MissionTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opponent_sessions",
    )
    status = models.CharField(
        max_length=32,
        choices=Status.choices,
        default=Status.REQUESTED,
    )
    reroll_count = models.PositiveSmallIntegerField(default=0)
    max_rerolls = models.PositiveSmallIntegerField(default=3)
    loser_vote_required = models.BooleanField(default=True)
    timer_seconds = models.PositiveIntegerField(null=True, blank=True)
    assigned_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="claimed_mission_sessions",
        null=True,
        blank=True,
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="won_mission_sessions",
        null=True,
        blank=True,
    )
    loser = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="lost_mission_sessions",
        null=True,
        blank=True,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                check=~Q(requester=F("opponent")),
                name="missionsession_requester_not_opponent",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["requester", "status"]),
            models.Index(fields=["opponent", "status"]),
        ]

    def __str__(self):
        return f"Mission #{self.pk} - {self.requester} ({self.status})"


class MissionQueueEntry(models.Model):
    class QueueStatus(models.TextChoices):
        WAITING = "waiting", "Waiting"
        MATCHED = "matched", "Matched"
        PAUSED = "paused", "Paused"
        CLOSED = "closed", "Closed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mission_queue_entries",
    )
    status = models.CharField(
        max_length=20,
        choices=QueueStatus.choices,
        default=QueueStatus.WAITING,
    )
    reason = models.CharField(max_length=255, blank=True, default="")
    mission_session = models.ForeignKey(
        "MissionSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="queue_entries",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["user", "status"]),
        ]

    def __str__(self):
        return f"Queue {self.user} ({self.status})"


class MissionEvidence(models.Model):
    class ReviewStatus(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    mission_session = models.ForeignKey(
        "MissionSession",
        on_delete=models.CASCADE,
        related_name="evidence_items",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mission_evidence_submissions",
    )
    screenshot = models.ImageField(upload_to="mission_evidence/", null=True, blank=True)
    explanation = models.TextField(blank=True, default="")
    chat_transcript = models.TextField(blank=True, default="")
    ai_confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    review_status = models.CharField(
        max_length=20,
        choices=ReviewStatus.choices,
        default=ReviewStatus.SUBMITTED,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_mission_evidence",
    )
    review_notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["review_status", "created_at"]),
            models.Index(fields=["mission_session", "review_status"]),
        ]

    def __str__(self):
        return f"Evidence #{self.pk} for mission #{self.mission_session_id}"


class TokenPurchaseRequest(models.Model):
    class Status(models.TextChoices):
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="token_purchase_requests",
    )
    requested_tokens = models.PositiveIntegerField()
    payment_channel = models.CharField(max_length=40, blank=True, default="")
    payment_reference = models.CharField(max_length=120, blank=True, default="")
    receipt_file = models.FileField(upload_to="token_payment_receipts/", null=True, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    assigned_admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_token_purchase_requests",
    )
    approved_tokens = models.PositiveIntegerField(default=0)
    review_notes = models.TextField(blank=True, default="")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["requester", "status"]),
            models.Index(fields=["assigned_admin", "status"]),
        ]

    def __str__(self):
        return f"Token request #{self.pk} by {self.requester} ({self.status})"


class AdminDecisionLog(models.Model):
    class ActorType(models.TextChoices):
        AI = "ai", "AI"
        MANUAL = "manual", "Manual"

    actor_type = models.CharField(max_length=10, choices=ActorType.choices)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="admin_decision_logs",
    )
    mission_session = models.ForeignKey(
        "MissionSession",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="decision_logs",
    )
    token_purchase_request = models.ForeignKey(
        "TokenPurchaseRequest",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="decision_logs",
    )
    action = models.CharField(max_length=64)
    rationale = models.TextField(blank=True, default="")
    confidence = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["actor_type", "created_at"]),
            models.Index(fields=["mission_session", "created_at"]),
            models.Index(fields=["token_purchase_request", "created_at"]),
        ]

    def __str__(self):
        target = self.mission_session_id or self.token_purchase_request_id
        return f"Decision {self.actor_type}:{self.action} on {target}"


class ReviewAutomationTicket(models.Model):
    class TicketStatus(models.TextChoices):
        QUEUED = "queued", "Queued"
        PROCESSING = "processing", "Processing"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    mission_session = models.ForeignKey(
        "MissionSession",
        on_delete=models.CASCADE,
        related_name="automation_tickets",
    )
    mission_evidence = models.ForeignKey(
        "MissionEvidence",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="automation_tickets",
    )
    route_actor_type = models.CharField(
        max_length=10,
        choices=AdminDecisionLog.ActorType.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=TicketStatus.choices,
        default=TicketStatus.QUEUED,
    )
    policy_snapshot = models.JSONField(default=dict, blank=True)
    input_payload = models.JSONField(default=dict, blank=True)
    output_payload = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["mission_session", "created_at"]),
            models.Index(fields=["route_actor_type", "created_at"]),
        ]

    def __str__(self):
        return f"Automation ticket #{self.pk} ({self.status}) for mission #{self.mission_session_id}"


class MissionReviewControl(models.Model):
    class RouteMode(models.TextChoices):
        ALTERNATE = "alternate", "Alternate"
        MANUAL_ONLY = "manual_only", "Manual Only"
        AI_PREFERRED = "ai_preferred", "AI Preferred"

    route_mode = models.CharField(
        max_length=20,
        choices=RouteMode.choices,
        default=RouteMode.ALTERNATE,
    )
    reason = models.CharField(max_length=255, blank=True, default="")
    mission_timer_seconds = models.PositiveIntegerField(default=120)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(fields=["route_mode", "updated_at"]),
        ]

    def __str__(self):
        return f"Mission review mode: {self.route_mode}; timer {self.mission_timer_seconds}s"


class MissionWinFeed(models.Model):
    mission_session = models.OneToOneField(
        "MissionSession",
        on_delete=models.CASCADE,
        related_name="win_feed_entry",
    )
    winner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="mission_win_feed_entries",
    )
    approved_evidence = models.ForeignKey(
        "MissionEvidence",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_win_entries",
    )
    homepage_visible = models.BooleanField(default=True)
    published_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-published_at"]
        indexes = [
            models.Index(fields=["homepage_visible", "published_at"]),
            models.Index(fields=["winner", "published_at"]),
        ]

    def __str__(self):
        return f"Win feed #{self.pk} - {self.winner}"

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
    media_file = models.FileField(upload_to="direct_chat_media/", null=True, blank=True)
    media_type = models.CharField(max_length=20, blank=True, default="")
    media_name = models.CharField(max_length=160, blank=True, default="")
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
