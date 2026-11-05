"""Isolated regression settings; never use to serve the application."""
from .settings import *  # noqa: F403

# Exercise password checking/login without repeatedly paying production's
# password-stretching cost for hundreds of generated test accounts.
PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
CHANNEL_LAYERS = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
