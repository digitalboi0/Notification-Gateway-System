"""
URL configuration for notification_gateway project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path
from gateway_api.views import (
    NotificationAPIView, 
    HealthCheckView, 
    InternalStatusView, 
    NotificationStatusCheckView,
    UserServiceView,
    InternalOrganizationSyncView,
    InternalOrganizationCreationView,

)
from django_prometheus.exports import ExportToDjangoView
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

    
class PublicSpectacularAPIView(SpectacularAPIView):
    permission_classes = []
    authentication_classes = []

class PublicSpectacularSwaggerView(SpectacularSwaggerView):
    permission_classes = []
    authentication_classes = []

class PublicSpectacularRedocView(SpectacularRedocView):
    permission_classes = []
    authentication_classes = []    

urlpatterns = [
    
    
    path('api/v1/notifications/', NotificationAPIView.as_view(), name='create_notification'),
    path('api/v1/notifications/status/', NotificationStatusCheckView.as_view(), name='check_notification_status'),
   
    
    
    path('internal/email/status/', InternalStatusView.as_view(), {'notification_type': 'email'}, name='internal_email_status'),
    path('internal/push/status/', InternalStatusView.as_view(), {'notification_type': 'push'}, name='internal_push_status'),
    
    
    path('health/', HealthCheckView.as_view(), name='health_check'),
    path('metrics/', ExportToDjangoView, name='prometheus_metrics'),
    
    path('api/v1/users/health/', UserServiceView.as_view(), name='user-service-health'),
    path('api/v1/users/', UserServiceView.as_view(), name='user-service-create'),
    path('api/v1/users/<str:user_id>/', UserServiceView.as_view(), name='user-service-detail'),
    path('api/v1/users/<str:user_id>/preferences/', UserServiceView.as_view(), name='user-service-preferences'),
    path('mock/organizations/', UserServiceView.as_view(), name='mock-organization-create'),
    path('internal/organizations/', UserServiceView.as_view()),
    path('internal/organizations/create-template-org/', InternalOrganizationSyncView.as_view(), name='internal-org-sync-to-template'),
    path('internal/organizations/trigger-create/', InternalOrganizationCreationView.as_view(), name='internal-trigger-create-org'),
    
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/',  SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
 
]