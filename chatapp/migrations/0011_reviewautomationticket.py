from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("chatapp", "0010_missiontemplate_missionsession_missionevidence_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReviewAutomationTicket",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "route_actor_type",
                    models.CharField(
                        choices=[("ai", "AI"), ("manual", "Manual")],
                        max_length=10,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("queued", "Queued"),
                            ("processing", "Processing"),
                            ("completed", "Completed"),
                            ("failed", "Failed"),
                            ("cancelled", "Cancelled"),
                        ],
                        default="queued",
                        max_length=20,
                    ),
                ),
                ("policy_snapshot", models.JSONField(blank=True, default=dict)),
                ("input_payload", models.JSONField(blank=True, default=dict)),
                ("output_payload", models.JSONField(blank=True, default=dict)),
                ("error_message", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "mission_evidence",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="automation_tickets",
                        to="chatapp.missionevidence",
                    ),
                ),
                (
                    "mission_session",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="automation_tickets",
                        to="chatapp.missionsession",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="reviewautomationticket",
            index=models.Index(fields=["status", "created_at"], name="rat_status_created_idx"),
        ),
        migrations.AddIndex(
            model_name="reviewautomationticket",
            index=models.Index(fields=["mission_session", "created_at"], name="rat_mission_created_idx"),
        ),
        migrations.AddIndex(
            model_name="reviewautomationticket",
            index=models.Index(fields=["route_actor_type", "created_at"], name="rat_route_created_idx"),
        ),
    ]
