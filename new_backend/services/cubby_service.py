from datetime import timedelta
from django.db import transaction
from django.utils import timezone

from ..models import Cubby


class CubbyService:

    RESERVATION_MINUTES = 10

    @staticmethod
    @transaction.atomic
    def allocate_cubby(box, cubby_type):
        cubby = (
            Cubby.objects
            .select_for_update()
            .filter(
                box=box,
                cubby_type=cubby_type,
                status=Cubby.Status.AVAILABLE,
            )
            .first()
        )

        if not cubby:
            return None

        return cubby

    @staticmethod
    @transaction.atomic
    def allocate_and_occupy_cubby(box, cubby_type):
        cubby = (
            Cubby.objects
            .select_for_update()
            .filter(
                box=box,
                cubby_type=cubby_type,
                status=Cubby.Status.AVAILABLE,
            )
            .first()
        )

        if not cubby:
            return None

        cubby.status = Cubby.Status.OCCUPIED
        cubby.reserved_until = None
        cubby.save(update_fields=["status", "reserved_until"])

        return cubby

    @staticmethod
    def occupy_cubby(cubby):
        cubby.status = Cubby.Status.OCCUPIED
        cubby.reserved_until = None
        cubby.save()

    @staticmethod
    def release_cubby(cubby):
        cubby.status = Cubby.Status.AVAILABLE
        cubby.reserved_until = None
        cubby.save()

    @staticmethod
    def release_expired_reservations():
        expired = Cubby.objects.filter(
            status=Cubby.Status.RESERVED,
            reserved_until__lt=timezone.now()
        )

        count = expired.count()

        expired.update(
            status=Cubby.Status.AVAILABLE,
            reserved_until=None
        )

        return count