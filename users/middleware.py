from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse


class SuspendedUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated and user.is_suspended_by_admin and not user.is_admin():
            allowed_paths = {
                reverse("login"),
                reverse("logout"),
            }
            if request.path not in allowed_paths and not request.path.startswith("/static/"):
                logout(request)
                messages.error(request, "Your account is suspended. Contact support for access.")
                return redirect("login")

        return self.get_response(request)
