from rest_framework import viewsets
from rest_framework.response import Response

from core.models import CoreGroup, Organization
from core.serializers import CoreGroupSerializer
from core.permissions import IsOrgMember


class CoreGroupViewSet(viewsets.ModelViewSet):
    """
    CoreGroup is similar to Django Group, but it is associated with an organization.
    It's used for creating groups of Core Users inside an organization and defining model level permissions
    for this group
    """

    queryset = CoreGroup.objects.all()
    serializer_class = CoreGroupSerializer
    permission_classes = (IsOrgMember,)

    def list(self, request, *args, **kwargs):

        queryset = self.get_queryset()
        if not request.user.is_global_admin:
            q1 = queryset.filter(organization=None)
            organization_id = request.user.organization_id
            if request.user.is_org_admin:
                reseller_orgs = [organization_id]
                org = Organization.objects.get(pk=organization_id)
                if org.is_reseller and org.reseller_customer_orgs is not None and len(org.reseller_customer_orgs) > 0:
                    for ro in org.reseller_customer_orgs:
                        reseller_orgs.append(ro)

                q2 = queryset.filter(organization_id__in=reseller_orgs)
            else:
                q2 = queryset.filter(organization_id=organization_id)
            queryset = q1.union(q2, all=True)
        return Response(self.get_serializer(queryset, many=True).data)

    def perform_create(self, serializer):
        """ override this method to set organization from request """
        organization = self.request.user.organization
        serializer.save(organization=organization)
