"""Signed per-job file transfer; remote workers receive no database access."""
import tempfile
import wave
from django.core.files import File
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .capacity import artist_storage
from .limits import MAX_AUDIO_BYTES
from .models import AudioJob
from .remote_extraction import authorize


@csrf_exempt
def exchange(request, pk, action):
    allowed = {'source': 'GET', 'control': 'GET', 'result': 'PUT'}
    if action not in allowed or request.method != allowed[action]:
        return JsonResponse({'error': 'Method not allowed.'}, status=405)
    try:
        job = authorize(request, pk, action)
    except (PermissionError, AudioJob.DoesNotExist):
        return JsonResponse({'error': 'Invalid or inactive job authorization.'}, status=403)
    if action == 'source':
        response = FileResponse(job.source.open('rb'), content_type='audio/wav')
    elif action == 'control':
        response = JsonResponse({'active': not bool(job.result)})
    else:
        try:
            size = int(request.headers.get('Content-Length', '0'))
            if request.content_type == 'application/json':
                if not 0 < size <= 4096:
                    raise ValidationError('Invalid error notification.')
                AudioJob.objects.filter(pk=job.pk, status='running', remote_nonce=job.remote_nonce, result='').update(error='Remote worker failed to extract this audio. Review the worker before starting another test.')
                return JsonResponse({'ok': True})
            if not 44 <= size <= MAX_AUDIO_BYTES:
                raise ValidationError('Choose a result under 64 MB.')
            with tempfile.TemporaryFile() as spool:
                received = 0
                while block := request.read(min(65536, size - received + 1)):
                    received += len(block)
                    if received > size:
                        raise ValidationError('Invalid result length.')
                    spool.write(block)
                if received != size:
                    raise ValidationError('Incomplete result.')
                spool.seek(0)
                from .views import validate_audio
                output = validate_audio(File(spool, name='remote.wav'))
                with job.source.open('rb') as source, wave.open(source, 'rb') as original, wave.open(output, 'rb') as rendered:
                    if rendered.getnchannels() != 2 or rendered.getframerate() != 44100 or abs(rendered.getnframes() / 44100 - original.getnframes() / original.getframerate()) > .02:
                        raise ValidationError('The remote result format or duration differs from its source.')
                output.seek(0)
                with transaction.atomic():
                    current = AudioJob.objects.select_for_update().get(pk=job.pk)
                    if current.status != 'running' or current.remote_nonce != job.remote_nonce:
                        return JsonResponse({'error': 'This task is no longer active.'}, status=409)
                    if not current.result:
                        with artist_storage(current.track.project.artist_id):
                            current.result.save('remote.wav', output, save=False)
                        current.save(update_fields=['result'])
            response = JsonResponse({'ok': True})
        except (ValidationError, ValueError, wave.Error) as exc:
            return JsonResponse({'error': exc.messages[0] if isinstance(exc, ValidationError) else 'Invalid result.'}, status=400)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
