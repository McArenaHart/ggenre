from django.db import migrations
from django.utils import timezone


def expire_legacy(apps, schema_editor):
    apps.get_model('studio', 'AudioJob').objects.filter(status='running', lease_until__isnull=True).update(lease_until=timezone.now())


class Migration(migrations.Migration):
    dependencies = [('studio', '0013_alter_track_options_alter_track_managers_and_more')]
    operations = [migrations.RunPython(expire_legacy, migrations.RunPython.noop)]
