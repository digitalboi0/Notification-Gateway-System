# gateway/exceptions.py
from rest_framework.views import exception_handler
from rest_framework.response import Response

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    
    if response is not None:
        error_response = {
            'success': False,
            'error': str(exc),
            'message': response.data.get('detail', str(exc)),
            'meta': {}
        }
        response.data = error_response
    
    return response