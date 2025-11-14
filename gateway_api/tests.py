
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient
from rest_framework import status
from unittest.mock import patch, MagicMock
from django.utils import timezone
from django.conf import settings
import json
import secrets

from .models import Organization, Notification # Import your models
from .views import NotificationAPIView # Import the view class being tested

# Mock data for tests
MOCK_ORGANIZATION_DATA = {
    'id': 'test_org_id_123',
    'name': 'Test Org',
    'api_key': 'org_TestApiKey123...',
    'plan': 'pro',
    'quota_limit': 10000,
    'is_active': True,
    'created_at': timezone.now().isoformat()
}

MOCK_USER_DATA = {
    'success': True,
    'data': {
        'id': 'test_user_id_456',
        'email': 'test@example.com',
        'name': 'Test User',
        'push_token': 'mock_push_token_abc123',
        'preferences': {'email': True, 'push': False},
        'organization_id': MOCK_ORGANIZATION_DATA['id'],
        'created_at': timezone.now().isoformat(),
        'updated_at': timezone.now().isoformat(),
    },
    'message': 'User found',
    'meta': {}
}

MOCK_TEMPLATE_DATA = {
    'success': True,
    'data': {
        'id': 'test_template_id_789',
        'code': 'welcome_email',
        'name': 'Welcome Email Template',
        'content': 'Hi {{ name }}, welcome!',
        'subject': 'Welcome!',
        'language': 'en',
        'status': 'active',
        'is_default': True,
        'version': 1,
        'variables': ['name'],
        'organization_id': MOCK_ORGANIZATION_DATA['id'], # Include org ID
        'created_at': timezone.now().isoformat(),
        'updated_at': timezone.now().isoformat(),
    },
    'message': 'Template retrieved successfully',
    'meta': {}
}

MOCK_RENDERED_TEMPLATE_DATA = {
    'success': True,
    'data': {
        'subject': 'Welcome, Test User!',
        'content': 'Hi Test User, welcome!',
        'html_content': '<p>Hi Test User, welcome!</p>',
        'template_id': 'test_template_id_789',
        'template_version': 1,
        'render_time': 0.001
    },
    'message': 'Template rendered successfully',
    'meta': {}
}


class NotificationAPIViewTestCase(APITestCase):
    """
    Unit tests for NotificationAPIView
    Mocks external dependencies (UserService, TemplateService, RabbitMQ).
    """

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.client = APIClient()
        self.url = reverse('create_notification') # Use the name from urls.py

        # Create an organization in the database for testing
        self.organization = Organization.objects.create(**MOCK_ORGANIZATION_DATA)

        # Sample valid request data
        self.valid_payload = {
            "notification_type": "email",
            "user_id": "test_user_id_456",
            "template_code": "welcome_email",
            "variables": {"name": "Test User"},
            "request_id": "req_test_unit_1",
            "priority": 7
        }

    @patch('gateway_api.views.NotificationAPIView._get_user_data')
    @patch('gateway_api.views.NotificationAPIView._get_template')
    @patch('gateway_api.views.NotificationAPIView._validate_template_variables')
    @patch('gateway_api.views.NotificationAPIView._publish_to_queue')
    @patch('gateway_api.views.redis_client') # Patch the redis client instance used for idempotency
    def test_create_notification_success_email(self, mock_redis, mock_publish_queue, mock_validate_vars, mock_get_template, mock_get_user_data):
        """
        Test successful creation of an email notification.
        Mocks user service, template service, validation, and queue publishing.
        """
        # Arrange: Set up mocks
        mock_get_user_data.return_value = MOCK_USER_DATA
        mock_get_template.return_value = MOCK_TEMPLATE_DATA
        mock_validate_vars.return_value = {'valid': True, 'missing': [], 'extra': []}
        mock_redis.get.return_value = None # No idempotency key found
        mock_redis.setex.return_value = None # Mock setting the idempotency key

        # Act: Send the POST request
        response = self.client.post(self.url, self.valid_payload, format='json', HTTP_X_API_KEY=MOCK_ORGANIZATION_DATA['api_key'])

        # Assert: Check the response
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['data']['status'], 'accepted')
        self.assertIsNotNone(response.data['data']['notification_id'])
        # Assert mocks were called correctly
        mock_get_user_data.assert_called_once_with('test_user_id_456', MOCK_ORGANIZATION_DATA['id'], response.wsgi_request.correlation_id)
        mock_get_template.assert_called_once_with('welcome_email', MOCK_ORGANIZATION_DATA['id'], response.wsgi_request.correlation_id)
        mock_validate_vars.assert_called_once_with(MOCK_TEMPLATE_DATA['data'], {"name": "Test User"})
        mock_publish_queue.assert_called_once() # Check if publish was called, details depend on internal logic
        mock_redis.get.assert_called_once_with(f"notification:request:req_test_unit_1") # Check idempotency check
        mock_redis.setex.assert_called_once() # Check idempotency cache set

    @patch('gateway_api.views.NotificationAPIView._get_user_data')
    def test_create_notification_user_not_found(self, mock_get_user_data):
        """
        Test notification creation fails when user is not found.
        """
        # Arrange: Mock user service to return failure
        mock_get_user_data.return_value = {'success': False, 'message': 'User not found'}

        # Act: Send the POST request
        response = self.client.post(self.url, self.valid_payload, format='json', HTTP_X_API_KEY=MOCK_ORGANIZATION_DATA['api_key'])

        # Assert: Check the response
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error'], 'User not found')

    @patch('gateway_api.views.NotificationAPIView._get_user_data')
    @patch('gateway_api.views.NotificationAPIView._get_template')
    def test_create_notification_template_not_found(self, mock_get_template, mock_get_user_data):
        """
        Test notification creation fails when template is not found.
        """
        # Arrange: Mock user service to succeed and template service to fail
        mock_get_user_data.return_value = MOCK_USER_DATA
        mock_get_template.return_value = {'success': False, 'message': 'Template not found'}

        # Act: Send the POST request
        response = self.client.post(self.url, self.valid_payload, format='json', HTTP_X_API_KEY=MOCK_ORGANIZATION_DATA['api_key'])

        # Assert: Check the response
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error'], 'Template error')

    @patch('gateway_api.views.NotificationAPIView._get_user_data')
    @patch('gateway_api.views.NotificationAPIView._get_template')
    @patch('gateway_api.views.NotificationAPIView._validate_template_variables')
    def test_create_notification_missing_variables(self, mock_validate_vars, mock_get_template, mock_get_user_data):
        """
        Test notification creation fails when required template variables are missing.
        """
        # Arrange: Mock services to succeed, but validation to fail
        mock_get_user_data.return_value = MOCK_USER_DATA
        mock_get_template.return_value = MOCK_TEMPLATE_DATA
        mock_validate_vars.return_value = {'valid': False, 'missing': ['name'], 'extra': []}

        # Act: Send the POST request
        response = self.client.post(self.url, self.valid_payload, format='json', HTTP_X_API_KEY=MOCK_ORGANIZATION_DATA['api_key'])

        # Assert: Check the response
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error'], 'Missing template variables')

    @patch('gateway_api.views.NotificationAPIView._get_user_data')
    @patch('gateway_api.views.NotificationAPIView._get_template')
    @patch('gateway_api.views.NotificationAPIView._validate_template_variables')
    @patch('gateway_api.views.NotificationAPIView._publish_to_queue')
    @patch('gateway_api.views.redis_client.get')
    def test_create_notification_duplicate_request(self, mock_redis_get, mock_publish_queue, mock_validate_vars, mock_get_template, mock_get_user_data):
        """
        Test notification creation returns success if a duplicate request ID is detected (idempotency).
        """
        # Arrange: Mock redis to return existing data for the request ID
        existing_response_data = {'notification_id': 'notif_duplicate_abc123', 'status': 'accepted', 'request_id': 'req_test_unit_1', 'correlation_id': 'corr_123...'}
        mock_redis_get.return_value = json.dumps(existing_response_data).encode('utf-8')

        # Act: Send the POST request with the same request_id as the cached one
        response = self.client.post(self.url, self.valid_payload, format='json', HTTP_X_API_KEY=MOCK_ORGANIZATION_DATA['api_key'])

        # Assert: Check the response
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data['success'])
        self.assertEqual(response.data['data']['notification_id'], 'notif_duplicate_abc123')
        # Assert that downstream services (user, template, validation, publish) were NOT called due to idempotency
        mock_get_user_data.assert_not_called()
        mock_get_template.assert_not_called()
        mock_validate_vars.assert_not_called()
        mock_publish_queue.assert_not_called()

    @patch('gateway_api.views.redis_client') # Patch redis client instance
    def test_create_notification_missing_api_key(self, mock_redis):
        """
        Test notification creation fails when X-API-Key header is missing.
        """
        # Arrange: Ensure redis doesn't find the API key
        mock_redis.get.return_value = None
        # Note: This test relies on the API key not being in the gateway's local DB either.

        # Act: Send the POST request WITHOUT the X-API-Key header
        response = self.client.post(self.url, self.valid_payload, format='json')

        # Assert: Check the response
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error'], 'Authentication required')

    @patch('gateway_api.views.NotificationAPIView._get_user_data')
    @patch('gateway_api.views.NotificationAPIView._get_template')
    @patch('gateway_api.views.NotificationAPIView._validate_template_variables')
    @patch('gateway_api.views.NotificationAPIView._publish_to_queue')
    @patch('gateway_api.views.redis_client') # Patch the redis client instance used for idempotency
    def test_create_notification_push_user_no_token(self, mock_redis, mock_publish_queue, mock_validate_vars, mock_get_template, mock_get_user_data):
        """
        Test notification creation fails for push type if user has no push token.
        """
        # Arrange: Set up mocks, including user without push token
        user_data_no_token = MOCK_USER_DATA.copy()
        user_data_no_token['data']['push_token'] = None # User has no push token
        mock_get_user_data.return_value = user_data_no_token # Return user data without token
        mock_get_template.return_value = MOCK_TEMPLATE_DATA
        mock_validate_vars.return_value = {'valid': True, 'missing': [], 'extra': []}
        mock_redis.get.return_value = None # No idempotency key found
        mock_redis.setex.return_value = None # Mock setting the idempotency key

        # Modify payload for push notification
        push_payload = self.valid_payload.copy()
        push_payload['notification_type'] = 'push'

        # Act: Send the POST request for a push notification
        response = self.client.post(self.url, push_payload, format='json', HTTP_X_API_KEY=MOCK_ORGANIZATION_DATA['api_key'])

        # Assert: Check the response
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data['success'])
        self.assertEqual(response.data['error'], 'No push token')


# Example of a test for an internal sync view (if InternalOrganizationSyncView is in gateway_api)
# from .views import InternalOrganizationSyncView
# class InternalOrganizationSyncViewTestCase(APITestCase):
#     def setUp(self):
#         self.client = APIClient()
#         self.url = reverse('internal-org-sync') # Use the name from urls.py
#         self.org_data = {
#             'id': 'sync_test_org_id',
#             'name': 'Sync Test Org',
#             # ... other fields ...
#         }
#
#     @patch('requests.post') # Mock the call to the template service
#     def test_sync_organization_success(self, mock_requests_post):
#         # Arrange
#         mock_response = MagicMock()
#         mock_response.status_code = 201
#         mock_response.json.return_value = self.org_data
#         mock_requests_post.return_value = mock_response
#
#         # Act
#         response = self.client.post(self.url, self.org_data, format='json', HTTP_X_INTERNAL_SECRET=settings.INTERNAL_API_SECRET)
#
#         # Assert
#         self.assertEqual(response.status_code, status.HTTP_201_CREATED)
#         self.assertTrue(response.data['success'])
#         mock_requests_post.assert_called_once()
#         # Add assertions for the call arguments to requests.post
#
#     # Add more tests for InternalOrganizationSyncView (failure cases, etc.)

# Example of a test for HealthCheckView (if HealthCheckView is in gateway_api)
# from .views import HealthCheckView
# class HealthCheckViewTestCase(APITestCase):
#     def setUp(self):
#         self.client = APIClient()
#         self.url = reverse('health_check') # Use the name from urls.py
#
#     @patch('django.db.connection.ensure_connection') # Mock DB check
#     @patch('gateway_api.redis_client') # Mock Redis check
#     @patch('requests.get') # Mock checks for user/template services
#     def test_health_check_healthy(self, mock_requests_get, mock_redis, mock_db_connection):
#         # Arrange
#         mock_db_connection.return_value = None # Simulate successful DB connection
#         mock_redis.get.return_value = 'ok' # Simulate successful Redis ping
#         mock_response = MagicMock()
#         mock_response.status_code = 200
#         mock_requests_get.return_value = mock_response
#
#         # Act
#         response = self.client.get(self.url)
#
#         # Assert
#         self.assertEqual(response.status_code, status.HTTP_200_OK)
#         self.assertEqual(response.data['status'], 'healthy')
#         # Add assertions for other checks if needed
#
#     # Add more tests for HealthCheckView (unhealthy scenarios)

# Remember to run tests using: python manage.py test gateway_api
# Or for specific test class: python manage.py test gateway_api.tests.NotificationAPIViewTestCase