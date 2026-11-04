import hashlib
import jwt
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from .models import Station


def generate_station_token(station):
    """Generate a 30-day JWT for station web dashboard authentication."""
    payload = {
        'station_id': station.id,
        'email': station.email,
        'name': station.name,
        'type': 'station',
        'exp': timezone.now() + timedelta(days=30),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm='HS256')


class StationAuthentication(BaseAuthentication):
    """
    Authenticate a station using either:
    1. A Station JWT token (issued when the station owner logs into the web dashboard)
    2. A Station raw API key (Authorization: Bearer stn_...)
    """

    keyword = b"bearer"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if len(parts) != 2 or parts[0].lower() != self.keyword:
            raise AuthenticationFailed("Use Authorization: Bearer <token_or_api_key>.")

        try:
            raw_token = parts[1].decode("utf-8")
        except UnicodeError:
            raise AuthenticationFailed("Invalid token encoding.")

        # 1. Try decoding as Station JWT
        try:
            payload = jwt.decode(raw_token, settings.SECRET_KEY, algorithms=["HS256"])
            if payload.get("type") == "station" and payload.get("station_id"):
                station = Station.objects.get(id=payload["station_id"], is_active=True)
                station.last_seen_at = timezone.now()
                station.save(update_fields=["last_seen_at"])
                return (station, station)
        except (jwt.PyJWTError, Station.DoesNotExist):
            pass

        # 2. Try authenticating as raw API Key
        digest = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        try:
            station = Station.objects.get(api_key_hash=digest, is_active=True)
            station.last_seen_at = timezone.now()
            station.save(update_fields=["last_seen_at"])
            return (station, station)
        except Station.DoesNotExist:
            raise AuthenticationFailed("Invalid or inactive station credentials.")

    def authenticate_header(self, request):
        return "Bearer"


# Backwards compatibility alias
StationAPIKeyAuthentication = StationAuthentication


class IsAuthenticatedStation(BasePermission):
    """Reject requests that were not authenticated as a registered station."""

    def has_permission(self, request, view):
        auth_obj = request.auth if isinstance(request.auth, Station) else request.user
        return isinstance(auth_obj, Station) and auth_obj.is_active
