from rest_framework.views import APIView
from rest_framework import status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import PrivateCubby, PrivateCubbyApplication, PrivateCubbyTemporaryPin, PrivateCubbySharedAccess, PrivateCubbyActivityLog, PrivateBox, Cubby
from .serializers_private_cubby import PrivateCubbySerializer, PrivateCubbyApplicationSerializer, PrivateCubbySetupSerializer, GenerateTemporaryPinSerializer, VerifyTemporaryPinSerializer, ShareCubbySerializer, PrivateCubbyActivitySerializer
from datetime import timedelta
from django.utils import timezone
from random import randint
from .utils import log_cubby_activity
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404


def get_user_private_cubby(user):
    private_box = get_object_or_404(PrivateBox, owner=user)
    return get_object_or_404(PrivateCubby, private_box=private_box)

class CubbyStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            private_box = request.user.private_box
        except PrivateBox.DoesNotExist:
            return Response({
                "has_cubby": False
            })

        try:
            cubby = private_box.cubby
        except PrivateCubby.DoesNotExist:
            return Response({
                "has_cubby": True,
                "cubby": {
                    "is_setup_complete": False,
                    "name": private_box.name,
                    "latitude": private_box.latitude,
                    "longitude": private_box.longitude,
                    "address": private_box.address,
                }
            })

        return Response({
            "has_cubby": True,
            "cubby": {
                "id": cubby.id,
                "name": private_box.name,
                "latitude": private_box.latitude,
                "longitude": private_box.longitude,
                "address": private_box.address,
                "status": cubby.status,
                "is_setup_complete": cubby.is_setup_complete,
            }
        })


class ApplyForCubbyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if hasattr(request.user, 'private_box'):
            return Response({
                "error": "You already have a private box."
            }, status=400)

        name = request.data.get('name')
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        address = request.data.get('address', '')

        if not name:
            return Response(
                {"error": "Box name is required."},
                status=400,
            )

        if latitude is None or longitude is None:
            return Response(
                {"error": "Box location is required."},
                status=400,
            )

        private_box = PrivateBox.objects.create(
            owner=request.user,
            name=name,
            latitude=latitude,
            longitude=longitude,
            address=address,
            status='pending',
        )

        return Response({
            "message": "Private box application submitted successfully.",
            "private_box_id": private_box.id,
            "status": private_box.status,
        }, status=201)


class SetupCubbyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = PrivateCubbySetupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        private_box = get_object_or_404(PrivateBox, owner=request.user)

        private_cubby, created = PrivateCubby.objects.get_or_create(
            private_box=private_box,
            defaults={
                "cubby": Cubby.objects.filter(
                    status=Cubby.Status.AVAILABLE
                ).first(),
                "pin_hash": "",
            },
        )

        if private_cubby.cubby is None:
            available_cubby = Cubby.objects.filter(
                status=Cubby.Status.AVAILABLE
            ).first()

            if not available_cubby:
                return Response(
                    {"error": "No cubbies are currently available."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            private_cubby.cubby = available_cubby

        private_cubby.set_pin(serializer.validated_data["pin"])
        private_cubby.is_setup_complete = True
        private_cubby.status = PrivateCubby.Status.ACTIVE
        private_cubby.save()

        private_cubby.cubby.status = Cubby.Status.OCCUPIED
        private_cubby.cubby.save(update_fields=["status"])

        log_cubby_activity(
            private_cubby=private_cubby,
            action=PrivateCubbyActivityLog.Action.CUBBY_CREATED,
            performed_by=request.user,
            description="Private cubby activated.",
        )

        return Response({
            "message": "Private cubby activated successfully.",
            "cubby_code": private_cubby.cubby.code,
        })


class GenerateTemporaryPinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        private_cubby = get_user_private_cubby(request.user)

        if not private_cubby.is_setup_complete:
            return Response(
                {"error": "Please complete cubby setup first."},
                status=400,
            )

        serializer = GenerateTemporaryPinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        pin = str(randint(100000, 999999))

        temp_pin = PrivateCubbyTemporaryPin(
            private_cubby=private_cubby,
            expires_at=timezone.now()
            + timedelta(
                minutes=serializer.validated_data[
                    "expires_in_minutes"
                ]
            ),
            one_time=serializer.validated_data["one_time"],
        )

        temp_pin.set_pin(pin)
        temp_pin.save()

        log_cubby_activity(
            private_cubby=private_cubby,
            action=PrivateCubbyActivityLog.Action.TEMP_PIN_CREATED,
            performed_by=request.user,
            description="Temporary access PIN generated.",
        )

        return Response({
            "temporary_pin": pin,
            "expires_at": temp_pin.expires_at,
            "one_time": temp_pin.one_time,
        })


class VerifyTemporaryPinView(APIView):
    permission_classes = [AllowAny]

    def post(self, request, cubby_code):
        serializer = VerifyTemporaryPinSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        try:
            private_cubby = PrivateCubby.objects.select_related('cubby').get(
                cubby__cubby_code=cubby_code,
                status=PrivateCubby.Status.ACTIVE,
            )
        except PrivateCubby.DoesNotExist:
            return Response({"error": "Cubby not found."}, status=404)

        now = timezone.now()

        pins = private_cubby.temporary_pins.filter(
            active=True,
            expires_at__gt=now,
        )

        for temp_pin in pins:
            if temp_pin.verify_pin(serializer.validated_data['pin']):
                if temp_pin.one_time:
                    temp_pin.used_at = now
                    temp_pin.active = False
                    temp_pin.save()

                log_cubby_activity(
                    private_cubby=private_cubby,
                    action=PrivateCubbyActivityLog.Action.TEMP_PIN_USED,
                    description="Temporary PIN used for cubby access."
                )

                return Response({
                    "valid": True,
                    "message": "Access granted.",
                    "cubby_id": private_cubby.cubby.id,
                })

        return Response(
            {"valid": False, "message": "Invalid or expired PIN."},
            status=400,
        )


class RevokeTemporaryPinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pin_id):
        private_cubby = get_user_private_cubby(request.user)

        temp_pin = get_object_or_404(
            PrivateCubbyTemporaryPin,
            id=pin_id,
            private_cubby=private_cubby,
        )

        temp_pin.active = False
        temp_pin.save()

        log_cubby_activity(
            private_cubby=private_cubby,
            action=PrivateCubbyActivityLog.Action.TEMP_PIN_REVOKED,
            performed_by=request.user,
            description="Temporary PIN revoked.",
        )

        return Response({"message": "Temporary PIN revoked."})



User = get_user_model()


class ShareCubbyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            private_cubby = get_user_private_cubby(request.user)
        except PrivateCubby.DoesNotExist:
            return Response(
                {"error": "Private cubby not found."},
                status=404,
            )

        serializer = ShareCubbySerializer(data=request.data)

        if serializer.is_valid():
            shared_user = User.objects.get(
                email=serializer.validated_data['email']
            )

            if shared_user == request.user:
                return Response(
                    {"error": "You cannot share with yourself."},
                    status=400,
                )

            expires_at = None

            if serializer.validated_data.get('duration_days'):
                expires_at = timezone.now() + timedelta(
                    days=serializer.validated_data['duration_days']
                )

            access, created = PrivateCubbySharedAccess.objects.update_or_create(
                private_cubby=private_cubby,
                shared_user=shared_user,
                defaults={
                    'owner': request.user,
                    'permission': serializer.validated_data['permission'],
                    'expires_at': expires_at,
                    'active': True,
                }
            )

            log_cubby_activity(
                private_cubby=private_cubby,
                action=PrivateCubbyActivityLog.Action.ACCESS_SHARED,
                performed_by=request.user,
                description=f"Shared cubby with {shared_user.email}.",
                metadata={
                    "shared_user_email": shared_user.email,
                    "permission": access.permission,
                }
            )

            return Response({
                "message": "Cubby shared successfully.",
                "shared_user": shared_user.email,
                "permission": access.permission,
                "expires_at": access.expires_at,
            })

        return Response(serializer.errors, status=400)


class SharedUsersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        private_cubby = get_user_private_cubby(request.user)

        accesses = private_cubby.shared_accesses.filter(active=True)

        data = [
            {
                "id": access.id,
                "email": access.shared_user.email,
                "name": access.shared_user.get_full_name(),
                "permission": access.permission,
                "expires_at": access.expires_at,
            }
            for access in accesses
        ]

        return Response(data)



class RevokeSharedAccessView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, access_id):
        private_cubby = get_user_private_cubby(request.user)

        access = get_object_or_404(
            PrivateCubbySharedAccess,
            id=access_id,
            private_cubby=private_cubby,
        )

        access.active = False
        access.save()

        log_cubby_activity(
            private_cubby=private_cubby,
            action=PrivateCubbyActivityLog.Action.ACCESS_REVOKED,
            performed_by=request.user,
            description="Shared access revoked.",
        )

        return Response({
            "message": "Access revoked successfully."
        })


class CubbyActivityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        private_cubby = get_user_private_cubby(request.user)

        logs = private_cubby.activity_logs.all()[:100]

        serializer = PrivateCubbyActivitySerializer(
            logs,
            many=True,
        )

        return Response(serializer.data)