"""One entitlement per immutable audio version across both studio sources."""
from django.db import transaction
from django.db.models import F
from .models import Export, ExportAllowance


@transaction.atomic
def request_export(artist, source, payment_reference=''):
    # Callers lock their source first. Allowance serialization also protects
    # requests for different sources belonging to the same artist.
    allowance, _ = ExportAllowance.objects.get_or_create(artist=artist)
    allowance = ExportAllowance.objects.select_for_update().get(pk=allowance.pk)
    key = {'project': source} if source._meta.model_name == 'project' else {'instrumental': source}
    audio = source.mix.name if 'project' in key else source.audio.name
    existing = Export.objects.filter(**key, audio=audio, status__in=['free', 'approved', 'pending']).order_by('-pk').first()
    if existing:
        return existing, False
    free = allowance.unlimited_exports or ExportAllowance.objects.filter(pk=allowance.pk, free_used__lt=F('free_limit')).update(free_used=F('free_used') + 1)
    return Export.objects.create(**key, audio=audio, status='free' if free else 'pending', payment_reference=payment_reference[:160]), True
