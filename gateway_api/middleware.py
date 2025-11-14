import uuid
import logging

logger = logging.getLogger(__name__)

class CorrelationIdMiddleware:
    """Add correlation ID to every request for distributed tracing"""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Get or generate correlation ID
        correlation_id = request.headers.get(
            'X-Correlation-ID', 
            str(uuid.uuid4())
        )
        request.correlation_id = correlation_id
        
        # Log the request with correlation ID
        logger.info(
            f"Request received: {request.method} {request.path} [correlation_id={correlation_id}]"
        )
        
        response = self.get_response(request)
        response['X-Correlation-ID'] = correlation_id
        return response