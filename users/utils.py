from .models import Notification

def send_notification(user, message):
    """
    Creates a new notification for the given user.
    """
    Notification.objects.create(user=user, message=message)
