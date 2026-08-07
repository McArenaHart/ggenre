from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("chatapp", "0013_rename_mrc_route_updated_idx_chatapp_mis_route_m_3cfdf9_idx_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="missionsession",
            name="assigned_admin",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="claimed_mission_sessions",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="missionsession",
            name="assigned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
