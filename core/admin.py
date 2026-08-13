from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import (
    CoreUser,
    CoreGroup,
    CoreSites,
    EmailTemplate,
    Industry,
    Invitation,
    LogicModule,
    Organization,
    OrganizationType,
    Consortium,
    PasswordResetCode,
)


class LogicModuleAdmin(admin.ModelAdmin):
    list_display = ('name',)
    list_filter = ('name',)


class CoreSitesAdmin(admin.ModelAdmin):
    list_display = ('name',)
    display = 'Core Site'
    list_filter = ('name',)
    search_fields = ('name',)


class OrganizationTypeAdmin(admin.ModelAdmin):
    list_display = ('name',)
    display = 'Organization Type'


class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'organization_type', 'create_date', 'edit_date')
    display = 'Organization'


class CoreGroupAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'organization',
        'is_global',
        'is_org_level',
        'is_default',
        'permissions',
    )
    display = 'Core Group'
    search_fields = ('name', 'organization__name')


class CoreUserAdmin(UserAdmin):
    list_display = (
        'username',
        'first_name',
        'last_name',
        'organization',
        'title',
        'is_active',
        'user_timezone',
        'user_language',
    )
    display = 'Core User'
    list_filter = ('is_staff', 'organization')
    search_fields = (
        'first_name',
        'first_name',
        'username',
        'title',
        'organization__name',
    )
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        (
            _('Personal info'),
            {
                'fields': (
                    'title',
                    'first_name',
                    'last_name',
                    'email',
                    'contact_info',
                    'organization',
                    'user_timezone',
                    'user_language',
                )
            },
        ),
        (
            _('Permissions'),
            {
                'fields': (
                    'is_active',
                    'is_staff',
                    'is_superuser',
                    'core_groups',
                    'user_permissions',
                )
            },
        ),
        (_('Preferences'), {'fields': ('geo_alert_preferences', 'env_alert_preferences', 'sms_number', 'whatsApp_number')}),
        (
            _('Important dates'),
            {'fields': ('last_login', 'date_joined', 'create_date', 'edit_date', 'last_gdpr_shown')},
        ),
    )
    filter_horizontal = ('core_groups', 'user_permissions')

    def get_fieldsets(self, request, obj=None):

        if not obj:
            return self.add_fieldsets

        fieldsets = super().get_fieldsets(request, obj)

        if not request.user.is_superuser:
            fieldsets[2][1]['fields'] = ('is_active', 'is_staff')
        else:
            fieldsets[2][1]['fields'] = (
                'is_active',
                'is_staff',
                'is_superuser',
                'core_groups',
                'user_permissions',
            )

        return fieldsets


class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ('organization', 'type')
    display = 'Email Template'


class PasswordResetCodeAdmin(admin.ModelAdmin):
    list_display = ('user', 'code', 'expires_at', 'is_used')


class InvitationAdmin(admin.ModelAdmin):
    list_display = ('email', 'organization', 'status', 'expires_at', 'reinvite_count')
    actions = ['cancel_invitations']

    @admin.action(description='Cancel selected invitations')
    def cancel_invitations(self, request, queryset):
        queryset.update(status=Invitation.STATUS_CANCELLED, cancelled_at=timezone.now())


admin.site.register(LogicModule, LogicModuleAdmin)
admin.site.register(Organization, OrganizationAdmin)
admin.site.register(OrganizationType, OrganizationTypeAdmin)
admin.site.register(CoreGroup, CoreGroupAdmin)
admin.site.register(CoreUser, CoreUserAdmin)
admin.site.register(CoreSites, CoreSitesAdmin)
admin.site.register(EmailTemplate, EmailTemplateAdmin)
admin.site.register(Industry)
admin.site.register(Consortium)
admin.site.register(PasswordResetCode, PasswordResetCodeAdmin)
admin.site.register(Invitation, InvitationAdmin)
