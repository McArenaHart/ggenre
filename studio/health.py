import shutil
from pathlib import Path
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from .models import AudioJob, StudioMaintenance
from .storage import private_storage


def report():
    now = timezone.now()
    worker = StudioMaintenance.objects.filter(pk='audio-worker').first()
    cleanup = StudioMaintenance.objects.filter(pk='audio-cleanup').first()
    root = Path(private_storage.location)
    while not root.exists():
        root = root.parent
    oldest = AudioJob.objects.filter(status='queued').order_by('created_at').first()
    completed = AudioJob.objects.filter(finished_at__isnull=False, started_at__isnull=False, status__in=['ready', 'applied']).order_by('-finished_at').first()
    return {
        'worker_seen_seconds_ago': round((now - worker.last_success_at).total_seconds()) if worker and worker.last_success_at else None,
        'queued': AudioJob.objects.filter(status='queued').count(),
        'oldest_queue_seconds': round((now - oldest.created_at).total_seconds()) if oldest else 0,
        'running': AudioJob.objects.filter(status='running').count(),
        'stale': AudioJob.objects.filter(status='running', lease_until__lt=now).count(),
        'disk_free_mib': shutil.disk_usage(root).free // (1024 * 1024),
        'cleanup_last_success': cleanup.last_success_at.isoformat() if cleanup and cleanup.last_success_at else None,
        'cleanup_error': cleanup.last_error if cleanup else '',
        'last_processing_seconds': round((completed.finished_at - completed.started_at).total_seconds(), 1) if completed else None,
    }


def view(request):
    if not request.user.is_authenticated or not (request.user.is_superuser or request.user.is_admin()):
        return JsonResponse({'error': 'Admin access required.'}, status=403)
    state = report()
    age = state['worker_seen_seconds_ago']
    state['worker_online'] = age is not None and age < 90
    response = render(request, 'studio/health.html', state)
    response['Cache-Control'] = 'private, no-store'
    return response
