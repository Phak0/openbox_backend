from decimal import Decimal
from django.core.exceptions import ValidationError

from ..models import GlobalPricing


class PricingService:

    @staticmethod
    def get_global_pricing():
        pricing = GlobalPricing.objects.first()

        if not pricing:
            raise ValidationError(
                "Instant Print pricing has not been configured by the administrator."
            )

        return pricing

    @staticmethod
    def calculate_instant_print_cost(pages, copies=1):
        pricing = PricingService.get_global_pricing()

        printed_pages = Decimal(pages) * Decimal(copies)

        return printed_pages * pricing.instant_print_price_per_page

    @staticmethod
    def calculate_print_cost(
        box,
        pages,
        copies=1,
        is_stored=False,
        storage_hours=0,
    ):
        """
        Box-based printing pricing.

        Used for Stored Print only.
        """

        printed_pages = Decimal(pages) * Decimal(copies)

        total = printed_pages * (
            box.printing_price or Decimal("0.00")
        )

        if is_stored:
            total += (
                Decimal(storage_hours)
                * (box.stored_print_hourly_price or Decimal("0.00"))
            )

        return total

    @staticmethod
    def calculate_package_cost(
        box,
        cubby_type,
        storage_days,
    ):
        pricing = box.dropbox_pricing or {}

        daily_price = Decimal(
            pricing.get(cubby_type, 0)
        )

        return daily_price * Decimal(storage_days)