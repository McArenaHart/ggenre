"""Three editable source ranges joined into one private instrumental."""
import json
import math
import tempfile
import wave
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .limits import MAX_AUDIO_SECONDS
from .models import AudioJob, Instrumental
from .video_render import run_ffmpeg
from .views import artist_only, validate_audio


def plan_ranges(config, rate, frames):
    if not isinstance(config, dict) or not isinstance(config.get('sections'), list) or len(config['sections']) != 3:
        raise ValueError('Choose an intro, middle and outro.')
    fade = float(config.get('crossfade_ms', 20))
    if not math.isfinite(fade) or not 0 <= fade <= 500:
        raise ValueError('Choose a join fade from 0 to 500 milliseconds.')
    sections = []
    for section in config['sections']:
        start, end, gain = (float(section[name]) for name in ('start', 'end', 'gain'))
        if not all(math.isfinite(value) for value in (start, end, gain)) or not 0 <= gain <= 1:
            raise ValueError('Check section times and volumes.')
        start, end = math.floor(start * rate + .5), math.floor(end * rate + .5)
        if start < 0 or end > frames or end - start < math.ceil(rate * .1):
            raise ValueError('Each section must be at least 0.1 seconds and stay inside the source.')
        sections.append({'start': start, 'end': end, 'gain': gain})
    fades = [min(math.floor(fade * rate / 1000 + .5), (sections[i]['end'] - sections[i]['start']) // 2,
                 (sections[i + 1]['end'] - sections[i + 1]['start']) // 2) for i in range(2)]
    length = sum(item['end'] - item['start'] for item in sections) - sum(fades)
    if length > MAX_AUDIO_SECONDS * rate:
        raise ValueError('Keep the joined instrumental within six minutes.')
    return sections, fades, length


def render_arrangement(source, config):
    with source.open('rb') as stream, wave.open(stream, 'rb') as audio:
        rate, frames = audio.getframerate(), audio.getnframes()
    sections, fades, length = plan_ranges(config, rate, frames)
    with tempfile.TemporaryDirectory() as folder:
        input_path, output = Path(folder) / 'source.wav', Path(folder) / 'joined.wav'
        with source.open('rb') as stream, input_path.open('wb') as destination:
            import shutil
            shutil.copyfileobj(stream, destination)
        filters = ['[0:a]asplit=3[s0][s1][s2]']
        for index, part in enumerate(sections):
            filters.append(f"[s{index}]atrim=start_sample={part['start']}:end_sample={part['end']},asetpts=PTS-STARTPTS,volume={part['gain']}[a{index}]")
        for index, (left, right, target) in enumerate([('a0', 'a1', 'join'), ('join', 'a2', 'out')]):
            join = f'acrossfade=ns={fades[index]}:c1=tri:c2=tri' if fades[index] else 'concat=n=2:v=0:a=1'
            filters.append(f'[{left}][{right}]{join}[{target}]')
        run_ffmpeg(['-protocol_whitelist', 'file,pipe', '-i', str(input_path), '-filter_complex', ';'.join(filters), '-map', '[out]', '-c:a', 'pcm_s16le', str(output)])
        result = validate_audio(ContentFile(output.read_bytes(), name='joined.wav'))
        with wave.open(result, 'rb') as audio:
            if audio.getnframes() != length:
                raise ValueError('The join length could not be verified.')
        result.seek(0)
        return result


def source_for(request, item_pk=None, job_pk=None):
    if item_pk is not None:
        item = get_object_or_404(Instrumental, pk=item_pk, artist=request.user)
        if not item.config.get('imported') or not item.audio:
            from django.http import Http404
            raise Http404
        return item, item.source_audio or item.audio
    job = get_object_or_404(AudioJob, pk=job_pk, operation='separate', status='ready', track__project__artist=request.user)
    return job, job.result


@artist_only
def editor(request, item_pk=None, job_pk=None):
    owner, source = source_for(request, item_pk, job_pk)
    with source.open('rb') as stream, wave.open(stream, 'rb') as audio:
        duration = audio.getnframes() / audio.getframerate()
        rate = audio.getframerate()
    config = owner.config.get('arrangement') if isinstance(owner, Instrumental) and owner.source_audio else None
    config = config or {'crossfade_ms': 20, 'sections': [{'start': i * duration / 3, 'end': (i + 1) * duration / 3, 'gain': 1} for i in range(3)]}
    return render(request, 'studio/extract_arrangement.html', {'title': owner.title if isinstance(owner, Instrumental) else owner.track.name,
        'revision': owner.updated_at.isoformat() if isinstance(owner, Instrumental) else str(owner.pk),
        'source_url': reverse('studio:arrange_source', args=[item_pk]) if item_pk else reverse('studio:audio_job_audio', args=[job_pk]),
        'save_url': reverse('studio:arrange_save', args=[item_pk]) if item_pk else reverse('studio:arrange_job_save', args=[job_pk]),
        'item_id': owner.pk if isinstance(owner, Instrumental) and owner.source_audio else None,
        'config': config, 'duration': duration, 'sample_rate': rate})


@artist_only
def source_audio(request, item_pk):
    owner, source = source_for(request, item_pk=item_pk)
    return FileResponse(source.open('rb'), content_type='audio/wav')


@artist_only
@require_POST
def save(request, item_pk=None, job_pk=None):
    owner, source = source_for(request, item_pk, job_pk)
    try:
        if item_pk and request.POST.get('revision') != owner.updated_at.isoformat():
            return JsonResponse({'error': 'This instrumental changed. Reload before saving.'}, status=409)
        title = request.POST.get('title', '').strip()
        if not title or len(title) > 160:
            raise ValueError('Enter a title up to 160 characters.')
        config = json.loads(request.POST.get('config', 'null'))
        with transaction.atomic():
            if item_pk:
                owner = get_object_or_404(Instrumental.objects.select_for_update(), pk=item_pk, artist=request.user)
                if request.POST.get('revision') != owner.updated_at.isoformat():
                    return JsonResponse({'error': 'This instrumental changed. Reload before saving.'}, status=409)
                category, bpm = owner.category, owner.config['bpm']
                item = owner if owner.source_audio else Instrumental(artist=request.user)
            else:
                owner = get_object_or_404(AudioJob.objects.select_for_update(), pk=job_pk, status='ready', operation='separate', track__project__artist=request.user)
                category, bpm = owner.track.project.category, owner.track.project.tempo
                source = owner.result
                item = Instrumental(artist=request.user)
            result = render_arrangement(source, config)
            with source.open('rb') as stream, wave.open(stream, 'rb') as audio:
                rate = audio.getframerate()
                parts, _, _ = plan_ranges(config, rate, audio.getnframes())
            config = {'crossfade_ms': float(config.get('crossfade_ms', 20)), 'sections': [
                {'start': part['start'] / rate, 'end': part['end'] / rate, 'gain': part['gain']} for part in parts]}
            item.title, item.category = title, category
            item.config = {'imported': True, 'bpm': bpm, 'arrangement': config}
            item.source_audio = source.name
            item.audio = result
            item.save()
        return JsonResponse({'ok': True, 'url': reverse('studio:arrange', args=[item.pk])})
    except (ValueError, KeyError, TypeError, ValidationError) as exc:
        return JsonResponse({'error': exc.messages[0] if isinstance(exc, ValidationError) else 'Check section ranges, volume and join settings.'}, status=400)
