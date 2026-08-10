"""
tp-core-reseller-scope: admin authority on CoreUser (update, partial_update,
invite, destroy) is anchored to the organization the acting user's own
org-admin CoreGroup belongs to, not to whichever organization they currently
sit in. See core/permissions.py:IsAnchoredOrgAdmin and the decision recorded
in data/tp-frontend-compat/decisions.md §1.

A reseller org admin may switch freely between its own organization and its
customer organizations (the switcher, exercised here via update_profile),
but while switched into a customer organization it may take no action on
that organization's users or admins. Switching itself, and a plain org
admin's authority over its own organization, must be unaffected.
"""
import json

import pytest
from rest_framework.reverse import reverse
from rest_framework.test import APIClient

import factories
from core.models import CoreGroup, CoreUser, PERMISSIONS_ADMIN
from core.tests.fixtures import org_admin, org  # noqa: F401  (fixtures)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def reseller_org():
    return factories.Organization.create(name='Reseller Org', is_reseller=True)


@pytest.fixture
def customer_org(reseller_org):
    org_ = factories.Organization.create(name='Customer Org')
    # reseller_customer_orgs is matched against organization_id in the list
    # endpoints (core/views/organization.py, coreuser.py, coregroup.py), so
    # it holds the customer organization's pk, not its name.
    reseller_org.reseller_customer_orgs = [str(org_.pk)]
    reseller_org.save()
    return org_


@pytest.fixture
def unrelated_org():
    return factories.Organization.create(name='Unrelated Org')


def _make_org_admin(organization, username):
    admins_group = CoreGroup.objects.get(organization=organization, name='Admins')
    user = factories.CoreUser.create(organization=organization, username=username)
    user.core_groups.add(admins_group)
    return user


@pytest.fixture
def reseller_admin(reseller_org):
    return _make_org_admin(reseller_org, 'reseller-admin')


@pytest.fixture
def reseller_org_user(reseller_org):
    return factories.CoreUser.create(organization=reseller_org, username='reseller-org-user')


@pytest.fixture
def customer_org_user(customer_org):
    return factories.CoreUser.create(organization=customer_org, username='customer-org-user')


@pytest.fixture
def customer_org_admin(customer_org):
    return _make_org_admin(customer_org, 'customer-org-admin')


@pytest.fixture
def unrelated_org_user(unrelated_org):
    return factories.CoreUser.create(organization=unrelated_org, username='unrelated-org-user')


@pytest.fixture
def global_admin_no_org_role():
    """
    A global admin whose only authority is the global-admin CoreGroup that
    loadinitialdata creates (is_global=True, no organization, not
    is_org_level) -- not is_superuser, and no org-level admin role at all.
    This is the shape that breaks a naive anchor: is_org_admin is False for
    this user, so an anchor that required a matching org-level role would
    refuse them everywhere.
    """
    group = CoreGroup.objects.create(
        name='Global Admin', is_global=True, permissions=PERMISSIONS_ADMIN
    )
    user = factories.CoreUser.create(username='global-admin-no-org-role')
    user.core_groups.add(group)
    return user


def switch_into(api_client, user, organization):
    """Exercise the real organization switcher (update_profile) and return
    its response. Refreshes `user` in place so callers see the new
    organization."""
    api_client.force_authenticate(user=user)
    response = api_client.patch(
        reverse('coreuser-update-profile', args=(user.pk,)),
        {'organization_name': organization.name},
    )
    user.refresh_from_db()
    return response


@pytest.mark.django_db()
class TestOrganizationSwitchingStillWorks:
    """Acceptance criterion 3."""

    def test_reseller_admin_switches_in_and_back(
        self, api_client, reseller_admin, reseller_org, customer_org
    ):
        response = switch_into(api_client, reseller_admin, customer_org)
        assert response.status_code == 200
        assert reseller_admin.organization_id == customer_org.pk

        response = switch_into(api_client, reseller_admin, reseller_org)
        assert response.status_code == 200
        assert reseller_admin.organization_id == reseller_org.pk

    def test_organization_list_keeps_full_reseller_tree_while_switched_in(
        self, api_client, reseller_admin, reseller_org, customer_org
    ):
        switch_into(api_client, reseller_admin, customer_org)

        response = api_client.get(reverse('organization-list'))
        assert response.status_code == 200
        returned_ids = {row['id'] for row in response.data}
        assert str(reseller_org.pk) in returned_ids
        assert str(customer_org.pk) in returned_ids

    def test_own_org_users_not_listed_while_switched_in_but_restored_after_switch_back(
        self, api_client, reseller_admin, reseller_org, customer_org, reseller_org_user
    ):
        # Captain's clarification, 2026-08-10: this falls out of the
        # existing list scoping, not the anchor, and needs no change --
        # asserted here rather than fixed.
        switch_into(api_client, reseller_admin, customer_org)
        response = api_client.get(reverse('coreuser-list'))
        listed_ids = {row['id'] for row in response.data}
        assert reseller_org_user.id not in listed_ids

        switch_into(api_client, reseller_admin, reseller_org)
        response = api_client.get(reverse('coreuser-list'))
        listed_ids = {row['id'] for row in response.data}
        assert reseller_org_user.id in listed_ids


@pytest.mark.django_db()
class TestSwitchedResellerAdminCannotManageCustomerOrgUsers:
    """Acceptance criterion 1."""

    def test_cannot_deactivate_customer_org_user(
        self, api_client, reseller_admin, customer_org, customer_org_user
    ):
        switch_into(api_client, reseller_admin, customer_org)

        response = api_client.patch(
            reverse('coreuser-detail', args=(customer_org_user.pk,)),
            {'is_active': False},
        )
        assert response.status_code == 403
        customer_org_user.refresh_from_db()
        assert customer_org_user.is_active

    def test_cannot_delete_customer_org_user(
        self, api_client, reseller_admin, customer_org, customer_org_user
    ):
        switch_into(api_client, reseller_admin, customer_org)

        response = api_client.delete(
            reverse('coreuser-detail', args=(customer_org_user.pk,))
        )
        assert response.status_code == 403
        assert CoreUser.objects.filter(pk=customer_org_user.pk).exists()

    def test_cannot_change_role_of_customer_org_user(
        self, api_client, reseller_admin, customer_org, customer_org_user
    ):
        switch_into(api_client, reseller_admin, customer_org)
        new_group = factories.CoreGroup(organization=customer_org)

        response = api_client.patch(
            reverse('coreuser-detail', args=(customer_org_user.pk,)),
            {'core_groups': [new_group.pk]},
        )
        assert response.status_code == 403
        assert new_group not in customer_org_user.core_groups.all()

    def test_cannot_delete_customer_org_admin(
        self, api_client, reseller_admin, customer_org, customer_org_admin
    ):
        # Rule 2 names admins as well as users.
        switch_into(api_client, reseller_admin, customer_org)

        response = api_client.delete(
            reverse('coreuser-detail', args=(customer_org_admin.pk,))
        )
        assert response.status_code == 403
        assert CoreUser.objects.filter(pk=customer_org_admin.pk).exists()

    def test_cannot_invite_into_customer_org(
        self, api_client, reseller_admin, customer_org
    ):
        switch_into(api_client, reseller_admin, customer_org)

        response = api_client.post(
            reverse('coreuser-invite'),
            {
                'emails': ['new-customer-admin@example.com'],
                'org_data': json.dumps({'name': customer_org.name}),
                'user_role': 'Admins',
            },
        )
        assert response.status_code == 403
        assert not CoreUser.objects.filter(
            email='new-customer-admin@example.com'
        ).exists()


@pytest.mark.django_db()
class TestResellerAdminCanStillManageOwnOrgUsers:
    """Acceptance criterion 2 -- positive control: the fix must not
    over-block the reseller admin's authority over its own organization."""

    def test_can_deactivate_own_org_user(
        self, api_client, reseller_admin, reseller_org_user
    ):
        api_client.force_authenticate(user=reseller_admin)

        response = api_client.patch(
            reverse('coreuser-detail', args=(reseller_org_user.pk,)),
            {'is_active': False},
        )
        assert response.status_code == 200
        reseller_org_user.refresh_from_db()
        assert not reseller_org_user.is_active

    def test_can_delete_own_org_user(
        self, api_client, reseller_admin, reseller_org_user
    ):
        api_client.force_authenticate(user=reseller_admin)

        response = api_client.delete(
            reverse('coreuser-detail', args=(reseller_org_user.pk,))
        )
        assert response.status_code == 204
        assert not CoreUser.objects.filter(pk=reseller_org_user.pk).exists()

    def test_can_invite_into_own_org(self, api_client, reseller_admin, reseller_org):
        api_client.force_authenticate(user=reseller_admin)

        response = api_client.post(
            reverse('coreuser-invite'),
            {
                'emails': ['new-reseller-user@example.com'],
                'org_data': json.dumps({'name': reseller_org.name}),
                'user_role': 'Users',
            },
        )
        assert response.status_code == 200


@pytest.mark.django_db()
class TestPlainOrgAdminUnaffected:
    """Acceptance criterion 4."""

    def test_can_still_manage_own_org_user(self, api_client, org_admin, org):
        target = factories.CoreUser.create(organization=org, username='plain-org-user')
        api_client.force_authenticate(user=org_admin)

        response = api_client.delete(reverse('coreuser-detail', args=(target.pk,)))
        assert response.status_code == 204

    def test_still_refused_cross_org(self, api_client, org_admin):
        other_org = factories.Organization.create(name='Other Plain Org')
        target = factories.CoreUser.create(
            organization=other_org, username='other-plain-org-user'
        )
        api_client.force_authenticate(user=org_admin)

        response = api_client.delete(reverse('coreuser-detail', args=(target.pk,)))
        assert response.status_code == 403
        assert CoreUser.objects.filter(pk=target.pk).exists()


@pytest.mark.django_db()
class TestJoiningUnrelatedOrgGrantsNoAdminAuthority:
    """Acceptance criterion 5 -- the wider escalation the anchor closes as a
    side effect: an admin who joins an unrelated organization by name (not
    even a reseller/customer relationship) gains no admin authority over
    it.

    tp-core-switch-scope, 2026-08-10: the switcher itself now enforces this
    same entitlement server-side (`CoreUserProfileSerializer`), so a plain
    org admin can no longer switch into an unrelated organization at all --
    the first test below now asserts exactly that, refused at the switch.
    That leaves the original claim of this class -- that the anchor holds
    even for a user who *is* inside another organization -- with nothing
    left to exercise via the switcher. The second test below rebuilds that
    state directly on the model (bypassing the switcher entirely) so the
    permission layer keeps independent coverage of the anchor, regardless
    of how a user came to sit in another organization."""

    def test_org_admin_cannot_switch_into_unrelated_org(
        self, api_client, org_admin, unrelated_org
    ):
        response = switch_into(api_client, org_admin, unrelated_org)
        assert response.status_code == 400
        assert org_admin.organization_id != unrelated_org.pk

    def test_org_admin_inside_unrelated_org_still_has_no_admin_authority(
        self, api_client, org_admin, unrelated_org, unrelated_org_user
    ):
        # Bypasses the switcher on purpose -- see class docstring -- so this
        # exercises IsAnchoredOrgAdmin alone, independent of whether the
        # switch that produced this state would itself be permitted today.
        org_admin.organization = unrelated_org
        org_admin.save()
        api_client.force_authenticate(user=org_admin)

        response = api_client.delete(
            reverse('coreuser-detail', args=(unrelated_org_user.pk,))
        )
        assert response.status_code == 403
        assert CoreUser.objects.filter(pk=unrelated_org_user.pk).exists()


@pytest.mark.django_db()
class TestGlobalAdminUnaffected:
    """Acceptance criterion 8 -- the most likely way to break this task. A
    global admin has no org-level admin role to anchor to, and must be
    resolved before the anchor check looks for one at all."""

    def test_can_manage_user_in_organization_never_joined(
        self, api_client, global_admin_no_org_role, unrelated_org, unrelated_org_user
    ):
        api_client.force_authenticate(user=global_admin_no_org_role)

        response = api_client.delete(
            reverse('coreuser-detail', args=(unrelated_org_user.pk,))
        )
        assert response.status_code == 204
        assert not CoreUser.objects.filter(pk=unrelated_org_user.pk).exists()

    def test_can_invite_into_organization_never_joined(
        self, api_client, global_admin_no_org_role, unrelated_org
    ):
        api_client.force_authenticate(user=global_admin_no_org_role)

        response = api_client.post(
            reverse('coreuser-invite'),
            {
                'emails': ['global-invitee@example.com'],
                'org_data': json.dumps({'name': unrelated_org.name}),
                'user_role': 'Users',
            },
        )
        assert response.status_code == 200

    def test_can_switch_to_any_organization(
        self, api_client, global_admin_no_org_role, unrelated_org
    ):
        response = switch_into(api_client, global_admin_no_org_role, unrelated_org)
        assert response.status_code == 200
        assert global_admin_no_org_role.organization_id == unrelated_org.pk
