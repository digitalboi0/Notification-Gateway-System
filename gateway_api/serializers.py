# gateway_api/serializers.py

from rest_framework import serializers


class NotificationCreateSerializer(serializers.Serializer):
    """Serializer for creating notifications"""
    notification_type = serializers.ChoiceField(
        choices=['email', 'push'],
        required=True,
        help_text="Type of notification to send"
    )
    user_id = serializers.CharField(
        required=True,
        help_text="ID of the user to send notification to"
    )
    template_code = serializers.CharField(
        required=True,
        help_text="Template code to use for the notification"
    )
    variables = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        default=dict,
        help_text="Variables to populate the template"
    )
    request_id = serializers.CharField(
        required=False,
        help_text="Idempotency key for the request"
    )
    priority = serializers.IntegerField(
        required=False,
        default=5,
        min_value=1,
        max_value=10,
        help_text="Priority level (1-10, higher is more urgent)"
    )
    metadata = serializers.DictField(
        required=False,
        default=dict,
        help_text="Additional metadata for the notification"
    )


class NotificationResponseSerializer(serializers.Serializer):
    """Serializer for notification response"""
    notification_id = serializers.CharField()
    status = serializers.CharField()
    request_id = serializers.CharField()
    correlation_id = serializers.CharField()


class NotificationStatusRequestSerializer(serializers.Serializer):
    """Serializer for checking notification status"""
    notification_id = serializers.CharField(
        required=True,
        help_text="ID of the notification to check"
    )


class NotificationStatusResponseSerializer(serializers.Serializer):
    """Serializer for notification status response"""
    notification_id = serializers.CharField()
    status = serializers.CharField()
    notification_type = serializers.CharField()
    template_code = serializers.CharField()
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField()
    delivered_at = serializers.DateTimeField(allow_null=True)
    error_message = serializers.CharField(allow_null=True)


class InternalStatusUpdateSerializer(serializers.Serializer):
    """Serializer for internal status updates from workers"""
    notification_id = serializers.CharField(required=True)
    organization_id = serializers.CharField(required=True)
    status = serializers.ChoiceField(
        choices=['queued', 'processing', 'delivered', 'failed', 'bounced', 'rejected'],
        required=True
    )
    timestamp = serializers.DateTimeField(required=False)
    error = serializers.CharField(required=False, allow_null=True)


class StandardResponseSerializer(serializers.Serializer):
    """Standard API response wrapper"""
    success = serializers.BooleanField()
    data = serializers.DictField(required=False)
    message = serializers.CharField()
    error = serializers.CharField(required=False)
    meta = serializers.DictField()


class UserSerializer(serializers.Serializer):
    """Serializer for user data"""
    id = serializers.CharField(read_only=True)
    email = serializers.EmailField(required=True)
    name = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True, required=True)
    push_token = serializers.CharField(required=False, allow_null=True)
    preferences = serializers.DictField(required=False, default=dict)
    organization_id = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)


class UserUpdateSerializer(serializers.Serializer):
    """Serializer for updating user data"""
    name = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)
    password = serializers.CharField(write_only=True, required=False)
    push_token = serializers.CharField(required=False, allow_null=True)


class UserPreferencesSerializer(serializers.Serializer):
    """Serializer for user preferences"""
    preferences = serializers.DictField(
        child=serializers.BooleanField(),
        required=True,
        help_text="User notification preferences"
    )


class OrganizationSerializer(serializers.Serializer):
    """Serializer for organization data"""
    id = serializers.CharField()
    name = serializers.CharField()
    api_key = serializers.CharField()
    plan = serializers.CharField()
    quota_limit = serializers.IntegerField()
    is_active = serializers.BooleanField()
    created_at = serializers.DateTimeField()


class HealthCheckSerializer(serializers.Serializer):
    """Serializer for health check response"""
    service = serializers.CharField()
    status = serializers.CharField()
    timestamp = serializers.DateTimeField()
    checks = serializers.DictField()