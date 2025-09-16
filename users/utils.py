
from django.contrib.auth import get_user_model
from .models import Notification, Follow

def send_notification(user, message):
    """
    Creates a new notification for the given user.
    """
    Notification.objects.create(user=user, message=message)



User = get_user_model()

User = get_user_model()

def send_notification_to_followers(artist, message):
    """
    Send notifications to all followers of an artist who have consented
    """
    try:
        # Get all followers through the Follow model
        follower_relationships = Follow.objects.filter(following=artist)
        
        notifications = []
        for relationship in follower_relationships:
            follower = relationship.follower
            # Check if user has notification consent
            if (follower.receive_notifications and 
                follower.notify_on_new_content):
                notification = Notification(
                    user=follower,
                    message=message
                )
                notifications.append(notification)
        
        # Bulk create notifications for efficiency
        if notifications:
            Notification.objects.bulk_create(notifications)
        
        return True
    except Exception as e:
        print(f"Error sending notifications: {e}")
        return False