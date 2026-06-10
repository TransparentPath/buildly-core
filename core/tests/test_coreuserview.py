import json
import re
from datetime import date, timedelta
from unittest import mock

import pytest
from django.core import mail
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from rest_framework.reverse import reverse

import factories
from core.models import CoreUser, PasswordResetCode
from core.views import CoreUserViewSet
from core.jwt_utils import create_invitation_token
from core.tests.fixtures import (
    TEST_USER_DATA,
    org_admin,
    org_member,
    org,
    reset_password_request,
)


@pytest.mark.django_db()
def test_coreuser_views_permissions_unauth(request_factory):
    # has no permission
    request = request_factory.get(reverse('coreuser-list'))
    response = CoreUserViewSet.as_view({'get': 'list'})(request)
    assert response.status_code == 403

    # has permission but need to send data
    request = request_factory.post(reverse('coreuser-list'))
    response = CoreUserViewSet.as_view({'post': 'create'})(request)
    assert response.status_code == 400

    # has no permission
    request = request_factory.post(reverse('coreuser-invite'))
    response = CoreUserViewSet.as_view({'post': 'invite'})(request)
    assert response.status_code == 403

    # not authorized (without token parameter)
    request = request_factory.get(reverse('coreuser-invite-check'))
    response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
    assert response.status_code == 401

    # has no permission
    request = request_factory.get(reverse('coreuser-detail', args=(1,)))
    response = CoreUserViewSet.as_view({'get': 'retrieve'})(request, pk=1)
    assert response.status_code == 403

    # has no permission
    request = request_factory.put(reverse('coreuser-detail', args=(1,)))
    response = CoreUserViewSet.as_view({'put': 'update'})(request, pk=1)
    assert response.status_code == 403

    # has no permission
    request = request_factory.patch(reverse('coreuser-detail', args=(1,)))
    response = CoreUserViewSet.as_view({'patch': 'partial_update'})(request, pk=1)
    assert response.status_code == 403


@pytest.mark.django_db()
def test_coreuser_views_permissions_org_member(request_factory, org_member):
    pk = org_member.pk

    # has permission
    request = request_factory.get(reverse('coreuser-list'))
    request.user = org_member
    response = CoreUserViewSet.as_view({'get': 'list'})(request)
    assert response.status_code == 200

    # has no permission
    request = request_factory.post(reverse('coreuser-invite'))
    request.user = org_member
    response = CoreUserViewSet.as_view({'post': 'invite'})(request)
    assert response.status_code == 403

    # has permission
    request = request_factory.get(reverse('coreuser-detail', args=(pk,)))
    request.user = org_member
    response = CoreUserViewSet.as_view({'get': 'retrieve'})(request, pk=pk)
    assert response.status_code == 200

    # has no permission
    request = request_factory.put(reverse('coreuser-detail', args=(pk,)))
    request.user = org_member
    response = CoreUserViewSet.as_view({'put': 'update'})(request, pk=pk)
    assert response.status_code == 403

    # has no permission
    request = request_factory.patch(reverse('coreuser-detail', args=(1,)))
    request.user = org_member
    response = CoreUserViewSet.as_view({'patch': 'partial_update'})(request, pk=1)
    assert response.status_code == 403


@pytest.mark.django_db()
class TestCoreUserCreate:
    def test_registration_fail(self, request_factory):
        # check that 'password' and 'organization name' fields are required
        for field_name in ['password', 'organization_name']:
            data = TEST_USER_DATA.copy()
            data.pop(field_name)
            request = request_factory.post(reverse('coreuser-list'), data)
            response = CoreUserViewSet.as_view({'post': 'create'})(request)
            assert response.status_code == 400

    def test_registration_of_first_org_user(self, request_factory):
        request = request_factory.post(reverse('coreuser-list'), TEST_USER_DATA)
        response = CoreUserViewSet.as_view({'post': 'create'})(request)
        assert response.status_code == 201

        user = CoreUser.objects.get(username=TEST_USER_DATA['username'])
        assert user.email == TEST_USER_DATA['email']
        assert user.first_name == TEST_USER_DATA['first_name']
        assert user.last_name == TEST_USER_DATA['last_name']
        assert user.organization.name == TEST_USER_DATA['organization_name']
        assert user.is_active

        # check this user is org admin
        assert user.is_org_admin

    def test_registration_of_second_org_user(self, request_factory, org_admin):
        request = request_factory.post(reverse('coreuser-list'), TEST_USER_DATA)
        response = CoreUserViewSet.as_view({'post': 'create'})(request)
        assert response.status_code == 201

        user = CoreUser.objects.get(username=TEST_USER_DATA['username'])
        assert user.email == TEST_USER_DATA['email']
        assert user.first_name == TEST_USER_DATA['first_name']
        assert user.last_name == TEST_USER_DATA['last_name']
        assert user.organization.name == TEST_USER_DATA['organization_name']
        assert not user.is_active

        # check this user is org admin as well
        assert user.is_org_admin

    def test_registration_of_invited_org_user(self, request_factory, org_admin):
        data = TEST_USER_DATA.copy()
        token = create_invitation_token(data['email'], org_admin.organization, data['user_role'])
        data['invitation_token'] = token

        request = request_factory.post(reverse('coreuser-list'), data)
        response = CoreUserViewSet.as_view({'post': 'create'})(request)
        assert response.status_code == 201

        user = CoreUser.objects.get(username=TEST_USER_DATA['username'])
        assert user.email == TEST_USER_DATA['email']
        assert user.first_name == TEST_USER_DATA['first_name']
        assert user.last_name == TEST_USER_DATA['last_name']
        assert user.organization.name == TEST_USER_DATA['organization_name']
        assert user.is_active

        # check this user is org admin as well
        assert user.is_org_admin

    def test_reused_token_invalidation(self, request_factory, org_admin):
        data = TEST_USER_DATA.copy()
        registered_user = factories.CoreUser.create(
            is_active=False, email=data['email'], username='user_org'
        )
        token = create_invitation_token(data['email'], org_admin.organization, data['user_role'])
        data['invitation_token'] = token

        request = request_factory.post(reverse('coreuser-list'), data)
        response = CoreUserViewSet.as_view({'post': 'create'})(request)
        assert response.status_code == 400

    def test_email_mismatch_token_invalidation(self, request_factory, org_admin):
        data = TEST_USER_DATA.copy()
        token = create_invitation_token("foobar@example.com", org_admin.organization, data['user_role'])
        data['invitation_token'] = token

        request = request_factory.post(reverse('coreuser-list'), data)
        response = CoreUserViewSet.as_view({'post': 'create'})(request)
        assert response.status_code == 400


@pytest.mark.django_db()
class TestCoreUserUpdate:
    def test_coreuser_update(self, request_factory, org_admin):
        user = factories.CoreUser.create(
            is_active=False, organization=org_admin.organization, username='org_user'
        )
        pk = user.pk

        data = {'is_active': True}
        request = request_factory.patch(reverse('coreuser-detail', args=(pk,)), data)
        request.user = org_admin
        response = CoreUserViewSet.as_view({'patch': 'partial_update'})(request, pk=pk)
        assert response.status_code == 200
        coreuser = CoreUser.objects.get(pk=pk)
        assert coreuser.is_active

    def test_coreuser_update_dif_org(self, request_factory, org_admin):
        dif_org = factories.Organization(name='Another Org')
        user = factories.CoreUser.create(
            is_active=False, organization=dif_org, username='another_org_user'
        )
        pk = user.pk

        data = {'is_active': True}
        request = request_factory.patch(reverse('coreuser-detail', args=(pk,)), data)
        request.user = org_admin
        response = CoreUserViewSet.as_view({'patch': 'partial_update'})(request, pk=pk)
        assert response.status_code == 403

    def test_coreuser_update_groups(self, request_factory, org_admin):
        user = factories.CoreUser.create(
            is_active=False, organization=org_admin.organization, username='user_org'
        )
        initial_groups = factories.CoreGroup.create_batch(
            2, organization=user.organization
        )
        user.core_groups.add(*initial_groups)
        pk = user.pk

        new_groups = factories.CoreGroup.create_batch(2, organization=user.organization)
        data = {'core_groups': [item.pk for item in new_groups]}
        request = request_factory.patch(reverse('coreuser-detail', args=(pk,)), data)
        request.user = org_admin
        response = CoreUserViewSet.as_view({'patch': 'partial_update'})(request, pk=pk)
        assert response.status_code == 200
        coreuser = CoreUser.objects.get(pk=pk)
        assert set(coreuser.core_groups.all()) == set(new_groups)


@pytest.mark.django_db()
class TestCoreUserInvite:
    def test_invitation(self, request_factory, org_admin):
        data = {'emails': [TEST_USER_DATA['email']], 'org_data': json.dumps({ 'name': TEST_USER_DATA['organization_name'] }), 'user_role': TEST_USER_DATA['user_role']}
        request = request_factory.post(reverse('coreuser-invite'), data)
        request.user = org_admin
        response = CoreUserViewSet.as_view({'post': 'invite'})(request)
        assert response.status_code == 200
        assert len(response.data['invitations']) == 1

    def test_invitation_check(self, request_factory, org):
        token = create_invitation_token(TEST_USER_DATA['email'], org, TEST_USER_DATA['user_role'])
        request = request_factory.get(
            reverse('coreuser-invite-check'), {'token': token}
        )
        response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
        assert response.status_code == 200
        assert response.data['email'] == TEST_USER_DATA['email']
        assert response.data['organization_name'] == TEST_USER_DATA['organization_name']
        assert response.data['user_role'] == TEST_USER_DATA['user_role']

    def test_prevent_token_reuse(self, request_factory, org):
        token = create_invitation_token(TEST_USER_DATA['email'], org, TEST_USER_DATA['user_role'])
        registered_user = factories.CoreUser.create(
            is_active=False, email=TEST_USER_DATA['email'], username='user_org'
        )
        request = request_factory.get(
            reverse('coreuser-invite-check'), {'token': token}
        )
        response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
        assert response.status_code == 401


@pytest.mark.django_db()
class TestResetPassword(object):
    def test_reset_password_sends_code(self, request_factory, org):
        # Username is an email-format value so it passes EmailField validation
        user = factories.CoreUser.create(
            organization=org,
            username='user@example.com',
            email='user@example.com',
            is_active=True,
        )
        request = request_factory.post(
            reverse('coreuser-reset-password'), {'email': 'user@example.com'}
        )
        response = CoreUserViewSet.as_view({'post': 'reset_password'})(request)
        assert response.status_code == 200
        assert response.data['count'] == 1
        assert mail.outbox

        message = mail.outbox[0]
        assert message.to == [user.email]
        assert re.search(r'\b\d{6}\b', message.body)

        assert PasswordResetCode.objects.filter(user=user).exists()

    def test_reset_password_no_user(self, request_factory):
        request = request_factory.post(
            reverse('coreuser-reset-password'), {'email': 'foo@example.com'}
        )
        response = CoreUserViewSet.as_view({'post': 'reset_password'})(request)
        assert response.status_code == 200
        assert response.data['count'] == 0

    def test_reset_password_matches_on_username_not_email(self, request_factory, org):
        # Create a user whose username (login) differs from their contact email.
        # Both must be valid email format since the serializer uses EmailField.
        user = factories.CoreUser.create(
            organization=org,
            username='jane.login@example.com',
            email='jane.contact@example.com',
            is_active=True,
        )

        # Posting the username value → lookup by username matches → email sent
        request = request_factory.post(
            reverse('coreuser-reset-password'), {'email': 'jane.login@example.com'}
        )
        response = CoreUserViewSet.as_view({'post': 'reset_password'})(request)
        assert response.status_code == 200
        assert response.data['count'] == 1
        assert len(mail.outbox) == 1

        # Posting the contact email address → no match on username → count 0
        mail.outbox.clear()
        request = request_factory.post(
            reverse('coreuser-reset-password'), {'email': 'jane.contact@example.com'}
        )
        response = CoreUserViewSet.as_view({'post': 'reset_password'})(request)
        assert response.status_code == 200
        assert response.data['count'] == 0
        assert len(mail.outbox) == 0

    def test_reset_password_inactive_user_skipped(self, request_factory, org):
        user = factories.CoreUser.create(
            organization=org,
            username='inactive@example.com',
            email='inactive@example.com',
            is_active=False,
        )
        request = request_factory.post(
            reverse('coreuser-reset-password'), {'email': 'inactive@example.com'}
        )
        response = CoreUserViewSet.as_view({'post': 'reset_password'})(request)
        assert response.status_code == 200
        assert response.data['count'] == 0
        assert len(mail.outbox) == 0
        assert not PasswordResetCode.objects.filter(user=user).exists()

    def test_reset_password_marks_previous_codes_expired(self, request_factory, org):
        user = factories.CoreUser.create(
            organization=org,
            username='repeat@example.com',
            email='repeat@example.com',
            is_active=True,
        )

        # First request
        request = request_factory.post(
            reverse('coreuser-reset-password'), {'email': 'repeat@example.com'}
        )
        CoreUserViewSet.as_view({'post': 'reset_password'})(request)

        first_code = PasswordResetCode.objects.filter(user=user).first()
        assert first_code is not None
        assert first_code.is_used is False

        # Second request — previous code must be marked used
        request = request_factory.post(
            reverse('coreuser-reset-password'), {'email': 'repeat@example.com'}
        )
        CoreUserViewSet.as_view({'post': 'reset_password'})(request)

        first_code.refresh_from_db()
        assert first_code.is_used is True

        latest_code = PasswordResetCode.objects.filter(user=user, is_used=False).first()
        assert latest_code is not None
        assert latest_code.pk != first_code.pk

    def test_reset_password_code_format(self, request_factory, org):
        user = factories.CoreUser.create(
            organization=org,
            username='format@example.com',
            email='format@example.com',
            is_active=True,
        )
        request = request_factory.post(
            reverse('coreuser-reset-password'), {'email': 'format@example.com'}
        )
        CoreUserViewSet.as_view({'post': 'reset_password'})(request)

        code_obj = PasswordResetCode.objects.filter(user=user).first()
        assert code_obj is not None
        assert len(code_obj.code) == 6
        assert code_obj.code.isdigit()

    def test_reset_password_code_expires_at_15_minutes(self, request_factory, org):
        user = factories.CoreUser.create(
            organization=org,
            username='expiry@example.com',
            email='expiry@example.com',
            is_active=True,
        )
        request = request_factory.post(
            reverse('coreuser-reset-password'), {'email': 'expiry@example.com'}
        )
        CoreUserViewSet.as_view({'post': 'reset_password'})(request)

        code_obj = PasswordResetCode.objects.filter(user=user).first()
        assert code_obj is not None
        delta = code_obj.expires_at - code_obj.created_at
        assert abs(delta.total_seconds() - 900) < 5  # 15 minutes ± 5 seconds

    def test_reset_password_email_sent_to_user_email_not_username(self, request_factory, org):
        # username is the login identifier; email is the actual delivery address
        user = factories.CoreUser.create(
            organization=org,
            username='delivery.login@example.com',
            email='delivery.actual@example.com',
            is_active=True,
        )
        request = request_factory.post(
            reverse('coreuser-reset-password'), {'email': 'delivery.login@example.com'}
        )
        CoreUserViewSet.as_view({'post': 'reset_password'})(request)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == ['delivery.actual@example.com']

    def test_reset_password_check(self, request_factory, reset_password_request):
        user, uid, token = reset_password_request
        data = {'uid': uid, 'token': token}
        request = request_factory.post(reverse('coreuser-reset-password-check'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_check'})(request)
        assert response.status_code == 200
        assert response.data['success'] is True

    def test_reset_password_check_expired(
        self, request_factory, reset_password_request
    ):
        user, uid, token = reset_password_request
        data = {'uid': uid, 'token': token}
        mock_date = date.today() + timedelta(
            int(settings.PASSWORD_RESET_TIMEOUT_DAYS) + 1
        )
        with mock.patch(
            'django.contrib.auth.tokens.PasswordResetTokenGenerator._today',
            return_value=mock_date,
        ):
            request = request_factory.post(
                reverse('coreuser-reset-password-check'), data
            )
            response = CoreUserViewSet.as_view({'post': 'reset_password_check'})(
                request
            )
            assert response.status_code == 200
            assert response.data['success'] is False

    def test_reset_password_confirm(self, request_factory, reset_password_request):
        test_password = '5UU74e7nfU'
        user, uid, token = reset_password_request
        data = {
            'new_password1': test_password,
            'new_password2': test_password,
            'uid': uid,
            'token': token,
        }
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        assert response.status_code == 200

        # check that password was changed
        updated_user = CoreUser.objects.get(pk=user.pk)
        assert updated_user.check_password(test_password)

    def test_reset_password_confirm_diff_passwords(
        self, request_factory, reset_password_request
    ):
        test_password1 = '5UU74e7nfU'
        test_password2 = '5UU74e7nfUa'
        user, uid, token = reset_password_request
        data = {
            'new_password1': test_password1,
            'new_password2': test_password2,
            'uid': uid,
            'token': token,
        }
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        assert (
            response.status_code == 400
        )  # validation error (password fields didn't match)

    def test_reset_password_confirm_token_expired(
        self, request_factory, reset_password_request
    ):
        test_password = '5UU74e7nfU'
        user, uid, token = reset_password_request
        data = {
            'new_password1': test_password,
            'new_password2': test_password,
            'uid': uid,
            'token': token,
        }
        mock_date = date.today() + timedelta(
            int(settings.PASSWORD_RESET_TIMEOUT_DAYS) + 1
        )
        with mock.patch(
            'django.contrib.auth.tokens.PasswordResetTokenGenerator._today',
            return_value=mock_date,
        ):
            request = request_factory.post(
                reverse('coreuser-reset-password-confirm'), data
            )
            response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(
                request
            )
            assert (
                response.status_code == 400
            )  # validation error (the token is expired)


@pytest.mark.django_db()
class TestCoreUserRead(object):

    keys = {
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
        'geo_alert_preferences',
        'env_alert_preferences',
        'sms_number',
        'whatsApp_number',
        'user_timezone',
        'last_gdpr_shown',
        'user_language',
    }

    def test_coreuser_list(self, request_factory, org_member):
        factories.CoreUser.create(
            organization=org_member.organization, username='another_user'
        )  # 2nd user of the org
        factories.CoreUser.create(
            organization=factories.Organization(name='another otg'),
            username='yet_another_user',
        )  # user of the different org
        request = request_factory.get(reverse('coreuser-list'))
        request.user = org_member
        response = CoreUserViewSet.as_view({'get': 'list'})(request)
        assert response.status_code == 200
        data = response.data
        assert len(data) == 2
        assert set(data[0].keys()) == self.keys

    def test_coreuser_retrieve(self, request_factory, org_member):
        core_user = factories.CoreUser.create(
            organization=org_member.organization, username='another_user'
        )

        request = request_factory.get(reverse('coreuser-detail', args=(core_user.pk,)))
        request.user = org_member
        response = CoreUserViewSet.as_view({'get': 'retrieve'})(
            request, pk=core_user.pk
        )
        assert response.status_code == 200
        assert set(response.data.keys()) == self.keys

    def test_coreuser_retrieve_me(self, request_factory, org_member):
        request = request_factory.get(reverse('coreuser-list'))
        request.user = org_member
        response = CoreUserViewSet.as_view({'get': 'me'})(request)
        assert response.status_code == 200
        assert response.data['username'] == org_member.username
