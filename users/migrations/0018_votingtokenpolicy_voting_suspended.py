from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0017_customuser_has_free_pass_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="votingtokenpolicy",
            name="voting_suspended",
            field=models.BooleanField(default=False),
        ),
    ]
