from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
@never_cache
def web_manifest(request):
    return render(
        request,
        "pwa/manifest.webmanifest",
        content_type="application/manifest+json",
    )


@require_GET
@never_cache
def service_worker(request):
    response = render(
        request,
        "pwa/service-worker.js",
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def offline(request):
    return render(request, "pwa/offline.html")
