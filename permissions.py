from rest_framework.permissions import BasePermission
from new_backend.models import Box

class IsAuthenticatedBox(BasePermission):
    """
    Allows access only to physical hardware boxes that provide 
    a valid secret token in their request headers.
    """
    def has_permission(self, request, view):
        # Look for a custom header sent by the hardware: X-Box-Token
        token = request.headers.get('X-Box-Token')
        
        if not token:
            return False
            
        try:
            # Check if this token matches any registered box in the database
            box = Box.objects.get(api_token=token)
            
            # Attach the identified box to the request object.
            # This is incredibly useful so your view knows EXACTLY which box is calling.
            request.box = box
            
            return True
        except Box.DoesNotExist:
            return False