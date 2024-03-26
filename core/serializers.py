import jwt
import requests
import secrets

from urllib.parse import urljoin

from django.contrib.auth import password_validation
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from django.utils.encoding import force_bytes, force_text
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
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
    TEMPLATE_RESET_PASSWORD,
    OrganizationType,
    Consortium,
)


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
        except jwt.DecodeError:
            raise serializers.ValidationError('Token is not valid.')
        except jwt.ExpiredSignatureError:
            raise serializers.ValidationError('Token is expired.')
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
        )
        read_only_fields = ('core_user_uuid', 'organization')
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
        # get or create organization
        try:
            organization = validated_data.pop('organization')
        except (KeyError):
            organization = {'name': settings.DEFAULT_ORG}
        organization, is_new_org = Organization.objects.get_or_create(**organization)

        core_groups = validated_data.pop('core_groups', [])
        user_role = validated_data.pop('user_role', '')

        if user_role:
            core_groups = CoreGroup.objects.filter(name=user_role, organization=organization.organization_uuid)

        # create core user
        invitation_token = validated_data.pop('invitation_token', None)
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
            default_timezone = requests.get(uom_timezone_url).json()[0]
            coreuser.user_timezone = default_timezone['unit_of_measure']

        coreuser.core_groups.set(core_groups)
        coreuser.save()

        # create the used context for the E-mail templates
        body_text = 'Administrator ' if 'admins' in user_role.lower() else core_groups[0].name
        body_text += ' Account for ' + organization.name + ' was successfully created.'

        context = {
            'signin_link': settings.FRONTEND_URL,
            'organization_name': organization.name,
            'body_text': body_text,
        }
        subject = 'Administrator Account Setup' if 'admins' in user_role.lower() else 'Account Setup'
        template_name = 'email/coreuser/account_setup.txt'
        html_template_name = 'email/coreuser/account_setup.html'
        send_email(
            coreuser.email, subject, context, template_name, html_template_name
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
    last_gdpr_shown = serializers.DateTimeField(required=False)

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
        )

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
        instance.user_timezone = validated_data.get(
            'user_timezone', instance.user_timezone
        )
        instance.last_gdpr_shown = validated_data.get('last_gdpr_shown', instance.last_gdpr_shown)
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
    user_role = serializers.CharField(required=False)


class CoreUserResetPasswordSerializer(serializers.Serializer):
    """Serializer for reset password request data
    """

    email = serializers.EmailField()

    def save(self, **kwargs):
        resetpass_url = urljoin(
            settings.FRONTEND_URL, settings.RESETPASS_CONFIRM_URL_PATH
        )
        resetpass_url = resetpass_url + '{uid}/{token}/'

        email = self.validated_data["email"]

        count = 0
        for user in CoreUser.objects.filter(email=email, is_active=True):
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            context = {
                'password_reset_link': resetpass_url.format(uid=uid, token=token),
                'user': user,
            }

            # get specific subj and templates for user's organization
            tpl = EmailTemplate.objects.filter(
                organization=user.organization, type=TEMPLATE_RESET_PASSWORD
            ).first()
            if not tpl:
                tpl = EmailTemplate.objects.filter(
                    organization__name=settings.DEFAULT_ORG,
                    type=TEMPLATE_RESET_PASSWORD,
                ).first()
            if tpl and tpl.template:
                context = Context(context)
                text_content = Template(tpl.template).render(context)
                html_content = (
                    Template(tpl.template_html).render(context)
                    if tpl.template_html
                    else None
                )
                count += send_email_body(email, tpl.subject, text_content, html_content)
                continue

            # default subject and templates
            subject = 'Update Password'
            template_name = 'email/coreuser/password_reset.txt'
            html_template_name = 'email/coreuser/password_reset.html'
            count += send_email(
                email, subject, context, template_name, html_template_name
            )

        return count


class CoreUserResetPasswordCheckSerializer(serializers.Serializer):
    """Serializer for checking token for resetting password
    """

    uid = serializers.CharField()
    token = serializers.CharField()

    def validate(self, attrs):
        # Decode the uidb64 to uid to get User object
        try:
            uid = force_text(urlsafe_base64_decode(attrs['uid']))
            self.user = CoreUser.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, CoreUser.DoesNotExist):
            raise serializers.ValidationError({'uid': ['Invalid value']})

        # Check the token
        if not default_token_generator.check_token(self.user, attrs['token']):
            raise serializers.ValidationError({'token': ['Invalid value']})

        return attrs


class CoreUserResetPasswordConfirmSerializer(CoreUserResetPasswordCheckSerializer):
    """Serializer for reset password data
    """

    new_password1 = serializers.CharField(max_length=128)
    new_password2 = serializers.CharField(max_length=128)

    def validate(self, attrs):

        attrs = super().validate(attrs)

        password1 = attrs.get('new_password1')
        password2 = attrs.get('new_password2')
        if password1 != password2:
            raise serializers.ValidationError("The two password fields didn't match.")
        password_validation.validate_password(password2, self.user)

        return attrs

    def save(self):
        self.user.set_password(self.validated_data["new_password1"])
        self.user.save()
        return self.user


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
    Serializer for email alert of shipment
    """

    organization_uuid = serializers.UUIDField()
    message = serializers.JSONField()


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
