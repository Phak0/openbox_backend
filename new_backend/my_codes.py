#from views.py
class Cubby(models.Model):
    class CubbyType(models.TextChoices):
        SMALL = 'small', 'Small Package Cubby'
        MEDIUM = 'medium', 'Medium Package Cubby'
        LARGE = 'large', 'Large Package Cubby'
        PRINT = 'print', 'Stored Print Cubby'
        UNIVERSAL = 'universal', 'Universal Instant Print Cubby'

    class Status(models.TextChoices):
        AVAILABLE = 'available', 'Available'
        RESERVED = 'reserved', 'Reserved'
        OCCUPIED = 'occupied', 'Occupied'
        OUT_OF_SERVICE = 'out_of_service', 'Out of Service'

    box = models.ForeignKey(
        Box,
        on_delete=models.CASCADE,
        related_name='cubbies'
    )

    code = models.CharField(max_length=20)
    cubby_type = models.CharField(
        max_length=20,
        choices=CubbyType.choices
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE
    )

    reserved_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('box', 'code')
        ordering = ['box', 'code']

    def __str__(self):
        return f'{self.box.name} - {self.code}'


class PrivateBox(models.Model):
    owner = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='private_box'
    )

    name = models.CharField(max_length=100)

    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=10, decimal_places=7)
    address = models.TextField(blank=True)

    status = models.CharField(max_length=20, default='pending')

    created_at = models.DateTimeField(auto_now_add=True)


class PrivateCubbyApplication(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        REJECTED = 'rejected', 'Rejected'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='private_cubby_applications'
    )

    preferred_name = models.CharField(max_length=100)
    preferred_box = models.ForeignKey(
        Box,
        on_delete=models.PROTECT,
        related_name='private_cubby_applications'
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    is_setup_complete = models.BooleanField(default=False)

    payment_reference = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.preferred_name} ({self.status})"


class PrivateCubby(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        SUSPENDED = 'suspended', 'Suspended'

    private_box = models.OneToOneField(
        PrivateBox,
        on_delete=models.CASCADE,
        related_name='cubby',
        null=True,
        blank=True
    )

    cubby = models.OneToOneField(
        Cubby,
        on_delete=models.PROTECT,
        related_name='private_assignment'
    )

    pin_hash = models.CharField(max_length=255)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE
    )

    is_setup_complete = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def set_pin(self, pin):
        self.pin_hash = make_password(pin)

    def verify_pin(self, pin):
        return check_password(pin, self.pin_hash)

    @property
    def owner(self):
        return self.private_box.owner

    @property
    def custom_name(self):
        return self.private_box.name

    def __str__(self):
        return f"{self.private_box.name} ({self.private_box.owner.username})"


class PrivateCubbyTemporaryPin(models.Model):
    private_cubby = models.ForeignKey(
        PrivateCubby,
        on_delete=models.CASCADE,
        related_name='temporary_pins'
    )

    pin_hash = models.CharField(max_length=255)
    expires_at = models.DateTimeField()

    one_time = models.BooleanField(default=True)

    used_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def set_pin(self, pin):
        self.pin_hash = make_password(pin)

    def verify_pin(self, pin):
        return check_password(pin, self.pin_hash)

    def __str__(self):
        return f"Temp PIN for {self.private_cubby.custom_name}"


class PrivateCubbySharedAccess(models.Model):
    class Permission(models.TextChoices):
        DEPOSIT_ONLY = 'deposit_only', 'Deposit only'
        PICKUP_ONLY = 'pickup_only', 'Pickup only'
        FULL_ACCESS = 'full_access', 'Full access'

    private_cubby = models.ForeignKey(
        PrivateCubby,
        on_delete=models.CASCADE,
        related_name='shared_accesses'
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cubby_access_granted'
    )

    shared_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='cubby_access_received'
    )

    permission = models.CharField(
        max_length=20,
        choices=Permission.choices,
        default=Permission.FULL_ACCESS
    )

    expires_at = models.DateTimeField(null=True, blank=True)
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('private_cubby', 'shared_user')

    def __str__(self):
        return f"{self.shared_user.username} - {self.private_cubby.custom_name}"


class PrivateCubbyActivityLog(models.Model):
    class Action(models.TextChoices):
        CUBBY_CREATED = 'cubby_created', 'Cubby created'
        PIN_CHANGED = 'pin_changed', 'PIN changed'
        PACKAGE_DEPOSITED = 'package_deposited', 'Package deposited'
        PACKAGE_PICKED_UP = 'package_picked_up', 'Package picked up'
        TEMP_PIN_CREATED = 'temp_pin_created', 'Temporary PIN created'
        TEMP_PIN_USED = 'temp_pin_used', 'Temporary PIN used'
        TEMP_PIN_REVOKED = 'temp_pin_revoked', 'Temporary PIN revoked'
        ACCESS_SHARED = 'access_shared', 'Access shared'
        ACCESS_REVOKED = 'access_revoked', 'Access revoked'
        OWNER_ACCESS = 'owner_access', 'Owner accessed cubby'
        SHARED_USER_ACCESS = 'shared_user_access', 'Shared user accessed cubby'

    private_cubby = models.ForeignKey(
        PrivateCubby,
        on_delete=models.CASCADE,
        related_name='activity_logs'
    )

    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    action = models.CharField(max_length=50, choices=Action.choices)

    description = models.TextField(blank=True)

    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.private_cubby.custom_name} - {self.action}"


#from views_private_cubby.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from .models import PrivateCubby, PrivateCubbyApplication, PrivateCubbyTemporaryPin, PrivateCubbySharedAccess, PrivateCubbyActivityLog, PrivateBox
from .serializers_private_cubby import PrivateCubbySerializer, PrivateCubbyApplicationSerializer, PrivateCubbySetupSerializer, GenerateTemporaryPinSerializer, VerifyTemporaryPinSerializer, ShareCubbySerializer, PrivateCubbyActivitySerializer
from datetime import timedelta
from django.utils import timezone
from random import randint
from .utils import log_cubby_activity
from django.contrib.auth import get_user_model




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
        try:
            private_cubby = request.user.private_cubby
        except PrivateCubby.DoesNotExist:
            return Response(
                {"error": "You do not have an assigned private cubby."},
                status=404,
            )

        serializer = PrivateCubbySetupSerializer(data=request.data)

        if serializer.is_valid():
            private_cubby.custom_name = serializer.validated_data['custom_name']
            private_cubby.set_pin(serializer.validated_data['pin'])
            private_cubby.save()

            log_cubby_activity(
                private_cubby=private_cubby,
                action=PrivateCubbyActivityLog.Action.CUBBY_CREATED,
                performed_by=request.user,
                description="Cubby setup completed."
            )

            return Response({
                "message": "Cubby setup completed successfully.",
                "cubby": PrivateCubbySerializer(private_cubby).data
            })

        return Response(serializer.errors, status=400)


class GenerateTemporaryPinView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            private_cubby = request.user.private_cubby
        except PrivateCubby.DoesNotExist:
            return Response(
                {"error": "Private cubby not found."},
                status=404,
            )

        if not private_cubby.is_setup_complete:
            return Response(
                {"error": "Please complete cubby setup first."},
                status=400,
            )

        serializer = GenerateTemporaryPinSerializer(data=request.data)

        if serializer.is_valid():
            pin = str(randint(100000, 999999))

            temp_pin = PrivateCubbyTemporaryPin(
                private_cubby=private_cubby,
                expires_at=timezone.now() + timedelta(
                    minutes=serializer.validated_data['expires_in_minutes']
                ),
                one_time=serializer.validated_data['one_time'],
            )

            temp_pin.set_pin(pin)
            temp_pin.save()

            log_cubby_activity(
                private_cubby=private_cubby,
                action=PrivateCubbyActivityLog.Action.TEMP_PIN_CREATED,
                performed_by=request.user,
                description="Temporary access PIN generated.",
                metadata={
                    "expires_at": temp_pin.expires_at.isoformat(),
                    "one_time": temp_pin.one_time,
                }
            )

            return Response({
                "temporary_pin": pin,
                "expires_at": temp_pin.expires_at,
                "one_time": temp_pin.one_time,
            })

        return Response(serializer.errors, status=400)


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
        try:
            private_cubby = request.user.private_cubby
        except PrivateCubby.DoesNotExist:
            return Response({"error": "Private cubby not found."}, status=404)

        try:
            temp_pin = private_cubby.temporary_pins.get(id=pin_id)
        except PrivateCubbyTemporaryPin.DoesNotExist:
            return Response({"error": "Temporary PIN not found."}, status=404)

        temp_pin.active = False
        temp_pin.save()

        return Response({"message": "Temporary PIN revoked."})


User = get_user_model()


class ShareCubbyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            private_cubby = request.user.private_cubby
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
        try:
            private_cubby = request.user.private_cubby
        except PrivateCubby.DoesNotExist:
            return Response(
                {"error": "Private cubby not found."},
                status=404,
            )

        accesses = private_cubby.shared_accesses.filter(active=True)

        data = []

        for access in accesses:
            data.append({
                'id': access.id,
                'email': access.shared_user.email,
                'name': access.shared_user.get_full_name(),
                'permission': access.permission,
                'expires_at': access.expires_at,
            })

        return Response(data)


class RevokeSharedAccessView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, access_id):
        try:
            private_cubby = request.user.private_cubby
        except PrivateCubby.DoesNotExist:
            return Response(
                {"error": "Private cubby not found."},
                status=404,
            )

        try:
            access = private_cubby.shared_accesses.get(id=access_id)
        except PrivateCubbySharedAccess.DoesNotExist:
            return Response(
                {"error": "Shared access not found."},
                status=404,
            )

        access.active = False
        access.save()

        return Response({
            "message": "Access revoked successfully."
        })


class CubbyActivityView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            private_cubby = request.user.private_cubby
        except PrivateCubby.DoesNotExist:
            return Response(
                {"error": "Private cubby not found."},
                status=404,
            )

        logs = private_cubby.activity_logs.all()[:100]

        serializer = PrivateCubbyActivitySerializer(logs, many=True)

        return Response(serializer.data)


#from serializers_private_cubby.py
from rest_framework import serializers
from .models import PrivateCubbyApplication, PrivateCubby, PrivateCubbyTemporaryPin, PrivateCubbySharedAccess, PrivateCubbyActivityLog


class PrivateCubbyApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrivateCubbyApplication
        fields = ['preferred_name', 'preferred_box']


class PrivateCubbySerializer(serializers.ModelSerializer):
    cubby_code = serializers.CharField(source='cubby.cubby_code', read_only=True)
    box_name = serializers.CharField(source='cubby.box.name', read_only=True)

    class Meta:
        model = PrivateCubby
        fields = [
            'id',
            'custom_name',
            'status',
            'cubby_code',
            'box_name',
            'created_at',
        ]


class PrivateCubbySetupSerializer(serializers.Serializer):
    custom_name = serializers.CharField(max_length=100)
    pin = serializers.CharField(min_length=4, max_length=6)

    def validate_pin(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("PIN must contain only digits.")


class GenerateTemporaryPinSerializer(serializers.Serializer):
    expires_in_minutes = serializers.IntegerField(min_value=5, max_value=10080)
    one_time = serializers.BooleanField(default=True)


class VerifyTemporaryPinSerializer(serializers.Serializer):
    pin = serializers.CharField(min_length=4, max_length=6)


class ShareCubbySerializer(serializers.Serializer):
    email = serializers.EmailField()
    permission = serializers.ChoiceField(
        choices=PrivateCubbySharedAccess.Permission.choices
    )
    duration_days = serializers.IntegerField(required=False, min_value=1, max_value=365)

    def validate_email(self, value):
        from django.contrib.auth import get_user_model

        User = get_user_model()

        if not User.objects.filter(email=value).exists():
            raise serializers.ValidationError("User with this email does not exist.")

        return value


class PrivateCubbyActivitySerializer(serializers.ModelSerializer):
    performed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = PrivateCubbyActivityLog
        fields = [
            'id',
            'action',
            'description',
            'metadata',
            'created_at',
            'performed_by_name',
        ]

    def get_performed_by_name(self, obj):
        if obj.performed_by:
            return obj.performed_by.get_full_name() or obj.performed_by.username
        return "System"