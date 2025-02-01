from django.conf import settings
from django.db import models
from django.utils.timezone import now
from datetime import timedelta
from django.core.mail import send_mail
from django.db.models.signals import post_save
from django.dispatch import receiver

class Payment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateTimeField(auto_now_add=True)
    transaction_id = models.CharField(max_length=100, unique=True)
    payment_method = models.CharField(
        max_length=50, 
        choices=[('cash', 'Cash'), ('bank_transfer', 'Bank Transfer')], 
        default='cash'
    )
    payment_status = models.CharField(
        max_length=20, 
        choices=[('pending', 'Pending'), ('completed', 'Completed'), ('rejected', 'Rejected')], 
        default='pending'
    )
    note = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Payment of {self.amount} by {self.user} ({self.payment_status})"


class UserSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_subscriptions')  # Updated related_name
    subscription_type = models.CharField(max_length=100, null=True, blank=True)  # Null for free tier
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=False)
    upload_limit = models.IntegerField(default=0)  # Subscription-based upload limit
    vote_limit = models.IntegerField(default=0)  # Subscription-based vote limit
    free_uploads_used = models.IntegerField(default=0)  # Free tier uploads
    free_votes_used = models.IntegerField(default=0)  # Free tier votes
    suspended_by_admin = models.BooleanField(default=False)  # Admin override for limits
    payment = models.OneToOneField(Payment, on_delete=models.CASCADE, related_name='user_subscription', null=True, blank=True)

    def __str__(self):
        return f"{self.user}'s Subscription ({'Active' if self.is_active else 'Inactive'})"


    def activate_subscription(self):
        self.is_active = True
        self.save()
        send_mail(
            subject="Subscription Activated",
            message="Your subscription has been activated successfully!",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[self.user.email],
        )

    def deactivate_subscription(self):
        self.is_active = False
        self.upload_limit = 0
        self.vote_limit = 0
        self.save()
        send_mail(
            subject="Subscription Expired",
            message="Your subscription has expired. Renew to continue using premium features.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[self.user.email],
        )
    
    def has_upload_quota(self):
        """Check if the user has upload quota, considering admin suspension."""
        return self.suspended_by_admin or (self.is_active and self.upload_limit > self.free_uploads_used)

    def has_vote_quota(self):
        """Check if the user has vote quota, considering admin suspension."""
        return self.suspended_by_admin or (self.is_active and self.vote_limit > self.free_votes_used)

    def __str__(self):
        return f"{self.user.username}'s Subscription ({'Active' if self.is_active else 'Inactive'})"

    def increment_vote_usage(self):
        if self.has_vote_quota():
            self.free_votes_used += 1
            self.save()
        else:
            raise ValueError("Vote quota exceeded.")
        
    def increment_upload_usage(self):
        if self.has_upload_quota():
            self.free_uploads_used += 1
            self.save()
        else:
            raise ValueError("Upload quota exceeded.")
        
    def check_and_deactivate(self):
        if self.end_date and self.end_date < now():
            self.deactivate_subscription()


@receiver(post_save, sender=UserSubscription)
def check_subscription_expiry(sender, instance, **kwargs):
    instance.check_and_deactivate()


# In subscriptions/models.py

@receiver(post_save, sender=Payment)
def activate_subscription_on_payment(sender, instance, **kwargs):
    if instance.payment_status == 'completed' and hasattr(instance, 'user_subscription'):
        instance.user_subscription.activate_subscription()





class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=100)  # Name of the plan (e.g., Basic, Premium, VIP)
    description = models.TextField()  # Description of the plan
    price = models.DecimalField(max_digits=10, decimal_places=2)  # Price of the plan
    duration = models.IntegerField()  # Duration in days (e.g., 30 for basic, 365 for premium)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Subscription Plan'
        verbose_name_plural = 'Subscription Plans'


class ArtistUploadLimit(models.Model):
    artist = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscription_upload_limit'  # Unique related name
    )
    uploads_used = models.PositiveIntegerField(default=0)
    upload_limit = models.PositiveIntegerField(default=10)
    reset_on_payment = models.BooleanField(default=False)
    suspended_by_admin = models.BooleanField(default=False)


    def has_quota(self):
        """Check if artist has quota, considering admin suspension."""
        return self.suspended_by_admin or self.uploads_used < self.upload_limit

    def __str__(self):
        return f"{self.artist.username} - {self.uploads_used} uploads used"


