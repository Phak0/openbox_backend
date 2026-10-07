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