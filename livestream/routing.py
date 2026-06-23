from django.urls import re_path

from .consumers import LiveStreamSignalConsumer

websocket_urlpatterns = [
    re_path(r"ws/livestream/(?P<stream_key>[0-9a-f-]+)/$", LiveStreamSignalConsumer.as_asgi()),
]
