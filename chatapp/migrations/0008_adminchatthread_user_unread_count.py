from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chatapp", "0007_peerchatthread_unlocked_until"),
    ]

    operations = [
        migrations.AddField(
            model_name="adminchatthread",
            name="user_unread_count",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
