# Generated by Django 5.1.4 on 2025-01-27 17:12

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0012_artistuploadlimit_suspended_by_admin_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='artistsubscription',
            name='artist',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='subscribed_artists', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name='artistsubscription',
            name='fan',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='artist_subscriptions', to=settings.AUTH_USER_MODEL),
        ),
    ]
