# gateway_api/authentication.py

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
        # Get API key from header
        api_key = request.headers.get('X-API-Key')
        
        if not api_key:
            logger.debug("No X-API-Key header provided")
            return None  # Not an error - just no API key provided
        
        logger.info(f"Authenticating API key: {api_key[:15]}...")
        
        try:
            # Get sync Redis client
            redis_client = get_redis()
            
            # Create cache key using SHA256 hash
            api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
            cache_key = f"api_key:{api_key_hash}"
            logger.debug(f"Cache key: {cache_key}")
            
            # Try to get from cache
            org_data = None
            cached_value = None
            
            try:
                cached_value = redis_client.get(cache_key)
                logger.debug(f"Redis returned: {type(cached_value)} = {repr(cached_value)}")
                
                if cached_value:
                    # Since decode_responses=True in your config, this should already be a string
                    # But let's handle both cases for safety
                    if isinstance(cached_value, bytes):
                        cached_value = cached_value.decode('utf-8')
                    
                    # Parse JSON
                    org_data = json.loads(cached_value)
                    logger.info(f"✓ Cache HIT for org: {org_data.get('organization_id', 'unknown')}")
                else:
                    logger.info("✗ Cache MISS - querying database")
                    
            except json.JSONDecodeError as e:
                logger.warning(f"Failed to decode cached JSON: {e}. Value: {repr(cached_value)}")
                # Delete corrupted cache
                try:
                    redis_client.delete(cache_key)
                except:
                    pass
            except Exception as cache_error:
                logger.warning(f"Cache read error: {cache_error}", exc_info=True)
            
            # If not in cache or cache failed, fetch from database
            if not org_data:
                from .models import Organization
                
                try:
                    # Query database
                    org = Organization.objects.get(api_key=api_key, is_active=True)
                    logger.info(f"✓ Found organization in database: {org.name} (ID: {org.id})")
                    
                    # Prepare data
                    org_data = {
                        "organization_id": str(org.id),
                        "name": org.name,
                        "quota_limit": org.quota_limit,
                    }
                    
                    # Cache it for 5 minutes (300 seconds)
                    try:
                        cache_value = json.dumps(org_data)
                        redis_client.setex(cache_key, 300, cache_value)
                        logger.info(f"✓ Cached organization data (TTL: 300s)")
                    except Exception as cache_error:
                        logger.warning(f"Failed to cache organization data: {cache_error}")
                        # Continue anyway - caching failure is not critical
                        
                except Organization.DoesNotExist:
                    logger.warning(f"✗ Invalid API key attempted: {api_key[:15]}...")
                    raise AuthenticationFailed('Invalid API Key')
                    
                except Exception as db_error:
                    logger.error(f"✗ Database query error: {db_error}", exc_info=True)
                    raise AuthenticationFailed('Database error during authentication')
            
            # Create user object
            user = OrganizationUser(
                organization_id=org_data['organization_id'],
                name=org_data['name'],
                quota_limit=org_data['quota_limit']
            )
            
            logger.info(f"✓ Authentication successful for: {user.name} ({user.organization_id})")
            return (user, None)
            
        except AuthenticationFailed:
            # Re-raise authentication failures as-is
            raise
            
        except Exception as e:
            # Log unexpected errors with full stack trace
            logger.error(f"✗ Unexpected authentication error: {type(e).__name__}: {e}", exc_info=True)
            raise AuthenticationFailed('Authentication service error')
    
    def authenticate_header(self, request):
        """Return header type for 401 responses"""
        return 'X-API-Key'


class InternalKeyAuthentication(BaseAuthentication):
    """
    Lightweight authentication for internal services using 'X-Internal-Secret' header.
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
            logger.debug("No X-Internal-Secret header (not an internal request)")
            return None  # Not an error - just not an internal request
        
        # Validate secret
        if secret != settings.INTERNAL_API_SECRET:
            logger.warning(f"✗ Invalid internal secret attempted: {secret[:10]}...")
            raise AuthenticationFailed('Invalid internal secret')
        
        logger.info("✓ Internal service authentication successful")
        return (self.InternalUser(), None)
    
    def authenticate_header(self, request):
        """Return header type for 401 responses"""
        return 'X-Internal-Secret'