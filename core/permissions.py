import json
import logging

from rest_framework import permissions

from core.models import Organization


logger = logging.getLogger(__name__)


def merge_permissions(permissions1: str, permissions2: str) -> str:
    """ Merge two CRUD permissions string representations"""
    return ''.join(
        map(str, [max(int(i), int(j)) for i, j in zip(permissions1, permissions2)])
    )


def has_permission(permissions_: str, method: str) -> bool:
    """ Check if HTTP method or CRUD action corresponds to permissions"""
    methods = {
        # HTTP methods
        'POST': 0,
        'GET': 1,
        'HEAD': 1,
        'PUT': 2,
        'PATCH': 2,
        'DELETE': 3,
        'OPTIONS': 1,
        # CRUD actions
        'create': 0,
        'list': 1,
        'retrieve': 1,
        'update': 2,
        'partial_update': 2,
        'destroy': 3,
    }
    try:
        i = methods[method]
    except KeyError:
        logger.warning(f'No view method with such name: {method}')
        return False
    return bool(int(permissions_[i]))


class IsSuperUserBrowseableAPI(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.user.is_authenticated:
            if view.__class__.__name__ == 'SchemaView':
                return request.user.is_superuser
            else:
                return True
        return False


class IsSuperUser(permissions.BasePermission):
    """
    Only superusers are allowed to access.
    """

    def has_permission(self, request, view):
        return request.user.is_active and request.user.is_superuser


class AllowAuthenticatedRead(permissions.BasePermission):
    """
    Require an authenticated user for every request.

    Previously only safe (read) methods were checked, so anonymous callers were
    granted unconditional access to POST/PUT/PATCH/DELETE on any view using this
    class. Finer-grained authorization is the job of the per-action permissions
    in each viewset's ``get_permissions()``.
    """

    def has_permission(self, request, view):
        return not request.user.is_anonymous


class AllowOnlyOrgAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.user.is_anonymous:
            return False

        if request.user.is_active and request.user.is_global_admin:
            return True

        if request.user.is_org_admin:
            return True

        return False


class IsOrgMember(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.user.is_anonymous or not request.user.is_active:
            return False

        if request.user.is_superuser or request.user.is_global_admin:
            return True

        if view.action == 'create':
            user_org = request.user.organization_id

            if 'organization' in request.data:
                org_serializer = view.get_serializer_class()().get_fields()[
                    'organization'
                ]
                primitive_value = request.data.get('organization')
                org = org_serializer.run_validation(primitive_value)
                return org.pk == user_org
            elif 'CoreGroup' in view.__class__.__name__:
                return False

        return True

    def has_object_permission(self, request, view, obj):
        """
        Object level permissions are used to determine if a user
        should be allowed to act on a particular object
        """

        if request.user.is_active and request.user.is_global_admin:
            return True
        user_org = request.user.organization_id
        try:
            if obj.__class__ in [Organization]:
                return obj.pk == user_org
            elif hasattr(obj, 'organization'):
                return obj.organization.pk == user_org
        except AttributeError:
            pass
        return False


class IsAnchoredOrgAdmin(permissions.BasePermission):
    """
    Admin authority over a CoreUser is anchored to the organization the
    acting user's own org-admin CoreGroup belongs to -- not to whichever
    organization the acting user currently sits in.

    Without this, a user who merely joins an organization (for instance a
    reseller admin switched into a customer organization via the
    organization switcher) would appear to administer it, because
    `CoreUser.is_org_admin` and `organization_id` are both person-level and
    carry no memory of which organization granted the admin role. This
    mirrors the derivation `OrganizationViewSet.list` already uses
    (`core/views/organization.py`), applied at the object level instead of
    for list-scoping.

    Used only for the CoreUser actions that act on an existing or
    about-to-exist user: update, partial_update, destroy (object-level) and
    invite (has_permission, since no object exists yet). It does not affect
    list/retrieve visibility, which is intentionally wider for reseller
    admins and is untouched.
    """

    def has_permission(self, request, view):
        if request.user.is_anonymous or not request.user.is_active:
            return False

        if request.user.is_superuser or request.user.is_global_admin:
            return True

        if getattr(view, 'action', None) == 'invite':
            target_org_id = self._invite_target_organization_id(request)
            return target_org_id in request.user.org_admin_organization_ids

        # For update/partial_update/destroy the target does not exist yet
        # at this point; has_object_permission below does the real check.
        return True

    def has_object_permission(self, request, view, obj):
        if request.user.is_active and request.user.is_global_admin:
            return True

        target_org_id = getattr(obj, 'organization_id', None)
        return target_org_id in request.user.org_admin_organization_ids

    @staticmethod
    def _invite_target_organization_id(request):
        """
        Resolve the organization `invite` would create the invitation
        under, mirroring how `CoreUserViewSet.perform_invite` reads
        `org_data` from the request, so it can be checked against the
        anchor before any invitation is sent.
        """
        org_data = request.data.get('org_data')
        if isinstance(org_data, str):
            try:
                org_data = json.loads(org_data)
            except (TypeError, ValueError):
                return None
        if not isinstance(org_data, dict):
            return None
        name = org_data.get('name')
        if not name:
            return None
        return Organization.objects.filter(name=name).values_list(
            'pk', flat=True
        ).first()


class IsSelf(permissions.BasePermission):
    """
    Restrict a CoreUser action to the caller's own record. Self only --
    deliberately no org-admin or global-admin branch, unlike
    `IsAnchoredOrgAdmin` above.

    Used for `update_profile`. `has_permission` stays at "authenticated";
    the real check happens in `has_object_permission`, which
    `update_profile` is guaranteed to reach because it calls
    `self.get_object()` before mutating anything. Judging against `obj`
    (the stored instance) rather than the request body is what lets the
    organization switcher PATCH the caller's own pk while deliberately
    sending a *different* organization in the payload -- that is how
    switching works, and it must keep working.
    """

    def has_permission(self, request, view):
        return not request.user.is_anonymous and request.user.is_active

    def has_object_permission(self, request, view, obj):
        return obj.pk == request.user.pk
