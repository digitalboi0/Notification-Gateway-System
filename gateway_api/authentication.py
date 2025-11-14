
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
import hashlib
import json
from gateway_api.redis_client import get_redis
from django.conf import settings


class OrganizationUser:
    """Lightweight user object representing an authenticated organization."""
    def __init__(self, organization_id, name, quota_limit):
        self.organization_id = organization_id
        self.name = name
        self.quota_limit = quota_limit
        self.is_authenticated = True
    
    def __str__(self):
        return f"OrganizationUser({self.organization_id})"

class APIKeyAuthentication(BaseAuthentication):
    """
    API Key authentication middleware
    Header: X-API-Key: your_api_key_here
    """
    
    def authenticate(self, request):
        api_key = request.headers.get('X-API-Key')
        if not api_key:
            raise AuthenticationFailed('API Key required in X-API-Key header')
        
        redis_client = get_redis()
        cache_key = f"api_key:{hashlib.sha256(api_key.encode()).hexdigest()}"
        org_data_json = redis_client.get(cache_key)
        
        if not org_data_json:
            from .models import Organization
            try:
                org = Organization.objects.get(api_key=api_key, is_active=True)
                org_data = {
                    "organization_id": str(org.id),
                    "name": org.name,
                    "quota_limit": org.quota_limit,
                }
                redis_client.setex(cache_key, 300, json.dumps(org_data))
            except Organization.DoesNotExist:
                raise AuthenticationFailed('Invalid API Key')
        else:
            org_data = json.loads(org_data_json)
        
        user = OrganizationUser(
            organization_id=org_data['organization_id'],
            name=org_data['name'],
            quota_limit=org_data['quota_limit']
        )
        
        return (user, None)




class InternalKeyAuthentication(BaseAuthentication):
    """
    Lightweight authentication for internal services using 'X-Internal-Secret' header.
    Checks against settings.INTERNAL_API_SECRET; creates a privileged InternalUser.
    """
    def authenticate(self, request):
        """Authenticate request using X-Internal-Secret header."""
        secret = request.headers.get('X-Internal-Secret')

        if not secret:
            
            
            
            
            
            
            logger.debug("X-Internal-Secret header missing for internal request")
            
            
            
            return None

        if secret != settings.INTERNAL_API_SECRET:
            logger.warning(f"Invalid X-Internal-Secret provided for internal request: {secret[:10]}...") 
            raise AuthenticationFailed('Invalid internal secret')

        
        
        class InternalUser:
            def __init__(self):
                self.is_authenticated = True
                self.is_internal = True
                
                
                

        
        
        return (InternalUser(), None) 

    def authenticate_header(self, request):
        """Return header type for 401 responses"""
        
        
        
        return 'X-Internal-Secret' 