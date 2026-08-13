import requests

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files import File
from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone as dj_timezone
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
import django_filters
import jwt
from drf_yasg.utils import swagger_auto_schema
from core.models import CoreUser, Organization, CoreGroup, OrganizationType, PasswordResetCode, Invitation
from core.serializers import (
    CoreUserSerializer,
    CoreUserWritableSerializer,
    CoreUserInvitationSerializer,
    CoreUserInvitationResendSerializer,
    CoreUserResetPasswordSerializer,
    CoreUserResetPasswordCheckSerializer,
    CoreUserResetPasswordConfirmSerializer,
    CoreUserEmailAlertSerializer,
    CoreUserStatusBatteryAlertSerializer,
    CoreUserProfileSerializer,
    CoreUserEmailShipmentReporSerializer,
)

from core.permissions import AllowAuthenticatedRead, AllowOnlyOrgAdmin, IsAnchoredOrgAdmin, IsSelf
from core.swagger import (
    COREUSER_INVITE_RESPONSE,
    COREUSER_INVITE_CHECK_RESPONSE,
    COREUSER_INVITE_RESEND_RESPONSE,
    COREUSER_RESETPASS_RESPONSE,
    DETAIL_RESPONSE,
    SUCCESS_RESPONSE,
    TOKEN_QUERY_PARAM,
)
from core.invitations import issue_invitation_email
from core.email_utils import send_email
import logging

from datetime import datetime, timedelta
from pytz import timezone
# from twilio.rest import Client
logger = logging.getLogger(__name__)


class CoreUserViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """
    A core user is an extension of the default User object.  A core user is also the primary relationship for identity
    and access to a logged in user. They are associated with an organization, Group (for permission though WorkflowTeam)
    and WorkflowLevel 1 (again through WorkflowTeam)

    title:
    A core user is an extension of the default User object.

    description:
    A core user is also the primary relationship for identity and access to a logged in user.
    They are associated with an organization, Group (for permission though WorkflowTeam)
    and WorkflowLevel 1 (again through WorkflowTeam)

    retrieve:
    Return the given core user.

    list:
    Return a list of all the existing core users.

    create:
    Create a new core user instance.
    """

    SERIALIZERS_MAP = {
        'default': CoreUserSerializer,
        'create': CoreUserWritableSerializer,
        'update': CoreUserWritableSerializer,
        'partial_update': CoreUserWritableSerializer,
        'update_profile': CoreUserProfileSerializer,
        'invite': CoreUserInvitationSerializer,
        'invite_resend': CoreUserInvitationResendSerializer,
        'reset_password': CoreUserResetPasswordSerializer,
        'reset_password_check': CoreUserResetPasswordCheckSerializer,
        'reset_password_confirm': CoreUserResetPasswordConfirmSerializer,
        'alert': CoreUserEmailAlertSerializer,
        'status_alert': CoreUserStatusBatteryAlertSerializer,
        'battery_alert': CoreUserStatusBatteryAlertSerializer,
        'email_shipment_report': CoreUserEmailShipmentReporSerializer,
    }

    def list(self, request, *args, **kwargs):
        # Use this queryset or the django-filters lib will not work
        queryset = self.filter_queryset(self.get_queryset())
        
        if not request.user.is_global_admin:
            organization_id = request.user.organization_id

            if request.user.is_org_admin:
                reseller_orgs = [organization_id]
                org = Organization.objects.get(pk=organization_id)
                
                if org.is_reseller and org.reseller_customer_orgs:
                    reseller_orgs.extend(org.reseller_customer_orgs)
                
                queryset = queryset.filter(organization_id__in=reseller_orgs)
            else:
                queryset = queryset.filter(organization_id=organization_id)
        
        serializer = self.get_serializer(instance=queryset, context={'request': request}, many=True)
        return Response(serializer.data)

    def retrieve(self, request, *args, **kwargs):
        queryset = self.queryset
        user = get_object_or_404(queryset, pk=kwargs.get('pk'))
        serializer = self.get_serializer(instance=user, context={'request': request})
        return Response(serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        # Authorization is enforced by get_permissions() (AllowOnlyOrgAdmin +
        # IsAnchoredOrgAdmin) and, via get_object(), by IsAnchoredOrgAdmin's
        # object-level check, which confines an org admin to users in the
        # organization their own admin role belongs to.
        user = self.get_object()
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=['GET'], detail=False)
    def me(self, request, *args, **kwargs):
        """
        Gives you the user information based on the user token sent within the request.
        """
        user = request.user
        serializer = self.get_serializer(instance=user, context={'request': request})
        return Response(serializer.data)

    @swagger_auto_schema(
        methods=['post'],
        request_body=CoreUserInvitationSerializer,
        responses=COREUSER_INVITE_RESPONSE,
    )
    @action(methods=['POST'], detail=False)
    def invite(self, request, *args, **kwargs):
        """
        This endpoint is used to invite multiple user at the same time.
        It's expected a list of email, for example:
        {
            'emails': ['john@example.com', 'paul@example.com']
        }
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        emails = request.data.get('emails', [])
        for email in emails:
            if CoreUser.objects.filter(email=email).exists():
                return Response(
                    {'message': 'User with email ' + email + ' already exists.'}, status.HTTP_409_CONFLICT
                )

        links = self.perform_invite(serializer)

        return Response(
            {'detail': 'The invitations were sent successfully.', 'invitations': links},
            status=status.HTTP_200_OK,
        )

    @swagger_auto_schema(
        methods=['get'],
        responses=COREUSER_INVITE_CHECK_RESPONSE,
        manual_parameters=[TOKEN_QUERY_PARAM],
    )
    @action(methods=['GET'], detail=False)
    def invite_check(self, request, *args, **kwargs):
        """
        This endpoint is used to validate an invitation token and return
        information about the invitation. Status codes are unchanged from
        before invitations were tracked -- 200 on success, 401 on every
        failure -- so this stays backwards compatible; the `reason` field
        added to every failure body is purely additive.
        """
        try:
            token = self.request.query_params['token']
        except KeyError:
            return Response(
                {'detail': 'No token is provided.', 'reason': 'invalid'}, status.HTTP_401_UNAUTHORIZED
            )

        try:
            # `verify_exp=False` reads an expired-but-authentic token's
            # payload while still enforcing the signature -- a tampered or
            # mis-signed token still raises DecodeError. Expiry is checked
            # manually below, against the invitation record where one exists.
            decoded = jwt.decode(
                token, settings.SECRET_KEY, algorithms=['HS256'], options={'verify_exp': False},
            )
        except jwt.DecodeError:
            return Response(
                {'detail': 'Token is not valid.', 'reason': 'invalid'}, status.HTTP_401_UNAUTHORIZED
            )

        token_expires_at = datetime.fromtimestamp(decoded['exp'], tz=timezone('UTC'))
        token_is_expired = token_expires_at <= dj_timezone.now()
        jti = decoded.get('jti')

        if jti is None:
            # Legacy (pre-change) link: no `jti` claim, so there is no
            # Invitation row to consult. Behaves exactly as this endpoint
            # did before invitations were tracked -- see the deploy-day
            # tolerance rule.
            if token_is_expired:
                return Response(
                    {'detail': 'This invitation is no longer on record.', 'reason': 'no_record'},
                    status.HTTP_401_UNAUTHORIZED,
                )
            if CoreUser.objects.filter(email=decoded['email']).exists():
                return Response(
                    {'detail': 'Token has been used.', 'reason': 'already_registered'}, status.HTTP_401_UNAUTHORIZED
                )
            return Response(
                {
                    'email': decoded['email'],
                    'organization_name': decoded['organization_name'],
                    'user_role': decoded['user_role'],
                },
                status=status.HTTP_200_OK,
            )

        try:
            invitation = Invitation.objects.select_related('organization').get(token_jti=jti)
        except Invitation.DoesNotExist:
            return Response(
                {'detail': 'This invitation is no longer on record.', 'reason': 'no_record'},
                status.HTTP_401_UNAUTHORIZED,
            )

        if CoreUser.objects.filter(email=invitation.email).exists():
            return Response(
                {'detail': 'Token has been used.', 'reason': 'already_registered'}, status.HTTP_401_UNAUTHORIZED
            )

        if invitation.status == Invitation.STATUS_CANCELLED:
            # Byte-identical to the no_record body above -- cancellation is
            # deliberately indistinguishable from "never recorded".
            return Response(
                {'detail': 'This invitation is no longer on record.', 'reason': 'no_record'},
                status.HTTP_401_UNAUTHORIZED,
            )

        if invitation.status == Invitation.STATUS_SUPERSEDED:
            return Response(
                {'detail': 'A newer invitation has been sent.', 'reason': 'superseded'}, status.HTTP_401_UNAUTHORIZED
            )

        if invitation.status == Invitation.STATUS_ACCEPTED:
            # The CoreUser check above already catches this in practice; a
            # row marked accepted with no matching user is treated as no_record.
            return Response(
                {'detail': 'This invitation is no longer on record.', 'reason': 'no_record'},
                status.HTTP_401_UNAUTHORIZED,
            )

        if invitation.is_valid():
            if not token_is_expired:
                return Response(
                    {
                        'email': invitation.email,
                        # The current name, not the frozen `organization_name_at_issue`.
                        'organization_name': invitation.organization.name,
                        'user_role': invitation.user_role,
                        'expires_at': invitation.expires_at,
                    },
                    status=status.HTTP_200_OK,
                )
            # A stale token while a live one (re-minted, same jti, later
            # expiry) exists.
            return Response(
                {'detail': 'A newer invitation has been sent.', 'reason': 'superseded'}, status.HTTP_401_UNAUTHORIZED
            )

        can_reinvite, reason = invitation.can_reinvite()
        if can_reinvite:
            return Response(
                {
                    'detail': 'Token is expired.',
                    'reason': 'expired',
                    'expires_at': invitation.expires_at,
                    'request_window_closes_at': invitation.reinvite_window_closes_at,
                    'can_request_new': True,
                },
                status.HTTP_401_UNAUTHORIZED,
            )
        return Response(
            {'detail': 'Token is expired.', 'reason': reason, 'expires_at': invitation.expires_at},
            status.HTTP_401_UNAUTHORIZED,
        )

    @swagger_auto_schema(
        methods=['post'],
        request_body=CoreUserInvitationResendSerializer,
        responses=COREUSER_INVITE_RESEND_RESPONSE,
    )
    @action(methods=['POST'], detail=False)
    def invite_resend(self, request, *args, **kwargs):
        """
        Mint a fresh token for an expired, on-record, in-window invitation
        and send it. The request body carries only the original invitation
        token -- no email, no organization, no role -- so there is no
        user-supplied value that isn't covered by the signature. Every
        outcome that isn't "a new invitation was actually sent" collapses
        into the identical `not_renewable` body, so this endpoint cannot be
        used to enumerate invitation or registration state.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data['token']

        not_renewable = Response(
            {'detail': 'This invitation cannot be renewed.', 'reason': 'not_renewable'}, status.HTTP_200_OK,
        )

        try:
            decoded = jwt.decode(
                token, settings.SECRET_KEY, algorithms=['HS256'], options={'verify_exp': False},
            )
        except jwt.DecodeError:
            return not_renewable

        jti = decoded.get('jti')
        if jti is None:
            # Legacy link: no Invitation row can exist for it.
            return not_renewable

        with transaction.atomic():
            try:
                invitation = Invitation.objects.select_for_update().get(token_jti=jti)
            except Invitation.DoesNotExist:
                return not_renewable

            if CoreUser.objects.filter(email=invitation.email).exists():
                return not_renewable

            can_reinvite, _ = invitation.can_reinvite()
            if not can_reinvite:
                return not_renewable

            if invitation.reinvite_count >= settings.INVITATION_REINVITE_MAX_COUNT:
                return Response(
                    {
                        'detail': 'This invitation has been re-sent the maximum number of times.',
                        'reason': 'cap_reached',
                    },
                    status.HTTP_200_OK,
                )

            if invitation.last_reinvite_at is not None:
                cooldown_ends_at = invitation.last_reinvite_at + timedelta(
                    minutes=settings.INVITATION_REINVITE_COOLDOWN_MINUTES
                )
                retry_after = (cooldown_ends_at - dj_timezone.now()).total_seconds()
                if retry_after > 0:
                    return Response(
                        {
                            'detail': 'An invitation was sent recently. Please check your inbox.',
                            'reason': 'cooldown',
                            'retry_after_seconds': int(retry_after),
                        },
                        status.HTTP_200_OK,
                    )

            invitation.reinvite_count += 1
            invitation.last_reinvite_at = dj_timezone.now()
            invitation.save(update_fields=['reinvite_count', 'last_reinvite_at'])

        issue_invitation_email(invitation, is_reinvite=True)

        return Response({'detail': 'A new invitation has been sent.', 'reason': 'sent'}, status.HTTP_200_OK)

    @transaction.atomic
    def perform_invite(self, serializer):

        email_addresses = serializer.validated_data.get('emails')
        org_data = serializer.validated_data.get('org_data')
        country = serializer.validated_data.get('country', '')
        currency = serializer.validated_data.get('currency', '')
        date_format = serializer.validated_data.get('date_format', '')
        time_format = serializer.validated_data.get('time_format', '')
        distance = serializer.validated_data.get('distance', '')
        temperature = serializer.validated_data.get('temperature', '')
        weight = serializer.validated_data.get('weight', '')
        org_timezone = serializer.validated_data.get('org_timezone', '')
        org_language = serializer.validated_data.get('org_language', '')
        user_role = serializer.validated_data.get('user_role', [])

        # Check if organization exists or create new organization
        if org_data.get('organization_type', ''):
            org_data['organization_type'] = OrganizationType.objects.filter(id=org_data['organization_type']).first()

        organization, is_new_org = Organization.objects.get_or_create(**org_data)

        if is_new_org:
            uom_url = settings.TP_SHIPMENT_URL + 'unit_of_measure/'
            data = {
                'organization_uuid': str(organization.organization_uuid),
                'create_date': datetime.today().isoformat(),
                'edit_date': datetime.today().isoformat(),
            }

            if country:
                country_data = {**data, 'unit_of_measure_for': 'Country', 'unit_of_measure': country}
                requests.post(uom_url, data=country_data).json()

            if currency:
                currency_data = {**data, 'unit_of_measure_for': 'Currency', 'unit_of_measure': currency}
                requests.post(uom_url, data=currency_data).json()

            if date_format:
                date_format_data = {**data, 'unit_of_measure_for': 'Date', 'unit_of_measure': date_format}
                requests.post(uom_url, data=date_format_data).json()

            if time_format:
                time_format_data = {**data, 'unit_of_measure_for': 'Time', 'unit_of_measure': time_format}
                requests.post(uom_url, data=time_format_data).json()

            if distance:
                distance_data = {**data, 'unit_of_measure_for': 'Distance', 'unit_of_measure': distance}
                requests.post(uom_url, data=distance_data).json()

            if temperature:
                temperature_data = {**data, 'unit_of_measure_for': 'Temperature', 'unit_of_measure': temperature}
                requests.post(uom_url, data=temperature_data).json()

            if weight:
                weight_data = {**data, 'unit_of_measure_for': 'Weight', 'unit_of_measure': weight}
                requests.post(uom_url, data=weight_data).json()

            if org_timezone:
                org_timezone_data = {**data, 'unit_of_measure_for': 'Time Zone', 'unit_of_measure': org_timezone}
                requests.post(uom_url, data=org_timezone_data).json()

            if org_language:
                org_language_data = {**data, 'unit_of_measure_for': 'Language', 'unit_of_measure': org_language}
                requests.post(uom_url, data=org_language_data).json()

        registered_emails = CoreUser.objects.filter(email__in=email_addresses).values_list('email', flat=True)
        invited_by = self.request.user if self.request.user.is_authenticated else None

        links = []
        for email_address in email_addresses:
            if email_address not in registered_emails:
                # Repeat invite to the same address: supersede, then create
                # -- only one pending invitation is ever live per address,
                # matching PasswordResetCode's is_used=True precedent for
                # old, unused codes (never deleted).
                Invitation.objects.filter(
                    email=email_address, status=Invitation.STATUS_PENDING,
                ).update(status=Invitation.STATUS_SUPERSEDED)

                expires_at = dj_timezone.now() + timedelta(hours=settings.INVITATION_EXPIRE_HOURS)
                invitation = Invitation.objects.create(
                    email=email_address,
                    organization=organization,
                    organization_name_at_issue=organization.name,
                    user_role=user_role,
                    invited_by=invited_by,
                    expires_at=expires_at,
                    original_expires_at=expires_at,
                )

                invitation_link = issue_invitation_email(invitation, is_reinvite=False)
                links.append(invitation_link)

        return links

    @swagger_auto_schema(
        methods=['post'],
        request_body=CoreUserResetPasswordSerializer,
        responses=COREUSER_RESETPASS_RESPONSE,
    )
    @action(methods=['POST'], detail=False)
    def reset_password(self, request, *args, **kwargs):
        """
        This endpoint is used to request password resetting.
        It requests the Email field
        """
        logger.warning('EMAIL EVENT!')
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        count = serializer.save()
        return Response(
            {
                'detail': 'The reset password code was sent successfully.',
                'count': count,
            },
            status=status.HTTP_200_OK,
        )

    @swagger_auto_schema(
        methods=['post'],
        request_body=CoreUserResetPasswordCheckSerializer,
        responses=DETAIL_RESPONSE,
    )
    @action(methods=['POST'], detail=False)
    def reset_password_check(self, request, *args, **kwargs):
        """
        Verify that a 6-digit password reset code is valid for the given email.
        Always returns HTTP 200; the `is_valid` flag in the body indicates outcome.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        code = serializer.validated_data['code']

        user = CoreUser.objects.filter(username=email).first()
        if user:
            reset_code = PasswordResetCode.objects.filter(
                user=user,
                code=code,
                is_used=False,
            ).first()
            if reset_code and reset_code.is_valid():
                return Response(
                    {
                        'message': 'Reset code verified and found valid',
                        'is_valid': True,
                    },
                    status=status.HTTP_200_OK,
                )

        return Response(
            {
                'message': 'Invalid code or code has expired. Please resend code and try again.',
                'is_valid': False,
            },
            status=status.HTTP_200_OK,
        )

    @swagger_auto_schema(
        methods=['post'],
        request_body=CoreUserResetPasswordConfirmSerializer,
        responses=DETAIL_RESPONSE,
    )
    @action(methods=['POST'], detail=False)
    def reset_password_confirm(self, request, *args, **kwargs):
        """
        Confirm a password reset using a 6-digit code.
        Sets the new password and marks the code as used to prevent replay.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        code = serializer.validated_data['code']
        new_password1 = serializer.validated_data['new_password1']
        new_password2 = serializer.validated_data['new_password2']

        if new_password1 != new_password2:
            return Response(
                {'message': "The two password fields didn't match."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        failure_response = Response(
            {'message': 'Invalid code or code has expired. Please resend code and try again.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

        user = CoreUser.objects.filter(username=email, is_active=True).first()
        if not user:
            return failure_response

        reset_code = PasswordResetCode.objects.filter(
            user=user,
            code=code,
            is_used=False,
        ).first()
        if not reset_code or not reset_code.is_valid():
            return failure_response

        try:
            password_validation.validate_password(new_password1, user)
        except DjangoValidationError as exc:
            return Response(
                {'message': exc.messages[0]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            user.set_password(new_password1)
            user.save()
            reset_code.is_used = True
            reset_code.save()

        return Response(
            {'message': 'The password was changed successfully.'},
            status=status.HTTP_200_OK,
        )

    def get_serializer_class(self):
        action_ = getattr(self, 'action', 'default')
        return self.SERIALIZERS_MAP.get(action_, self.SERIALIZERS_MAP['default'])

    def get_permissions(self):
        if hasattr(self, 'action'):
            # different permissions when creating a new user or resetting password
            if self.action in [
                'create',
                'reset_password',
                'reset_password_check',
                'reset_password_confirm',
                'invite_check',
                'invite_resend',
            ]:
                return [permissions.AllowAny()]

            if self.action in ['update', 'partial_update', 'invite', 'destroy']:
                return [AllowOnlyOrgAdmin(), IsAnchoredOrgAdmin()]

            # update_profile edits the caller's own record only -- no
            # org-admin or global-admin branch. See core.permissions.IsSelf.
            if self.action == 'update_profile':
                return [AllowAuthenticatedRead(), IsSelf()]

        return super(CoreUserViewSet, self).get_permissions()

    def get_throttles(self):
        # Narrowest possible introduction of throttling: only invite_resend
        # opts in (via `throttle_scope`, below), and DEFAULT_THROTTLE_CLASSES
        # stays empty so no other endpoint's behaviour changes. Set as a
        # class attribute rather than an `@action` kwarg so it also applies
        # when the view is dispatched directly (as the test suite does),
        # not only through a router.
        if getattr(self, 'action', None) == 'invite_resend':
            self.throttle_scope = 'invite_resend'
            return [ScopedRateThrottle()]
        return super(CoreUserViewSet, self).get_throttles()

    filterset_fields = ('organization__organization_uuid',)
    filter_backends = (django_filters.rest_framework.DjangoFilterBackend,)
    queryset = CoreUser.objects.all()
    permission_classes = (AllowAuthenticatedRead,)

    @swagger_auto_schema(
        methods=['post'],
        request_body=CoreUserEmailAlertSerializer,
        responses=SUCCESS_RESPONSE,
    )
    @action(methods=['POST'], detail=False)
    def alert(self, request, *args, **kwargs):
        """
        a)Request alert message and uuid of organization
        b)Access user uuids for that respective organization
        c)Check if opted for email alert service
        d)Send Email to the user's email with alert message
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org_uuid = request.data['organization_uuid']
        messages = request.data['messages']
        try:
            for message in messages:
                subject = message['header']
                message['color'] = color_codes.get(message['severity'])
                context = {'message': message}
                alert_time = datetime.strptime(message['alert_time'], "%Y-%m-%dT%H:%M:%S.%f%z")
                template_name = 'email/coreuser/shipment_alert.txt'
                html_template_name = 'email/coreuser/shipment_alert.html'

                # Set shipment url
                message['shipment_url'] = settings.FRONTEND_URL + 'app/reporting/?shipment=' + message['shipment_id']

                # Get Currency default for the organization
                uom_currency_url = (
                    settings.TP_SHIPMENT_URL
                    + 'unit_of_measure/?organization_uuid='
                    + org_uuid
                    + '&unit_of_measure_for=Currency'
                )
                uom_currency = requests.get(uom_currency_url).json()[0]
                message['currency'] = ' ' + uom_currency.get('unit_of_measure')

                # TODO send email via preferences
                core_users = CoreUser.objects.filter(
                    organization__organization_uuid=org_uuid
                )
                for user in core_users:
                    email_address = user.email
                    geo_preferences = user.geo_alert_preferences
                    env_preferences = user.env_alert_preferences
                    if ((geo_preferences and geo_preferences.get('email', False))
                        or (env_preferences and env_preferences.get('email', False))):
                            user_timezone = user.user_timezone
                            if user_timezone:
                                message['local_time'] = alert_time.astimezone(timezone(user_timezone)).strftime('%-d %b, %Y %-I:%M:%S %p %Z')
                            else:
                                message['local_time'] = alert_time.strftime('%-d %b, %Y %-I:%M:%S %p %Z')
                            send_email(
                                email_address,
                                subject,
                                context,
                                template_name,
                                html_template_name,
                            )
        except Exception as ex:
            print('Exception: ', ex)
        return Response(
            {'detail': 'The alert messages were sent successfully on email.'},
            status=status.HTTP_200_OK,
        )
        # This code is commented out as in future, It will need to impliment message service.
        # for phone in phones:
        #     phone_number = phone
        #     account_sid = os.environ['TWILIO_ACCOUNT_SID']
        #     auth_token = os.environ['TWILIO_AUTH_TOKEN']
        #     client = Client(account_sid, auth_token)
        #     message = client.messages.create(
        #                     body=alert_message,
        #                     from_='+15082068927',
        #                     to=phone_number
        #                 )
        #     print(message.sid)

    @swagger_auto_schema(
        methods=['post'],
        request_body=CoreUserStatusBatteryAlertSerializer,
        responses=SUCCESS_RESPONSE,
    )
    @action(methods=['POST'], detail=False)
    def status_alert(self, request, *args, **kwargs):
        """
        a)Request alert message and uuid of organization
        b)Access user uuids for that respective organization
        c)Check if opted for email alert service
        d)Send Email to the user's email with alert message
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org_uuid = request.data['organization_uuid']
        message = request.data['message']
        try:
            subject = message['header']
            message['color'] = color_codes.get(message['severity'])
            context = {'message': message}
            template_name = 'email/coreuser/status_alert.txt'
            html_template_name = 'email/coreuser/status_alert.html'

            # Set shipment url
            message['shipment_url'] = settings.FRONTEND_URL + 'app/reporting/?shipment=' + message['shipment_id']

            # Get UOM for date and time
            if message['scheduled_departure']:
                DATE_TIME_FORMAT_1 = '%Y-%m-%dT%H:%M:%S.%fZ'
                DATE_TIME_FORMAT_2 = '%Y-%m-%dT%H:%M:%SZ'
                DATE_TIME_FORMAT_3 = '%Y-%m-%dT%H:%M:%S.%f%z'
                uoms = requests.get(settings.TP_SHIPMENT_URL + 'unit_of_measure/?organization_uuid=' + str(org_uuid)).json()

                try:
                    datetime_format = datetime.strptime(message['scheduled_departure'], DATE_TIME_FORMAT_1)
                except ValueError:
                    try:
                        datetime_format = datetime.strptime(message['scheduled_departure'], DATE_TIME_FORMAT_2)
                    except ValueError:
                        datetime_format = datetime.strptime(message['scheduled_departure'], DATE_TIME_FORMAT_3)

                org_date_time_format = ''

                if len(uoms) > 0:
                    date_format = [uom for uom in uoms if uom['unit_of_measure_for'].lower() == 'date'][0]['unit_of_measure']
                    time_format = [uom for uom in uoms if uom['unit_of_measure_for'].lower() == 'time'][0]['unit_of_measure']

                if date_format == 'MMM DD, YYYY':
                    org_date_time_format = '%b %d, %Y'
                elif date_format == 'DD MMM, YYYY':
                    org_date_time_format = '%d %b, %Y'
                elif date_format == 'MM/DD/YYYY':
                    org_date_time_format = '%m/%d/%Y'
                elif date_format == 'DD/MM/YYYY':
                    org_date_time_format = '%d/%m/%Y'

                if time_format == 'hh:mm:ss A':
                    org_date_time_format = org_date_time_format + ' %I:%M:%S %p %Z'
                elif time_format == 'HH:mm:ss':
                    org_date_time_format = org_date_time_format + ' %H:%M:%S %Z'

            # TODO send email via preferences
            core_users = CoreUser.objects.filter(
                organization__organization_uuid=org_uuid, 
            )
            for user in core_users:
                email_address = user.email
                geo_preferences = user.geo_alert_preferences
                env_preferences = user.env_alert_preferences
                if message['scheduled_departure']:
                    message['scheduled_departure'] = datetime_format.astimezone(timezone(user.user_timezone)).strftime(org_date_time_format)

                if ((geo_preferences and geo_preferences.get('email', False))
                    or (env_preferences and env_preferences.get('email', False))):
                        send_email(
                            email_address,
                            subject,
                            context,
                            template_name,
                            html_template_name,
                        )
        except Exception as ex:
            print('Exception: ', ex)
        return Response(
            {'detail': 'Status alert messages were sent successfully on email.'},
            status=status.HTTP_200_OK,
        )
    
    @swagger_auto_schema(
        methods=['post'],
        request_body=CoreUserStatusBatteryAlertSerializer,
        responses=SUCCESS_RESPONSE,
    )
    @action(methods=['POST'], detail=False)
    def battery_alert(self, request, *args, **kwargs):
        """
        a)Request alert message and uuid of organization
        b)Access user uuids for that respective organization
        c)Check if opted for email alert service
        d)Send Email to the user's email with alert message
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        org_uuid = request.data['organization_uuid']
        message = request.data['message']
        try:
            subject = message['header']
            message['color'] = color_codes.get(message['severity'])
            context = {'message': message}
            template_name = 'email/coreuser/battery_alert.txt'
            html_template_name = 'email/coreuser/battery_alert.html'

            # Set shipment url
            message['shipment_url'] = settings.FRONTEND_URL + 'app/reporting/?shipment=' + message['shipment_id']

            # TODO send email via preferences
            core_users = CoreUser.objects.filter(
                organization__organization_uuid=org_uuid, 
            )
            for user in core_users:
                email_address = user.email
                geo_preferences = user.geo_alert_preferences
                env_preferences = user.env_alert_preferences
                if ((geo_preferences and geo_preferences.get('email', False))
                    or (env_preferences and env_preferences.get('email', False))):
                        send_email(
                            email_address,
                            subject,
                            context,
                            template_name,
                            html_template_name,
                        )
        except Exception as ex:
            print('Exception: ', ex)
        return Response(
            {'detail': 'Battery alert messages were sent successfully on email.'},
            status=status.HTTP_200_OK,
        )
    
    @swagger_auto_schema(
        methods=['post'],
        request_body=CoreUserStatusBatteryAlertSerializer,
        responses=SUCCESS_RESPONSE,
    )
    @action(methods=['POST'], detail=False)
    def email_shipment_report(self, request, *args, **kwargs):
        """
        a)Request user email and attachment files
        b)Send Email to the user's email with attachements
        """

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        shipment_name = request.data['shipment_name']
        user_email = request.data['user_email']
        report_pdf = request.FILES['report_pdf']

        try:
            subject = 'Shipment Report PDF for shipment {0}'.format(shipment_name)
            context = {"message": {"shipment_name": shipment_name}}
            template_name = 'email/coreuser/shipment_report.txt'
            html_template_name = 'email/coreuser/shipment_report.html'

            send_email(
                user_email,
                subject,
                context,
                template_name,
                html_template_name,
                [dict(file=report_pdf.read(), name=report_pdf.name)],
            )
            return Response(
                {'detail': 'Report for shipment {0} was sent successfully to user.'.format(shipment_name)},
                status=status.HTTP_200_OK,
            )

        except Exception as ex:
            print('Exception: ', ex)
            return Response(
                {'detail': f'Report for shipment {0} was not sent to user.'.format(shipment_name)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    @action(detail=True, methods=['patch'], name='Update Profile')
    def update_profile(self, request, pk=None, *args, **kwargs):
        """
        Update a user Profile
        """
        # the particular user in CoreUser table
        user = self.get_object()
        serializer = CoreUserProfileSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


color_codes = {'error': '#FF0033', 'info': '#0099CC', 'success': '#009900'}
