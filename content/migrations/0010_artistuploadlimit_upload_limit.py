# Generated by Django 5.1.4 on 2025-01-26 23:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0009_artistuploadlimit'),
    ]

    operations = [
        migrations.AddField(
            model_name='artistuploadlimit',
            name='upload_limit',
            field=models.PositiveIntegerField(default=10),
        ),
    ]
