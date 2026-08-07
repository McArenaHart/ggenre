from django.urls import re_path

from .consumers import DirectChatConsumer, UserEventConsumer

websocket_urlpatterns = [
    re_path(r"ws/chat/user/(?P<user_id>\d+)/$", DirectChatConsumer.as_asgi()),
    re_path(r"ws/events/$", UserEventConsumer.as_asgi()),
]
