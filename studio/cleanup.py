"""Reference-aware reclamation of private, immutable Studio WAV files."""
from pathlib import Path

from django.apps import apps
from django.db import models

from .storage import private_storage


def private_file_fields():
    root = Path(private_storage.location).resolve()
    for model in apps.get_models():
        for field in model._meta.fields:
            if not isinstance(field, models.FileField):
                continue
            location = getattr(field.storage, 'location', None)
            if location and Path(location).resolve() == root:
                yield model, field.name


def referenced_names(fields):
    names = set()
    for model, field in fields:
        names.update(model._base_manager.exclude(**{field: ''}).values_list(field, flat=True).iterator())
    return names


def is_referenced(name, fields):
    return any(model._base_manager.filter(**{field: name}).exists() for model, field in fields)
