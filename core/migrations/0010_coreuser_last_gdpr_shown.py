# Generated by Django 2.2.10 on 2024-01-22 09:15

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_auto_20240118_0940'),
    ]

    operations = [
        migrations.AddField(
            model_name='coreuser',
            name='last_gdpr_shown',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]