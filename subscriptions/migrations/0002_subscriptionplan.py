# Generated by Django 5.1.4 on 2025-01-27 02:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='SubscriptionPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('description', models.TextField()),
                ('price', models.DecimalField(decimal_places=2, max_digits=10)),
                ('duration', models.IntegerField()),
            ],
            options={
                'verbose_name': 'Subscription Plan',
                'verbose_name_plural': 'Subscription Plans',
            },
        ),
    ]
