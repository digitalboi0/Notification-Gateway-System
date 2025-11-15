
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status as http_status
from django.utils import timezone
from django.db import connection
import json
import requests
import logging
import os
import secrets
import aio_pika
from dateutil import parser
from django.conf import settings

from gateway_api.redis_client import get_redis_client
from gateway_api.models import Notification, User, Organization
import asyncio
import httpx

from aio_pika import connect_robust, Message, DeliveryMode
from asgiref.sync import sync_to_async
from channels.db import database_sync_to_async
#from gateway_api.authentication import APIKeyAuthentication, InternalKeyAuthentication
import subprocess

from django.core.management import call_command
from io import StringIO
from contextlib import redirect_stdout
import sys
from rest_framework.permissions import IsAuthenticated 

from .rabbitmq import get_channel

from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse, OpenApiExample
from drf_spectacular.types import OpenApiTypes
from gateway_api.serializers import (
    NotificationCreateSerializer,
    NotificationResponseSerializer,
    NotificationStatusRequestSerializer,
    NotificationStatusResponseSerializer,
    InternalStatusUpdateSerializer,
    StandardResponseSerializer,
    UserSerializer,
    UserUpdateSerializer,
    UserPreferencesSerializer,
    OrganizationSerializer,
    HealthCheckSerializer,
)
from django.views.decorators.csrf import csrf_exempt

logger = logging.getLogger(__name__)



from prometheus_client import Counter, Histogram, REGISTRY, CollectorRegistry





_registry = REGISTRY


NOTIF_ACCEPTED_TOTAL_NAME = 'gateway_notifications_accepted_total'
NOTIF_ACCEPTED_CREATED_NAME = f'{NOTIF_ACCEPTED_TOTAL_NAME}_created' 
NOTIF_ACCEPTED_NAME = NOTIF_ACCEPTED_TOTAL_NAME 

NOTIF_REJECTED_TOTAL_NAME = 'gateway_notifications_rejected_total'
NOTIF_REJECTED_CREATED_NAME = f'{NOTIF_REJECTED_TOTAL_NAME}_created'
NOTIF_REJECTED_NAME = NOTIF_REJECTED_TOTAL_NAME

REQ_LATENCY_NAME = 'gateway_request_duration_seconds'
REQ_LATENCY_SUM_NAME = f'{REQ_LATENCY_NAME}_sum'
REQ_LATENCY_COUNT_NAME = f'{REQ_LATENCY_NAME}_count'
REQ_LATENCY_CREATED_NAME = f'{REQ_LATENCY_NAME}_created'




def safe_register_metric(metric_class, name, *args, **kwargs):
    """Safely register a metric, checking for duplicates first."""
    
    if name in _registry._names_to_collectors:
        logger.warning(f"Metric '{name}' is already registered. Skipping re-registration.")
        
        
        
        return _registry._names_to_collectors[name]
    else:
        
        metric_instance = metric_class(*args, **kwargs)
        
        
        
        
        return metric_instance


NOTIFICATIONS_ACCEPTED = safe_register_metric(
    Counter,
    NOTIF_ACCEPTED_TOTAL_NAME,
    NOTIF_ACCEPTED_TOTAL_NAME, 
    'Total notifications accepted',
    ['notification_type', 'org_id_prefix']
)
NOTIFICATIONS_REJECTED = safe_register_metric(
    Counter,
    NOTIF_REJECTED_TOTAL_NAME,
    NOTIF_REJECTED_TOTAL_NAME, 
    'Total notifications rejected',
    ['reason', 'org_id_prefix']
)
REQUEST_LATENCY = safe_register_metric(
    Histogram,
    REQ_LATENCY_NAME,
    REQ_LATENCY_NAME, 
    'Request latency in seconds',
    ['endpoint']
)


USER_CACHE_TTL = 600  
TEMPLATE_CACHE_TTL = 300  


from rest_framework.views import APIView as BaseAPIView







class InternalOrganizationCreationView(APIView):
    """
    Internal API endpoint to trigger the create_org management command.
    Requires internal authentication.
    """

    #authentication_classes = [InternalKeyAuthentication] 
    #permission_classes = [IsAuthenticated] 
    
    @extend_schema(
        operation_id='trigger_create_organization',
        summary='Create organization via management command (Internal)',
        description='''
        **Internal endpoint for organization creation.**
        
        Triggers the `create_org` management command and returns the generated
        organization ID and API key.
        
        This is used internally to create organizations programmatically.
        ''',
        tags=['Internal'],
        request={
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Organization name'},
                'plan': {'type': 'string', 'enum': ['free', 'pro', 'enterprise'], 'default': 'pro'},
                'quota': {'type': 'integer', 'default': 10000, 'description': 'Daily quota limit'}
            },
            'required': ['name']
        },
        responses={
            201: OpenApiResponse(
                description='Organization created successfully',
                examples=[
                    OpenApiExample(
                        'Success',)])}
    )
    
            
    @csrf_exempt
    def post(self, request):
        """Receive organization details and run the create_org command."""
        try:
            org_details = request.data
            name = org_details.get('name')
            plan = org_details.get('plan', 'pro') 
            quota = org_details.get('quota', 10000) 

            if not name:
                 return Response({
                     'success': False,
                     'error': 'Missing name',
                     'message': 'Organization name is required',
                     'meta': get_standard_meta()
                 }, status=http_status.HTTP_400_BAD_REQUEST)

            
            out = StringIO()
            err = StringIO()
            try:
                
                call_command('create_org', name, plan=plan, quota=quota, stdout=out, stderr=err)
                output = out.getvalue()
                error_output = err.getvalue()

                if error_output:
                     
                     logger.error(f"create_org command failed: {error_output}")
                     return Response({
                         'success': False,
                         'error': 'Command execution failed',
                         'message': f'Command failed: {error_output}',
                         'meta': get_standard_meta()
                     }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

                
                
                
                
                
                lines = output.strip().split('\n')
                org_id = None
                api_key = None
                for line in lines:
                    if line.startswith('ID: '):
                        org_id = line.split('ID: ')[1].strip()
                    elif line.startswith('API Key: '):
                        api_key = line.split('API Key: ')[1].strip()

                if not org_id or not api_key:
                     logger.error(f"Failed to parse org ID or API key from command output: {output}")
                     return Response({
                         'success': False,
                         'error': 'Command output parsing failed',
                         'message': 'Could not extract organization details from command output',
                         'meta': get_standard_meta()
                     }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

                logger.info(f"Organization creation command triggered successfully via API: {name} (ID: {org_id})")
                return Response({
                    'success': True,
                    'data': {
                        'organization_id': org_id,
                        'api_key': api_key
                    },
                    'message': 'Organization creation command executed successfully',
                    'meta': get_standard_meta()
                }, status=http_status.HTTP_201_CREATED)

            except subprocess.CalledProcessError as e:
                 logger.error(f"create_org command subprocess error: {str(e)}")
                 return Response({
                     'success': False,
                     'error': 'Subprocess error',
                     'message': f'Command execution failed: {str(e)}',
                     'meta': get_standard_meta()
                 }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            except Exception as e:
                 logger.error(f"create_org command execution failed: {str(e)}", exc_info=True)
                 return Response({
                     'success': False,
                     'error': 'Execution error',
                     'message': f'An error occurred while executing the command: {str(e)}',
                     'meta': get_standard_meta()
                 }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

        except Exception as e:
            logger.error(f"Internal organization creation API failed: {str(e)}", exc_info=True)
            return Response({
                'success': False,
                'error': 'Internal server error',
                'message': 'An unexpected error occurred',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)





class AsyncAPIView(BaseAPIView):
    """
    Custom APIView with async dispatch to handle async handlers (e.g., async def post).
    Awaits async methods seamlessly in ASGI environments.
    """

    async def dispatch(self, request, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        request = self.initialize_request(request, *args, **kwargs)
        self.request = request
        self.headers = self.default_response_headers  

        try:
            await sync_to_async(self.initial)(request, *args, **kwargs)  

            if request.method.lower() in self.http_method_names:
                handler = getattr(self, request.method.lower(), self.http_method_not_allowed)
            else:
                handler = self.http_method_not_allowed

            if asyncio.iscoroutinefunction(handler):
                response = await handler(request, *args, **kwargs)  
            else:
                response = handler(request, *args, **kwargs)  

        except Exception as exc:
            response = self.handle_exception(exc)

        self.response = self.finalize_response(request, response, *args, **kwargs)
        return self.response





def get_standard_meta():
    """Get standard meta data for responses"""
    return {
        'total': 1,
        'limit': 1,
        'page': 1,
        'total_pages': 1,
        'has_next': False,
        'has_previous': False
    }


async def handle_status_update(notification_id, organization_id, new_status, timestamp=None, error=None):
    """
    Handle notification status update from workers
    Shared function used by internal status endpoints
    """
    
    if not all([notification_id, new_status, organization_id]):
        return {
            'success': False,
            'error': 'Missing required fields',
            'message': 'notification_id, status, and organization_id are required',
            'status_code': http_status.HTTP_400_BAD_REQUEST
        }
    
    
    valid_statuses = ['queued', 'processing', 'delivered', 'failed', 'bounced', 'rejected']
    if new_status not in valid_statuses:
        return {
            'success': False,
            'error': 'Invalid status',
            'message': f'status must be one of {valid_statuses}',
            'status_code': http_status.HTTP_400_BAD_REQUEST
        }
    
    try:
        notification = await database_sync_to_async(Notification.objects.get)(id=notification_id)
        
        
        if notification.status in ['delivered', 'failed', 'bounced', 'rejected'] and notification.status == new_status:
            logger.info(f"Duplicate status update for {notification_id} (current: {notification.status})")
            return {
                'success': True,
                'message': 'Status already updated',
                'status_code': http_status.HTTP_200_OK
            }
        
        
        if new_status == 'delivered' and notification.status != 'delivered':
            await update_quota(organization_id, successful=True)
        elif new_status in ['failed', 'bounced', 'rejected'] and notification.status not in ['delivered', 'failed', 'bounced', 'rejected']:
            await update_quota(organization_id, successful=False)
        
        
        notification.status = new_status
        if timestamp:
            try:
                notification.delivered_at = parser.parse(timestamp)
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid timestamp format: {timestamp} - {e}")
        if error:
            notification.error_message = error[:500]  
        await database_sync_to_async(notification.save)() 
        
        logger.info(f"Status updated: {notification_id} -> {new_status}")
        return {
            'success': True,
            'message': 'Status updated successfully',
            'status_code': http_status.HTTP_200_OK
        }
        
    except Notification.DoesNotExist:
        return {
            'success': False,
            'error': 'Notification not found',
            'message': 'Invalid notification ID',
            'status_code': http_status.HTTP_404_NOT_FOUND
        }
    except Exception as e:
        logger.error(f"Error updating status: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': 'Internal error',
            'message': str(e),
            'status_code': http_status.HTTP_500_INTERNAL_SERVER_ERROR
        }


async def update_quota(organization_id, successful):
    """Handle quota updates based on delivery success"""
    pending_key = f"pending:{organization_id}"
    quota_key = f"quota:{organization_id}"
    redis_client = await get_redis_client() 
    
    try:
        if successful:
            
            current_pending = await redis_client.decr(pending_key)
            if current_pending < 0:
               await redis_client.incr(pending_key)  
            
            
            current_quota = await redis_client.incr(quota_key)
            if current_quota == 1:  
               await redis_client.expire(quota_key, 86400)  
        else:
            
            current_pending = await redis_client.decr(pending_key)
            if current_pending < 0:
               await redis_client.incr(pending_key)
    except Exception as e:
        logger.error(f"Error updating quota for {organization_id}: {e}")






class NotificationAPIView(AsyncAPIView):
    
    
    
    
    """
    Public API for notification management
    POST /api/v1/notifications/ - Create notification
    """
    
    
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    
    @extend_schema(
        operation_id='create_notification',
        summary='Create a new notification',
        description='''
        Submit a notification request for email or push delivery.
        
        **Flow:**
        1. Validates user exists and has not opted out
        2. Checks template exists and validates variables
        3. Verifies rate limits and quota
        4. Queues notification for processing
        5. Returns notification ID for tracking
        
        **Rate Limits:** 100 requests/minute per organization
        **Quota:** Based on your plan (check with status endpoint)
        ''',
        tags=['Notifications'],
        request=NotificationCreateSerializer,
        responses={
            202: OpenApiResponse(
                response=StandardResponseSerializer,
                description='Notification accepted for processing',
                examples=[
                    OpenApiExample(
                        'Email Notification',
                        value={
                            'success': True,
                            'data': {
                                'notification_id': 'abc123xyz',
                                'status': 'accepted',
                                'request_id': 'req_xyz789',
                                'correlation_id': 'corr_456'
                            },
                            'message': 'Notification accepted for processing',
                            'meta': {
                                'total': 1,
                                'limit': 1,
                                'page': 1,
                                'total_pages': 1,
                                'has_next': False,
                                'has_previous': False
                            }
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description='Bad request - missing fields or invalid parameters'),
            401: OpenApiResponse(description='Unauthorized - invalid or missing API key'),
            403: OpenApiResponse(description='Forbidden - user opted out of notifications'),
            404: OpenApiResponse(description='Not found - user or template does not exist'),
            429: OpenApiResponse(description='Too many requests - rate limit or quota exceeded'),
            500: OpenApiResponse(description='Internal server error'),
        },
        parameters=[
            OpenApiParameter(
                name='X-API-Key',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description='Organization API key for authentication',
                examples=[
                    OpenApiExample('Example Key', value='org_test_key_12345')
                ]
            ),
        ],
        examples=[
            OpenApiExample(
                'Email Welcome Notification',
                value={
                    'notification_type': 'email',
                    'user_id': 'user_123',
                    'template_code': 'welcome_email',
                    'variables': {
                        'name': 'John Doe',
                        'company': 'Acme Corp'
                    },
                    'priority': 5
                },
                request_only=True,
            ),
            OpenApiExample(
                'Push Alert Notification',
                value={
                    'notification_type': 'push',
                    'user_id': 'user_456',
                    'template_code': 'alert_urgent',
                    'variables': {
                        'message': 'Your order has shipped!'
                    },
                    'priority': 9
                },
                request_only=True,
            ),
        ]
    )
    @csrf_exempt
    async  def post(self, request):
        """Create a new notification request"""
        redis_client = await get_redis_client() 

        with REQUEST_LATENCY.labels(endpoint='create_notification').time():
            org_prefix = 'unknown'
            org_id = None

            
            try:
                
                notification_type = request.data.get('notification_type')
                user_id = request.data.get('user_id')
                template_code = request.data.get('template_code')
                variables = request.data.get('variables', {})
                request_id = request.data.get('request_id', secrets.token_urlsafe(16))
                priority = request.data.get('priority', 5)
                metadata = request.data.get('metadata', {})
                api_key = request.headers.get('X-API-Key')
                
                
                if hasattr(request, 'user') and hasattr(request.user, 'organization_id'):
                    org_id = request.user.organization_id
                    org_prefix = org_id[:8] if org_id else 'unknown'
                else:
                    NOTIFICATIONS_REJECTED.labels(reason='unauthenticated', org_id_prefix='unauthenticated').inc()
                    return Response({
                        'success': False,
                        'error': 'Authentication required',
                        'message': 'X-API-Key header is required',
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_401_UNAUTHORIZED)

                
                if not all([notification_type, user_id, template_code]):
                    NOTIFICATIONS_REJECTED.labels(reason='missing_fields', org_id_prefix=org_prefix).inc()
                    return Response({
                        'success': False,
                        'error': 'Missing required fields',
                        'message': 'notification_type, user_id, and template_code are required',
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_400_BAD_REQUEST)
                
                if notification_type not in ['email', 'push']:
                    NOTIFICATIONS_REJECTED.labels(reason='invalid_type', org_id_prefix=org_prefix).inc()
                    return Response({
                        'success': False,
                        'error': 'Invalid notification type',
                        'message': 'notification_type must be "email" or "push"',
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_400_BAD_REQUEST)

                
                idempotency_key = f"notification:request:{request_id}"
                existing = await redis_client.get(idempotency_key)
                if existing:
                    logger.info(f"Duplicate request detected: {request_id}")
                    existing_data = json.loads(existing)
                    return Response({
                        'success': True,
                        'data': existing_data,
                        'message': 'Notification already accepted (duplicate request)',
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_200_OK)



                user_task = self._get_user_data(user_id, org_id, request.correlation_id, api_key)
                template_task = self._get_template(template_code, org_id, request.correlation_id)

                user_response, template_response = await asyncio.gather(user_task, template_task)



                if not user_response.get('success'):
                    NOTIFICATIONS_REJECTED.labels(reason='user_not_found', org_id_prefix=org_prefix).inc()
                    return Response({
                        'success': False,
                        'error': 'User not found',
                        'message': user_response.get('message', 'User does not exist'),
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_404_NOT_FOUND)

                user_data = user_response['data']
                user_prefs = user_data.get('preferences', {})

                
                if notification_type == 'email' and not user_prefs.get('email', True):
                    NOTIFICATIONS_REJECTED.labels(reason='email_opt_out', org_id_prefix=org_prefix).inc()
                    return Response({
                        'success': False,
                        'error': 'User opted out',
                        'message': 'User has disabled email notifications',
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_403_FORBIDDEN)
                
                if notification_type == 'push' and not user_prefs.get('push', True):
                    NOTIFICATIONS_REJECTED.labels(reason='push_opt_out', org_id_prefix=org_prefix).inc()
                    return Response({
                        'success': False,
                        'error': 'User opted out',
                        'message': 'User has disabled push notifications',
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_403_FORBIDDEN)
                
                if notification_type == 'push' and not user_data.get('push_token'):
                    NOTIFICATIONS_REJECTED.labels(reason='no_push_token', org_id_prefix=org_prefix).inc()
                    return Response({
                        'success': False,
                        'error': 'No push token',
                        'message': 'User does not have a push token registered',
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_400_BAD_REQUEST)

                
               
                if not template_response.get('success'):
                    NOTIFICATIONS_REJECTED.labels(reason='template_error', org_id_prefix=org_prefix).inc()
                    return Response({
                        'success': False,
                        'error': 'Template error',
                        'message': template_response.get('message', 'Template could not be retrieved'),
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_400_BAD_REQUEST)
                
                template_data = template_response['data']

                
                missing_variables = await self._validate_template_variables(template_data, variables)
                if missing_variables:
                    NOTIFICATIONS_REJECTED.labels(reason='missing_template_variables', org_id_prefix=org_prefix).inc()
                    return Response({
                        'success': False,
                        'error': 'Missing template variables',
                        'message': f'Missing required template variables: {", ".join(missing_variables)}',
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_400_BAD_REQUEST)

                
                rate_key = f"rate:{org_id}"
                current_rate = await redis_client.incr(rate_key)
                if current_rate == 1:
                    await redis_client.expire(rate_key, 60)
                if current_rate > 100:
                    NOTIFICATIONS_REJECTED.labels(reason='rate_limit', org_id_prefix=org_prefix).inc()
                    return Response({
                        'success': False,
                        'error': 'Rate limit exceeded',
                        'message': 'Max 100 requests per minute',
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_429_TOO_MANY_REQUESTS)

                
                quota_key = f"quota:{org_id}"
                pending_key = f"pending:{org_id}"

                quota_result, pending_result = await asyncio.gather(
                redis_client.get(quota_key),
                redis_client.get(pending_key)
                )

                

                current_quota = int(quota_result or 0)
                pending_quota = int(pending_result or 0)
                

                total_used = current_quota + pending_quota
                
                if total_used >= request.user.quota_limit:
                    NOTIFICATIONS_REJECTED.labels(reason='quota_exceeded', org_id_prefix=org_prefix).inc()
                    return Response({
                        'success': False,
                        'error': 'Quota exceeded',
                        'message': 'Your notification quota has been exhausted',
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_429_TOO_MANY_REQUESTS)

                
                await redis_client.incr(pending_key)
                if pending_quota == 0:
                    await redis_client.expire(pending_key, 3600)

                
                notification_id = secrets.token_urlsafe(16)
                correlation_id = request.correlation_id

                
                try:
                    await database_sync_to_async(Notification.objects.create)(
                        id=notification_id,
                        correlation_id=correlation_id,
                        organization_id=org_id,
                        user_id=user_id,
                        notification_type=notification_type,
                        template_code=template_code,
                        status='queued',
                        priority=priority,
                        request_id=request_id
                    )
                except Exception as e:
                    logger.error(f"Failed to create notification record: {str(e)}")
                    

                response_data = {
                    'notification_id': notification_id,
                    'status': 'accepted',
                    'request_id': request_id,
                    'correlation_id': correlation_id
                }

                
                message = {
                    'notification_id': notification_id,
                    'correlation_id': correlation_id,
                    'organization_id': org_id,
                    'user_id': user_id,
                    'notification_type': notification_type,
                    'template_code': template_code,
                    'template_content': template_data.get('content', ''),
                    'template_subject': template_data.get('subject', ''),
                    'template_variables': template_data.get('variables', []),
                    'variables': variables,
                    'priority': priority,
                    'metadata': metadata,
                    'user_email': user_data.get('email'),
                    'user_name': user_data.get('name'),
                    'push_token': user_data.get('push_token'),
                    'created_at': timezone.now().isoformat(),
                    'request_id': request_id
                }

                
                await self._publish_to_queue(
                    routing_key=f'{notification_type}.queue',
                    message=message,
                    priority=priority,
                    correlation_id=correlation_id
                )

                
                await redis_client.setex(idempotency_key, 600, json.dumps(response_data))

                
                NOTIFICATIONS_ACCEPTED.labels(
                    notification_type=notification_type,
                    org_id_prefix=org_prefix
                ).inc()

                logger.info(
                    "Notification accepted",
                    extra={
                        'correlation_id': correlation_id,
                        'notification_type': notification_type,
                        'template_code': template_code
                    }
                )

                return Response({
                    'success': True,
                    'data': response_data,
                    'message': 'Notification accepted for processing',
                    'meta': get_standard_meta()
                }, status=http_status.HTTP_202_ACCEPTED)

            except Exception as e:
                NOTIFICATIONS_REJECTED.labels(reason='internal_error', org_id_prefix=org_prefix).inc()
                logger.error(
                    f"Failed to accept notification: {str(e)}",
                    extra={'correlation_id': getattr(request, 'correlation_id', 'unknown')},
                    exc_info=True
                )
                return Response({
                    'success': False,
                    'error': 'Internal server error',
                    'message': 'An unexpected error occurred',
                    'meta': get_standard_meta()
                }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

    async def _get_user_data(self, user_id, org_id, correlation_id, api_key):
        redis_client = await get_redis_client() 
        """Get user data with Redis caching"""
        user_cache_key = f"user:{user_id}:{org_id}"
        cached = await redis_client.get(user_cache_key)
        if cached:
            logger.debug(f"User cache hit: {user_id}")
            return json.loads(cached)

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                
                response = await client.get (
                    f"{settings.USER_SERVICE_URL}/users/{user_id}",
                    headers={
                        'X-Organization-ID': org_id,
                        'X-Correlation-ID': correlation_id,
                        'Content-Type': 'application/json',
                        'X-Internal-Secret': settings.INTERNAL_API_SECRET,
                        'X-API-Key': api_key

                    },
                    timeout=3
                )
                
                response.raise_for_status()
                data = response.json()
            await redis_client.setex(user_cache_key, USER_CACHE_TTL, json.dumps(data))
            return data
        except httpx.HTTPError as e:
            logger.error(f"User service error for {user_id}: {e}")
            return {'success': False, 'message': f'User service unavailable: {str(e)}'}

    async def _get_template(self, template_code, org_id, correlation_id):
        redis_client = await get_redis_client() 
        """Get template data from Template Service with caching"""
        template_cache_key = f"template:{template_code}:en"
        cached = await redis_client.get(template_cache_key)
        if cached:
            logger.debug(f"Template cache hit: {template_code}")
            return json.loads(cached)

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                response = await client.get(
                    f"{settings.TEMPLATE_SERVICE_URL}/api/v1/templates/{template_code}/",
                    headers={
                        'X-Internal-Secret': settings.INTERNAL_API_SECRET,
                        'X-Organization-ID': org_id,
                        'X-Correlation-ID': correlation_id,
                        'Content-Type': 'application/json'
                    },
                    timeout=3
                )
                response.raise_for_status()
                data = response.json()
                
            if data.get('success', False):
                await redis_client.setex(template_cache_key, TEMPLATE_CACHE_TTL, json.dumps(data))
            return data
        except httpx.HTTPError as e:
            logger.error(f"Template service error for {template_code}: {e}")
            return {
                'success': False, 
                'message': f'Template service unavailable: {str(e)}'
            }

    async def _validate_template_variables(self, template_data, provided_variables):
        """Validate that all required template variables are provided"""
        required_variables = template_data.get('variables', [])
        missing = []
        
        for var in required_variables:
            if var not in provided_variables:
                missing.append(var)
                
        return missing

    async def _publish_to_queue(self, routing_key, message, priority, correlation_id):
        """Publish message to RabbitMQ using shared async connection"""
        try:
            channel = await get_channel()  
            
            
            queue = await channel.declare_queue(
                routing_key,
                durable=True,
                arguments={
                    'x-max-priority': 10,
                    'x-dead-letter-exchange': 'dlx.notifications',
                    'x-dead-letter-routing-key': f'dl.{routing_key}'
                }
            )
            
            
            await queue.bind('notifications.direct', routing_key)
            
            
            exchange = await channel.get_exchange('notifications.direct')
            
            
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(message, default=str).encode(),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    priority=min(priority, 10),
                    correlation_id=correlation_id,
                    content_type='application/json'
                ),
                routing_key=routing_key
            )
            logger.debug(f"Published to queue: {routing_key}")
        except Exception as e:
            logger.critical(f"RabbitMQ publish failed: {e}", exc_info=True)
            raise

class NotificationStatusCheckView(AsyncAPIView):
    """POST /api/v1/notifications/status/ - Check notification status"""
    authentication_classes = [APIKeyAuthentication]
    permission_classes = [IsAuthenticated]
    
    
    @extend_schema(
        operation_id='check_notification_status',
        summary='Check notification delivery status',
        description='''
        Retrieve the current status of a notification by its ID.
        
        **Possible Statuses:**
        - `queued` - Waiting to be processed
        - `processing` - Currently being sent
        - `delivered` - Successfully delivered
        - `failed` - Delivery failed (check error_message)
        - `bounced` - Email bounced
        - `rejected` - Rejected by provider
        ''',
        tags=['Notifications'],
        request=NotificationStatusRequestSerializer,
        responses={
            200: OpenApiResponse(
                response=StandardResponseSerializer,
                description='Notification status retrieved successfully',
                examples=[
                    OpenApiExample(
                        'Delivered Notification',
                        value={
                            'success': True,
                            'data': {
                                'notification_id': 'abc123xyz',
                                'status': 'delivered',
                                'notification_type': 'email',
                                'template_code': 'welcome_email',
                                'created_at': '2025-01-01T12:00:00Z',
                                'updated_at': '2025-01-01T12:01:00Z',
                                'delivered_at': '2025-01-01T12:01:00Z',
                                'error_message': None
                            },
                            'message': 'Notification status retrieved',
                            'meta': {}
                        }
                    ),
                    OpenApiExample(
                        'Failed Notification',
                        value={
                            'success': True,
                            'data': {
                                'notification_id': 'xyz789abc',
                                'status': 'failed',
                                'notification_type': 'email',
                                'template_code': 'welcome_email',
                                'created_at': '2025-01-01T12:00:00Z',
                                'updated_at': '2025-01-01T12:02:00Z',
                                'delivered_at': None,
                                'error_message': 'Invalid email address'
                            },
                            'message': 'Notification status retrieved',
                            'meta': {}
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description='Bad request - missing notification_id'),
            401: OpenApiResponse(description='Unauthorized - invalid API key'),
            404: OpenApiResponse(description='Not found - notification does not exist'),
        },
        parameters=[
            OpenApiParameter(
                name='X-API-Key',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description='Organization API key'
            ),
        ]
    )
    async def post(self, request):
        notification_id = request.data.get('notification_id')
        if not notification_id:
            return Response({
                'success': False,
                'error': 'Missing notification_id',
                'message': 'notification_id is required',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_400_BAD_REQUEST)
        
        try:
            notification = await database_sync_to_async(Notification.objects.get)(
                id=notification_id,
                organization_id=request.user.organization_id
            )
            return Response({
                'success': True,
                'data': {
                    'notification_id': str(notification.id),
                    'status': notification.status,
                    'notification_type': notification.notification_type,
                    'template_code': notification.template_code,
                    'created_at': notification.created_at.isoformat(),
                    'updated_at': notification.updated_at.isoformat(),
                    'delivered_at': notification.delivered_at.isoformat() if notification.delivered_at else None,
                    'error_message': notification.error_message
                },
                'message': 'Notification status retrieved',
                'meta': get_standard_meta()
            })
        except Notification.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Notification not found',
                'message': 'The requested notification does not exist',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_404_NOT_FOUND)


class InternalStatusView(AsyncAPIView):
    """
    Internal API for worker services to report notification status
    POST /internal/email/status/ - Email worker status updates
    POST /internal/push/status/ - Push worker status updates
    """
    #authentication_classes = [APIKeyAuthentication]
    
    @extend_schema(
        operation_id='update_notification_status_internal',
        summary='Update notification status (Internal)',
        description='''
        **Internal endpoint for worker services only.**
        
        Workers use this endpoint to report delivery status back to the gateway.
        Requires internal authentication via X-Internal-Secret header.
        
        This endpoint handles:
        - Quota adjustments (release pending on failure, increment delivered on success)
        - Idempotency (won't reprocess finalized statuses)
        - Timestamp tracking
        - Error message recording
        ''',
        tags=['Internal'],
        request=InternalStatusUpdateSerializer,
        responses={
            200: OpenApiResponse(description='Status updated successfully'),
            400: OpenApiResponse(description='Bad request - missing fields or invalid status'),
            401: OpenApiResponse(description='Unauthorized - invalid internal secret'),
            404: OpenApiResponse(description='Notification not found'),
            500: OpenApiResponse(description='Internal error'),
        },
        parameters=[
            OpenApiParameter(
                name='X-Internal-Secret',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description='Internal service secret key (not the same as X-API-Key)'
            ),
            OpenApiParameter(
                name='notification_type',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                required=True,
                description='Type of notification worker',
                enum=['email', 'push']
            ),
        ]
    )
    @csrf_exempt
    async def post(self, request, notification_type):
        
        if request.headers.get('X-Internal-Secret') != os.getenv('INTERNAL_API_SECRET'):
            return Response({
                'success': False,
                'error': 'Unauthorized',
                'message': 'Invalid internal secret',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_401_UNAUTHORIZED)
        
        
        notification_id = request.data.get('notification_id')
        organization_id = request.data.get('organization_id')
        new_status = request.data.get('status')
        timestamp = request.data.get('timestamp')
        error = request.data.get('error')
        
        
        result = await handle_status_update(
            notification_id=notification_id,
            organization_id=organization_id,
            new_status=new_status,
            timestamp=timestamp,
            error=error
        )
        
        return Response({
            'success': result['success'],
            'message': result.get('message'),
            'error': result.get('error'),
            'meta': get_standard_meta()
        }, status=result['status_code'])


class HealthCheckView(AsyncAPIView):
    """Health check endpoint - ASYNC VERSION"""
    #authentication_classes = [APIKeyAuthentication]
    
    @extend_schema(
        operation_id='health_check',
        summary='Service health check',
        description='''
        Check the health status of the gateway and all its dependencies.
        
        **Checks performed:**
        - Database connectivity
        - Redis cache availability
        - RabbitMQ message queue
        - Template service availability
        - User service availability
        - Email service availability
        - Push service availability
        
        Returns 200 if all checks pass, 503 if any fail.
        ''',
        tags=['System'],
        responses={
            200: OpenApiResponse(
                response=HealthCheckSerializer,
                description='Service is healthy',
                examples=[
                    OpenApiExample(
                        'All Services Healthy',
                        value={
                            'service': 'api-gateway',
                            'status': 'healthy',
                            'timestamp': '2025-01-01T12:00:00Z',
                            'checks': {
                                'database': 'healthy',
                                'redis': 'healthy',
                                'rabbitmq': 'healthy',
                                'template_service': 'healthy',
                                'user_service': 'healthy',
                                'email_service': 'healthy',
                                'push_service': 'healthy'
                            }
                        }
                    )
                ]
            ),
            503: OpenApiResponse(
                description='Service is unhealthy',
                examples=[
                    OpenApiExample(
                        'Redis Down',
                        value={
                            'service': 'api-gateway',
                            'status': 'unhealthy',
                            'timestamp': '2025-01-01T12:00:00Z',
                            'checks': {
                                'database': 'healthy',
                                'redis': 'unhealthy: Connection refused',
                                'rabbitmq': 'healthy',
                                'template_service': 'healthy',
                                'user_service': 'healthy',
                                'email_service': 'healthy',
                                'push_service': 'healthy'
                            }
                        }
                    )
                ]
            ),
        }
    )
    @csrf_exempt
    async def get(self, request):
        health_status = {
            'service': 'api-gateway',
            'status': 'healthy',
            'timestamp': timezone.now().isoformat(),
            'checks': {}
        }
        
        
        results = await asyncio.gather(
            self._check_database(),
            self._check_redis(),
            self._check_rabbitmq(),
            self._check_template_service(),
            self._check_user_service(),
            self._check_email_service(),
            self._check_push_service(),
            return_exceptions=True
        )
        
        
        checks = ['database', 'redis', 'rabbitmq', 'template_service', 'user_service', 'email_service', 'push_service']
        for check_name, result in zip(checks, results):
            if isinstance(result, Exception):
                health_status['checks'][check_name] = f'unhealthy: {str(result)}'
                health_status['status'] = 'unhealthy'
            else:
                health_status['checks'][check_name] = result
                if result != 'healthy':
                    health_status['status'] = 'unhealthy'
        
        status_code = 200 if health_status['status'] == 'healthy' else 503
        return Response(health_status, status=status_code)
    
    async def _check_database(self):
        """Check database connection"""
        try:
            await database_sync_to_async(connection.ensure_connection)()
            return 'healthy'
        except Exception as e:
            return f'unhealthy: {str(e)}'
    
    async def _check_redis(self):
        redis_client = await get_redis_client() 
        """Check Redis connection"""
        try:

            await redis_client.setex('health_check', 10, 'ok')
            await redis_client.get('health_check')
            return 'healthy'
        except Exception as e:
            return f'unhealthy: {str(e)}'
    
    async def _check_rabbitmq(self):
        """Check RabbitMQ connection"""
        try:
            connection = await connect_robust(
                os.getenv('RABBITMQ_URL'),
                timeout=2
            )
            await connection.close()
            return 'healthy'
        except Exception as e:
            return f'unhealthy: {str(e)}'
    
    async def _check_template_service(self):
        """Check Template Service"""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{settings.TEMPLATE_SERVICE_URL}/health/")
                return 'healthy' if response.status_code == 200 else f'unhealthy: HTTP {response.status_code}'
        except Exception as e:
            return f'unhealthy: {str(e)}'
    
    async def _check_user_service(self):
        """Check User Service"""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{settings.USER_SERVICE_URL}/health")
                return 'healthy' if response.status_code == 200 else f'unhealthy: HTTP {response.status_code}'
        except Exception as e:
            return f'unhealthy: {str(e)}'

    async def _check_email_service(self):
        """Check User Service"""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{settings.EMAIL_SERVICE_URL}/health")
                return 'healthy' if response.status_code == 200 else f'unhealthy: HTTP {response.status_code}'
        except Exception as e:
            return f'unhealthy: {str(e)}'

    async def _check_push_service(self):
        """Check User Service"""
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(f"{settings.PUSH_SERVICE_URL}/health")
                return 'healthy' if response.status_code == 200 else f'unhealthy: HTTP {response.status_code}'
        except Exception as e:
            return f'unhealthy: {str(e)}'
            
            
    



class UserServiceView(APIView):
    
    #authentication_classes = [APIKeyAuthentication]
    #permission_classes = [IsAuthenticated]
    
    
    
    """
    User Service endpoints (PROXY VERSION)
    Validates headers and forwards requests to the real user service.
    Does not interact with the local database anymore.
    """
    
    @extend_schema(
        operation_id='get_user',
        summary='Get user details',
        description='''
        Retrieve user profile information.
        
        **This is a proxy endpoint** that forwards requests to the real user service.
        Validates organization ID and forwards with internal authentication.
        ''',
        tags=['Users'],
        responses={
            200: OpenApiResponse(
                response=StandardResponseSerializer,
                description='User found',
                examples=[
                    OpenApiExample(
                        'User Profile',
                        value={
                            'success': True,
                            'data': {
                                'id': 'user_123',
                                'email': 'john@example.com',
                                'name': 'John Doe',
                                'push_token': 'token_abc',
                                'preferences': {
                                    'email': True,
                                    'push': True
                                },
                                'organization_id': 'org_456',
                                'created_at': '2025-01-01T00:00:00Z',
                                'updated_at': '2025-01-01T00:00:00Z'
                            },
                            'message': 'User found',
                            'meta': {}
                        }
                    )
                ]
            ),
            400: OpenApiResponse(description='Bad request - missing X-Organization-ID header'),
            404: OpenApiResponse(description='User not found'),
            502: OpenApiResponse(description='Bad gateway - user service unavailable'),
        },
        parameters=[
            OpenApiParameter(
                name='user_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                required=True,
                description='User ID'
            ),
            OpenApiParameter(
                name='X-Organization-ID',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description='Organization ID'
            ),
            OpenApiParameter(
                name='X-API-Key',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description='API Key for authentication'
            ),
        ]
    )



    def get(self, request, user_id=None):
        """Handle GET requests - health check or proxy to real user service"""
        if request.path == '/api/v1/users/health/' or request.path.endswith('/health'):
            return self._health_check(request)
        elif user_id and request.path.endswith('/preferences/'):
            
            return self._proxy_request_to_real_service(request, user_id, 'GET_PREFS')
        elif user_id:
            
            return self._proxy_request_to_real_service(request, user_id, 'GET_USER')
        else:
            return Response({
                'success': False,
                'error': 'Not found',
                'message': 'Endpoint not found',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_404_NOT_FOUND)
            
    @extend_schema(
        operation_id='create_user',
        summary='Create a new user',
        description='''
        Create a new user in the system.
        
        **This is a proxy endpoint** that forwards to the real user service.
        ''',
        tags=['Users'],
        request=UserSerializer,
        responses={
            201: OpenApiResponse(description='User created successfully'),
            400: OpenApiResponse(description='Bad request - missing required fields'),
            409: OpenApiResponse(description='Conflict - email already exists'),
            502: OpenApiResponse(description='Bad gateway - user service unavailable'),
        },
        parameters=[
            OpenApiParameter(
                name='X-Organization-ID',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description='Organization ID'
            ),
            OpenApiParameter(
                name='X-API-Key',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description='API Key for authentication'
            ),
        ]
    )        

    def post(self, request, user_id=None):
        """Handle POST requests - proxy to real user service or handle mock org sync"""
        if user_id:
            return Response({
                'success': False,
                'error': 'Method not allowed',
                'message': 'Use PATCH to update user',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_405_METHOD_NOT_ALLOWED)


        if request.path == '/mock/organizations/':
            
            
            
            
            
            
            
            
            return self._proxy_request_to_real_service(request, None, 'CREATE_ORG_INTERNAL') 

        
        return self._proxy_request_to_real_service(request, user_id, 'CREATE_USER')
    
    @extend_schema(
        operation_id='update_user',
        summary='Update user details',
        description='''
        Update user profile or preferences.
        
        **This is a proxy endpoint** that forwards to the real user service.
        ''',
        tags=['Users'],
        request=UserUpdateSerializer,
        responses={
            200: OpenApiResponse(description='User updated successfully'),
            400: OpenApiResponse(description='Bad request'),
            404: OpenApiResponse(description='User not found'),
            502: OpenApiResponse(description='Bad gateway - user service unavailable'),
        },
        parameters=[
            OpenApiParameter(
                name='user_id',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.PATH,
                required=True,
                description='User ID'
            ),
            OpenApiParameter(
                name='X-Organization-ID',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description='Organization ID'
            ),
            OpenApiParameter(
                name='X-API-Key',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description='API Key for authentication'
            ),
        ]
    )

    def patch(self, request, user_id=None):
        """Handle PATCH requests - proxy to real user service"""
        if not user_id:
            return Response({
                'success': False,
                'error': 'User ID required',
                'message': 'User ID is required for PATCH',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_400_BAD_REQUEST)

        
        if request.path.endswith('/preferences/'):
            return self._proxy_request_to_real_service(request, user_id, 'UPDATE_PREFS')
        else:
            return self._proxy_request_to_real_service(request, user_id, 'UPDATE_USER')

    def _health_check(self, request):
        """Health check endpoint - Could check the real user service's health"""
        
        
        logger.info("Health check requested for user service proxy")
        
        try:
            response = requests.get(f"{settings.USER_SERVICE_URL}/health/", timeout=3)
            real_service_healthy = response.status_code == 200
        except requests.RequestException:
            real_service_healthy = False

        if real_service_healthy:
             return Response({
                 'service': 'user-service-proxy',
                 'status': 'healthy',
                 'upstream_status': 'healthy', 
                 'timestamp': timezone.now().isoformat(),
                 'meta': get_standard_meta()
             })
        else:
             return Response({
                 'service': 'user-service-proxy',
                 'status': 'unhealthy',
                 'upstream_status': 'unhealthy', 
                 'timestamp': timezone.now().isoformat(),
                 'meta': get_standard_meta()
             }, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    def _proxy_request_to_real_service(self, request, user_id, action):
        """
        Generic method to proxy requests to the real user service.
        Validates the X-Organization-ID header and forwards the request.
        """
        
        org_id = request.headers.get('X-Organization-ID')
        if not org_id:
            logger.warning(f"X-Organization-ID header missing for {request.method} request to {request.path}")
            return Response({
                'success': False,
                'error': 'Missing Organization ID',
                'message': 'X-Organization-ID header is required',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_400_BAD_REQUEST)

        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        
        

        
        real_user_service_url = getattr(settings, 'USER_SERVICE_URL') 
        if action == 'GET_USER':
            target_url = f"{real_user_service_url}/users/{user_id}"
        elif action == 'GET_PREFS':
            target_url = f"{real_user_service_url}/users/{user_id}/preferences"
        elif action == 'CREATE_USER':
            target_url = f"{real_user_service_url}/users"
        elif action == 'UPDATE_USER':
            target_url = f"{real_user_service_url}/users/{user_id}"
        elif action == 'UPDATE_PREFS':
            target_url = f"{real_user_service_url}/users/{user_id}/preferences"
        elif action == 'CREATE_ORG_INTERNAL':
            
            target_url = f"{real_user_service_url}/internal/organizations/" 
        else:
            
            logger.error(f"Unknown action for proxy: {action}")
            return Response({
                'success': False,
                'error': 'Internal server error',
                'message': 'Proxy configuration error',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            
            
            
            
            
            proxy_headers = {
                'X-Organization-ID': org_id, 
                'X-Correlation-ID': request.headers.get('X-Correlation-ID', ''), 
                
                'X-Internal-Secret': settings.INTERNAL_API_SECRET, 
                'Content-Type': request.content_type, 
            }
            
            

            
            proxy_data = request.data 

            
            if request.method == 'GET':
                response = requests.get(target_url, headers=proxy_headers, timeout=5)
            elif request.method == 'POST':
                response = requests.post(target_url, headers=proxy_headers, json=proxy_data, timeout=5)
            elif request.method == 'PATCH':
                response = requests.patch(target_url, headers=proxy_headers, json=proxy_data, timeout=5)
            else:
                
                return Response({
                    'success': False,
                    'error': 'Method not allowed',
                    'message': f'Method {request.method} not supported for proxying',
                    'meta': get_standard_meta()
                }, status=http_status.HTTP_405_METHOD_NOT_ALLOWED)

            
            response_data = response.json() if response.content else {}
            return Response(response_data, status=response.status_code)

        except requests.RequestException as e:
            logger.error(f"Failed to proxy request to real user service ({target_url}): {e}")
            
            return Response({
                'success': False,
                'error': 'Upstream service error',
                'message': f'Failed to communicate with the real user service: {str(e)}',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_502_BAD_GATEWAY) 
        except json.JSONDecodeError:
            logger.error(f"Real user service returned non-JSON response: {response.text[:200]}...") 
            return Response({
                'success': False,
                'error': 'Upstream service error',
                'message': 'The real user service returned an invalid response format.',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_502_BAD_GATEWAY)


    
    

    
    
    
    




from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.conf import settings




@method_decorator(csrf_exempt, name='dispatch')
class InternalOrganizationSyncView(AsyncAPIView):
    #authentication_classes = [APIKeyAuthentication]
    
    
    @extend_schema(
        operation_id='sync_organization_to_template',
        summary='Sync organization to template service (Internal)',
        description='''
        **Internal endpoint for organization synchronization.**
        
        When a new organization is created, this endpoint forwards the organization
        data to the template service so templates can be scoped per organization.
        
        Requires internal authentication.
        ''',
        tags=['Internal'],
        request=OrganizationSerializer,
        responses={
            201: OpenApiResponse(description='Organization synced to template service'),
            400: OpenApiResponse(description='Bad request - missing required fields'),
            502: OpenApiResponse(description='Bad gateway - template service unavailable'),
            500: OpenApiResponse(description='Internal server error'),
        },
        parameters=[
            OpenApiParameter(
                name='X-Internal-Secret',
                type=OpenApiTypes.STR,
                location=OpenApiParameter.HEADER,
                required=True,
                description='Internal service secret'
            ),
        ]
    )

     
    async def post(self, request):
        """Receive organization data from the gateway and forward to template service."""
        try:
            org_data = request.data

            
            required_fields = ['id', 'name', 'api_key', 'plan', 'quota_limit', 'is_active', 'created_at']
            for field in required_fields:
                if field not in org_data:
                    logger.error(f"Missing required field '{field}' in organization sync data: {org_data}")
                    return Response({
                        'success': False,
                        'error': 'Missing required field',
                        'message': f'Missing: {field}',
                        'meta': get_standard_meta()
                    }, status=http_status.HTTP_400_BAD_REQUEST)

            
            
            
            template_service_url = f"{settings.TEMPLATE_SERVICE_URL}/api/v1/organizations/"

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    template_service_url,
                    json=org_data, 
                    headers={
                        'X-Internal-Secret': settings.INTERNAL_API_SECRET, 
                        'Content-Type': 'application/json'
                        
                        
                    },
                    timeout=5
                    )
                
                response.raise_for_status()

                logger.info(f"Organization synced to template service via gateway: {org_data.get('id')}")
                return Response({
                    'success': True,
                    'message': 'Organization synced to template service',
                    'meta': get_standard_meta()
                }, status=http_status.HTTP_201_CREATED)

        except httpx.HTTPError as e:
            logger.error(f"Failed to sync organization to template service: {e}")
            return Response({
                'success': False,
                'error': 'Template service error',
                'message': f'Failed to sync to template service: {str(e)}',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_502_BAD_GATEWAY) 
        except Exception as e:
            logger.error(f"Internal error syncing organization to template service: {str(e)}", exc_info=True)
            return Response({
                'success': False,
                'error': 'Internal server error',
                'message': 'An unexpected error occurred while syncing organization',
                'meta': get_standard_meta()
            }, status=http_status.HTTP_500_INTERNAL_SERVER_ERROR)
            


 
    

class TemplateDocsProxyView(APIView):
    """
    Proxy view to forward requests to the Template Service's Swagger UI.
    Adds the required X-Internal-Secret header for the template service's internal endpoints.
    Intended for internal access (e.g., by developers/admins via the gateway).
    """

    authentication_classes = [] 
    permission_classes = []          

    def get(self, request, path=''):
        """
        Proxy GET requests to the template service's documentation endpoint.
        Adds X-Internal-Secret header for the *template service's* internal auth.
        Preserves response status, headers, and content.
        """
        
        template_service_base_url = settings.TEMPLATE_SERVICE_URL.rstrip('/') 
        
        path_segment = f"/{path.lstrip('/')}" if path else "/"
        target_url = f"{template_service_base_url}{path_segment}"

        logger.info(f"Proxying GET request to template docs: {target_url}")

        try:
            
            
            proxy_headers = {
                'X-Internal-Secret': settings.INTERNAL_API_SECRET, 
                
                'User-Agent': request.META.get('HTTP_USER_AGENT', 'Django-Notification-Gateway-Proxy'),
                
                'Accept': request.META.get('HTTP_ACCEPT', '*/*'),
                
                
            }

            response = requests.get(
                target_url,
                headers=proxy_headers,
                
                stream=True,
                timeout=10 
            )
            
            

            
            content_type = response.headers.get('Content-Type', 'application/octet-stream')

            
            content = b"" 
            for chunk in response.iter_content(chunk_size=8192):
                if chunk: 
                    content += chunk

            
            return Response(
                content, 
                status=response.status_code, 
                content_type=content_type 
            )

        except requests.RequestException as e:
            logger.error(f"Error proxying request to template docs ({target_url}): {e}")
            
            return Response(
                {'error': 'Template service documentation unavailable', 'details': str(e)},
                status=http_status.HTTP_502_BAD_GATEWAY
            )
        except Exception as e:
            logger.error(f"Unexpected error in TemplateDocsProxyView: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Internal server error in proxy'},
                status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def post(self, request, path=''):
        """
        Proxy POST requests (e.g., for Swagger UI's 'Try it out' feature).
        Adds X-Internal-Secret header for template service internal auth.
        Preserves response status, headers, and content.
        """
        
        template_service_base_url = settings.TEMPLATE_SERVICE_URL.rstrip('/')
        path_segment = f"/{path.lstrip('/')}" if path else "/"
        target_url = f"{template_service_base_url}{path_segment}"

        logger.info(f"Proxying POST request to template service: {target_url}")

        try:
            
            
            proxy_headers = {
                'X-Internal-Secret': settings.INTERNAL_API_SECRET, 
                'Content-Type': request.content_type, 
                'User-Agent': request.META.get('HTTP_USER_AGENT', 'Django-Notification-Gateway-Proxy'),
                
                
            }

            response = requests.post(
                target_url,
                json=request.data, 
                headers=proxy_headers,
                stream=True,
                timeout=10
            )
            

            content_type = response.headers.get('Content-Type', 'application/octet-stream')
            content = b""
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    content += chunk

            return Response(
                content,
                status=response.status_code,
                content_type=content_type
            )

        except requests.RequestException as e:
            logger.error(f"Error proxying POST request to template service ({target_url}): {e}")
            return Response(
                {'error': 'Template service unavailable for the requested action', 'details': str(e)},
                status=http_status.HTTP_502_BAD_GATEWAY
            )
        except Exception as e:
            logger.error(f"Unexpected error in TemplateDocsProxyView POST: {str(e)}", exc_info=True)
            return Response(
                {'error': 'Internal server error in proxy'},
                status=http_status.HTTP_500_INTERNAL_SERVER_ERROR
            )


from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from rest_framework.views import APIView
import requests
from urllib.parse import unquote, urljoin
import logging



class TemplateDocsProxyView(APIView):
    """
    Proxy view for Template Service docs.
    - GET /template-docs/            -> redirects to /template-docs/api/docs/
    - GET /template-docs/<path>      -> proxies to settings.TEMPLATE_SERVICE_URL/<path>
    - If the requested path (after cleaning) is an absolute URL (http/https),
      redirect the client to that URL (so CDN assets load directly).
    """

    authentication_classes = []
    permission_classes = []

    def _clean_path(self, path: str) -> str:
        
        if path is None:
            return ''
        cleaned = unquote(path)
        
        cleaned = cleaned.strip().strip('"').strip("'")
        return cleaned

    def _proxy_request(self, request, target_url, method='GET', data=None):
        headers = {
            'X-Internal-Secret': getattr(settings, 'INTERNAL_API_SECRET', ''),
            'User-Agent': request.META.get('HTTP_USER_AGENT', 'Django-Notification-Gateway-Proxy'),
            'Accept': request.META.get('HTTP_ACCEPT', '*/*'),
        }

        try:
            if method == 'GET':
                resp = requests.get(target_url, headers=headers, params=request.GET, stream=True, timeout=10)
            else:
                resp = requests.post(target_url, headers=headers, json=data, stream=True, timeout=10)
        except requests.RequestException as e:
            logger.error("Error proxying request to template service %s: %s", target_url, e, exc_info=True)
            return None, e

        
        content = b''
        for chunk in resp.iter_content(chunk_size=8192):
            if chunk:
                content += chunk

        return resp, content

    def get(self, request, path=''):
        
        if not path:
            
            
            return HttpResponseRedirect(request.path + 'api/docs/')

        cleaned = self._clean_path(path)

        
        if cleaned.startswith('http://') or cleaned.startswith('https://'):
            logger.info("Redirecting client to external URL from proxy: %s", cleaned)
            return HttpResponseRedirect(cleaned)

        
        base = getattr(settings, 'TEMPLATE_SERVICE_URL', 'http://localhost:8002').rstrip('/')
        target_url = urljoin(base + '/', cleaned.lstrip('/'))  
        logger.info("Proxying GET request to template docs: %s", target_url)

        resp, content_or_error = self._proxy_request(request, target_url, method='GET')
        if resp is None:
            return JsonResponse(
                {'error': 'Template service documentation unavailable', 'details': str(content_or_error)},
                status=502
            )

        content_type = resp.headers.get('Content-Type', 'application/octet-stream')
        return HttpResponse(content_or_error, status=resp.status_code, content_type=content_type)

    def post(self, request, path=''):
        cleaned = self._clean_path(path)
        base = getattr(settings, 'TEMPLATE_SERVICE_URL', 'http://localhost:8002').rstrip('/')

        if cleaned.startswith('http://') or cleaned.startswith('https://'):
            
            return HttpResponseRedirect(cleaned)

        target_url = urljoin(base + '/', cleaned.lstrip('/'))
        logger.info("Proxying POST request to template service: %s", target_url)

        resp, content_or_error = self._proxy_request(request, target_url, method='POST', data=request.data)
        if resp is None:
            return JsonResponse(
                {'error': 'Template service unavailable for the requested action', 'details': str(content_or_error)},
                status=502
            )

        content_type = resp.headers.get('Content-Type', 'application/octet-stream')
        return HttpResponse(content_or_error, status=resp.status_code, content_type=content_type)
            
            