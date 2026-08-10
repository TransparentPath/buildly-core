import base64
import binascii
import jwt
import re
import requests
import secrets

from datetime import timedelta
from urllib.parse import urljoin

from django.contrib.auth import password_validation
from django.conf import settings
from django.utils import timezone
from django.template import Template, Context

from rest_framework import serializers

from oauth2_provider.models import AccessToken, Application, RefreshToken

from core.email_utils import send_email, send_email_body

from core.models import (
    CoreUser,
    CoreGroup,
    EmailTemplate,
    LogicModule,
    Organization,
    PasswordResetCode,
    TEMPLATE_RESET_PASSWORD,
    OrganizationType,
    Consortium,
)

_PROFILE_PIC_DATA_URL_RE = re.compile(r'^data:image/(png|jpeg|webp);base64,(.+)$', re.IGNORECASE)
_PROFILE_PIC_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_PROFILE_PIC_ERROR = (
    'profile_pic must be a base64 data URL with mime type '
    'image/png, image/jpeg, or image/webp, and decoded size ≤ 5 MB.'
)


def validate_profile_pic_data_url(value):
    """Allow empty/null (clears the field). Otherwise enforce data URL + mime + size."""
    if value in (None, ''):
        return value
    match = _PROFILE_PIC_DATA_URL_RE.match(value)
    if not match:
        raise serializers.ValidationError(_PROFILE_PIC_ERROR)
    try:
        decoded = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise serializers.ValidationError(_PROFILE_PIC_ERROR)
    if len(decoded) > _PROFILE_PIC_MAX_BYTES:
        raise serializers.ValidationError(_PROFILE_PIC_ERROR)
    return value


class LogicModuleSerializer(serializers.ModelSerializer):
    id = serializers.ReadOnlyField()
    uuid = serializers.ReadOnlyField()

    class Meta:
        model = LogicModule
        fields = '__all__'


class PermissionsField(serializers.DictField):
    """
    Field for representing int-value permissions as a JSON object in the format.
    For example:
    9 -> '1001' (binary representation) -> `{'create': True, 'read': False, 'update': False, 'delete': True}`
    """

    _keys = ('create', 'read', 'update', 'delete')

    def __init__(self, *args, **kwargs):
        kwargs['child'] = serializers.BooleanField()
        super().__init__(*args, **kwargs)

    def to_representation(self, value):
        permissions = list('{0:04b}'.format(value if value < 16 else 15))
        return dict(zip(self._keys, map(bool, map(int, permissions))))

    def to_internal_value(self, data):
        data = super().to_internal_value(data)
        keys = data.keys()
        if not set(keys) == set(self._keys):
            raise serializers.ValidationError(
                "Permissions field: incorrect keys format"
            )

        permissions = ''.join([str(int(data[key])) for key in self._keys])
        return int(permissions, 2)


class UUIDPrimaryKeyRelatedField(serializers.PrimaryKeyRelatedField):
    def to_representation(self, value):
        return str(super().to_representation(value))


class CoreGroupSerializer(serializers.ModelSerializer):

    permissions = PermissionsField(required=False)
    organization = UUIDPrimaryKeyRelatedField(
        required=False,
        queryset=Organization.objects.all(),
        help_text="Related Org to associate with",
    )

    class Meta:
        model = CoreGroup
        read_only_fields = ('uuid', 'workflowlevel1s', 'workflowlevel2s')
        fields = (
            'id',
            'uuid',
            'name',
            'is_global',
            'is_org_level',
            'permissions',
            'organization',
            'workflowlevel1s',
            'workflowlevel2s',
        )


class CoreUserSerializer(serializers.ModelSerializer):
    """
    Default CoreUser serializer
    """

    is_active = serializers.BooleanField(required=False)
    core_groups = CoreGroupSerializer(read_only=True, many=True)
    invitation_token = serializers.CharField(required=False)

    def validate_invitation_token(self, value):
        try:
            decoded = jwt.decode(value, settings.SECRET_KEY, algorithms='HS256')
            coreuser_exists = CoreUser.objects.filter(email=decoded['email']).exists()
            if coreuser_exists or decoded['email'] != self.initial_data['email']:
                raise serializers.ValidationError('Token is not valid.')

            # The invitation binds organization and role; the request body
            # may not override them. Reject outright rather than silently
            # overriding, so a body/token conflict surfaces as a client error.
            # A field the token does not carry (perform_invite defaults
            # user_role to []) must not be supplied by the body either -
            # otherwise a role-less/org-less invite would let the body pick
            # any value with no token value ever contradicting it.
            # CoreUser.save() already assigns the organization's default
            # group when no role was set, so a role-less invite correctly
            # yields the default (Users) role on its own.
            token_organization_name = decoded.get('organization_name')
            body_organization_name = self.initial_data.get('organization_name')
            if token_organization_name:
                if body_organization_name and body_organization_name != token_organization_name:
                    raise serializers.ValidationError('organization_name does not match the invitation.')
            elif body_organization_name:
                raise serializers.ValidationError('organization_name is not permitted by this invitation.')

            token_user_role = decoded.get('user_role')
            body_user_role = self.initial_data.get('user_role')
            if token_user_role:
                if body_user_role and body_user_role != token_user_role:
                    raise serializers.ValidationError('user_role does not match the invitation.')
            elif body_user_role:
                raise serializers.ValidationError('user_role is not permitted by this invitation.')
        except jwt.DecodeError:
            raise serializers.ValidationError('Token is not valid.')
        except jwt.ExpiredSignatureError:
            raise serializers.ValidationError('Token is expired.')
        # Stash the decoded payload so create() derives organization/role from
        # the token itself, not merely from a body value that passed the check above.
        self._invitation_payload = decoded
        return value

    class Meta:
        model = CoreUser
        fields = (
            'id',
            'core_user_uuid',
            'first_name',
            'last_name',
            'email',
            'username',
            'is_active',
            'title',
            'contact_info',
            'privacy_disclaimer_accepted',
            'organization',
            'core_groups',
            'invitation_token',
            'geo_alert_preferences',
            'env_alert_preferences',
            'sms_number',
            'whatsApp_number',
            'user_timezone',
            'last_gdpr_shown',
            'user_language',
            'profile_pic',
        )
        read_only_fields = ('core_user_uuid', 'organization', 'profile_pic')
        depth = 1


class CoreUserWritableSerializer(CoreUserSerializer):
    """
    Override default CoreUser serializer for writable actions (create, update, partial_update)
    """

    password = serializers.CharField(write_only=True)
    organization_name = serializers.CharField(source='organization.name')
    core_groups = serializers.PrimaryKeyRelatedField(
        many=True, queryset=CoreGroup.objects.all(), required=False
    )
    user_role = serializers.CharField(required=False)

    class Meta:
        model = CoreUser
        fields = CoreUserSerializer.Meta.fields + ('password', 'organization_name', 'user_role')
        read_only_fields = CoreUserSerializer.Meta.read_only_fields

    def create(self, validated_data):
        core_groups = validated_data.pop('core_groups', [])
        user_role = validated_data.pop('user_role', '')
        invitation_token = validated_data.pop('invitation_token', None)
        organization = validated_data.pop('organization', None)

        # On an invited registration, organization and role come from the
        # signed token, not from the request body: the body cannot override
        # them. validate_invitation_token() already rejects a conflicting
        # body value; this also covers the case where the body simply omits
        # them and the token value must still apply.
        invitation_payload = getattr(self, '_invitation_payload', None)
        if invitation_payload:
            token_organization_name = invitation_payload.get('organization_name')
            if token_organization_name:
                organization = {'name': token_organization_name}
            token_user_role = invitation_payload.get('user_role')
            if token_user_role:
                user_role = token_user_role

        # get or create organization
        if organization is None:
            organization = {'name': settings.DEFAULT_ORG}
        organization, is_new_org = Organization.objects.get_or_create(**organization)

        if user_role:
            core_groups = CoreGroup.objects.filter(name=user_role, organization=organization.organization_uuid)

        # create core user
        validated_data['is_active'] = is_new_org or bool(invitation_token)
        coreuser = CoreUser.objects.create(organization=organization, **validated_data)

        # set user password
        coreuser.set_password(validated_data['password'])

        # default organization timezone as user timezone
        if not is_new_org:
            uom_timezone_url = (
                settings.TP_SHIPMENT_URL
                + 'unit_of_measure/?organization_uuid='
                + str(organization.organization_uuid)
                + '&unit_of_measure_for=Time%20Zone'
            )
            uom_language_url = (
                settings.TP_SHIPMENT_URL
                + 'unit_of_measure/?organization_uuid='
                + str(organization.organization_uuid)
                + '&unit_of_measure_for=Language'
            )
            default_timezone_response = requests.get(uom_timezone_url).json()
            default_language_response = requests.get(uom_language_url).json()
            default_timezone = default_timezone_response[0]['unit_of_measure'] if len(default_timezone_response) > 0 else 'America/Los_Angeles'
            default_language = default_language_response[0]['unit_of_measure'] if len(default_language_response) > 0 else 'English'
            coreuser.user_timezone = default_timezone
            coreuser.user_language = default_language

        # Only overwrite groups when the request actually named a role/group -
        # CoreUser.save() (above) already assigned the organization's default
        # group, and an empty .set() here would wipe that out for a role-less
        # invite instead of leaving the default group in place.
        if core_groups:
            coreuser.core_groups.set(core_groups)
        coreuser.save()

        # compute the role display name for the E-mail templates
        role_lower = user_role.lower()
        if 'admins' in role_lower:
            role = 'Administrator'
        elif role_lower == 'users' or role_lower.endswith('users'):
            role = 'User'
        elif user_role:
            role = user_role[:-1] if user_role[-1].lower() == 's' else user_role
        elif core_groups:
            role = core_groups[0].name
        else:
            role = 'User'

        context = {
            'organization_name': organization.name,
            'role': role,
            'signin_link': settings.FRONTEND_URL,
        }
        subject = f"Welcome to {organization.name} on Transparent Path"
        template_name = 'email/coreuser/account_setup.txt'
        html_template_name = 'email/coreuser/account_setup.html'
        send_email(
            coreuser.email, subject, context, template_name, html_template_name, cc_email_address=settings.SUPPORT_EMAIL_ADDRESS
        )

        return coreuser


class CoreUserProfileSerializer(serializers.Serializer):
    """ Let's user update his first_name,last_name,title,contact_info,
    password and organization_name """

    first_name = serializers.CharField(required=False)
    last_name = serializers.CharField(required=False)
    title = serializers.CharField(required=False)
    contact_info = serializers.CharField(required=False)
    password = serializers.CharField(required=False)
    organization_name = serializers.CharField(required=False)
    geo_alert_preferences = serializers.JSONField(required=False)
    env_alert_preferences = serializers.JSONField(required=False)
    sms_number = serializers.CharField(required=False)
    whatsApp_number = serializers.CharField(required=False)
    user_timezone = serializers.CharField(required=False)
    user_language = serializers.CharField(required=False)
    last_gdpr_shown = serializers.DateTimeField(required=False)
    profile_pic = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = CoreUser
        fields = (
            'first_name',
            'last_name',
            'password',
            'title',
            'contact_info',
            'organization_name',
            'geo_alert_preferences',
            'env_alert_preferences',
            'sms_number',
            'whatsApp_number',
            'user_timezone',
            'last_gdpr_shown',
            'user_language',
            'profile_pic',
        )

    def validate_profile_pic(self, value):
        return validate_profile_pic_data_url(value)

    def update(self, instance, validated_data):

        organization_name = validated_data.pop('organization_name')

        name = Organization.objects.filter(name=organization_name).first()
        if name is not None:
            instance.organization = name
            instance.organization_name = name

        instance.first_name = validated_data.get('first_name', instance.first_name)
        instance.last_name = validated_data.get('last_name', instance.last_name)
        instance.title = validated_data.get('title', instance.title)
        instance.contact_info = validated_data.get(
            'contact_info', instance.contact_info
        )
        instance.geo_alert_preferences = validated_data.get(
            'geo_alert_preferences', instance.geo_alert_preferences
        )
        instance.env_alert_preferences = validated_data.get(
            'env_alert_preferences', instance.env_alert_preferences
        )
        instance.sms_number = validated_data.get('sms_number', instance.sms_number)
        instance.whatsApp_number = validated_data.get('whatsApp_number', instance.whatsApp_number)
        instance.user_timezone = validated_data.get('user_timezone', instance.user_timezone)
        instance.user_language = validated_data.get('user_language', instance.user_language)
        instance.last_gdpr_shown = validated_data.get('last_gdpr_shown', instance.last_gdpr_shown)
        instance.profile_pic = validated_data.get('profile_pic', instance.profile_pic)
        password = validated_data.get('password', None)
        if password is not None:
            instance.set_password(password)
        instance.save()

        return instance


class CoreUserInvitationSerializer(serializers.Serializer):
    emails = serializers.ListField(
        child=serializers.EmailField(), min_length=1, max_length=10
    )
    org_data = serializers.JSONField(required=False)
    country = serializers.CharField(required=False)
    currency = serializers.CharField(required=False)
    date_format = serializers.CharField(required=False)
    time_format = serializers.CharField(required=False)
    distance = serializers.CharField(required=False)
    temperature = serializers.CharField(required=False)
    weight = serializers.CharField(required=False)
    org_timezone = serializers.CharField(required=False)
    org_language = serializers.CharField(required=False)
    user_role = serializers.CharField(required=False)


class CoreUserResetPasswordSerializer(serializers.Serializer):
    """Serializer for reset password request data
    """

    email = serializers.EmailField()

    def save(self, **kwargs):
        email = self.validated_data['email']

        count = 0
        for user in CoreUser.objects.filter(username=email, is_active=True):
            expiry_minutes = 15
            # Invalidate all prior unused codes for this user
            PasswordResetCode.objects.filter(user=user, is_used=False).update(is_used=True)

            # Generate a cryptographically secure 6-digit code
            code = f'{secrets.randbelow(1_000_000):06d}'

            # Persist new code with 15-minute expiry
            PasswordResetCode.objects.create(
                user=user,
                code=code,
                expires_at=timezone.now() + timedelta(minutes=expiry_minutes),
            )

            context = {
                'reset_password_code': code,
                'expiry_minutes': expiry_minutes,
            }

            # default subject and templates
            subject = 'Verify your email'
            template_name = 'email/coreuser/password_reset.txt'
            html_template_name = 'email/coreuser/password_reset.html'
            count += send_email(
                user.email, subject, context, template_name, html_template_name, cc_email_address=settings.SUPPORT_EMAIL_ADDRESS
            )

        return count


class CoreUserResetPasswordCheckSerializer(serializers.Serializer):
    """Serializer for validating 6-digit password reset code payload."""

    email = serializers.EmailField()
    code = serializers.CharField(min_length=6, max_length=6)


class CoreUserResetPasswordConfirmSerializer(serializers.Serializer):
    """Serializer for 6-digit password reset confirm payload (field shape only)."""

    email = serializers.EmailField()
    code = serializers.CharField(min_length=6, max_length=6)
    new_password1 = serializers.CharField(max_length=128)
    new_password2 = serializers.CharField(max_length=128)


class OrganizationSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source='organization_uuid', read_only=True)

    class Meta:
        model = Organization
        fields = '__all__'


class AccessTokenSerializer(serializers.ModelSerializer):
    user = CoreUserSerializer()

    class Meta:
        model = AccessToken
        fields = ('id', 'user', 'token', 'expires')


class RefreshTokenSerializer(serializers.ModelSerializer):
    access_token = AccessTokenSerializer()
    user = CoreUserSerializer()

    class Meta:
        model = RefreshToken
        fields = ('id', 'user', 'token', 'access_token', 'revoked')


class ApplicationSerializer(serializers.ModelSerializer):
    client_id = serializers.CharField(read_only=True, max_length=100)
    client_secret = serializers.CharField(read_only=True, max_length=255)

    class Meta:
        model = Application
        fields = (
            'id',
            'authorization_grant_type',
            'client_id',
            'client_secret',
            'client_type',
            'name',
            'redirect_uris',
        )

    def create(self, validated_data):
        validated_data['client_id'] = secrets.token_urlsafe(75)
        validated_data['client_secret'] = secrets.token_urlsafe(190)
        return super(ApplicationSerializer, self).create(validated_data)


class CoreUserEmailAlertSerializer(serializers.Serializer):
    """
    Serializer for email alert of shipment
    """

    organization_uuid = serializers.UUIDField()
    messages = serializers.JSONField()


class CoreUserStatusBatteryAlertSerializer(serializers.Serializer):
    """
    Serializer for email status or battery alert of shipment
    """

    organization_uuid = serializers.UUIDField()
    message = serializers.JSONField()


class CoreUserEmailShipmentReporSerializer(serializers.Serializer):
    """
    Serializer for email shipment report
    """

    shipment_name = serializers.CharField()
    user_email = serializers.CharField()
    report_pdf = serializers.FileField()


class OrganizationTypeSerializer(serializers.ModelSerializer):
    id = serializers.ReadOnlyField()

    class Meta:
        model = OrganizationType
        fields = '__all__'


class ConsortiumSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(source='consortium_uuid', read_only=True)

    class Meta:
        model = Consortium
        fields = '__all__'
