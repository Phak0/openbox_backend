
import random
import uuid
from datetime import timedelta
import string
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.validators import MinValueValidator
from decimal import Decimal
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import models
from django.db.models import Q
from django.db import migrations, models
import django.db.models.deletion
from django.contrib.auth.hashers import make_password, check_password
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('new_backend', 'YOUR_PREVIOUS_MIGRATION'),
    ]

    operations = [
        migrations.AlterField(
            model_name='task',
            name='cubby',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='tasks',
                to='new_backend.cubby',
            ),
        ),
    ]

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email: raise ValueError("Email required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('user_type', 'supervisor') # Default for admins

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)

class User(AbstractBaseUser, PermissionsMixin):
    # Identity Fields
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=100)
    user_code = models.CharField(max_length=50, unique=True)
    user_type = models.CharField(max_length=20, default='supervisee')
    verification_code = models.CharField(max_length=6, blank=True, null=True)
    
    # Logic Fields (Replacing the old system)
    cash_balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    is_verified = models.BooleanField(default=False) # For the email confirmation phase
    is_active = models.BooleanField(default=True)

    is_staff = models.BooleanField(default=False) # Add this!
    is_active = models.BooleanField(default=True)
    
    objects = UserManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']


class Box(models.Model):
    BOX_TYPES = (
        ('print', 'Print Box'),
        ('package', 'Package Storage Box'),
        ('combined', 'Combined (Print & Package Storage)')
    )

    name = models.CharField(max_length=50)
    address = models.CharField(max_length=255)
    picture = models.ImageField(upload_to='box_images/', null=True, blank=True)

    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)

    is_available = models.BooleanField(default=True)
    box_type = models.CharField(max_length=20, choices=BOX_TYPES)

    printing_price = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True
    )

    stored_print_hourly_price = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True
    )

    dropbox_pricing = models.JSONField(
        null=True,
        blank=True,
        help_text='{"small": 2.5, "medium": 5.0, "large": 8.0}'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def supports_printing(self):
        return self.box_type in ['print', 'combined']

    @property
    def supports_package_storage(self):
        return self.box_type in ['package', 'combined']

    def __str__(self):
        return self.name


class GlobalPricing(models.Model):
    """
    Global platform-wide pricing configuration.

    There should only ever be one row.
    """

    instant_print_price_per_page = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )

    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Prevent deletion of the global pricing configuration.
        raise ValueError("Global pricing configuration cannot be deleted.")

    def __str__(self):
        return "Global Pricing"

class Wallet(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    def __str__(self):
        return f"{self.user.email}'s Wallet - ₦{self.balance}"

# This Signal acts as a trigger: When a User is created, automatically create a Wallet for them!
@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_wallet(sender, instance, created, **kwargs):
    if created:
        Wallet.objects.create(user=instance)
    



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


class PrintDocument(models.Model):
    task = models.ForeignKey(
        'Task',
        on_delete=models.CASCADE,
        related_name='documents',
    )

    file = models.FileField(
        upload_to='tasks/documents/',
    )

    original_filename = models.CharField(
        max_length=255,
        blank=True,
    )

    copies = models.PositiveIntegerField(
        default=1,
    )

    page_count = models.PositiveIntegerField(
        default=0,
    )

    print_settings = models.JSONField(
        default=dict,
        blank=True,
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
    )

    storage_path = models.CharField(
    max_length=500,
    blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return (
            f'{self.original_filename or self.file.name} '
            f'- Task #{self.task_id}'
        )


class Status(models.TextChoices):
    PENDING_PAYMENT = 'pending_payment', 'Pending Payment'

    QUEUED = 'queued', 'Queued'
    BOX_RECEIVED = 'box_received', 'Box Received Task'
    PROCESSING = 'processing', 'Processing'

    PRINTING = 'printing', 'Printing'
    READY_FOR_PICKUP = 'ready_for_pickup', 'Ready for Pickup'

    ACTIVE = 'active', 'Active Storage'

    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'
    EXPIRED = 'expired', 'Expired'
        

class Task(models.Model):
    class TaskType(models.TextChoices):
        INSTANT_PRINT = 'instant_print', 'Instant Print'
        STORED_PRINT = 'stored_print', 'Stored Print'
        PACKAGE_STORAGE = 'package_storage', 'Package Storage'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending Payment'
        ACTIVE = 'active', 'Active Storage'
        COMPLETED = 'completed', 'Completed'
        WITHDRAWN = 'withdrawn', 'Withdrawn'
        EXPIRED = 'expired', 'Expired'
        CANCELLED = 'cancelled', 'Cancelled'


    class BoxStatus(models.TextChoices):
        NOT_SENT = 'not_sent', 'Not Sent'
        QUEUED = 'queued', 'Queued'
        RECEIVED = 'received', 'Received'
        PROCESSING = 'processing', 'Processing'
        PRINTING = 'printing', 'Printing'
        WAITING_FOR_DEPOSIT = 'waiting_for_deposit', 'Waiting for Deposit'
        PACKAGE_STORED = 'package_stored', 'Package Stored'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='tasks'
    )

    box = models.ForeignKey(
        Box,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
    )
    

    cubby = models.ForeignKey(
        Cubby,
        on_delete=models.PROTECT,
        related_name='tasks',
        null=True,
        blank=True,
    )

    task_type = models.CharField(
        max_length=30,
        choices=TaskType.choices
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    box_status = models.CharField(
        max_length=30,
        choices=BoxStatus.choices,
        default=BoxStatus.NOT_SENT,
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    storage_until = models.DateTimeField(
        null=True,
        blank=True
    )

    access_code = models.CharField(
        max_length=20,
        blank=True
    )

    completed_at = models.DateTimeField(
        null=True,
        blank=True
    )

    visible_until = models.DateTimeField(
        null=True,
        blank=True
    )


    task_data = models.JSONField(
    default=dict,
    blank=True,
    help_text="Stores task-specific details such as printing options or package storage selections."
)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['cubby'],
                condition=Q(
                    cubby__isnull=False,
                    status=Status.ACTIVE,
                ),
                name='one_active_task_per_cubby'
            )
        ]

    def __str__(self):
        return f'{self.user} - {self.get_task_type_display()} ({self.status})'


class PendingPrintDocument(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='pending_documents',
    )

    file = models.FileField(
        upload_to='tasks/pending_documents/'
    )

    original_filename = models.CharField(
        max_length=255,
        blank=True
    )

    copies = models.PositiveIntegerField(default=1)

    page_count = models.PositiveIntegerField(default=0)

    print_settings = models.JSONField(
        default=dict,
        blank=True
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return (
            f"Pending document {self.id} "
            f"- Task {self.task_id}"
        )


class PackageAccessShare(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="access_shares",
    )

    token_hash = models.CharField(
        max_length=64,
        unique=True,
    )

    expires_at = models.DateTimeField()

    used_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    revoked_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Package access share for Task #{self.task_id}"


class ConversationSession(models.Model):
    class State(models.TextChoices):
        SUMMARY = 'summary', 'Summary'
        COST_REVIEW = 'cost_review', 'Cost Review'
        DOCUMENT_REVIEW = 'document_review', 'Document Review'
        EXTENSION_REVIEW = 'extension_review', 'Extension Review'
        PAYMENT = 'payment', 'Payment'
        ACTIVE_PRINT = "active_print", "Active Print"
        ACTIVE_STORAGE = 'active_storage', 'Active Storage'
        COMPLETED = 'completed', 'Completed'

    task = models.OneToOneField(
        Task,
        on_delete=models.CASCADE,
        related_name='conversation'
    )

    cubby = models.ForeignKey(
    Cubby,
    on_delete=models.SET_NULL,
    related_name='conversations',
    null=True,
    blank=True,
)

    current_state = models.CharField(
        max_length=30,
        choices=State.choices,
        default=State.SUMMARY
    )

    is_active = models.BooleanField(default=True)

    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'Conversation for Task #{self.task.id}'

    @property
    def available_actions(self):
        if not self.is_active:
            return []

        # Handle COST_REVIEW state specially based on wallet balance
        if self.current_state == self.State.COST_REVIEW:
            wallet = self.task.user.wallet
            if wallet.balance >= self.task.amount:
                return [
                    {"id": "pay", "label": "Pay"},
                    {"id": "edit", "label": "Edit"},
                    {"id": "cancel", "label": "Cancel"},
                ]
            return [
                {"id": "topup", "label": "Top Up Wallet"},
                {"id": "edit", "label": "Edit"},
                {"id": "cancel", "label": "Cancel"},
            ]

        state_actions = {
            self.State.SUMMARY: [
                {'id': 'proceed', 'label': 'Proceed'},
                {'id': 'edit', 'label': 'Edit'},
                {'id': 'cancel', 'label': 'Cancel'},
            ],
            self.State.ACTIVE_STORAGE: [
                {'id': 'extend', 'label': 'Extend Duration'},
                {'id': 'withdraw', 'label': 'Withdraw Item'},
            ],
            self.State.COMPLETED: [],
        }

        return state_actions.get(self.current_state, [])

    

class ConversationMessage(models.Model):
    class Sender(models.TextChoices):
        SYSTEM = 'system', 'System'
        USER = 'user', 'User'

    class MessageType(models.TextChoices):
        TEXT = 'text', 'Text'
        SUMMARY = 'summary', 'Summary'
        PAYMENT = 'payment', 'Payment'
        STATUS = 'status', 'Status'
        ACTION = 'action', 'Action'

    session = models.ForeignKey(
        ConversationSession,
        on_delete=models.CASCADE,
        related_name='messages'
    )

    sender = models.CharField(
        max_length=10,
        choices=Sender.choices
    )

    message_type = models.CharField(
        max_length=20,
        choices=MessageType.choices,
        default=MessageType.TEXT
    )

    content = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class WalletTransaction(models.Model):
    class TransactionType(models.TextChoices):
        DEPOSIT = 'deposit', 'Deposit'
        PAYMENT = 'payment', 'Task Payment'
        REFUND = 'refund', 'Refund'
        ADJUSTMENT = 'adjustment', 'Adjustment'

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name='transactions'
    )

    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    balance_before = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    balance_after = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    reference = models.CharField(
        max_length=100,
        unique=True
    )

    description = models.TextField(blank=True)

    task = models.ForeignKey(
        'Task',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='wallet_transactions'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return (
            f'{self.wallet.user.email} - '
            f'{self.get_transaction_type_display()} '
            f'₦{self.amount}'
        )

#///////////////////////////////////////////////////////////


class Deposit(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed')
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='deposits')
    amount = models.DecimalField(max_digits=10, decimal_places=2, help_text="Amount in Naira")
    reference = models.CharField(max_length=100, unique=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # Generate a unique reference for Paystack if we don't have one
        if not self.reference:
            self.reference = f"DEP-{uuid.uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.email} - ₦{self.amount} - {self.status}"