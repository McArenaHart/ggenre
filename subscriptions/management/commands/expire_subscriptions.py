from django.core.management.base import BaseCommand
from subscriptions.models import UserSubscription
from django.utils.timezone import now

class Command(BaseCommand):
    help = "Deactivate expired subscriptions"

    def handle(self, *args, **kwargs):
        expired_subscriptions = UserSubscription.objects.filter(end_date__lt=now(), is_active=True)
        for subscription in expired_subscriptions:
            subscription.deactivate_subscription()
            self.stdout.write(f"Deactivated subscription for {subscription.user.username}")
