from django.db import transaction
from django.utils import timezone

from ..models import Task
from .cubby_service import CubbyService
from .pricing_service import PricingService
from ..models import ConversationSession, ConversationMessage
from datetime import timedelta


class TaskService:

    @staticmethod
    @transaction.atomic
    def create_instant_print_task(
        user,
        pages,
        document_name,
        copies,
        color_mode,
        duplex,
        orientation,
    ):
        amount = PricingService.calculate_instant_print_cost(
            pages=pages,
            copies=copies,
        )

        task = Task.objects.create(
            user=user,
            box=None,
            cubby=None,
            task_type=Task.TaskType.INSTANT_PRINT,
            status=Task.Status.PENDING,
            amount=amount,
            task_data={
                "document_name": document_name,
                "pages": pages,
                "copies": copies,
                "color_mode": color_mode,
                "duplex": duplex,
                "orientation": orientation,
                "total_printed_pages": pages * copies,
            },
        )

        return task

    @staticmethod
    @transaction.atomic
    def create_stored_print_task(
        user,
        box,
        pages,
        document_name,
        copies,
        color_mode,
        duplex,
        orientation,
        storage_hours

    ):
        if not box.supports_printing:
            raise ValueError(
                'This box does not support printing.'
            )

        amount = PricingService.calculate_print_cost(
            box,
            pages,
            is_stored=True,
            storage_hours=storage_hours
        )

        task = Task.objects.create(
    user=user,
    box=box,
    cubby=None,
    task_type=Task.TaskType.STORED_PRINT,
    status=Task.Status.PENDING,
    amount=amount,
    task_data={
        "document_name": document_name,
        "pages": pages,
        "copies": copies,
        "color_mode": color_mode,
        "duplex": duplex,
        "orientation": orientation,
        "storage_hours": storage_hours,
    }
)

        return task

    @staticmethod
    @transaction.atomic
    def create_package_task(
        user,
        box,
        cubby_type,
        storage_days
    ):
        if not box.supports_package_storage:
            raise ValueError(
                'This box does not support package storage.'
            )

        amount = PricingService.calculate_package_cost(
            box,
            cubby_type,
            storage_days,
        )

        task = Task.objects.create(
            user=user,
            box=box,
            cubby=None,
            task_type=Task.TaskType.PACKAGE_STORAGE,
            status=Task.Status.PENDING,
            amount=amount,
            task_data={
        "storage_days": storage_days,
    }
        )

        return task

    @staticmethod
    def expire_storage_tasks():
        expired_tasks = Task.objects.filter(
            status=Task.Status.ACTIVE,
            storage_until__lt=timezone.now(),
        )

        for task in expired_tasks:
            # Storage expiry does NOT end the task.
            #
            # The task remains ACTIVE so the user can still:
            # - view the conversation
            # - extend the storage duration
            #
            # The storage_until field itself determines whether
            # the storage period is currently valid.

            if hasattr(task, "conversation"):
                conversation = task.conversation

                # Only add the expiry message once.
                already_notified = conversation.messages.filter(
                    message_type=ConversationMessage.MessageType.STATUS,
                    content__title="Storage period expired",
                ).exists()

                if not already_notified:
                    ConversationMessage.objects.create(
                        session=conversation,
                        sender=ConversationMessage.Sender.SYSTEM,
                        message_type=ConversationMessage.MessageType.STATUS,
                        content={
                            "title": "Storage period expired",
                            "message": (
                                "Your storage period has expired. "
                                "Your item is still associated with this "
                                "storage task. You can extend the storage "
                                "duration to continue using it."
                            ),
                        },
                    )

        return expired_tasks.count()