
from django.core.management.base import BaseCommand
from gateway_api.models import Organization
import secrets
import uuid
import requests
from django.conf import settings
import json

class Command(BaseCommand):
    help = 'Create a new organization with API key and sync to user service and template service via gateway'

    def add_arguments(self, parser):
        parser.add_argument('name', type=str, help='Organization name')
        parser.add_argument('--plan', type=str, default='pro', choices=['pro', 'enterprise', "bronze", "plantinum", "industry"], help='Plan type')
        parser.add_argument('--quota', type=int, default=10000, help='Quota limit')
    #    parser.add_argument('--skip-user-service', action='store_true', help='Skip syncing to user service')

    def handle(self, *args, **options):
        org_id = str(uuid.uuid4())
        api_key = f"org_{secrets.token_urlsafe(32)}"

        
        org = Organization.objects.create(
            id=org_id,
            name=options['name'],
            api_key=api_key,
            plan=options['plan'],
            quota_limit=options['quota'],
            is_active=True,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'Organization created in gateway successfully!\n'
                f'ID: {org.id}\n'
                f'Name: {org.name}\n'
                f'API Key: {api_key}\n'
                f'Plan: {org.plan}\n'
                f'Quota Limit: {org.quota_limit}'
            )
        )

        
        #if not options.get('skip_user_service', False):
        #    self.sync_to_user_service(org)

        
        self.sync_org_to_template_service_via_gateway(org)

    def sync_to_user_service(self, org):
        """Sync organization data to user service"""
        try:
            org_data = {
                'id': str(org.id),
                'name': org.name,
                'plan': org.plan,
                'quota_limit': org.quota_limit,
                'api_key': org.api_key,
                'is_active': org.is_active,
                'created_at': org.created_at.isoformat()
            }

            
            response = requests.post(
                f"{settings.USER_SERVICE_URL}/mock/organizations/",
                json=org_data,
                headers={
                    'X-Internal-Secret': settings.INTERNAL_API_SECRET,
                    'Content-Type': 'application/json',
                    'X-API-Key': org.api_key,
                },
                timeout=5
            )

            if response.status_code == 201:
                self.stdout.write(
                    self.style.SUCCESS('Organization successfully synced to user service!')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'User service returned status {response.status_code}: {response.text}')
                )
                
                self.fallback_to_mock_service(org_data)

        except requests.RequestException as e:
            self.stdout.write(
                self.style.WARNING(f'Failed to sync to user service: {str(e)}')
            )


    def fallback_to_mock_service(self, org_data):
        """Fallback to mock user service if real service is unavailable"""
        try:
            response = requests.post(
                'http://localhost:8000/mock/organizations/',
                json=org_data,
                headers={
                    'X-Internal-Secret': settings.INTERNAL_API_SECRET,
                    'Content-Type': 'application/json',
                    'X-API-Key': org_data.get("api_key"),
                
                },
                timeout=5
            )

            if response.status_code == 201:
                self.stdout.write(
                    self.style.SUCCESS('Organization synced to mock user service!')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Mock service returned status {response.status_code}')
                )

        except requests.RequestException as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to sync to mock service: {str(e)}')
            )

    
    def sync_org_to_template_service_via_gateway(self, org):
        """Sync organization data to template service via the gateway's internal endpoint."""
        try:
            org_data = {
                'id': str(org.id),
                'name': org.name,
                'plan': org.plan,
                'quota_limit': org.quota_limit,
                'api_key': org.api_key,
                'is_active': org.is_active,
                'created_at': org.created_at.isoformat()
            }

            
            
            gateway_internal_url = f"{settings.TEMPLATE_SERVICE_URL}/internal/organizations/create-template-org/" 
            response = requests.post(
                gateway_internal_url,
                json=org_data,
                headers={
                    'X-Internal-Secret': settings.INTERNAL_API_SECRET, 
                    'Content-Type': 'application/json'
                },
                timeout=5
            )

            if response.status_code == 201:
                self.stdout.write(
                    self.style.SUCCESS('Organization successfully synced to template service via gateway!')
                )
            else:
                self.stdout.write(
                    self.style.WARNING(f'Gateway internal endpoint returned status {response.status_code}: {response.text}')
                )

        except requests.RequestException as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to sync organization to template service via gateway: {str(e)}')
            )