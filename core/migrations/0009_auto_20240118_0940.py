# Generated by Django 2.2.10 on 2024-01-18 09:40

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_auto_20240115_1310'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='organization',
            name='enable_env_emails',
        ),
        migrations.RemoveField(
            model_name='organization',
            name='enable_geofence_emails',
        ),
    ]