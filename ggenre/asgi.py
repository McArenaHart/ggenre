import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ggenre.settings")

# Initialize Django ASGI application early to ensure the AppRegistry
# is populated before importing code that may import ORM models.
django_asgi_app = get_asgi_application()

from chatapp.routing import websocket_urlpatterns as chat_websocket_urlpatterns
from content.routing import websocket_urlpatterns as content_websocket_urlpatterns
from livestream.routing import websocket_urlpatterns as livestream_websocket_urlpatterns

websocket_urlpatterns = (
    content_websocket_urlpatterns
    + chat_websocket_urlpatterns
    + livestream_websocket_urlpatterns
)

application = ProtocolTypeRouter(
    {
        "http": django_asgi_app,
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
        ),
    }
)
