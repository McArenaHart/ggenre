from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chatapp", "0011_reviewautomationticket"),
    ]

    operations = [
        migrations.CreateModel(
            name="MissionReviewControl",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "route_mode",
                    models.CharField(
                        choices=[
                            ("alternate", "Alternate"),
                            ("manual_only", "Manual Only"),
                            ("ai_preferred", "AI Preferred"),
                        ],
                        default="alternate",
                        max_length=20,
                    ),
                ),
                ("reason", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["-updated_at", "-id"],
            },
        ),
        migrations.AddIndex(
            model_name="missionreviewcontrol",
            index=models.Index(fields=["route_mode", "updated_at"], name="mrc_route_updated_idx"),
        ),
    ]
