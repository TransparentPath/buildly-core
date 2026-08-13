import json
import re
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest import mock

import jwt
import pytest
from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.reverse import reverse
from rest_framework.throttling import ScopedRateThrottle

import factories
from core.models import CoreUser, Invitation, Organization, PasswordResetCode
from core.views import CoreUserViewSet
from core.jwt_utils import create_invitation_token
from core.tests.fixtures import (
    TEST_USER_DATA,
    org_admin,
    org_member,
    org,
    valid_reset_code,
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

    # has no permission
    request = request_factory.delete(reverse('coreuser-detail', args=(1,)))
    response = CoreUserViewSet.as_view({'delete': 'destroy'})(request, pk=1)
    assert response.status_code == 403

    # has no permission
    request = request_factory.patch(reverse('coreuser-update-profile', args=(1,)))
    response = CoreUserViewSet.as_view({'patch': 'update_profile'})(request, pk=1)
    assert response.status_code == 403

    # has no permission
    request = request_factory.get(reverse('coreuser-me'))
    response = CoreUserViewSet.as_view({'get': 'me'})(request)
    assert response.status_code == 403

    # has no permission
    for action_ in ('alert', 'status_alert', 'battery_alert', 'email_shipment_report'):
        request = request_factory.post(reverse(f'coreuser-{action_.replace("_", "-")}'))
        response = CoreUserViewSet.as_view({'post': action_})(request)
        assert response.status_code == 403, action_


@pytest.mark.django_db()
def test_coreuser_alert_authenticated_still_allowed(request_factory, org_member):
    """
    Service-to-service callers (pushnotification_service) authenticate with a
    Bearer token, so closing the alert endpoints must not break them.
    """
    request = request_factory.post(
        reverse('coreuser-alert'),
        {'organization_uuid': str(org_member.organization.organization_uuid),
         'messages': []},
        format='json',
    )
    request.user = org_member
    response = CoreUserViewSet.as_view({'post': 'alert'})(request)
    assert response.status_code == 200


@pytest.mark.django_db()
def test_coreuser_destroy_anonymous_does_not_delete(request_factory, org_member):
    """An anonymous DELETE must be refused and must not delete the user."""
    pk = org_member.pk
    request = request_factory.delete(reverse('coreuser-detail', args=(pk,)))
    response = CoreUserViewSet.as_view({'delete': 'destroy'})(request, pk=pk)
    assert response.status_code == 403
    assert CoreUser.objects.filter(pk=pk).exists()


@pytest.mark.django_db()
def test_coreuser_destroy_org_member_forbidden(request_factory, org_member, org):
    """An authenticated non-admin cannot delete another user in their own org."""
    victim = factories.CoreUser.create(
        organization=org, username='victim@example.com', email='victim@example.com'
    )
    request = request_factory.delete(reverse('coreuser-detail', args=(victim.pk,)))
    request.user = org_member
    response = CoreUserViewSet.as_view({'delete': 'destroy'})(request, pk=victim.pk)
    assert response.status_code == 403
    assert CoreUser.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db()
def test_coreuser_destroy_org_admin_same_org_succeeds(request_factory, org_admin, org):
    """An org admin can delete a user inside their own organization."""
    victim = factories.CoreUser.create(
        organization=org, username='victim2@example.com', email='victim2@example.com'
    )
    request = request_factory.delete(reverse('coreuser-detail', args=(victim.pk,)))
    request.user = org_admin
    response = CoreUserViewSet.as_view({'delete': 'destroy'})(request, pk=victim.pk)
    assert response.status_code == 204
    assert not CoreUser.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db()
def test_coreuser_destroy_org_admin_other_org_forbidden(request_factory, org_admin):
    """An org admin cannot delete a user belonging to a different organization."""
    other_org = factories.Organization.create(name='Some Other Org')
    victim = factories.CoreUser.create(
        organization=other_org,
        username='outsider@example.com',
        email='outsider@example.com',
    )
    request = request_factory.delete(reverse('coreuser-detail', args=(victim.pk,)))
    request.user = org_admin
    response = CoreUserViewSet.as_view({'delete': 'destroy'})(request, pk=victim.pk)
    assert response.status_code == 403
    assert CoreUser.objects.filter(pk=victim.pk).exists()


@pytest.mark.django_db()
def test_coreuser_update_profile_anonymous_forbidden(request_factory, org_member):
    """An anonymous PATCH of update_profile must be refused."""
    org_member.first_name = 'Untouched'
    org_member.save()
    request = request_factory.patch(
        reverse('coreuser-update-profile', args=(org_member.pk,)),
        {'organization_name': org_member.organization.name, 'first_name': 'Hacked'},
        format='json',
    )
    response = CoreUserViewSet.as_view({'patch': 'update_profile'})(
        request, pk=org_member.pk
    )
    assert response.status_code == 403
    org_member.refresh_from_db()
    assert org_member.first_name == 'Untouched'


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

    def test_registration_of_second_org_user(self, request_factory, org_admin, mock_uom_lookup):
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

    def test_registration_of_invited_org_user(self, request_factory, org_admin, mock_uom_lookup):
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

    def test_invited_registration_cannot_override_organization_and_role(
        self, request_factory, org_admin, mock_uom_lookup
    ):
        # tp-core-invite-binding: a valid invitation to org_admin's organization
        # as "Users" must not let the body redirect registration into a
        # different organization as "Admins" of that organization.
        other_org = factories.Organization(name='Other Org')
        data = TEST_USER_DATA.copy()
        data['username'] = 'invited-escalation@example.com'
        data['email'] = 'invited-escalation@example.com'
        token = create_invitation_token(data['email'], org_admin.organization, 'Users')
        data['invitation_token'] = token
        data['organization_name'] = other_org.name
        data['user_role'] = 'Admins'

        request = request_factory.post(reverse('coreuser-list'), data)
        response = CoreUserViewSet.as_view({'post': 'create'})(request)

        assert response.status_code == 400
        assert not CoreUser.objects.filter(username=data['username']).exists()

    def test_invited_registration_honours_token_role_and_organization(
        self, request_factory, org_admin, mock_uom_lookup
    ):
        # Positive control: registering with exactly the token's own
        # organization and role still works, and is not over-blocked.
        data = TEST_USER_DATA.copy()
        data['username'] = 'invited-honest@example.com'
        data['email'] = 'invited-honest@example.com'
        data['user_role'] = 'Users'
        token = create_invitation_token(data['email'], org_admin.organization, 'Users')
        data['invitation_token'] = token

        request = request_factory.post(reverse('coreuser-list'), data)
        response = CoreUserViewSet.as_view({'post': 'create'})(request)
        assert response.status_code == 201

        user = CoreUser.objects.get(username=data['username'])
        assert user.organization == org_admin.organization
        assert user.core_groups.filter(name='Users').exists()
        assert user.is_active
        assert not user.is_org_admin

    def test_invited_registration_roleless_invite_cannot_gain_role_from_body(
        self, request_factory, org_admin, mock_uom_lookup
    ):
        # perform_invite defaults user_role to [] (falsy) when the inviter leaves
        # it blank. A field the token does not carry must not be supplied by the
        # body either, so the body cannot use a role-less invite to pick "Admins".
        data = TEST_USER_DATA.copy()
        data['username'] = 'invited-roleless-escalation@example.com'
        data['email'] = 'invited-roleless-escalation@example.com'
        token = create_invitation_token(data['email'], org_admin.organization, [])
        data['invitation_token'] = token
        data['user_role'] = 'Admins'

        request = request_factory.post(reverse('coreuser-list'), data)
        response = CoreUserViewSet.as_view({'post': 'create'})(request)

        assert response.status_code == 400
        assert not CoreUser.objects.filter(username=data['username']).exists()

    def test_invited_registration_roleless_invite_gets_default_group(
        self, request_factory, org_admin, mock_uom_lookup
    ):
        # Positive control for the role-less invite: honouring it (i.e. not
        # supplying a role) still registers the user, and CoreUser.save()'s
        # existing default-group assignment gives them the org's default
        # (Users) role rather than no role or an escalated one.
        data = TEST_USER_DATA.copy()
        data['username'] = 'invited-roleless-honest@example.com'
        data['email'] = 'invited-roleless-honest@example.com'
        data.pop('user_role', None)
        token = create_invitation_token(data['email'], org_admin.organization, [])
        data['invitation_token'] = token

        request = request_factory.post(reverse('coreuser-list'), data)
        response = CoreUserViewSet.as_view({'post': 'create'})(request)
        assert response.status_code == 201

        user = CoreUser.objects.get(username=data['username'])
        assert user.is_active
        assert not user.is_org_admin
        assert user.core_groups.filter(name='Users', is_default=True).exists()

    def test_tokenless_registration_unaffected_by_invite_binding(self, request_factory, org_admin, mock_uom_lookup):
        # tp-core-invite-binding must not touch the no-token self-signup path:
        # an unrecognised organization_name still creates a new organization,
        # and the resulting account is still active as before.
        data = TEST_USER_DATA.copy()
        data['username'] = 'self-signup@example.com'
        data['email'] = 'self-signup@example.com'
        data['organization_name'] = 'Brand New Self-Signup Org'
        data['user_role'] = 'Admins'

        request = request_factory.post(reverse('coreuser-list'), data)
        response = CoreUserViewSet.as_view({'post': 'create'})(request)
        assert response.status_code == 201

        user = CoreUser.objects.get(username=data['username'])
        assert user.organization.name == data['organization_name']
        assert user.is_active
        assert user.is_org_admin


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


def _tamper_token(token):
    """Flip a character inside the payload segment, leaving the header and
    signature untouched, so the signature no longer matches."""
    header, payload, signature = token.split('.')
    chars = list(payload)
    idx = len(chars) // 2
    chars[idx] = 'a' if chars[idx] != 'a' else 'b'
    return f'{header}.{"".join(chars)}.{signature}'


def _resign_with_other_key(token):
    """Decode the payload as-is (unmodified) and re-sign it with a
    different key, proving the signature -- not the payload shape -- is
    the gate."""
    decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'], options={'verify_exp': False})
    return jwt.encode(decoded, 'a-different-secret-key', algorithm='HS256')


@pytest.mark.django_db()
class TestCoreUserInvite:
    @pytest.fixture(autouse=True)
    def _clear_throttle_cache(self):
        # ScopedRateThrottle's LocMemCache state is per-process and would
        # otherwise carry request counts across tests in this class.
        cache.clear()
        yield

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

    # -- Security-property cases: these prove the design (plan §7). --

    def test_edited_link_is_refused(self, request_factory, org):
        invitation = factories.Invitation(organization=org)
        token = create_invitation_token(
            invitation.email, invitation.organization, invitation.user_role, invitation.token_jti
        )
        tampered = _tamper_token(token)

        request = request_factory.get(reverse('coreuser-invite-check'), {'token': tampered})
        response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
        assert response.status_code == 401
        assert response.data['reason'] == 'invalid'

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': tampered})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.status_code == 200
        assert response.data['reason'] == 'not_renewable'
        assert len(mail.outbox) == 0

    def test_token_signed_with_other_key_is_refused(self, request_factory, org):
        invitation = factories.Invitation(organization=org)
        token = create_invitation_token(
            invitation.email, invitation.organization, invitation.user_role, invitation.token_jti
        )
        re_signed = _resign_with_other_key(token)

        request = request_factory.get(reverse('coreuser-invite-check'), {'token': re_signed})
        response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
        assert response.status_code == 401
        assert response.data['reason'] == 'invalid'

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': re_signed})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.status_code == 200
        assert response.data['reason'] == 'not_renewable'
        assert len(mail.outbox) == 0

    def test_link_with_no_stored_record_is_refused(self, request_factory, org):
        # Legacy-shape (no `jti`) token, already expired, with no Invitation row.
        payload = {
            'email': 'ghost@example.com',
            'organization_name': org.name,
            'user_role': 'Users',
            'exp': timezone.now() - timedelta(hours=1),
        }
        token = jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')

        request = request_factory.get(reverse('coreuser-invite-check'), {'token': token})
        response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
        assert response.status_code == 401
        assert response.data['reason'] == 'no_record'

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.status_code == 200
        assert response.data['reason'] == 'not_renewable'
        assert len(mail.outbox) == 0

    def test_cancelled_invitation_is_refused(self, request_factory, org):
        invitation = factories.Invitation(organization=org, status=Invitation.STATUS_CANCELLED)
        token = create_invitation_token(
            invitation.email, invitation.organization, invitation.user_role, invitation.token_jti
        )

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.status_code == 200
        assert response.data['reason'] == 'not_renewable'
        assert len(mail.outbox) == 0

        request = request_factory.get(reverse('coreuser-invite-check'), {'token': token})
        cancelled_response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
        assert cancelled_response.status_code == 401
        assert cancelled_response.data == {
            'detail': 'This invitation is no longer on record.', 'reason': 'no_record',
        }

        # Byte-identical to the unknown-jti / never-recorded case.
        unknown_payload = {
            'email': 'nobody@example.com',
            'organization_name': org.name,
            'user_role': 'Users',
            'jti': str(uuid.uuid4()),
            'exp': timezone.now() - timedelta(hours=1),
        }
        unknown_token = jwt.encode(unknown_payload, settings.SECRET_KEY, algorithm='HS256')
        request = request_factory.get(reverse('coreuser-invite-check'), {'token': unknown_token})
        no_record_response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
        assert no_record_response.status_code == 401
        assert no_record_response.data == cancelled_response.data

    def test_reinvite_cooldown_holds(self, request_factory, org):
        invitation = factories.Invitation(
            organization=org,
            expires_at=timezone.now() - timedelta(hours=1),
            original_expires_at=timezone.now() - timedelta(hours=1),
        )
        token = create_invitation_token(
            invitation.email, invitation.organization, invitation.user_role, invitation.token_jti
        )

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.status_code == 200
        assert response.data['reason'] == 'sent'
        sent_count = len(mail.outbox)
        assert sent_count > 0

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.status_code == 200
        assert response.data['reason'] == 'cooldown'
        assert len(mail.outbox) == sent_count

        invitation.refresh_from_db()
        invitation.last_reinvite_at = invitation.last_reinvite_at - timedelta(minutes=16)
        invitation.save(update_fields=['last_reinvite_at'])

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.status_code == 200
        assert response.data['reason'] == 'sent'
        assert len(mail.outbox) > sent_count

    def test_reinvite_cap_holds(self, request_factory, org):
        invitation = factories.Invitation(
            organization=org,
            expires_at=timezone.now() - timedelta(hours=1),
            original_expires_at=timezone.now() - timedelta(hours=1),
            reinvite_count=settings.INVITATION_REINVITE_MAX_COUNT,
        )
        token = create_invitation_token(
            invitation.email, invitation.organization, invitation.user_role, invitation.token_jti
        )

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.status_code == 200
        assert response.data['reason'] == 'cap_reached'
        assert len(mail.outbox) == 0

    def test_reinvite_window_closes(self, request_factory, org):
        original_expires_at = timezone.now() - timedelta(days=31)
        invitation = factories.Invitation(
            organization=org,
            expires_at=original_expires_at,
            original_expires_at=original_expires_at,
        )
        token = create_invitation_token(
            invitation.email, invitation.organization, invitation.user_role, invitation.token_jti
        )

        request = request_factory.get(reverse('coreuser-invite-check'), {'token': token})
        response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
        assert response.status_code == 401
        assert response.data['reason'] == 'expired_window_closed'
        assert 'can_request_new' not in response.data

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.status_code == 200
        assert response.data['reason'] == 'not_renewable'
        assert len(mail.outbox) == 0

    def test_reinvite_does_not_touch_organization_or_uom(self, request_factory, org):
        invitation = factories.Invitation(
            organization=org,
            expires_at=timezone.now() - timedelta(hours=1),
            original_expires_at=timezone.now() - timedelta(hours=1),
        )
        token = create_invitation_token(
            invitation.email, invitation.organization, invitation.user_role, invitation.token_jti
        )
        org_count = Organization.objects.count()

        with mock.patch('core.views.coreuser.requests.post') as mocked_post:
            request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
            response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)

        assert response.status_code == 200
        assert response.data['reason'] == 'sent'
        mocked_post.assert_not_called()
        assert Organization.objects.count() == org_count

    def test_reinvite_of_registered_email_sends_nothing(self, request_factory, org):
        invitation = factories.Invitation(
            organization=org,
            expires_at=timezone.now() - timedelta(hours=1),
            original_expires_at=timezone.now() - timedelta(hours=1),
        )
        factories.CoreUser.create(
            email=invitation.email, username=invitation.email, organization=org,
        )
        token = create_invitation_token(
            invitation.email, invitation.organization, invitation.user_role, invitation.token_jti
        )

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.status_code == 200
        assert response.data['reason'] == 'not_renewable'
        assert len(mail.outbox) == 0

        request = request_factory.get(reverse('coreuser-invite-check'), {'token': token})
        response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
        assert response.status_code == 401
        assert response.data['reason'] == 'already_registered'

    def test_reinvite_window_measured_from_original_expiry(self, request_factory, org):
        original_expires_at = timezone.now() - timedelta(hours=1)
        invitation = factories.Invitation(
            organization=org,
            expires_at=original_expires_at,
            original_expires_at=original_expires_at,
        )
        token = create_invitation_token(
            invitation.email, invitation.organization, invitation.user_role, invitation.token_jti
        )

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.status_code == 200
        assert response.data['reason'] == 'sent'

        invitation.refresh_from_db()
        assert invitation.original_expires_at == original_expires_at
        assert invitation.expires_at > original_expires_at
        assert invitation.reinvite_window_closes_at == (
            original_expires_at + timedelta(days=settings.INVITATION_REINVITE_WINDOW_DAYS)
        )

    # -- Behavioural cases. --

    def test_invite_creates_invitation_record(self, request_factory, org_admin):
        data = {
            'emails': [TEST_USER_DATA['email']],
            'org_data': json.dumps({'name': TEST_USER_DATA['organization_name']}),
            'user_role': TEST_USER_DATA['user_role'],
        }
        request = request_factory.post(reverse('coreuser-invite'), data)
        request.user = org_admin
        response = CoreUserViewSet.as_view({'post': 'invite'})(request)
        assert response.status_code == 200

        invitation = Invitation.objects.get(email=TEST_USER_DATA['email'])
        assert invitation.status == Invitation.STATUS_PENDING
        assert invitation.organization == org_admin.organization
        assert invitation.invited_by == org_admin
        expected_expiry = timezone.now() + timedelta(hours=settings.INVITATION_EXPIRE_HOURS)
        assert abs((invitation.expires_at - expected_expiry).total_seconds()) < 5

        token = response.data['invitations'][0].split('token=')[1]
        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        assert decoded['jti'] == str(invitation.token_jti)

    def test_invite_supersedes_prior_pending_invitation(self, request_factory, org_admin):
        data = {
            'emails': [TEST_USER_DATA['email']],
            'org_data': json.dumps({'name': TEST_USER_DATA['organization_name']}),
            'user_role': TEST_USER_DATA['user_role'],
        }
        request = request_factory.post(reverse('coreuser-invite'), data)
        request.user = org_admin
        CoreUserViewSet.as_view({'post': 'invite'})(request)
        first = Invitation.objects.get(email=TEST_USER_DATA['email'], status=Invitation.STATUS_PENDING)

        request = request_factory.post(reverse('coreuser-invite'), data)
        request.user = org_admin
        CoreUserViewSet.as_view({'post': 'invite'})(request)

        first.refresh_from_db()
        assert first.status == Invitation.STATUS_SUPERSEDED
        pending = Invitation.objects.filter(email=TEST_USER_DATA['email'], status=Invitation.STATUS_PENDING)
        assert pending.count() == 1
        assert pending.first().pk != first.pk

    def test_superseded_link_reports_newer_invitation(self, request_factory, org_admin):
        data = {
            'emails': [TEST_USER_DATA['email']],
            'org_data': json.dumps({'name': TEST_USER_DATA['organization_name']}),
            'user_role': TEST_USER_DATA['user_role'],
        }
        request = request_factory.post(reverse('coreuser-invite'), data)
        request.user = org_admin
        response = CoreUserViewSet.as_view({'post': 'invite'})(request)
        old_token = response.data['invitations'][0].split('token=')[1]

        request = request_factory.post(reverse('coreuser-invite'), data)
        request.user = org_admin
        CoreUserViewSet.as_view({'post': 'invite'})(request)

        mail.outbox.clear()
        request = request_factory.get(reverse('coreuser-invite-check'), {'token': old_token})
        response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
        assert response.status_code == 401
        assert response.data['reason'] == 'superseded'
        assert 'can_request_new' not in response.data

        request = request_factory.post(reverse('coreuser-invite-resend'), {'token': old_token})
        response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
        assert response.data['reason'] == 'not_renewable'
        assert len(mail.outbox) == 0

    def test_unexpired_legacy_link_still_registers(self, request_factory, org):
        # No `jti` -- the deploy-day tolerance rule for pre-change links.
        token = create_invitation_token(TEST_USER_DATA['email'], org, TEST_USER_DATA['user_role'])
        request = request_factory.get(reverse('coreuser-invite-check'), {'token': token})
        response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
        assert response.status_code == 200
        assert response.data['email'] == TEST_USER_DATA['email']
        assert 'reason' not in response.data

    def test_reinvite_notifies_three_parties(self, request_factory, org_admin):
        invitation = factories.Invitation(
            organization=org_admin.organization,
            invited_by=org_admin,
            expires_at=timezone.now() - timedelta(hours=1),
            original_expires_at=timezone.now() - timedelta(hours=1),
        )
        token = create_invitation_token(
            invitation.email, invitation.organization, invitation.user_role, invitation.token_jti
        )

        with override_settings(SUPPORT_EMAIL_ADDRESS=['support@transparentpath.com']):
            request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
            response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)

        assert response.status_code == 200
        assert response.data['reason'] == 'sent'
        assert len(mail.outbox) == 2
        to_lists = [message.to for message in mail.outbox]
        assert [invitation.email] in to_lists
        assert [org_admin.email] in to_lists
        for message in mail.outbox:
            assert message.cc == ['support@transparentpath.com']

    def test_invite_check_reason_codes(self, request_factory, org):
        registered_invitation = factories.Invitation(organization=org)
        factories.CoreUser.create(
            email=registered_invitation.email, username=registered_invitation.email, organization=org,
        )
        superseded_invitation = factories.Invitation(organization=org, status=Invitation.STATUS_SUPERSEDED)
        expired_in_window = factories.Invitation(
            organization=org,
            expires_at=timezone.now() - timedelta(hours=1),
            original_expires_at=timezone.now() - timedelta(hours=1),
        )
        expired_window_closed = factories.Invitation(
            organization=org,
            expires_at=timezone.now() - timedelta(days=31),
            original_expires_at=timezone.now() - timedelta(days=31),
        )
        valid_pending = factories.Invitation(organization=org)

        cases = [
            (None, 401, 'invalid'),
            (jwt.encode(
                {
                    'email': 'nobody@example.com', 'organization_name': org.name, 'user_role': 'Users',
                    'jti': str(uuid.uuid4()), 'exp': timezone.now() - timedelta(hours=1),
                },
                settings.SECRET_KEY, algorithm='HS256',
            ), 401, 'no_record'),
            (create_invitation_token(
                registered_invitation.email, registered_invitation.organization,
                registered_invitation.user_role, registered_invitation.token_jti,
            ), 401, 'already_registered'),
            (create_invitation_token(
                superseded_invitation.email, superseded_invitation.organization,
                superseded_invitation.user_role, superseded_invitation.token_jti,
            ), 401, 'superseded'),
            (create_invitation_token(
                expired_in_window.email, expired_in_window.organization,
                expired_in_window.user_role, expired_in_window.token_jti,
            ), 401, 'expired'),
            (create_invitation_token(
                expired_window_closed.email, expired_window_closed.organization,
                expired_window_closed.user_role, expired_window_closed.token_jti,
            ), 401, 'expired_window_closed'),
            (create_invitation_token(
                valid_pending.email, valid_pending.organization,
                valid_pending.user_role, valid_pending.token_jti,
            ), 200, None),
        ]

        for token, expected_status, expected_reason in cases:
            params = {'token': token} if token is not None else {}
            request = request_factory.get(reverse('coreuser-invite-check'), params)
            response = CoreUserViewSet.as_view({'get': 'invite_check'})(request)
            assert response.status_code == expected_status
            if expected_reason is None:
                assert 'reason' not in response.data
            else:
                assert response.data['reason'] == expected_reason

    def test_invitation_expiry_is_72_hours(self, request_factory, org_admin):
        assert settings.INVITATION_EXPIRE_HOURS == 72
        data = {
            'emails': [TEST_USER_DATA['email']],
            'org_data': json.dumps({'name': TEST_USER_DATA['organization_name']}),
            'user_role': TEST_USER_DATA['user_role'],
        }
        request = request_factory.post(reverse('coreuser-invite'), data)
        request.user = org_admin
        response = CoreUserViewSet.as_view({'post': 'invite'})(request)
        token = response.data['invitations'][0].split('token=')[1]

        decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
        actual_exp = datetime.fromtimestamp(decoded['exp'], tz=dt_timezone.utc)
        expected_exp = timezone.now() + timedelta(hours=72)
        assert abs((actual_exp - expected_exp).total_seconds()) < 5

        message = mail.outbox[-1]
        assert '72 hours' in message.body

    def test_throttle_returns_429(self, request_factory, org):
        invitation = factories.Invitation(
            organization=org,
            expires_at=timezone.now() - timedelta(hours=1),
            original_expires_at=timezone.now() - timedelta(hours=1),
        )
        token = create_invitation_token(
            invitation.email, invitation.organization, invitation.user_role, invitation.token_jti
        )

        # `ScopedRateThrottle.THROTTLE_RATES` is a snapshot taken from
        # `api_settings` at import time, not a live setting -- overriding
        # `settings.REST_FRAMEWORK` doesn't reach it, so the rate itself
        # has to be patched directly to exercise the throttle in a test.
        with mock.patch.object(ScopedRateThrottle, 'THROTTLE_RATES', {'invite_resend': '1/hour'}):
            request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
            response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
            assert response.status_code == 200

            request = request_factory.post(reverse('coreuser-invite-resend'), {'token': token})
            response = CoreUserViewSet.as_view({'post': 'invite_resend'})(request)
            assert response.status_code == 429
            assert 'reason' not in response.data


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

    def test_reset_password_check_valid_code(self, request_factory, valid_reset_code):
        user, code_obj = valid_reset_code
        data = {'email': user.username, 'code': code_obj.code}
        request = request_factory.post(reverse('coreuser-reset-password-check'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_check'})(request)
        assert response.status_code == 200
        assert response.data['is_valid'] is True
        assert response.data['message'] == 'Reset code verified and found valid'
        # read-only — code must not be marked used
        code_obj.refresh_from_db()
        assert code_obj.is_used is False

    def test_reset_password_check_expired_code(self, request_factory, org):
        from django.utils import timezone as tz
        from datetime import timedelta as td
        user = factories.CoreUser.create(
            organization=org,
            username='expired@example.com',
            email='expired@example.com',
            is_active=True,
        )
        code_obj = factories.PasswordResetCode.create(
            user=user,
            code='654321',
            expires_at=tz.now() - td(minutes=1),
        )
        data = {'email': user.username, 'code': '654321'}
        request = request_factory.post(reverse('coreuser-reset-password-check'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_check'})(request)
        assert response.status_code == 200
        assert response.data['is_valid'] is False
        assert 'expired' in response.data['message']

    def test_reset_password_check_used_code(self, request_factory, org):
        user = factories.CoreUser.create(
            organization=org,
            username='usedcode@example.com',
            email='usedcode@example.com',
            is_active=True,
        )
        factories.PasswordResetCode.create(user=user, code='654321', is_used=True)
        data = {'email': user.username, 'code': '654321'}
        request = request_factory.post(reverse('coreuser-reset-password-check'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_check'})(request)
        assert response.status_code == 200
        assert response.data['is_valid'] is False

    def test_reset_password_check_wrong_code(self, request_factory, valid_reset_code):
        user, code_obj = valid_reset_code
        data = {'email': user.username, 'code': '999999'}
        request = request_factory.post(reverse('coreuser-reset-password-check'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_check'})(request)
        assert response.status_code == 200
        assert response.data['is_valid'] is False

    def test_reset_password_check_unknown_email(self, request_factory):
        data = {'email': 'nobody@example.com', 'code': '123456'}
        request = request_factory.post(reverse('coreuser-reset-password-check'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_check'})(request)
        assert response.status_code == 200
        assert response.data['is_valid'] is False
        # enumeration-safe: same body as wrong-code case
        assert response.data['message'] == (
            'Invalid code or code has expired. Please resend code and try again.'
        )

    def test_reset_password_check_missing_fields(self, request_factory):
        request = request_factory.post(reverse('coreuser-reset-password-check'), {})
        response = CoreUserViewSet.as_view({'post': 'reset_password_check'})(request)
        assert response.status_code == 400

    def test_reset_password_check_does_not_mark_code_used(self, request_factory, valid_reset_code):
        user, code_obj = valid_reset_code
        data = {'email': user.username, 'code': code_obj.code}
        request = request_factory.post(reverse('coreuser-reset-password-check'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_check'})(request)
        assert response.status_code == 200
        assert response.data['is_valid'] is True
        code_obj.refresh_from_db()
        assert code_obj.is_used is False

    def test_reset_password_confirm_success(self, request_factory, valid_reset_code):
        user, code_obj = valid_reset_code
        data = {
            'email': user.username,
            'code': '654321',
            'new_password1': '5UU74e7nfU',
            'new_password2': '5UU74e7nfU',
        }
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        assert response.status_code == 200
        assert response.data == {'message': 'The password was changed successfully.'}
        user.refresh_from_db()
        assert user.check_password('5UU74e7nfU')
        code_obj.refresh_from_db()
        assert code_obj.is_used is True

    def test_reset_password_confirm_marks_code_used(self, request_factory, valid_reset_code):
        user, code_obj = valid_reset_code
        data = {
            'email': user.username,
            'code': '654321',
            'new_password1': '5UU74e7nfU',
            'new_password2': '5UU74e7nfU',
        }
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), data)
        CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        code_obj.refresh_from_db()
        assert code_obj.is_used is True

    def test_reset_password_confirm_diff_passwords(self, request_factory, valid_reset_code):
        user, code_obj = valid_reset_code
        data = {
            'email': user.username,
            'code': '654321',
            'new_password1': '5UU74e7nfU',
            'new_password2': '5UU74e7nfUa',
        }
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        assert response.status_code == 400
        assert "didn't match" in response.data['message']
        code_obj.refresh_from_db()
        assert code_obj.is_used is False

    def test_reset_password_confirm_expired_code(self, request_factory, org):
        user = factories.CoreUser.create(
            organization=org,
            username='confirmexpired@example.com',
            email='confirmexpired@example.com',
            is_active=True,
        )
        factories.PasswordResetCode.create(
            user=user,
            code='111111',
            expires_at=timezone.now() - timedelta(minutes=1),
        )
        data = {
            'email': user.username,
            'code': '111111',
            'new_password1': '5UU74e7nfU',
            'new_password2': '5UU74e7nfU',
        }
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        assert response.status_code == 400
        assert 'expired' in response.data['message']

    def test_reset_password_confirm_used_code(self, request_factory, org):
        user = factories.CoreUser.create(
            organization=org,
            username='confirmused@example.com',
            email='confirmused@example.com',
            is_active=True,
        )
        factories.PasswordResetCode.create(user=user, code='222222', is_used=True)
        data = {
            'email': user.username,
            'code': '222222',
            'new_password1': '5UU74e7nfU',
            'new_password2': '5UU74e7nfU',
        }
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        assert response.status_code == 400
        assert response.data['message'] == (
            'Invalid code or code has expired. Please resend code and try again.'
        )

    def test_reset_password_confirm_wrong_code(self, request_factory, valid_reset_code):
        user, code_obj = valid_reset_code
        data = {
            'email': user.username,
            'code': '999999',
            'new_password1': '5UU74e7nfU',
            'new_password2': '5UU74e7nfU',
        }
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        assert response.status_code == 400
        assert response.data['message'] == (
            'Invalid code or code has expired. Please resend code and try again.'
        )

    def test_reset_password_confirm_unknown_email(self, request_factory):
        data = {
            'email': 'nobody@example.com',
            'code': '123456',
            'new_password1': '5UU74e7nfU',
            'new_password2': '5UU74e7nfU',
        }
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        assert response.status_code == 400
        assert response.data['message'] == (
            'Invalid code or code has expired. Please resend code and try again.'
        )

    def test_reset_password_confirm_inactive_user(self, request_factory, org):
        user = factories.CoreUser.create(
            organization=org,
            username='inactiveconfirm@example.com',
            email='inactiveconfirm@example.com',
            is_active=False,
        )
        factories.PasswordResetCode.create(user=user, code='333333')
        original_password = user.password
        data = {
            'email': user.username,
            'code': '333333',
            'new_password1': '5UU74e7nfU',
            'new_password2': '5UU74e7nfU',
        }
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        assert response.status_code == 400
        assert response.data['message'] == (
            'Invalid code or code has expired. Please resend code and try again.'
        )
        user.refresh_from_db()
        assert user.password == original_password

    def test_reset_password_confirm_weak_password(self, request_factory, valid_reset_code):
        user, code_obj = valid_reset_code
        data = {
            'email': user.username,
            'code': '654321',
            'new_password1': 'short',
            'new_password2': 'short',
        }
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), data)
        response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        assert response.status_code == 400
        assert 'message' in response.data
        # MinimumLengthValidator fires — message mentions password length
        assert len(response.data['message']) > 0

    def test_reset_password_confirm_missing_fields(self, request_factory):
        request = request_factory.post(reverse('coreuser-reset-password-confirm'), {})
        response = CoreUserViewSet.as_view({'post': 'reset_password_confirm'})(request)
        assert response.status_code == 400
        # DRF field-level errors — no 'message' key
        assert 'email' in response.data


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
        'profile_pic',
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


# A minimal valid 1x1 PNG expressed as a base64 data URL.
TINY_PNG_DATA_URL = (
    'data:image/png;base64,'
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII='
)


@pytest.mark.django_db()
class TestUpdateProfilePic:
    """Tests for profile_pic field on the update_profile action and read endpoints."""

    def _patch_update_profile(self, request_factory, user, data):
        """Helper: PATCH /coreuser/<pk>/update_profile/ as the user themselves."""
        pk = user.pk
        request = request_factory.patch(
            reverse('coreuser-update-profile', args=(pk,)), data, format='json'
        )
        request.user = user
        return CoreUserViewSet.as_view({'patch': 'update_profile'})(request, pk=pk)

    def test_update_profile_sets_profile_pic(self, request_factory, org_member):
        data = {'organization_name': org_member.organization.name, 'profile_pic': TINY_PNG_DATA_URL}
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 200
        assert response.data['profile_pic'] == TINY_PNG_DATA_URL
        org_member.refresh_from_db()
        assert org_member.profile_pic == TINY_PNG_DATA_URL

    def test_update_profile_clears_profile_pic_empty_string(self, request_factory, org_member):
        org_member.profile_pic = TINY_PNG_DATA_URL
        org_member.save()
        data = {'organization_name': org_member.organization.name, 'profile_pic': ''}
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 200
        org_member.refresh_from_db()
        assert org_member.profile_pic == ''

    def test_update_profile_clears_profile_pic_null(self, request_factory, org_member):
        org_member.profile_pic = TINY_PNG_DATA_URL
        org_member.save()
        data = {'organization_name': org_member.organization.name, 'profile_pic': None}
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 200
        org_member.refresh_from_db()
        assert org_member.profile_pic is None

    def test_update_profile_rejects_bad_mime(self, request_factory, org_member):
        import base64
        gif_payload = 'data:image/gif;base64,' + base64.b64encode(b'GIF89a').decode()
        data = {'organization_name': org_member.organization.name, 'profile_pic': gif_payload}
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 400

    def test_update_profile_rejects_oversize(self, request_factory, org_member):
        import base64 as b64
        oversized = b64.b64encode(b'\x00' * (5 * 1024 * 1024 + 1)).decode()
        data = {
            'organization_name': org_member.organization.name,
            'profile_pic': 'data:image/png;base64,' + oversized,
        }
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 400

    def test_update_profile_rejects_non_base64(self, request_factory, org_member):
        data = {
            'organization_name': org_member.organization.name,
            'profile_pic': 'data:image/png;base64,!!!not-base64!!!',
        }
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 400

    def test_update_profile_rejects_non_data_url(self, request_factory, org_member):
        data = {'organization_name': org_member.organization.name, 'profile_pic': 'hello'}
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 400

    def test_update_profile_partial_preserves_other_fields(self, request_factory, org_member):
        org_member.first_name = 'Preserved'
        org_member.save()
        data = {'organization_name': org_member.organization.name, 'profile_pic': TINY_PNG_DATA_URL}
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 200
        org_member.refresh_from_db()
        assert org_member.first_name == 'Preserved'
        assert org_member.profile_pic == TINY_PNG_DATA_URL

    def test_retrieve_includes_profile_pic(self, request_factory, org_member):
        org_member.profile_pic = TINY_PNG_DATA_URL
        org_member.save()
        pk = org_member.pk
        request = request_factory.get(reverse('coreuser-detail', args=(pk,)))
        request.user = org_member
        response = CoreUserViewSet.as_view({'get': 'retrieve'})(request, pk=pk)
        assert response.status_code == 200
        assert response.data['profile_pic'] == TINY_PNG_DATA_URL

    def test_me_includes_profile_pic(self, request_factory, org_member):
        org_member.profile_pic = TINY_PNG_DATA_URL
        org_member.save()
        request = request_factory.get(reverse('coreuser-list'))
        request.user = org_member
        response = CoreUserViewSet.as_view({'get': 'me'})(request)
        assert response.status_code == 200
        assert response.data['profile_pic'] == TINY_PNG_DATA_URL

    def test_create_ignores_profile_pic(self, request_factory):
        data = {**TEST_USER_DATA, 'profile_pic': TINY_PNG_DATA_URL}
        request = request_factory.post(reverse('coreuser-list'), data)
        response = CoreUserViewSet.as_view({'post': 'create'})(request)
        assert response.status_code == 201
        user = CoreUser.objects.get(username=TEST_USER_DATA['username'])
        assert not user.profile_pic

    def test_update_ignores_profile_pic(self, request_factory, org_admin):
        user = factories.CoreUser.create(
            organization=org_admin.organization, username='profile_pic_user'
        )
        user.profile_pic = TINY_PNG_DATA_URL
        user.save()
        pk = user.pk
        new_pic = 'data:image/jpeg;base64,' + 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgAAIAAAUAAeImBZsAAAAASUVORK5CYII='
        data = {'profile_pic': new_pic}
        request = request_factory.patch(reverse('coreuser-detail', args=(pk,)), data)
        request.user = org_admin
        response = CoreUserViewSet.as_view({'patch': 'partial_update'})(request, pk=pk)
        assert response.status_code == 200
        user.refresh_from_db()
        assert user.profile_pic == TINY_PNG_DATA_URL


@pytest.mark.django_db()
class TestUpdateProfileCurrentPassword:
    """Tests requiring current_password to change password via update_profile."""

    OLD_PASSWORD = 'OldPass123!'
    NEW_PASSWORD = 'NewPass456!'

    def _patch_update_profile(self, request_factory, user, data):
        """Helper: PATCH /coreuser/<pk>/update_profile/ as the user themselves."""
        pk = user.pk
        request = request_factory.patch(
            reverse('coreuser-update-profile', args=(pk,)), data, format='json'
        )
        request.user = user
        return CoreUserViewSet.as_view({'patch': 'update_profile'})(request, pk=pk)

    def test_update_profile_password_with_correct_current_password(self, request_factory, org_member):
        org_member.set_password(self.OLD_PASSWORD)
        org_member.save()
        data = {
            'organization_name': org_member.organization.name,
            'current_password': self.OLD_PASSWORD,
            'password': self.NEW_PASSWORD,
        }
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 200
        org_member.refresh_from_db()
        assert org_member.check_password(self.NEW_PASSWORD)

    def test_update_profile_password_with_wrong_current_password(self, request_factory, org_member):
        org_member.set_password(self.OLD_PASSWORD)
        org_member.save()
        data = {
            'organization_name': org_member.organization.name,
            'current_password': 'not-the-right-password',
            'password': self.NEW_PASSWORD,
        }
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 400
        org_member.refresh_from_db()
        assert org_member.check_password(self.OLD_PASSWORD)

    def test_update_profile_password_without_current_password(self, request_factory, org_member):
        org_member.set_password(self.OLD_PASSWORD)
        org_member.save()
        data = {
            'organization_name': org_member.organization.name,
            'password': self.NEW_PASSWORD,
        }
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 400
        org_member.refresh_from_db()
        assert org_member.check_password(self.OLD_PASSWORD)

    def test_update_profile_field_change_without_password_is_unaffected(self, request_factory, org_member):
        org_member.set_password(self.OLD_PASSWORD)
        org_member.save()
        data = {
            'organization_name': org_member.organization.name,
            'first_name': 'Changed',
        }
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 200
        org_member.refresh_from_db()
        assert org_member.first_name == 'Changed'
        assert org_member.check_password(self.OLD_PASSWORD)

    def test_update_profile_current_password_alone_is_ignored(self, request_factory, org_member):
        org_member.set_password(self.OLD_PASSWORD)
        org_member.save()
        data = {
            'organization_name': org_member.organization.name,
            'current_password': self.OLD_PASSWORD,
        }
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 200
        org_member.refresh_from_db()
        assert org_member.check_password(self.OLD_PASSWORD)

    def test_update_profile_current_password_not_in_response(self, request_factory, org_member):
        org_member.set_password(self.OLD_PASSWORD)
        org_member.save()
        data = {
            'organization_name': org_member.organization.name,
            'current_password': self.OLD_PASSWORD,
            'password': self.NEW_PASSWORD,
        }
        response = self._patch_update_profile(request_factory, org_member, data)
        assert response.status_code == 200
        assert 'current_password' not in response.data
