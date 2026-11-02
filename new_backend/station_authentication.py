import hashlib

from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from .models import Station


class StationAPIKeyAuthentication(BaseAuthentication):
    """Authenticate a physical station using Authorization: Bearer <station-key>."""

    keyword = b"bearer"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if len(parts) != 2 or parts[0].lower() != self.keyword:
            raise AuthenticationFailed("Use Authorization: Bearer <station_api_key>.")

        try:
            raw_key = parts[1].decode("utf-8")
        except UnicodeError:
            raise AuthenticationFailed("Invalid station API key.")

        digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        try:
            station = Station.objects.get(api_key_hash=digest, is_active=True)
        except Station.DoesNotExist:
            raise AuthenticationFailed("Invalid or inactive station API key.")

        station.last_seen_at = timezone.now()
        station.save(update_fields=["last_seen_at"])
        return (AnonymousUser(), station)

    def authenticate_header(self, request):
        return "Bearer"


class IsAuthenticatedStation(BasePermission):
    """Reject requests that were not authenticated as a registered station."""

    def has_permission(self, request, view):
        return isinstance(request.auth, Station) and request.auth.is_active
