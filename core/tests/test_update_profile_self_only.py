"""
tp-core-p1-idor: `PATCH /coreuser/<pk>/update_profile/` is confined to the
caller's own record -- `obj.pk == request.user.pk`, self only, no org-admin
or global-admin branch. See core/permissions.py:IsSelf and the decision
recorded in data/tp-frontend-compat/decisions.md §2.

Regression tests here deliberately run as a plain org member wherever the
task is "can this caller touch another user's profile", because an
admin-run test cannot detect the failure mode where `update_profile` was
mistakenly added to the org-admin action list (that list's
`AllowOnlyOrgAdmin.has_permission` would still let an admin through, while
silently breaking every plain member -- including password changes and the
organization switcher).
"""
import pytest
from rest_framework.reverse import reverse

import factories
from core.views import CoreUserViewSet
from core.tests.fixtures import org, org_admin, org_member, superuser  # noqa: F401


def _patch_update_profile(request_factory, actor, target_pk, data):
    """PATCH /coreuser/<target_pk>/update_profile/, authenticated as `actor`."""
    request = request_factory.patch(
        reverse('coreuser-update-profile', args=(target_pk,)), data, format='json'
    )
    request.user = actor
    return CoreUserViewSet.as_view({'patch': 'update_profile'})(request, pk=target_pk)


@pytest.mark.django_db()
class TestSelfOnly:
    """Acceptance criteria 1 and 2."""

    def test_plain_member_can_update_own_profile(self, request_factory, org_member):
        data = {
            'organization_name': org_member.organization.name,
            'first_name': 'Changed',
        }
        response = _patch_update_profile(
            request_factory, org_member, org_member.pk, data
        )
        assert response.status_code == 200
        org_member.refresh_from_db()
        assert org_member.first_name == 'Changed'

    def test_plain_member_cannot_update_another_users_profile(
        self, request_factory, org_member, org
    ):
        victim = factories.CoreUser.create(
            organization=org,
            username='victim-plain-profile',
            first_name='Untouched',
        )
        data = {'organization_name': org.name, 'first_name': 'Hacked'}
        response = _patch_update_profile(request_factory, org_member, victim.pk, data)
        assert response.status_code == 403
        victim.refresh_from_db()
        assert victim.first_name == 'Untouched'

    def test_org_admin_cannot_update_another_users_profile_via_update_profile(
        self, request_factory, org_admin, org
    ):
        # Self-only means self-only: admins manage other users through
        # update/partial_update, a different action with its own anchored
        # rule (IsAnchoredOrgAdmin). It does not extend to update_profile.
        victim = factories.CoreUser.create(
            organization=org,
            username='victim-admin-profile',
            first_name='Untouched',
        )
        data = {'organization_name': org.name, 'first_name': 'Hacked'}
        response = _patch_update_profile(request_factory, org_admin, victim.pk, data)
        assert response.status_code == 403
        victim.refresh_from_db()
        assert victim.first_name == 'Untouched'

    def test_global_admin_cannot_update_another_users_profile_via_update_profile(
        self, request_factory, superuser, org
    ):
        victim = factories.CoreUser.create(
            organization=org,
            username='victim-global-profile',
            first_name='Untouched',
        )
        data = {'organization_name': org.name, 'first_name': 'Hacked'}
        response = _patch_update_profile(request_factory, superuser, victim.pk, data)
        assert response.status_code == 403
        victim.refresh_from_db()
        assert victim.first_name == 'Untouched'


@pytest.mark.django_db()
class TestOrganizationSwitcherStillWorks:
    """Acceptance criterion 3 -- R4. The switcher PATCHes the caller's own
    pk while deliberately sending a *different* organization in the body;
    the rule must be judged against the stored instance (the pk in the
    URL), never against the organization in the payload.

    tp-core-switch-scope, 2026-08-10: the switch itself is now also
    entitlement-checked server-side (`CoreUserProfileSerializer`) -- an
    ordinary member has no anchor and may switch nowhere, so this must run
    as an entitled actor (here, a global admin) or it would be refused by
    that layer before IsSelf's object check is even relevant. A global
    admin switching its own record still exercises exactly what R4 is
    about at the permission layer: the pk in the URL is the caller's own,
    so IsSelf passes, and the different organization lives only in the
    payload -- never in what IsSelf.has_object_permission looks at.
    """

    def test_caller_can_switch_own_organization(self, request_factory, superuser):
        target_org = factories.Organization.create(name='Switch Target Org')
        data = {'organization_name': target_org.name}
        response = _patch_update_profile(
            request_factory, superuser, superuser.pk, data
        )
        assert response.status_code == 200
        superuser.refresh_from_db()
        assert superuser.organization_id == target_org.pk


@pytest.mark.django_db()
class TestPasswordChangeStillWorksForPlainMember:
    """Acceptance criterion 4. The current-password requirement landed
    separately (core/serializers.py); this only proves the object
    permission does not additionally block it for an ordinary member."""

    def test_plain_member_can_change_own_password(self, request_factory, org_member):
        org_member.set_password('OldPass123!')
        org_member.save()
        data = {
            'organization_name': org_member.organization.name,
            'current_password': 'OldPass123!',
            'password': 'NewPass456!',
        }
        response = _patch_update_profile(
            request_factory, org_member, org_member.pk, data
        )
        assert response.status_code == 200
        org_member.refresh_from_db()
        assert org_member.check_password('NewPass456!')
