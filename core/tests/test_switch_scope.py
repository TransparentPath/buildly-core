"""
tp-core-switch-scope: the organization switcher (`PATCH
/coreuser/<pk>/update_profile/`, `CoreUserProfileSerializer`) is enforced
server-side, not only in the browser. Previously `CoreUserProfileSerializer
.update` looked `organization_name` up by name and assigned it with no
entitlement check at all -- any authenticated caller could PATCH themselves
into any organization on the platform by calling the API directly.

Entitlement mirrors `core.permissions.IsAnchoredOrgAdmin`
(`core/tests/test_reseller_scope.py`): a global admin/superuser may switch
anywhere; a reseller org admin may switch between its own organization and
that organization's customer organizations; a plain org admin is confined to
its own organization; an ordinary user may switch nowhere.

The trap this module exists to catch: `organization_name` is sent on almost
every profile save (frontend call sites re-send the user's own organization
name purely to satisfy this field), not just on an actual switch. Only a
resolved *change* of organization is a switch subject to the entitlement
check -- echoing back the current organization must remain a permitted
no-op, or every ordinary profile save on the platform breaks.
"""
import pytest
from rest_framework.reverse import reverse

from core.tests.fixtures import org, org_admin, org_member  # noqa: F401  (fixtures)
from core.tests.test_reseller_scope import (  # noqa: F401  (fixtures + helper)
    api_client,
    customer_org,
    global_admin_no_org_role,
    reseller_admin,
    reseller_org,
    switch_into,
    unrelated_org,
)


@pytest.mark.django_db()
class TestEntitledSwitchesSucceed:
    def test_global_admin_switches_into_organization_never_joined(
        self, api_client, global_admin_no_org_role, unrelated_org
    ):
        response = switch_into(api_client, global_admin_no_org_role, unrelated_org)
        assert response.status_code == 200
        assert global_admin_no_org_role.organization_id == unrelated_org.pk

    def test_reseller_admin_switches_into_own_customer_org(
        self, api_client, reseller_admin, customer_org
    ):
        response = switch_into(api_client, reseller_admin, customer_org)
        assert response.status_code == 200
        assert reseller_admin.organization_id == customer_org.pk

    def test_reseller_admin_switches_back_to_own_org(
        self, api_client, reseller_admin, reseller_org, customer_org
    ):
        switch_into(api_client, reseller_admin, customer_org)

        response = switch_into(api_client, reseller_admin, reseller_org)
        assert response.status_code == 200
        assert reseller_admin.organization_id == reseller_org.pk


@pytest.mark.django_db()
class TestUnentitledSwitchesAreRefused:
    def test_reseller_admin_cannot_switch_into_unrelated_org(
        self, api_client, reseller_admin, reseller_org, unrelated_org
    ):
        response = switch_into(api_client, reseller_admin, unrelated_org)
        assert response.status_code == 400
        assert reseller_admin.organization_id == reseller_org.pk

    def test_plain_org_admin_cannot_switch_into_unrelated_org(
        self, api_client, org_admin, org, unrelated_org
    ):
        response = switch_into(api_client, org_admin, unrelated_org)
        assert response.status_code == 400
        assert org_admin.organization_id == org.pk

    def test_ordinary_user_cannot_switch_anywhere(
        self, api_client, org_member, org, unrelated_org
    ):
        response = switch_into(api_client, org_member, unrelated_org)
        assert response.status_code == 400
        assert org_member.organization_id == org.pk


@pytest.mark.django_db()
class TestOwnOrganizationNameEchoIsAlwaysPermitted:
    """The trap: `organization_name` is sent on almost every profile save,
    not just on a switch. Sending the caller's own organization name must
    stay a no-op, not something the entitlement check ever sees, so
    ordinary profile edits keep working for every user regardless of admin
    role."""

    def test_ordinary_user_profile_save_with_own_org_name_succeeds(
        self, api_client, org_member, org
    ):
        api_client.force_authenticate(user=org_member)

        response = api_client.patch(
            reverse('coreuser-update-profile', args=(org_member.pk,)),
            {'organization_name': org.name, 'title': 'mr'},
        )

        assert response.status_code == 200
        org_member.refresh_from_db()
        assert org_member.organization_id == org.pk
        assert org_member.title == 'mr'


@pytest.mark.django_db()
class TestNonExistentOrganizationNameIsIgnored:
    def test_unknown_organization_name_is_silently_ignored(
        self, api_client, org_member, org
    ):
        api_client.force_authenticate(user=org_member)

        response = api_client.patch(
            reverse('coreuser-update-profile', args=(org_member.pk,)),
            {'organization_name': 'Organization That Does Not Exist'},
        )

        assert response.status_code == 200
        org_member.refresh_from_db()
        assert org_member.organization_id == org.pk


@pytest.mark.django_db()
class TestRefusedSwitchSavesNothing:
    def test_refused_switch_leaves_other_fields_in_the_same_payload_unsaved(
        self, api_client, org_admin, org, unrelated_org
    ):
        api_client.force_authenticate(user=org_admin)
        original_title = org_admin.title

        response = api_client.patch(
            reverse('coreuser-update-profile', args=(org_admin.pk,)),
            {'organization_name': unrelated_org.name, 'title': 'mrs'},
        )

        assert response.status_code == 400
        org_admin.refresh_from_db()
        assert org_admin.organization_id == org.pk
        assert org_admin.title == original_title
