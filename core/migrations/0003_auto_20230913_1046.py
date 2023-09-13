# Generated by Django 2.2.10 on 2023-09-13 10:46

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_organization_abbrevation'),
    ]

    operations = [
        migrations.AddField(
            model_name='organization',
            name='default_light',
            field=models.FloatField(blank=True, default=5.0, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='default_max_humidity',
            field=models.FloatField(blank=True, default=100.0, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='default_max_temperature',
            field=models.FloatField(blank=True, default=100.0, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='default_measurement_interval',
            field=models.IntegerField(blank=True, default=20, null=True, verbose_name='Interval in minutes'),
        ),
        migrations.AddField(
            model_name='organization',
            name='default_min_humidity',
            field=models.FloatField(blank=True, default=0.0, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='default_min_temperature',
            field=models.FloatField(blank=True, default=0.0, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='default_shock',
            field=models.FloatField(blank=True, default=4.0, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='organization',
            name='default_transmission_interval',
            field=models.IntegerField(blank=True, default=20, null=True, verbose_name='Interval in minutes'),
        ),
        migrations.AddField(
            model_name='organization',
            name='email_notify_environmental',
            field=models.BooleanField(default=True, verbose_name='Allow Email Notification for Environmental Alerts'),
        ),
        migrations.AddField(
            model_name='organization',
            name='email_notify_geofence',
            field=models.BooleanField(default=True, verbose_name='Allow Email Notification for Geofence Alerts'),
        ),
        migrations.AddField(
            model_name='organization',
            name='push_notify_environmental',
            field=models.BooleanField(default=True, verbose_name='Allow Push Notification for Environmental Alerts'),
        ),
        migrations.AddField(
            model_name='organization',
            name='push_notify_geofence',
            field=models.BooleanField(default=True, verbose_name='Allow Push Notification for Geofence Alerts'),
        ),
    ]
