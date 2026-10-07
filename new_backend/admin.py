from django.contrib import admin
from .models import (
    User,
    Box,
    GlobalPricing,
    Cubby,
    Task,
    ConversationSession,
    ConversationMessage,
    Wallet,
    WalletTransaction,
    Deposit,
)


# 1. USER ADMIN
@admin.register(User)
class CustomUserAdmin(admin.ModelAdmin):
    list_display = ("email", "name", "user_type", "is_verified", "user_code")
    list_filter = ("user_type", "is_verified")
    search_fields = ("email", "name", "user_code")
    ordering = ("-id",)


# Cubby inline
class CubbyInline(admin.TabularInline):
    model = Cubby
    extra = 0


# 3. BOX ADMIN
@admin.register(Box)
class BoxAdmin(admin.ModelAdmin):
    list_display = ("name", "box_type", "address", "is_available")
    list_filter = ("box_type", "is_available")
    search_fields = ("name", "address")

    inlines = [CubbyInline]

    fieldsets = (
        (
            "Basic Info",
            {
                "fields": (
                    "name",
                    "address",
                    "latitude",
                    "longitude",
                    "picture",
                    "is_available",
                    "box_type",
                )
            },
        ),
        (
            "Pricing Configuration",
            {
                "fields": (
                    "printing_price",
                    "stored_print_hourly_price",
                    "dropbox_pricing",
                ),
                "classes": ("collapse",),
            },
        ),
    )


@admin.register(GlobalPricing)
class GlobalPricingAdmin(admin.ModelAdmin):
    list_display = (
        "instant_print_price_per_page",
        "updated_at",
    )

    readonly_fields = ("updated_at",)

    fieldsets = (
        (
            "Instant Print Pricing",
            {
                "fields": (
                    "instant_print_price_per_page",
                )
            },
        ),
        (
            "System",
            {
                "fields": (
                    "updated_at",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        # Only allow one configuration row.
        return not GlobalPricing.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

# Cubby admin
@admin.register(Cubby)
class CubbyAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "box",
        "cubby_type",
        "status",
        "reserved_until",
    )
    list_filter = ("cubby_type", "status", "box")
    search_fields = ("code", "box__name")


# Task admin
@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "box",
        "cubby",
        "task_type",
        "status",
        "amount",
        "storage_until",
        "created_at",
    )
    list_filter = ("task_type", "status", "box")
    search_fields = (
        "user__email",
        "cubby__code",
        "box__name",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "completed_at",
    )


# Conversation session admin
@admin.register(ConversationSession)
class ConversationSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "task",
        "cubby",
        "current_state",
        "is_active",
        "started_at",
    )
    list_filter = ("current_state", "is_active")
    search_fields = (
        "task__user__email",
        "cubby__code",
    )


# Conversation message admin
@admin.register(ConversationMessage)
class ConversationMessageAdmin(admin.ModelAdmin):
    list_display = (
        "session",
        "sender",
        "message_type",
        "created_at",
    )
    list_filter = (
        "sender",
        "message_type",
        "created_at",
    )
    search_fields = (
        "session__task__user__email",
    )
    readonly_fields = ("created_at",)


# Wallet admin
class WalletAdmin(admin.ModelAdmin):
    list_display = ("user", "balance")
    search_fields = (
        "user__email",
        "user__name",
    )

try:
    admin.site.register(Wallet, WalletAdmin)
except admin.sites.AlreadyRegistered:
    pass


# Wallet transaction admin
@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "wallet",
        "transaction_type",
        "amount",
        "balance_after",
        "reference",
        "created_at",
    )
    list_filter = (
        "transaction_type",
        "created_at",
    )
    search_fields = (
        "wallet__user__email",
        "reference",
    )
    readonly_fields = ("created_at",)





# 7. DEPOSIT ADMIN (NEW)
@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'status', 'reference', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__email', 'reference')
    readonly_fields = ('reference', 'created_at')
