# Generated by Django 5.1.4 on 2025-01-28 14:07

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0013_alter_artistsubscription_artist_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='content',
            name='thumbnail',
            field=models.ImageField(blank=True, null=True, upload_to='thumbnails/'),
        ),
    ]
