# Generated by Django 2.2.10 on 2022-03-24 11:57

import django.contrib.auth.models
import django.contrib.auth.validators
import django.contrib.postgres.fields
import django.contrib.postgres.fields.jsonb
from django.db import migrations, models
import django.db.migrations.operations.special
import django.db.models.deletion
import django.utils.timezone
import uuid


def migrate_email_alert(apps, schema_editor):
    CoreUser = apps.get_model("core", "CoreUser")
    for record in CoreUser.objects.all():
        record.email_preferences = {'environmental': record.email_alert_flag}
        record.save()


class Migration(migrations.Migration):

    dependencies = [
        ('sites', '0002_alter_domain_unique'),
        ('auth', '0011_update_proxy_permissions'),
    ]

    operations = [
        migrations.CreateModel(
            name='Industry',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'name',
                    models.CharField(
                        blank=True,
                        default='Tech',
                        max_length=255,
                        verbose_name='Industry Name',
                    ),
                ),
                (
                    'description',
                    models.TextField(
                        blank=True,
                        max_length=765,
                        null=True,
                        verbose_name='Description/Notes',
                    ),
                ),
                ('create_date', models.DateTimeField(blank=True, null=True)),
                ('edit_date', models.DateTimeField(blank=True, null=True)),
            ],
            options={'verbose_name_plural': 'Industries', 'ordering': ('name',)},
        ),
        migrations.CreateModel(
            name='Organization',
            fields=[
                (
                    'organization_uuid',
                    models.UUIDField(
                        default=uuid.uuid4,
                        primary_key=True,
                        serialize=False,
                        verbose_name='Organization UUID',
                    ),
                ),
                (
                    'name',
                    models.CharField(
                        blank=True,
                        help_text='Each end user must be grouped into an organization',
                        max_length=255,
                        verbose_name='Organization Name',
                    ),
                ),
                (
                    'description',
                    models.TextField(
                        blank=True,
                        help_text='Description of organization',
                        max_length=765,
                        null=True,
                        verbose_name='Description/Notes',
                    ),
                ),
                (
                    'organization_url',
                    models.CharField(
                        blank=True,
                        help_text='Link to organizations external web site',
                        max_length=255,
                        null=True,
                    ),
                ),
                ('create_date', models.DateTimeField(blank=True, null=True)),
                ('edit_date', models.DateTimeField(blank=True, null=True)),
                (
                    'oauth_domains',
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(
                            blank=True,
                            max_length=255,
                            null=True,
                            verbose_name='OAuth Domains',
                        ),
                        blank=True,
                        null=True,
                        size=None,
                    ),
                ),
                (
                    'date_format',
                    models.CharField(
                        blank=True,
                        default='DD.MM.YYYY',
                        max_length=50,
                        verbose_name='Date Format',
                    ),
                ),
                ('phone', models.CharField(blank=True, max_length=20, null=True)),
                (
                    'industries',
                    models.ManyToManyField(
                        blank=True,
                        help_text='Type of Industry the organization belongs to if any',
                        related_name='organizations',
                        to='core.Industry',
                    ),
                ),
                (
                    'allow_import_export',
                    models.BooleanField(
                        default=False,
                        verbose_name='To allow import export functionality',
                    ),
                ),
                ('radius', models.FloatField(blank=True, max_length=20, null=True)),
            ],
            options={'verbose_name_plural': 'Organizations', 'ordering': ('name',)},
        ),
        migrations.CreateModel(
            name='CoreSites',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('name', models.CharField(blank=True, max_length=255, null=True)),
                ('privacy_disclaimer', models.TextField(blank=True, null=True)),
                ('created', models.DateTimeField(blank=True, null=True)),
                ('updated', models.DateTimeField(blank=True, null=True)),
                (
                    'whitelisted_domains',
                    models.TextField(
                        blank=True, null=True, verbose_name='Whitelisted Domains'
                    ),
                ),
                (
                    'site',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to='sites.Site'
                    ),
                ),
            ],
            options={'verbose_name': 'Core Site', 'verbose_name_plural': 'Core Sites'},
        ),
        migrations.CreateModel(
            name='CoreGroup',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'uuid',
                    models.CharField(
                        default=uuid.uuid4,
                        max_length=255,
                        unique=True,
                        verbose_name='CoreGroup UUID',
                    ),
                ),
                (
                    'name',
                    models.CharField(max_length=80, verbose_name='Name of the role'),
                ),
                (
                    'is_global',
                    models.BooleanField(default=False, verbose_name='Is global group'),
                ),
                (
                    'is_org_level',
                    models.BooleanField(
                        default=False, verbose_name='Is organization level group'
                    ),
                ),
                (
                    'is_default',
                    models.BooleanField(
                        default=False, verbose_name='Is organization default group'
                    ),
                ),
                (
                    'permissions',
                    models.PositiveSmallIntegerField(
                        default=4,
                        help_text='Decimal integer from 0 to 15 converted from 4-bit binary, each bit indicates permissions for CRUD',
                        verbose_name='Permissions',
                    ),
                ),
                (
                    'create_date',
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ('edit_date', models.DateTimeField(blank=True, null=True)),
                (
                    'organization',
                    models.ForeignKey(
                        blank=True,
                        help_text='Related Org to associate with',
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to='core.Organization',
                    ),
                ),
            ],
            options={'ordering': ('name',)},
        ),
        migrations.CreateModel(
            name='EmailTemplate',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('subject', models.CharField(max_length=255, verbose_name='Subject')),
                (
                    'type',
                    models.PositiveSmallIntegerField(
                        choices=[(1, 'Password resetting'), (2, 'Invitation')],
                        verbose_name='Type of template',
                    ),
                ),
                (
                    'template',
                    models.TextField(
                        blank=True,
                        null=True,
                        verbose_name='Reset password e-mail template (text)',
                    ),
                ),
                (
                    'template_html',
                    models.TextField(
                        blank=True,
                        null=True,
                        verbose_name='Reset password e-mail template (HTML)',
                    ),
                ),
                (
                    'organization',
                    models.ForeignKey(
                        help_text='Related Org to associate with',
                        on_delete=django.db.models.deletion.CASCADE,
                        to='core.Organization',
                        verbose_name='Organization',
                    ),
                ),
            ],
            options={
                'verbose_name': 'Email Template',
                'verbose_name_plural': 'Email Templates',
                'unique_together': {('organization', 'type')},
            },
        ),
        migrations.CreateModel(
            name='LogicModule',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'module_uuid',
                    models.CharField(
                        default=uuid.uuid4,
                        max_length=255,
                        unique=True,
                        verbose_name='Logic Module UUID',
                    ),
                ),
                (
                    'name',
                    models.CharField(
                        blank=True, max_length=255, verbose_name='Logic Module Name'
                    ),
                ),
                (
                    'description',
                    models.TextField(
                        blank=True,
                        max_length=765,
                        null=True,
                        verbose_name='Description/Notes',
                    ),
                ),
                ('endpoint', models.CharField(blank=True, max_length=255, null=True)),
                (
                    'endpoint_name',
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                (
                    'api_specification',
                    django.contrib.postgres.fields.jsonb.JSONField(
                        blank=True, null=True
                    ),
                ),
                (
                    'docs_endpoint',
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                (
                    'core_groups',
                    models.ManyToManyField(
                        blank=True,
                        related_name='logic_module_set',
                        related_query_name='logic_module',
                        to='core.CoreGroup',
                        verbose_name='Logic Module groups',
                    ),
                ),
                ('create_date', models.DateTimeField(blank=True, null=True)),
                ('edit_date', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name_plural': 'Logic Modules',
                'ordering': ('name',),
                'unique_together': {('endpoint', 'endpoint_name')},
            },
        ),
        migrations.CreateModel(
            name='CoreUser',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('password', models.CharField(max_length=128, verbose_name='password')),
                (
                    'last_login',
                    models.DateTimeField(
                        blank=True, null=True, verbose_name='last login'
                    ),
                ),
                (
                    'is_superuser',
                    models.BooleanField(
                        default=False,
                        help_text='Designates that this user has all permissions without explicitly assigning them.',
                        verbose_name='superuser status',
                    ),
                ),
                (
                    'username',
                    models.CharField(
                        error_messages={
                            'unique': 'A user with that username already exists.'
                        },
                        help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.',
                        max_length=150,
                        unique=True,
                        validators=[
                            django.contrib.auth.validators.UnicodeUsernameValidator()
                        ],
                        verbose_name='username',
                    ),
                ),
                (
                    'first_name',
                    models.CharField(
                        blank=True, max_length=30, verbose_name='first name'
                    ),
                ),
                (
                    'last_name',
                    models.CharField(
                        blank=True, max_length=150, verbose_name='last name'
                    ),
                ),
                (
                    'email',
                    models.EmailField(
                        blank=True, max_length=254, verbose_name='email address'
                    ),
                ),
                (
                    'is_staff',
                    models.BooleanField(
                        default=False,
                        help_text='Designates whether the user can log into this admin site.',
                        verbose_name='staff status',
                    ),
                ),
                (
                    'is_active',
                    models.BooleanField(
                        default=True,
                        help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.',
                        verbose_name='active',
                    ),
                ),
                (
                    'date_joined',
                    models.DateTimeField(
                        default=django.utils.timezone.now, verbose_name='date joined'
                    ),
                ),
                (
                    'core_user_uuid',
                    models.CharField(
                        default=uuid.uuid4,
                        max_length=255,
                        unique=True,
                        verbose_name='CoreUser UUID',
                    ),
                ),
                (
                    'title',
                    models.CharField(
                        blank=True,
                        choices=[('mr', 'Mr.'), ('mrs', 'Mrs.'), ('ms', 'Ms.')],
                        max_length=3,
                        null=True,
                    ),
                ),
                (
                    'contact_info',
                    models.CharField(blank=True, max_length=255, null=True),
                ),
                ('privacy_disclaimer_accepted', models.BooleanField(default=False)),
                (
                    'create_date',
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ('edit_date', models.DateTimeField(blank=True, null=True)),
                (
                    'core_groups',
                    models.ManyToManyField(
                        blank=True,
                        related_name='user_set',
                        related_query_name='user',
                        to='core.CoreGroup',
                        verbose_name='User groups',
                    ),
                ),
                (
                    'groups',
                    models.ManyToManyField(
                        blank=True,
                        help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.',
                        related_name='user_set',
                        related_query_name='user',
                        to='auth.Group',
                        verbose_name='groups',
                    ),
                ),
                (
                    'organization',
                    models.ForeignKey(
                        blank=True,
                        help_text='Related Org to associate with',
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to='core.Organization',
                    ),
                ),
                (
                    'user_permissions',
                    models.ManyToManyField(
                        blank=True,
                        help_text='Specific permissions for this user.',
                        related_name='user_set',
                        related_query_name='user',
                        to='auth.Permission',
                        verbose_name='user permissions',
                    ),
                ),
                (
                    'email_alert_flag',
                    models.BooleanField(blank=True, default=False, null=True),
                ),
                (
                    'email_preferences',
                    django.contrib.postgres.fields.jsonb.JSONField(
                        blank=True, null=True
                    ),
                ),
                (
                    'push_preferences',
                    django.contrib.postgres.fields.jsonb.JSONField(
                        blank=True, null=True
                    ),
                ),
                (
                    'user_timezone',
                    models.CharField(blank=True, max_length=255, null=True),
                ),
            ],
            options={'ordering': ('first_name',)},
            managers=[('objects', django.contrib.auth.models.UserManager())],
        ),
        migrations.CreateModel(
            name='OrganizationType',
            fields=[
                (
                    'id',
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'name',
                    models.CharField(
                        blank=True,
                        help_text='Organization type',
                        max_length=255,
                        verbose_name='Name',
                    ),
                ),
                ('create_date', models.DateTimeField(blank=True, null=True)),
                ('edit_date', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'verbose_name_plural': 'Organization Types',
                'ordering': ('name',),
            },
        ),
        migrations.AddField(
            model_name='organization',
            name='organization_type',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to='core.OrganizationType',
            ),
        ),
        migrations.CreateModel(
            name='Consortium',
            fields=[
                (
                    'consortium_uuid',
                    models.UUIDField(
                        default=uuid.uuid4,
                        primary_key=True,
                        serialize=False,
                        verbose_name='Consortium UUID',
                    ),
                ),
                (
                    'name',
                    models.CharField(
                        blank=True,
                        help_text='Multiple organizations form a consortium together',
                        max_length=255,
                        verbose_name='Consortium Name',
                    ),
                ),
                (
                    'create_date',
                    models.DateTimeField(default=django.utils.timezone.now),
                ),
                ('edit_date', models.DateTimeField(blank=True, null=True)),
                (
                    'custodian_uuids',
                    django.contrib.postgres.fields.ArrayField(
                        base_field=models.CharField(
                            blank=True,
                            max_length=255,
                            null=True,
                            verbose_name='Custodian UUIDs',
                        ),
                        blank=True,
                        null=True,
                        size=None,
                    ),
                ),
            ],
            options={'verbose_name_plural': 'Consortiums', 'ordering': ('name',)},
        ),
        migrations.RunPython(migrate_email_alert, migrations.RunPython.noop),
        migrations.RemoveField(model_name='coreuser', name='email_alert_flag'),
        migrations.RemoveField(model_name='consortium', name='custodian_uuids'),
        migrations.AddField(
            model_name='consortium',
            name='organization_uuids',
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.UUIDField(
                    blank=True, null=True, verbose_name='Organization UUIDs'
                ),
                blank=True,
                null=True,
                size=None,
            ),
        ),
        migrations.AlterField(
            model_name='organization',
            name='radius',
            field=models.FloatField(blank=True, default=0.0, max_length=20, null=True),
        ),
    ]
