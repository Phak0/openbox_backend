# main/new_backend/serializers.py
from rest_framework import serializers
import uuid
from .models import User, Box, Station, ConversationSession, ConversationMessage, Task, PrintDocument, WalletTransaction
from .services.conversation_service import ConversationService

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = User
        fields = ['email', 'password', 'password_confirm', 'name', 'user_type']
        extra_kwargs = {
            'name': {'required': True},
            'user_type': {'required': False}
        }

    def validate(self, data):
        """Validate password match"""
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({
                "password_confirm": "Passwords do not match"
            })
        
        # Check if email already exists
        if User.objects.filter(email=data['email']).exists():
            raise serializers.ValidationError({
                "email": "This email is already registered"
            })
        
        # Remove password_confirm before create
        data.pop('password_confirm')
        return data

    def create(self, validated_data):
        """Create user with unique user_code"""
        # Generate a unique user_code
        validated_data['user_code'] = f"U-{uuid.uuid4().hex[:6].upper()}"
        
        # Create user using custom create_user method
        user = User.objects.create_user(**validated_data)
        return user

class BoxSerializer(serializers.ModelSerializer):
    
    # This sends the human-readable version (e.g., "Drop Box" instead of "drop")
    box_type_display = serializers.CharField(source='get_box_type_display', read_only=True)

    class Meta:
        model = Box
        fields = [
            'id', 'name', 'address', 'picture', 'latitude', 'longitude', 
            'is_available', 'box_type', 'box_type_display', 
            'printing_price', 'stored_print_hourly_price', 'dropbox_pricing',
        ]


class BoxListSerializer(serializers.ModelSerializer):
    distance = serializers.SerializerMethodField()

    class Meta:
        model = Box
        fields = ['id', 'name', 'address', 'picture', 'latitude', 'longitude', 
            'is_available', 'box_type', 'printing_price', 'stored_print_hourly_price', 'dropbox_pricing', 'distance']

    def get_distance(self, obj):
        # We will inject 'distance' into the object directly from the view!
        return getattr(obj, 'distance', None)


class StationRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6, trim_whitespace=False)
    name = serializers.CharField(required=True, max_length=50)
    email = serializers.EmailField(required=True)
    owner_name = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = Station
        fields = ['id', 'name', 'owner_name', 'email', 'password', 'address', 'picture',
                  'latitude', 'longitude', 'printing_price']
        extra_kwargs = {
            'address': {'required': False, 'allow_blank': True},
            'picture': {'required': False},
            'latitude': {'required': False, 'allow_null': True},
            'longitude': {'required': False, 'allow_null': True},
            'printing_price': {'required': False},
        }

    def validate_name(self, value):
        val = value.strip()
        if Station.objects.filter(name__iexact=val).exists():
            raise serializers.ValidationError('A station with this name already exists. Please choose a unique station name.')
        return val

    def validate_email(self, value):
        val = value.strip().lower()
        if Station.objects.filter(email__iexact=val).exists():
            raise serializers.ValidationError('A station with this email already exists.')
        return val

    def create(self, validated_data):
        raw_password = validated_data.pop('password')
        station = Station(**validated_data)
        station.set_password(raw_password)
        station.save()
        return station


class StationSerializer(serializers.ModelSerializer):
    distance = serializers.FloatField(read_only=True, required=False)

    class Meta:
        model = Station
        fields = [
            'id', 'name', 'owner_name', 'email', 'address', 'picture', 'latitude', 
            'longitude', 'is_available', 'is_active', 'printing_price', 'distance'
        ]


class StationDetailSerializer(serializers.ModelSerializer):
    active_tasks_count = serializers.SerializerMethodField()

    class Meta:
        model = Station
        fields = [
            'id', 'name', 'owner_name', 'email', 'address', 'picture', 'latitude', 
            'longitude', 'is_available', 'is_active', 'printing_price', 
            'created_at', 'active_tasks_count'
        ]

    def get_active_tasks_count(self, obj):
        return obj.tasks.filter(status=Task.Status.ACTIVE).count()


class StationUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Station
        fields = ['owner_name', 'address', 'picture', 'latitude', 'longitude', 'is_available', 'printing_price']
        extra_kwargs = {
            'owner_name': {'required': False, 'allow_blank': True},
            'address': {'required': False, 'allow_blank': True},
            'picture': {'required': False},
            'latitude': {'required': False, 'allow_null': True},
            'longitude': {'required': False, 'allow_null': True},
            'is_available': {'required': False},
            'printing_price': {'required': False},
        }

#.....................................................        

class ConversationMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConversationMessage
        fields = [
            'id',
            'sender',
            'message_type',
            'content',
            'created_at',
        ]


class ConversationSerializer(serializers.ModelSerializer):
    messages = ConversationMessageSerializer(
        many=True,
        read_only=True
    )

    available_actions = serializers.SerializerMethodField()

    task_summary = serializers.SerializerMethodField()
    storage_until = serializers.SerializerMethodField()
    latest_message = serializers.SerializerMethodField()

    class Meta:
        model = ConversationSession
        fields = [
            'id',
            'task_summary',
            'current_state',
            'is_active',
            'storage_until',
            "latest_message",
            'messages',
            'available_actions',
        ]
    
    def get_available_actions(self, obj):
        actions = ConversationService.get_available_actions(obj)

        if self.context.get("hide_access_actions"):
            hidden_actions = {
                "change_access_code",
                "share_access",
            }

            actions = [
                action
                for action in actions
                if action["id"] not in hidden_actions
            ]

        return actions

    def get_task_summary(self, obj):
        task = obj.task

        summary = {
            "task_id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "box_status": task.box_status,

            "box": {
                "id": task.box.id,
                "name": task.box.name,
            } if task.box else None,

            "station": {
                "id": task.station.id,
                "name": task.station.name,
                "address": getattr(task.station, 'address', '') or '',
            } if getattr(task, 'station', None) else None,

            "cubby": {
                "id": task.cubby.id,
                "name": task.cubby.code,
                "code": task.cubby.code,
                "type": task.cubby.cubby_type,
            } if task.cubby else None,
        }

        if task.task_type == Task.TaskType.INSTANT_PRINT:
            documents = (
                task.documents
                .all()
                .order_by("created_at")
            )

            document = documents.first()

            if document:
                copies = document.copies

                summary.update({
                    "title": "Instant Print",
                    "subtitle": (
                        f"{document.original_filename}"
                        f" · {copies} "
                        f"{'copy' if copies == 1 else 'copies'}"
                    ),
                })
            else:
                summary.update({
                    "title": "Instant Print",
                    "subtitle": "Print job",
                })

        elif task.task_type == Task.TaskType.STORED_PRINT:
            documents = task.documents.all()

            total_documents = documents.count()

            total_printed_pages = sum(
                document.page_count * document.copies
                for document in documents
            )

            summary.update({
                "title": "Stored Print",
                "subtitle": (
                    f"{total_documents} "
                    f"{'document' if total_documents == 1 else 'documents'}"
                    f" · {total_printed_pages} printed pages"
                ),
            })

        elif task.task_type == Task.TaskType.PACKAGE_STORAGE:
            if task.cubby:
                summary.update({
                    "title": "Package Storage",
                    "subtitle": (
                        f"{task.cubby.cubby_type.title()}"
                        f" cubby · {task.cubby.code}"
                    ),
                })
            else:
                summary.update({
                    "title": "Package Storage",
                    "subtitle": "Storage task",
                })

        return summary
    
    def get_storage_until(self, obj):
        task = obj.task

        if task.task_type not in [
            Task.TaskType.STORED_PRINT,
            Task.TaskType.PACKAGE_STORAGE,
        ]:
            return None

        return task.storage_until

    def get_latest_message(self, obj):
        message = (
            obj.messages
            .order_by("-created_at", "-id")
            .first()
        )

        if not message:
            return None
        
        return ConversationMessageSerializer(message).data



class ConversationSummarySerializer(serializers.ModelSerializer):
    updated_at = serializers.DateTimeField(
        source="last_activity_at",
        read_only=True,
    )
    task_summary = serializers.SerializerMethodField()
    latest_message = serializers.SerializerMethodField()
    messages = serializers.SerializerMethodField()
    available_actions = serializers.SerializerMethodField()
    storage_until = serializers.SerializerMethodField()

    class Meta:
        model = ConversationSession
        fields = [
            "id",
            "task_summary",
            "current_state",
            "is_active",
            "storage_until",
            "latest_message",
            "messages",
            "available_actions",
            "updated_at",
        ]

    def _is_expanded(self, obj):
        """Check if this conversation should be fully expanded"""
        return self.context.get("expand_conversation_id") == obj.id

    def get_task_summary(self, obj):
        task = obj.task

        summary = {
            "task_id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "box_status": task.box_status,

            "box": {
                "id": task.box.id,
                "name": task.box.name,
            } if task.box else None,

            "station": {
                "id": task.station.id,
                "name": task.station.name,
                "address": getattr(task.station, 'address', '') or '',
            } if getattr(task, 'station', None) else None,

            "cubby": {
                "id": task.cubby.id,
                "name": task.cubby.code,
                "code": task.cubby.code,
                "type": task.cubby.cubby_type,
            } if task.cubby else None,
        }

        if task.task_type == Task.TaskType.INSTANT_PRINT:
            document = (
                task.documents
                .all()
                .order_by("created_at")
                .first()
            )

            if document:
                copies = document.copies

                summary.update({
                    "title": "Instant Print",
                    "subtitle": (
                        f"{document.original_filename}"
                        f" · {copies} "
                        f"{'copy' if copies == 1 else 'copies'}"
                    ),
                })
            else:
                summary.update({
                    "title": "Instant Print",
                    "subtitle": "Print job",
                })

        elif task.task_type == Task.TaskType.STORED_PRINT:
            documents = task.documents.all()

            total_documents = documents.count()

            total_printed_pages = sum(
                document.page_count * document.copies
                for document in documents
            )

            summary.update({
                "title": "Stored Print",
                "subtitle": (
                    f"{total_documents} "
                    f"{'document' if total_documents == 1 else 'documents'}"
                    f" · {total_printed_pages} printed pages"
                ),
            })

        elif task.task_type == Task.TaskType.PACKAGE_STORAGE:
            if task.cubby:
                summary.update({
                    "title": "Package Storage",
                    "subtitle": (
                        f"{task.cubby.cubby_type.title()}"
                        f" cubby · {task.cubby.code}"
                    ),
                })
            else:
                summary.update({
                    "title": "Package Storage",
                    "subtitle": "Storage task",
                })

        return summary
    
    def get_storage_until(self, obj):
        task = obj.task

        if task.task_type not in [
            Task.TaskType.STORED_PRINT,
            Task.TaskType.PACKAGE_STORAGE,
        ]:
            return None

        return task.storage_until

    def get_latest_message(self, obj):
        message = (
            obj.messages
            .order_by("-created_at", "-id")
            .first()
        )

        if not message:
            return None

        return ConversationMessageSerializer(message).data

    def get_messages(self, obj):
        """Return full messages only if this conversation is expanded"""
        if not self._is_expanded(obj):
            return None

        return ConversationMessageSerializer(
            obj.messages.all(),
            many=True
        ).data

    def get_available_actions(self, obj):
        """Return list-safe available actions only."""
        if not self._is_expanded(obj):
            return None

        actions = ConversationService.get_available_actions(obj)

        hidden_actions = {
            "change_access_code",
            "share_access",
        }

        return [
            action
            for action in actions
            if action["id"] not in hidden_actions
        ]

class ConversationActionSerializer(serializers.Serializer):
    action = serializers.CharField()



class RecentTaskSerializer(serializers.ModelSerializer):
    box_name = serializers.CharField(
        source='box.name',
        read_only=True,
        allow_null=True,
    )

    station_name = serializers.CharField(source='station.name', read_only=True, allow_null=True)
    cubby_code = serializers.CharField(source='cubby.code', read_only=True, allow_null=True)
    
    # 1. Add cubby_id
    cubby_id = serializers.IntegerField(source='cubby.id', read_only=True, allow_null=True)
    
    # 2. Add custom fields for document, conversation, and latest message
    document_name = serializers.SerializerMethodField()
    conversation_summary = serializers.SerializerMethodField()
    latest_message = serializers.SerializerMethodField() # Added

    class Meta:
        model = Task
        fields = [
            'id',
            'task_type',
            'status',
            'box_name',
            'station_name',
            'cubby_id',             
            'cubby_code',
            'amount',
            'storage_until',
            'completed_at',
            'created_at',
            'document_name',        
            'conversation_summary', 
            'latest_message',       # Added
        ]

    def get_document_name(self, obj):
        """Extract the original filename for print tasks"""
        if obj.task_type in [Task.TaskType.INSTANT_PRINT, Task.TaskType.STORED_PRINT]:
            # Using the same logic you used in ConversationSerializer
            document = obj.documents.order_by("created_at").first()
            if document:
                return document.original_filename
        return None

    def get_conversation_summary(self, obj):
        """Safely fetch basic conversation details if one exists"""
        conversation = getattr(obj, 'conversation', getattr(obj, 'conversationsession', None))
        
        if conversation:
            return {
                "id": conversation.id,
                "current_state": conversation.current_state,
                "is_active": conversation.is_active,
            }
        return None

    def get_latest_message(self, obj):
        """Fetch the latest message for the task's conversation"""
        conversation = getattr(obj, 'conversation', getattr(obj, 'conversationsession', None))
        
        if not conversation:
            return None
            
        message = (
            conversation.messages
            .order_by("-created_at", "-id")
            .first()
        )

        if not message:
            return None
            
        return ConversationMessageSerializer(message).data

class TaskHistorySerializer(serializers.ModelSerializer):
    box_name = serializers.CharField(
        source='box.name',
        read_only=True,
        allow_null=True,
    )
    station_name = serializers.CharField(source='station.name', read_only=True, allow_null=True)
    cubby_code = serializers.CharField(source='cubby.code', read_only=True, allow_null=True)
    cubby_type = serializers.CharField(
        source='cubby.get_cubby_type_display',
        read_only=True, 
        allow_null=True
    )

    class Meta:
        model = Task
        fields = [
            'id',
            'task_type',
            'status',
            'box_name',
            'station_name',
            'cubby_code',
            'cubby_type',
            'amount',
            'task_data',
            'created_at',
            'completed_at',
            'storage_until',
        ]


class BoxPrintDocumentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = PrintDocument
        fields = ['id', 'file_url', 'original_filename', 'copies', 'page_count', 'print_settings']

    def get_file_url(self, obj):
        request = self.context.get('request')
        if obj.file and hasattr(obj.file, 'url'):
            return request.build_absolute_uri(obj.file.url)
        return None

class BoxTaskDownloadSerializer(serializers.ModelSerializer):
    documents = BoxPrintDocumentSerializer(many=True, read_only=True)
    cubby_code = serializers.CharField(source='cubby.code', read_only=True)
    storage_expiry = serializers.DateTimeField(source='storage_until', format="%Y-%m-%dT%H:%M:%SZ", read_only=True)

    class Meta:
        model = Task
        fields = [
            'id', 
            'task_type', 
            'box_status', 
            'access_code', 
            'cubby_code', 
            'storage_expiry',
            'task_data', # Contains size, storage_days, etc.
            'documents'
        ]

class WalletTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = WalletTransaction
        fields = [
            'id',
            'transaction_type',
            'amount',
            'balance_before',
            'balance_after',
            'reference',
            'description',
            'created_at',
        ]

#.....................................................


class UserProfileSerializer(serializers.ModelSerializer):
    # 1. Pull the wallet balance from the related OneToOne model
    wallet_balance = serializers.DecimalField(
        source='wallet.balance', 
        max_digits=10, 
        decimal_places=2, 
        read_only=True
    )

    class Meta:
        model = User
        # NOTE: If your custom User model has other fields (like 'phone_number'), add them here!
        fields = ['id', 'email', 'name', 'wallet_balance']
        
        # Prevent the user from changing their email or ID via a simple API call
        read_only_fields = ['id', 'email', 'wallet_balance'] 

   