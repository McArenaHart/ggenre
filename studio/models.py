import uuid
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
from .storage import private_storage


def audio_path(instance, filename):
    return f"audio/{uuid.uuid4().hex}.wav"

class Project(models.Model):
    TYPES = [("gospel", "Gospel"), ("acapella", "Acapella"), ("secular", "Secular / R&B / Hip Hop")]
    artist = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=16, choices=TYPES)
    description = models.TextField(blank=True)
    tempo = models.PositiveSmallIntegerField(default=80, validators=[MinValueValidator(40), MaxValueValidator(240)])
    mix = models.FileField(storage=private_storage, upload_to=audio_path, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def workflow_label(self):
        from .catalog import profile_for
        return profile_for(self.category)["label"]

    def __str__(self):
        return self.title

class ActiveTrackManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class Track(models.Model):
    project = models.ForeignKey(Project, related_name="tracks", on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=12, choices=[("vocal", "Vocal"), ("backing", "Imported backing"), ("beat", "Studio rhythm preset")], default="vocal")
    beat_preset = models.CharField(max_length=48, blank=True)
    beat_bpm = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MinValueValidator(40), MaxValueValidator(240)])
    audio = models.FileField(storage=private_storage, upload_to=audio_path)
    gain = models.FloatField(default=1)
    offset = models.FloatField(default=0)
    trim_start = models.FloatField(default=0)
    trim_end = models.FloatField(default=0)
    muted = models.BooleanField(default=False)
    deleted_at = models.DateTimeField(null=True, blank=True)
    upload_key = models.CharField(max_length=64, null=True, blank=True)
    objects = ActiveTrackManager()
    all_objects = models.Manager()

    class Meta:
        base_manager_name = 'all_objects'
        constraints = [models.UniqueConstraint(fields=['project', 'upload_key'], name='studio_upload_once')]

class AudioJob(models.Model):
    track = models.ForeignKey(Track, on_delete=models.CASCADE, related_name="audio_jobs")
    operation = models.CharField(max_length=16)
    options = models.JSONField(default=dict)
    status = models.CharField(max_length=12, default="queued")
    source = models.FileField(storage=private_storage, upload_to=audio_path)
    result = models.FileField(storage=private_storage, upload_to=audio_path, blank=True)
    error = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    lease_token = models.CharField(max_length=32, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['status', 'id'], name='studio_job_queue_idx'), models.Index(fields=['status', 'lease_until'], name='studio_job_lease_idx')]


class StudioMaintenance(models.Model):
    key = models.CharField(max_length=48, primary_key=True)
    next_run_at = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(default=timezone.now)
    lease_token = models.CharField(max_length=32, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)


class AudioJobInput(models.Model):
    job = models.ForeignKey(AudioJob, on_delete=models.CASCADE, related_name='inputs')
    audio = models.FileField(storage=private_storage, upload_to=audio_path)
    settings = models.JSONField(default=dict)


class StudioStorageAccount(models.Model):
    artist = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)


class StudioAsset(models.Model):
    artist = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=255, unique=True)
    size = models.PositiveBigIntegerField()


class ExportAllowance(models.Model):
    artist = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    free_used = models.PositiveIntegerField(default=0, help_text="Free exports consumed since the last reset; repeat downloads do not count.")
    free_limit = models.PositiveIntegerField(default=2, help_text="Free exports allowed before payment approval is required. Zero requires approval immediately.")

    unlimited_exports = models.BooleanField(default=False, help_text="Suspend free export limits and payment approval for new exports. Existing usage is retained.")

    @property
    def free_remaining(self):
        return max(0, self.free_limit - self.free_used)

    def __str__(self):
        return f"{self.artist} — unlimited exports" if self.unlimited_exports else f"{self.artist} — {self.free_remaining} free exports remaining"

class Export(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, null=True, blank=True)
    instrumental = models.ForeignKey('Instrumental', on_delete=models.CASCADE, null=True, blank=True)
    audio = models.FileField(storage=private_storage, upload_to=audio_path)
    status = models.CharField(max_length=12, choices=[("free", "Free"), ("pending", "Awaiting payment approval"), ("approved", "Payment verified"), ("rejected", "Rejected")])
    payment_reference = models.CharField(max_length=160, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="studio_export_reviews")

    class Meta:
        constraints = [models.CheckConstraint(condition=(models.Q(project__isnull=False, instrumental__isnull=True) | models.Q(project__isnull=True, instrumental__isnull=False)), name='studio_export_one_source')]

    @property
    def artist(self):
        return self.project.artist if self.project_id else self.instrumental.artist

    @property
    def title(self):
        return self.project.title if self.project_id else self.instrumental.title

class Release(models.Model):
    project = models.ForeignKey(Project, on_delete=models.SET_NULL, null=True)
    content = models.OneToOneField("content.Content", related_name="studio_release", on_delete=models.CASCADE)
    audio = models.FileField(storage=private_storage, upload_to=audio_path)


class Instrumental(models.Model):
    artist = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=160)
    category = models.CharField(max_length=16, choices=[("gospel", "Gospel"), ("secular", "Circular / Secular")])
    config = models.JSONField(default=dict)
    audio = models.FileField(storage=private_storage, upload_to=audio_path, blank=True)
    source_audio = models.FileField(storage=private_storage, upload_to=audio_path, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class VideoCollaboration(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    creator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    source = models.ForeignKey("content.Content", null=True, on_delete=models.SET_NULL, related_name="vocal_collaborations")
    content = models.OneToOneField("content.Content", null=True, blank=True, on_delete=models.SET_NULL, related_name="video_collaboration")
    source_title = models.CharField(max_length=255)
    credits = models.JSONField(default=list)
    role = models.CharField(max_length=32, default="Harmony")
    status = models.CharField(max_length=12, default="processing", choices=[("processing", "Processing"), ("ready", "Ready"), ("published", "Published"), ("failed", "Failed")])
    video = models.FileField(storage=private_storage, upload_to="collaborations/")
    created_at = models.DateTimeField(auto_now_add=True)
