from django.urls import include, path, re_path
from django.contrib import admin
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from rest_framework import routers
from core import views
from core.views.web import IndexView, send_tive_tracker_order_email

admin.autodiscover()
admin.site.site_header = 'Buildly Administration'

handler404 = 'core.views.web.handler404'

router = routers.SimpleRouter()

router.register(r'coregroups', views.CoreGroupViewSet)
router.register(r'coreuser', views.CoreUserViewSet)
router.register(r'oauth/accesstokens', views.AccessTokenViewSet)
router.register(r'oauth/applications', views.ApplicationViewSet)
router.register(r'oauth/refreshtokens', views.RefreshTokenViewSet)
router.register(r'organization', views.OrganizationViewSet)
router.register(r'logicmodule', views.LogicModuleViewSet)
router.register(r'consortium', views.ConsortiumViewSet)
router.register(r'organization_type', views.OrganizationTypeViewSet)

urlpatterns = [
    path('', IndexView.as_view(), name='index'),
    path('admin/', admin.site.urls),
    path('health_check/', include('health_check.urls')),
    path('datamesh/', include('datamesh.urls')),
    path('', include('gateway.urls')),
    path('', include('workflow.urls')),
    path('send_tive_tracker_order_email/', send_tive_tracker_order_email, name='send_tive_tracker_order_email'),
    path('oauth/login/', views.LoginView.as_view()),
]

urlpatterns += staticfiles_urlpatterns() + router.urls
