from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
import hashlib
import json
import logging
from gateway_api.redis_client import get_redis
from django.conf import settings

logger = logging.getLogger(__name__)


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
            return None  
        
        redis_client = get_redis()
        cache_key = f"api_key:{hashlib.sha256(api_key.encode()).hexdigest()}"
        
        try:
            
            org_data_json = redis_client.get(cache_key)
            
            if org_data_json:
                
                if isinstance(org_data_json, bytes):
                    org_data_json = org_data_json.decode('utf-8')
                
                try:
                    org_data = json.loads(org_data_json)
                    logger.debug(f"API key cache hit for org: {org_data.get('organization_id', 'unknown')}")
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to decode cached org data: {e}")
                    
                    redis_client.delete(cache_key)
                    org_data = None
            else:
                org_data = None
            
            
            if not org_data:
                from .models import Organization
                try:
                    org = Organization.objects.get(api_key=api_key, is_active=True)
                    org_data = {
                        "organization_id": str(org.id),
                        "name": org.name,
                        "quota_limit": org.quota_limit,
                    }
                    
                    
                    try:
                        redis_client.setex(cache_key, 300, json.dumps(org_data))
                        logger.debug(f"Cached API key for org: {org_data['organization_id']}")
                    except Exception as cache_error:
                        logger.warning(f"Failed to cache org data: {cache_error}")
                        
                    
                except Organization.DoesNotExist:
                    logger.warning(f"Invalid API key attempted: {api_key[:10]}...")
                    raise AuthenticationFailed('Invalid API Key')
                except Exception as db_error:
                    logger.error(f"Database error during authentication: {db_error}")
                    raise AuthenticationFailed('Authentication service error')
            
            
            user = OrganizationUser(
                organization_id=org_data['organization_id'],
                name=org_data['name'],
                quota_limit=org_data['quota_limit']
            )
            
            return (user, None)
            
        except Exception as e:
            logger.error(f"Authentication error: {e}", exc_info=True)
            raise AuthenticationFailed('Authentication failed')
    
    def authenticate_header(self, request):
        """Return header type for 401 responses"""
        return 'X-API-Key'


class InternalKeyAuthentication(BaseAuthentication):
    """
    Lightweight authentication for internal services using 'X-Internal-Secret' header.
    Checks against settings.INTERNAL_API_SECRET; creates a privileged InternalUser.
    """
    
    class InternalUser:
        """Internal service user representation"""
        def __init__(self):
            self.is_authenticated = True
            self.is_internal = True
            self.organization_id = "internal"
            self.name = "Internal Service"
            self.quota_limit = 999999999  
    
    def authenticate(self, request):
        """Authenticate request using X-Internal-Secret header."""
        secret = request.headers.get('X-Internal-Secret')
        
        if not secret:
            
            logger.debug("X-Internal-Secret header missing (not an internal request)")
            return None
        
        if secret != settings.INTERNAL_API_SECRET:
            logger.warning(f"Invalid X-Internal-Secret provided: {secret[:10]}...")
            raise AuthenticationFailed('Invalid internal secret')
        
        logger.debug("Internal service authenticated successfully")
        
        
        return (self.InternalUser(), None)
    
    def authenticate_header(self, request):
        """Return header type for 401 responses"""
        return 'X-Internal-Secret'