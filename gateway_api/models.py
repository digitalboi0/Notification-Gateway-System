from django.db import models
import uuid
from django.utils import timezone

class Organization(models.Model):
    PLAN_CHOICES = [
        ('pro', 'Pro'),
        ('enterprise', 'Enterprise'),
        ('bronze', 'Bronze'),
        ('platinum', 'Platinum'),
        ('industry', 'Industry'),
    ]
    
    id = models.CharField(max_length=36, primary_key=True)
    name = models.CharField(max_length=255)
    api_key = models.CharField(max_length=255, unique=True, db_index=True)
    plan = models.CharField(max_length=50, choices=PLAN_CHOICES)
    quota_limit = models.IntegerField(default=10000)
    quota_used = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'organizations'
        indexes = [
            models.Index(fields=['api_key', 'is_active']),
        ]
        
        


class Notification(models.Model):
    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed'),
        ('bounced', 'Bounced'),
        ('rejected', 'Rejected'),
    ]
    
    TYPE_CHOICES = [
        ('email', 'Email'),
        ('push', 'Push'),
    ]
    
    id = models.CharField(max_length=22, primary_key=True)
    correlation_id = models.CharField(max_length=36, db_index=True)
    organization_id = models.CharField(max_length=36, db_index=True)
    user_id = models.CharField(max_length=36, db_index=True)
    notification_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    template_code = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    priority = models.IntegerField(default=5)
    request_id = models.CharField(max_length=255, unique=True, db_index=True)
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'notifications'
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['organization_id', '-created_at']),
        ]
        

class User(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True) # Email should be unique across the system
    name = models.CharField(max_length=255)
    password = models.CharField(max_length=255) # In a real app, store a hash, not the plain text
    push_token = models.CharField(max_length=255, blank=True, null=True) # Can be blank if not a mobile user
    preferences = models.JSONField(default=dict) # Store preferences as JSON
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='users')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.email})"

    class Meta:
        db_table = 'users' # Optional: specify table name
        unique_together = ('email', 'organization') # Ensure email is unique within an org        