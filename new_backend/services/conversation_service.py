from datetime import timedelta
import hashlib
import secrets
import random

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from secrets import randbelow

from ..models import (
Task,
PendingPrintDocument,
Cubby,
ConversationSession,
ConversationMessage,
PrintDocument,
PackageAccessShare,
)
from .cubby_service import CubbyService
from .pricing_service import PricingService
from .wallet_service import WalletService

class ConversationService:
    """
    Handles all conversation workflow logic.

    The frontend should never decide workflow transitions.
    It simply sends an action and renders the updated conversation.
    """

    VALID_ACTIONS = {
        ConversationSession.State.ACTIVE_PRINT: [],
        ConversationSession.State.ACTIVE_STORAGE: ["extend", "withdraw", "add_document"],
        ConversationSession.State.DOCUMENT_REVIEW: ["pay", "cancel"],
        ConversationSession.State.EXTENSION_REVIEW: ["pay","cancel"],
        ConversationSession.State.COMPLETED: [],
    }

    @staticmethod
    @transaction.atomic
    def create_session(task):
        session = ConversationSession.objects.create(
            task=task,
            cubby=None,
            current_state=ConversationSession.State.COST_REVIEW,
            is_active=True,
        )

        ConversationService._add_system_message(
            session,
            ConversationService.build_summary(task),
            message_type=ConversationMessage.MessageType.SUMMARY,
        )

        return session


    @staticmethod
    def build_summary(task):
        data = task.task_data or {}

        documents = list(
            task.documents.all().order_by("created_at")
        )

        # -----------------------------------------
        # Calculate document information
        # -----------------------------------------

        total_pages = sum(
            document.page_count * document.copies
            for document in documents
        )

        total_copies = sum(
            document.copies
            for document in documents
        )

        document_charges = []

        for document in documents:
            document_charges.append({
                "document_id": document.id,
                "filename": (
                    document.original_filename
                    or document.file.name
                ),
                "pages": document.page_count,
                "copies": document.copies,
                "printed_pages": document.page_count * document.copies,
                "amount": str(document.amount),
                "print_settings": document.print_settings,
            })

        # -----------------------------------------
        # Instant Print
        # -----------------------------------------

        if task.task_type == Task.TaskType.INSTANT_PRINT:
            documents = task.documents.all().order_by("created_at")
            document = documents.first()

            if document:
                message = (
                    f"I've prepared your instant print request for "
                    f"{document.original_filename}.\n\n"
                    f"Copies: {document.copies}\n"
                    f"Printed pages: "
                    f"{document.page_count * document.copies}\n"
                    f"Total: ₦{task.amount}"
                )
            else:
                message = (
                    "I've prepared your instant print request.\n\n"
                    f"Total: ₦{task.amount}"
                )

            # ADD THIS:
            return {
                "title": "Your instant print request is ready",
                "message": message,
            }

        # -----------------------------------------
        # Stored Print
        # -----------------------------------------

        if task.task_type == Task.TaskType.STORED_PRINT:

            hours = int(
                data.get("storage_hours", 1)
            )

            storage_rate = (
                task.box.stored_print_hourly_price
                or Decimal("0.00")
            )

            storage_cost = (
                storage_rate
                * Decimal(hours)
            )

            printing_cost = sum(
                document.amount
                for document in documents
            )

            return {
                "title": "Your stored print request is ready",
                "message": (
                    f"I've prepared your print request "
                    f"for {task.box.name}.\n\n"
                    "Here’s a breakdown of the charges:"
                ),
                "documents": document_charges,
                "total_pages": total_pages,
                "total_copies": total_copies,
                "charges": [
                    {
                        "label": "Printing",
                        "amount": str(printing_cost),
                    },
                    {
                        "label": (
                            f"Storage ({hours} "
                            f"hour{'s' if hours != 1 else ''})"
                        ),
                        "amount": str(storage_cost),
                    },
                ],
                "total": str(task.amount),
                "notice": (
                    "A print cubby will be assigned "
                    "after payment."
                ),
            }

        # -----------------------------------------
        # Package Storage
        # -----------------------------------------

        storage_days = int(
            data.get("storage_days", 1)
        )

        size = str(data.get("size") or "medium").lower()


        pricing = task.box.dropbox_pricing or {}

        daily_rate = Decimal(
            str(pricing.get(size, 0))
        )

        storage_cost = (
            daily_rate
            * Decimal(storage_days)
        )

        size_label = size.capitalize()

        return {
            "title": "Your package storage request is ready",
            "message": (
                f"I've prepared a {size_label} package "
                f"storage request at {task.box.name}.\n\n"
                "Here’s a breakdown of the storage charges:"
            ),
            "charges": [
                {
                    "label": (
                        f"{size_label} cubby "
                        f"({storage_days} "
                        f"day{'s' if storage_days != 1 else ''})"
                    ),
                    "amount": str(storage_cost),
                },
            ],
            "total": str(task.amount),
            "notice": (
                f"A {size_label} storage cubby will be "
                "assigned after payment."
            ),
        }

    @staticmethod
    def get_available_actions(session):
        state = session.current_state
        task = session.task

        # -----------------------------------------
        # Payment review states
        # -----------------------------------------

        if state == ConversationSession.State.COST_REVIEW:

            balance = WalletService.get_balance(task.user)

            actions = []

            if balance >= task.amount:
                actions.append("pay")
            else:
                actions.append("topup")

            actions.extend([
                "edit",
                "cancel",
            ])

        elif state == ConversationSession.State.DOCUMENT_REVIEW:

            pending_document = (
                PendingPrintDocument.objects
                .filter(task=task)
                .order_by("-created_at")
                .first()
            )

            if not pending_document:
                return []

            amount = pending_document.amount
            balance = WalletService.get_balance(task.user)

            actions = []

            if balance >= amount:
                actions.append("pay")
            else:
                actions.append("topup")

            actions.append("cancel")

        elif state == ConversationSession.State.EXTENSION_REVIEW:

            pending_extension = (
                (task.task_data or {})
                .get("pending_extension")
            )
            print("EXTENSION DEBUG task_data:", task.task_data)
            print("EXTENSION DEBUG pending_extension:", pending_extension)

            if not pending_extension:
                return []

            amount = Decimal(
                str(pending_extension["amount"])
            )

            balance = WalletService.get_balance(task.user)

            actions = []

            if balance >= amount:
                actions.append("pay")
            else:
                actions.append("topup")

            actions.append("cancel")

        # -----------------------------------------
        # Active storage
        # -----------------------------------------

        elif state == ConversationSession.State.ACTIVE_STORAGE:

            now = timezone.now()

            storage_active = (
                task.storage_until
                and now < task.storage_until
            )

            actions = [
                "extend",
                "withdraw",
            ]

            if (
                task.task_type == Task.TaskType.STORED_PRINT
                and storage_active
            ):
                actions.append("add_document")

            if (
                task.task_type == Task.TaskType.PACKAGE_STORAGE
                and storage_active
            ):
                actions.append("change_access_code")
                actions.append("share_access")

        else:
            actions = list(
                ConversationService.VALID_ACTIONS.get(
                    state,
                    []
                )
            )

        return [
            {
                "id": action,
                "label": (
                    "Top Up Wallet"
                    if action == "topup"
                    else action.replace("_", " ").title()
                ),
            }
            for action in actions
        ]

    @staticmethod
    @transaction.atomic
    def perform_action(session, action, data=None):
        if not session.is_active:
            raise ValidationError(
                "This conversation has already ended."
            )

        allowed = [
            item["id"]
            for item in ConversationService.get_available_actions(session)
        ]

        if action not in allowed:
            raise ValidationError(
                f"Action '{action}' is not allowed in the current state."
            )

        # -----------------------------------------
        # Pay for adding a document
        # -----------------------------------------

        if (
            session.current_state
            == ConversationSession.State.DOCUMENT_REVIEW
            and action == "pay"
        ):
            return ConversationService._handle_document_payment(
                session
            )

        # -----------------------------------------
        # Pay for storage extension
        # -----------------------------------------

        if (
            session.current_state
            == ConversationSession.State.EXTENSION_REVIEW
            and action == "pay"
        ):
            return ConversationService._handle_extension_payment(
                session
            )
        # -----------------------------------------
        # Cancel payment review
        # -----------------------------------------

        if (
            session.current_state
            in (
                ConversationSession.State.DOCUMENT_REVIEW,
                ConversationSession.State.EXTENSION_REVIEW,
            )
            and action == "cancel"
        ):
            return ConversationService._handle_review_cancel(
                session
            )

        # -----------------------------------------
        # Request storage extension
        # -----------------------------------------

        if action == "extend":
            duration = (data or {}).get(
                "duration"
            )

            return ConversationService.prepare_extension_payment(
                session,
                duration,
            )

        if action == "change_access_code":
            return ConversationService._handle_change_access_code(session)

        if action == "share_access":
            return ConversationService._handle_share_access(session)

        # -----------------------------------------
        # Normal actions
        # -----------------------------------------

        if action == "pay":
            return ConversationService._handle_payment(session)

        if action == "edit":
            return ConversationService._handle_edit(session)

        if action == "topup":
            return ConversationService._handle_topup(session)

        if action == "withdraw":
            return ConversationService._handle_withdrawal(session)

        if action == "cancel":
            return ConversationService._handle_cancel(session)

        raise ValidationError(
            f"Unsupported action: {action}"
        )

    @staticmethod
    def _add_user_message(session, action, label=None):
        return ConversationMessage.objects.create(
            session=session,
            sender=ConversationMessage.Sender.USER,
            message_type=ConversationMessage.MessageType.ACTION,
            content={
                "action": action,
                "label": label or action.replace("_", " ").title(),
            },
        )

    @staticmethod
    def _add_system_message(session, content, message_type='text'):
        return ConversationMessage.objects.create(
            session=session,
            sender=ConversationMessage.Sender.SYSTEM,
            message_type=message_type,
            content=content,
        )

    @staticmethod
    @transaction.atomic
    def _handle_payment(session):
        task = (
            Task.objects
            .select_for_update()
            .get(pk=session.task.pk)
        )

        if task.status != Task.Status.PENDING:
            return session

        # -------------------------------------------------
        # Determine whether this task needs a cubby
        # BEFORE charging the user.
        # -------------------------------------------------
        cubby = None

        if task.task_type == Task.TaskType.STORED_PRINT:
            cubby_type = Cubby.CubbyType.PRINT

            cubby = CubbyService.allocate_cubby(
                task.box,
                cubby_type,
            )

            if not cubby:
                raise ValidationError(
                    "No available print cubby is currently available."
                )

        elif task.task_type == Task.TaskType.PACKAGE_STORAGE:
            size = str((task.task_data or {}).get("size", "medium") or "medium").lower()


            cubby_type = getattr(
                Cubby.CubbyType,
                size.upper(),
                None,
            )

            if cubby_type is None:
                raise ValidationError(
                    f"Invalid package size: {size}"
                )

            cubby = CubbyService.allocate_cubby(
                task.box,
                cubby_type,
            )

            if not cubby:
                raise ValidationError(
                    f"No available {size} cubby is currently available."
                )

        # -------------------------------------------------
        # Record the user's action
        # -------------------------------------------------
        ConversationService._add_user_message(
            session,
            action="pay",
            label="Pay",
        )

        # -------------------------------------------------
        # Charge wallet
        # -------------------------------------------------
        WalletService.charge(
            user=task.user,
            amount=task.amount,
            task=task,
        )

        # -------------------------------------------------
        # Instant Print
        # -------------------------------------------------

        if task.task_type == Task.TaskType.INSTANT_PRINT:

            access_code = f"{randbelow(1_000_000):06d}"

            task.status = Task.Status.ACTIVE
            task.box_status = Task.BoxStatus.QUEUED
            task.access_code = access_code

            task.save(
                update_fields=[
                    "status",
                    "box_status",
                    "access_code",
                    "updated_at",
                ]
            )

            from ..firebase_service import (
                create_task_in_firestore
            )

            create_task_in_firestore(task)

            ConversationService._add_system_message(
                session,
                {
                    "title": "Payment received successfully",
                    "message": (
                        "Your payment has been received.\n\n"
                        f"Access code: {task.access_code}\n\n"
                        "Use this code at any physical box "
                        "when you are ready to start printing."
                    ),
                    "access_code": task.access_code,
                },
                message_type=ConversationMessage.MessageType.STATUS,
            )

            session.current_state = (
                ConversationSession.State.ACTIVE_PRINT
            )

            session.save(
                update_fields=["current_state"]
            )

            return session

        # -------------------------------------------------
        # Storage tasks
        # -------------------------------------------------

        task.cubby = cubby
        session.cubby = cubby

        task.status = Task.Status.ACTIVE
        task.box_status = Task.BoxStatus.QUEUED

        task.access_code = str(
            random.randint(100000, 999999)
        )

        if task.task_type == Task.TaskType.STORED_PRINT:
            storage_hours = int(
                (task.task_data or {}).get(
                    "storage_hours",
                    1,
                )
            )

            task.storage_until = (
                timezone.now()
                + timedelta(hours=storage_hours)
            )

        elif task.task_type == Task.TaskType.PACKAGE_STORAGE:
            storage_days = int(
                (task.task_data or {}).get(
                    "storage_days",
                    1,
                )
            )

            task.storage_until = (
                timezone.now()
                + timedelta(days=storage_days)
            )

        task.save()

        # -------------------------------------------------
        # Convert the allocated cubby to occupied
        # -------------------------------------------------
        CubbyService.occupy_cubby(cubby)

        # -------------------------------------------------
        # Send the paid task to Firestore
        # -------------------------------------------------
        from ..firebase_service import (
            create_task_in_firestore
        )

        create_task_in_firestore(task)

        expiry = task.storage_until.strftime(
            "%A, %d %B at %I:%M %p"
        )

        if task.task_type == Task.TaskType.STORED_PRINT:

            message = (
                "Payment received successfully.\n\n"
                f"Your document has been sent to "
                f"{task.box.name} for printing.\n\n"
                f"It will be stored securely in "
                f"Cubby {cubby.code} once printing is complete.\n\n"
                f"Access code: {task.access_code}\n\n"
                f"It will remain available until {expiry}."
            )

        elif task.task_type == Task.TaskType.PACKAGE_STORAGE:

            message = (
                "Payment received successfully.\n\n"
                f"Your package has been assigned to "
                f"Cubby {cubby.code} at {task.box.name}.\n\n"
                f"Access code: {task.access_code}\n\n"
                f"Your storage reservation will expire on {expiry}."
            )

        else:
            raise ValidationError(
                "Unsupported storage task type."
            )

        ConversationService._add_system_message(
            session,
            {
                "title": "Payment received successfully",
                "message": message,
                "access_code": task.access_code,
                "storage_until": task.storage_until.isoformat(),
                "cubby": {
                    "id": cubby.id,
                    "code": cubby.code,
                } if cubby else None,
            },
            message_type=ConversationMessage.MessageType.STATUS,
        )

        session.current_state = (
            ConversationSession.State.ACTIVE_STORAGE
        )

        session.save(
            update_fields=["cubby", "current_state"]
        )

        return session

    
    @staticmethod
    def add_box_status_message(task, box_status):
        """
        Add a user-visible chat message whenever the physical box
        reports a new processing status.
        """

        box_name = task.box.name if task.box else "the box"

        messages = {
            Task.BoxStatus.QUEUED: {
                "title": "Task queued",
                "message": (
                    f"Your task has been sent to {box_name} "
                    "and is waiting to be processed."
                ),
            },

            Task.BoxStatus.RECEIVED: {
                "title": "Task received",
                "message": (
                    f"{box_name} has received your task."
                ),
            },

            Task.BoxStatus.PROCESSING: {
                "title": "Preparing your task",
                "message": (
                    f"{box_name} is now preparing your task."
                ),
            },

            Task.BoxStatus.PRINTING: {
                "title": "Printing started",
                "message": (
                    f"Your document is now being printed at {box_name}."
                ),
            },

            Task.BoxStatus.WAITING_FOR_DEPOSIT: {
                "title": "Ready for collection",
                "message": (
                    f"Your printed document is ready for collection "
                    f"at {box_name}."
                ),
            },

            Task.BoxStatus.PACKAGE_STORED: {
                "title": "Package stored",
                "message": (
                    f"Your package has been securely stored at {box_name}."
                ),
            },

            Task.BoxStatus.COMPLETED: {
                "title": "Task completed",
                "message": (
                    "Your task has been completed successfully."
                ),
            },

            Task.BoxStatus.FAILED: {
                "title": "Task could not be completed",
                "message": (
                    f"{box_name} was unable to complete your task. "
                    "Please contact support if you need assistance."
                ),
            },
        }

        payload = messages.get(box_status)

        if not payload:
            return None

        payload = {
            **payload,
            "task_id": task.id,
            "task_type": task.task_type,
            "box_status": task.box_status,
            "box": {
                "id": task.box.id,
                "name": task.box.name,
            } if task.box else None,
        }

        session = (
            ConversationSession.objects
            .filter(task=task)
            .order_by("-id")
            .first()
        )

        if not session:
            return None

        return ConversationService._add_system_message(
            session,
            payload,
            message_type=ConversationMessage.MessageType.STATUS,
        )


    @staticmethod
    @transaction.atomic
    def _handle_document_payment(session):

        task = (
            Task.objects
            .select_for_update()
            .get(pk=session.task.pk)
        )

        if task.status != Task.Status.ACTIVE:
            raise ValidationError(
                "This stored print task is no longer active."
            )

        if not task.storage_until:
            raise ValidationError(
                "This task has no active storage period."
            )

        if timezone.now() >= task.storage_until:
            raise ValidationError(
                "The storage period has ended."
            )

        pending_document = (
            PendingPrintDocument.objects
            .select_for_update()
            .filter(task=task)
            .order_by("-created_at")
            .first()
        )

        if not pending_document:
            raise ValidationError(
                "There is no document waiting for payment."
            )

        # -----------------------------------------
        # Re-check 100-page limit
        # -----------------------------------------

        existing_pages = sum(
            document.page_count * document.copies
            for document in task.documents.all()
        )

        pending_pages = sum(
            document.page_count * document.copies
            for document in task.pending_documents.exclude(
                id=pending_document.id
            )
        )

        new_pages = (
            pending_document.page_count
            * pending_document.copies
        )

        total_pages = (
            existing_pages
            + pending_pages
            + new_pages
        )

        if total_pages > 100:
            raise ValidationError(
                "Adding this document would exceed "
                "the 100 printed-page limit."
            )

        amount = pending_document.amount

        # -----------------------------------------
        # Check wallet
        # -----------------------------------------

        balance = WalletService.get_balance(
            task.user
        )

        if balance < amount:
            raise ValidationError(
                "Insufficient wallet balance."
            )

        # -----------------------------------------
        # Record payment action
        # -----------------------------------------

        ConversationService._add_user_message(
            session,
            action="pay",
            label="Pay",
        )

        # -----------------------------------------
        # Charge ONLY the new document
        # -----------------------------------------

        WalletService.charge(
            user=task.user,
            amount=amount,
            task=task,
        )

        # -----------------------------------------
        # Convert pending document into
        # permanent PrintDocument
        # -----------------------------------------

        document = PrintDocument.objects.create(
            task=task,
            file=pending_document.file,
            original_filename=(
                pending_document.original_filename
            ),
            copies=pending_document.copies,
            page_count=pending_document.page_count,
            print_settings=(
                pending_document.print_settings
            ),
            amount=pending_document.amount,
        )

        # -----------------------------------------
        # Delete temporary record
        # -----------------------------------------

        pending_document.delete()

        # -----------------------------------------
        # Send updated task to Firestore
        # -----------------------------------------

        from ..firebase_service import (
            create_task_in_firestore,
        )

        create_task_in_firestore(task)

        # -----------------------------------------
        # Conversation message
        # -----------------------------------------

        ConversationService._add_system_message(
            session,
            {
                "title": "Document added successfully",
                "message": (
                    f"'{document.original_filename}' "
                    "has been added to your stored print task.\n\n"
                    f"Printing charge: ₦{amount:.2f}\n\n"
                    "No additional storage charge was applied "
                    "because your existing storage period is "
                    "still active."
                ),
                "document_id": document.id,
                "filename": document.original_filename,
                "page_count": document.page_count,
                "copies": document.copies,
                "amount": str(amount),
                "storage_until": (
                    task.storage_until.isoformat()
                ),
            },
            message_type=(
                ConversationMessage.MessageType.STATUS
            ),
        )

        # -----------------------------------------
        # Return to active storage conversation
        # -----------------------------------------

        session.current_state = (
            ConversationSession.State.ACTIVE_STORAGE
        )

        session.save(
            update_fields=[
                "current_state",
            ]
        )

        return session


    @staticmethod
    def _handle_edit(session):
        ConversationService._add_user_message(
            session,
            action="edit",
            label="Edit",
        )

        ConversationService._add_system_message(
            session,
            {
                "title": "Edit request",
                "message": (
                    "No problem. Return to the previous screen to update your "
                    "printing or storage details."
                ),
            },
            message_type=ConversationMessage.MessageType.STATUS,
        )

        return session

    @staticmethod
    def _handle_topup(session):
        task = session.task
        wallet_balance = WalletService.get_balance(task.user)
        required = task.amount - wallet_balance

        ConversationService._add_user_message(
            session,
            action="topup",
            label="Top Up Wallet",
        )

        ConversationService._add_system_message(
            session,
            {
                "title": "Wallet top-up required",
                "message": (
                    f"A wallet top-up of ₦{required:.2f} is required to complete "
                    "this payment. Once your wallet has been funded, you can return "
                    "here and continue with the payment."
                ),
            },
            message_type=ConversationMessage.MessageType.PAYMENT,
        )

        return session


    @staticmethod
    @transaction.atomic
    def prepare_document_payment(session, pending_document):
        task = session.task

        if task.task_type != Task.TaskType.STORED_PRINT:
            raise ValidationError(
                "Documents can only be added to stored print tasks."
            )

        if task.status != Task.Status.ACTIVE:
            raise ValidationError(
                "This task is no longer active."
            )

        if not task.storage_until:
            raise ValidationError(
                "This task does not have an active storage period."
            )

        if timezone.now() >= task.storage_until:
            raise ValidationError(
                "The storage period has ended."
            )

        # -----------------------------------------
        # Check the 100 printed-page limit
        # -----------------------------------------

        existing_printed_pages = sum(
            document.page_count * document.copies
            for document in task.documents.all()
        )

        pending_printed_pages = sum(
            document.page_count * document.copies
            for document in PendingPrintDocument.objects.filter(
                task=task
            )
            if document.id != pending_document.id
        )

        new_printed_pages = (
            pending_document.page_count
            * pending_document.copies
        )

        total_printed_pages = (
            existing_printed_pages
            + pending_printed_pages
            + new_printed_pages
        )

        if total_printed_pages > 100:
            raise ValidationError(
                "This document would exceed the 100 printed-page limit."
            )

        # -----------------------------------------
        # Record the user's action
        # -----------------------------------------

        ConversationService._add_user_message(
            session,
            action="add_document",
            label="Add Document",
        )

        # -----------------------------------------
        # Build payment review
        # -----------------------------------------

        storage_remaining = (
            task.storage_until - timezone.now()
        )

        content = {
            "title": "New document ready for payment",

            "message": (
                f"Your document "
                f"'{pending_document.original_filename}' "
                "is ready to be added to your stored print task."
            ),

            "document": {
                "pending_document_id": pending_document.id,
                "filename": pending_document.original_filename,
                "pages": pending_document.page_count,
                "copies": pending_document.copies,
                "total_printed_pages": new_printed_pages,
                "print_settings": (
                    pending_document.print_settings
                ),
            },

            "page_limit": {
                "limit": 100,
                "existing_printed_pages": (
                    existing_printed_pages
                ),
                "new_printed_pages": new_printed_pages,
                "total_printed_pages": total_printed_pages,
                "remaining_before_document": (
                    100 - existing_printed_pages
                ),
                "remaining_after_document": (
                    100 - total_printed_pages
                ),
            },

            "charges": [
                {
                    "label": "Printing",
                    "amount": str(
                        pending_document.amount
                    ),
                },
                {
                    "label": "Additional storage",
                    "amount": "0.00",
                },
            ],

            "total": str(
                pending_document.amount
            ),

            "storage_until": (
                task.storage_until.isoformat()
            ),

            "storage_seconds_remaining": int(
                storage_remaining.total_seconds()
            ),

            "notice": (
                "Your existing storage period remains "
                "unchanged. No additional storage charge "
                "is applied."
            ),
        }

        ConversationService._add_system_message(
            session,
            content,
            message_type=(
                ConversationMessage.MessageType.PAYMENT
            ),
        )

        session.current_state = (
            ConversationSession.State.DOCUMENT_REVIEW
        )

        session.save(
            update_fields=[
                "current_state",
            ]
        )

        return session

    @staticmethod
    @transaction.atomic
    def prepare_extension_payment(session, duration):
        task = session.task

        if task.status != Task.Status.ACTIVE:
            raise ValidationError(
                "This task is no longer active."
            )

        if task.task_type not in (
            Task.TaskType.STORED_PRINT,
            Task.TaskType.PACKAGE_STORAGE,
        ):
            raise ValidationError(
                "Storage extensions are only available for storage tasks."
            )

        if not task.storage_until:
            raise ValidationError(
                "This task does not have a storage period."
            )

        try:
            duration = int(duration)
        except (TypeError, ValueError):
            raise ValidationError(
                "Duration must be a whole number."
            )

        if duration < 1:
            raise ValidationError(
                "Duration must be at least 1."
            )

        now = timezone.now()
        previous_expiry = task.storage_until

        if task.task_type == Task.TaskType.STORED_PRINT:
            purchased_duration = timedelta(hours=duration)
        else:
            purchased_duration = timedelta(days=duration)

        if now > previous_expiry:
            elapsed = now - previous_expiry
            new_expiry = now + elapsed + purchased_duration
        else:
            elapsed = timedelta(0)
            new_expiry = previous_expiry + purchased_duration

        if task.task_type == Task.TaskType.STORED_PRINT:
            hourly_rate = (
                task.box.stored_print_hourly_price or Decimal("0.00")
            )

            extension_cost = hourly_rate * Decimal(duration)

        else:
            size = (task.task_data or {}).get("size")
            pricing = task.box.dropbox_pricing or {}

            try:
                daily_rate = Decimal(str(pricing[size]))
            except (KeyError, TypeError, ValueError):
                raise ValidationError(
                    "Storage pricing is not configured for this size."
                )

            extension_cost = daily_rate * Decimal(duration)

        task_data = task.task_data or {}

        task_data["pending_extension"] = {
            "duration": duration,
            "previous_expiry": previous_expiry.isoformat(),
            "requested_at": now.isoformat(),
            "elapsed_since_expiry_seconds": int(
                elapsed.total_seconds()
            ),
            "new_expiry": new_expiry.isoformat(),
            "amount": str(extension_cost),
        }

        task.task_data = task_data
        task.save(update_fields=["task_data"])

        ConversationService._add_user_message(
            session,
            action="extend",
            label="Extend Storage",
        )

        content = {
            "title": "Storage extension ready for payment",
            "message": (
                f"Your storage extension is ready for payment.\n\n"
                f"You are extending your storage by "
                f"{duration} "
                f"{'hour' if task.task_type == Task.TaskType.STORED_PRINT else 'day'}"
                f"{'s' if duration != 1 else ''}.\n\n"
                f"Extension cost: ₦{extension_cost:.2f}."
            ),
            "charges": [
                {
                    "label": (
                        f"{duration} hours storage"
                        if task.task_type == Task.TaskType.STORED_PRINT
                        else f"{duration} "
                            f"day{'s' if duration != 1 else ''} storage"
                    ),
                    "amount": str(extension_cost),
                }
            ],
            "total": str(extension_cost),
        }

        ConversationService._add_system_message(
            session,
            content,
            message_type=ConversationMessage.MessageType.PAYMENT,
        )

        session.current_state = (
            ConversationSession.State.EXTENSION_REVIEW
        )

        session.save(
            update_fields=["current_state"]
        )

        return session


    @staticmethod
    @transaction.atomic
    def _handle_extension_payment(session):
        task = (
            Task.objects
            .select_for_update()
            .get(pk=session.task.pk)
        )

        if task.status != Task.Status.ACTIVE:
            raise ValidationError(
                "This task is no longer active."
            )

        task_data = task.task_data or {}
        pending_extension = task_data.get(
            "pending_extension"
        )
        print("EXTENSION DEBUG pending_extension:", pending_extension)

        if not pending_extension:
            raise ValidationError(
                "There is no storage extension waiting for payment."
            )

        duration = int(
            pending_extension["duration"]
        )

        amount = Decimal(
            str(pending_extension["amount"])
        )

        # -----------------------------------------
        # Check wallet balance
        # -----------------------------------------

        balance = WalletService.get_balance(
            task.user
        )

        if balance < amount:
            raise ValidationError(
                "Insufficient wallet balance."
            )

        # -----------------------------------------
        # Recalculate expiry at payment time
        # -----------------------------------------
        #
        # This is important because the user may have
        # waited between seeing the review and paying.
        #
        # If storage is still active:
        #
        #     old expiry + purchased duration
        #
        # If storage has expired:
        #
        #     now
        #     + elapsed time since expiry
        #     + purchased duration
        #
        # Example:
        #
        # Previous expiry: 10:00
        # Payment:         14:00
        # Purchase:        24 hours
        #
        # New expiry:      next day 18:00
        #
        # -----------------------------------------

        now = timezone.now()
        previous_expiry = task.storage_until

        if not previous_expiry:
            raise ValidationError(
                "This task does not have a storage expiry."
            )

        if task.task_type == Task.TaskType.STORED_PRINT:
            purchased_duration = timedelta(hours=duration)
        else:
            purchased_duration = timedelta(days=duration)

        if now > previous_expiry:
            elapsed = now - previous_expiry

            new_expiry = (
                now
                + elapsed
                + purchased_duration
            )

        else:
            new_expiry = (
                previous_expiry
                + purchased_duration
            )

        # -----------------------------------------
        # Record payment action
        # -----------------------------------------

        ConversationService._add_user_message(
            session,
            action="pay",
            label="Pay",
        )

        # -----------------------------------------
        # Charge wallet
        # -----------------------------------------

        WalletService.charge(
            user=task.user,
            amount=amount,
            task=task,
        )

        # -----------------------------------------
        # Update storage expiry
        # -----------------------------------------

        task.storage_until = new_expiry

        task_data.pop(
            "pending_extension",
            None,
        )

        task.task_data = task_data

        task.save(
            update_fields=[
                "storage_until",
                "task_data",
                "updated_at",
            ]
        )

        # -----------------------------------------
        # Update Firestore
        # -----------------------------------------

        from ..firebase_service import (
            create_task_in_firestore,
        )

        create_task_in_firestore(task)

        # -----------------------------------------
        # Conversation message
        # -----------------------------------------

        unit = "hour" if task.task_type == Task.TaskType.STORED_PRINT else "day"

        message = (
            f"Your storage has been extended by "
            f"{duration} {unit}"
            f"{'s' if duration != 1 else ''}.\n\n"
            f"New expiry: "
            f"{new_expiry.strftime('%A, %d %B at %I:%M %p')}."
        )

        ConversationService._add_system_message(
            session,
            {
                "title": "Storage extended successfully",
                "message": message,
                "amount": str(amount),
                "duration": duration,
                "storage_until": new_expiry.isoformat(),
            },
            message_type=(
                ConversationMessage.MessageType.STATUS
            ),
        )

        # -----------------------------------------
        # Return to active storage
        # -----------------------------------------

        session.current_state = (
            ConversationSession.State.ACTIVE_STORAGE
        )

        session.save(
            update_fields=[
                "current_state",
            ]
        )

        return session


    @staticmethod
    @transaction.atomic
    def _handle_change_access_code(session):
        task = (
            Task.objects
            .select_for_update()
            .get(pk=session.task.pk)
        )

        if task.task_type != Task.TaskType.PACKAGE_STORAGE:
            raise ValidationError(
                "Access codes can only be changed for package storage tasks."
            )

        if task.status != Task.Status.ACTIVE:
            raise ValidationError(
                "This task is no longer active."
            )

        if not task.storage_until:
            raise ValidationError(
                "This task does not have an active storage period."
            )

        if timezone.now() >= task.storage_until:
            raise ValidationError(
                "The storage period has ended."
            )

        if not task.cubby:
            raise ValidationError(
                "This task does not have an assigned cubby."
            )

        # Generate a new 6-digit access code.
        new_access_code = f"{randbelow(1_000_000):06d}"

        # Avoid accidentally generating the same code.
        while new_access_code == task.access_code:
            new_access_code = f"{randbelow(1_000_000):06d}"

        #old_access_code = task.access_code

        task.access_code = new_access_code

        # Update all unused access shares to mark them as used.
        PackageAccessShare.objects.filter(
            task=task,
            used_at__isnull=True,
            revoked_at__isnull=True,
        ).update(
            revoked_at=timezone.now()
        )
        task.save(
            update_fields=[
                "access_code",
                "updated_at",
            ]
        )

        # Record the user's action.
        ConversationService._add_user_message(
            session,
            action="change_access_code",
            label="Change Access Code",
        )

        # Update Firestore.
        from ..firebase_service import create_task_in_firestore

        create_task_in_firestore(task)

        # Tell the user the new code.
        ConversationService._add_system_message(
            session,
            {
                "title": "Access code changed",
                "message": (
                    "Your package storage access code has been "
                    "changed successfully.\n\n"
                    f"New access code: {new_access_code}\n\n"
                    "Your storage expiry remains unchanged."
                ),
                "access_code": new_access_code,
                "storage_until": task.storage_until.isoformat(),
                "expires_at": task.storage_until.isoformat(),
            },
            message_type=ConversationMessage.MessageType.STATUS,
        )

        return session


    @staticmethod
    @transaction.atomic
    def _handle_share_access(session):
        task = (
            Task.objects
            .select_for_update()
            .select_related("box", "cubby")
            .get(pk=session.task.pk)
        )

        if task.task_type != Task.TaskType.PACKAGE_STORAGE:
            raise ValidationError(
                "Access sharing is only available for package storage tasks."
            )

        if task.status != Task.Status.ACTIVE:
            raise ValidationError(
                "This task is no longer active."
            )

        if not task.storage_until:
            raise ValidationError(
                "This task does not have an active storage period."
            )

        now = timezone.now()

        if now >= task.storage_until:
            raise ValidationError(
                "The storage period has expired."
            )

        if not task.cubby:
            raise ValidationError(
                "This task does not have an assigned cubby."
            )

        if not task.access_code:
            raise ValidationError(
                "This task does not have an access code."
            )

        # Generate a high-entropy secret token.
        raw_token = secrets.token_urlsafe(32)

        # Store only the SHA-256 hash.
        token_hash = hashlib.sha256(
            raw_token.encode("utf-8")
        ).hexdigest()

        # Invalidate any previous unused share links.
        PackageAccessShare.objects.filter(
            task=task,
            used_at__isnull=True,
            revoked_at__isnull=True,
        ).update(
            revoked_at=now
        )

        PackageAccessShare.objects.create(
            task=task,
            token_hash=token_hash,
            expires_at=task.storage_until,
        )

        ConversationService._add_user_message(
            session,
            action="share_access",
            label="Share Access",
        )

        storage_remaining = (
            task.storage_until - now
        )

        content = {
            "title": "Access link created",
            "message": (
                "A one-time access link has been created. "
                "Anyone with this link can use it once to view "
                "the package access information."
            ),
            "share_token": raw_token,
            "expires_at": task.storage_until.isoformat(),
            "storage_seconds_remaining": int(
                storage_remaining.total_seconds()
            ),
        }

        ConversationService._add_system_message(
            session,
            content,
            message_type=ConversationMessage.MessageType.STATUS,
        )

        return session


    @staticmethod
    @transaction.atomic
    def redeem_package_access(raw_token):
        if not raw_token:
            raise ValidationError(
                "Invalid access link."
            )

        token_hash = hashlib.sha256(
            raw_token.encode("utf-8")
        ).hexdigest()

        try:
            share = (
                PackageAccessShare.objects
                .select_for_update()
                .select_related(
                    "task",
                    "task__box",
                    "task__cubby",
                )
                .get(token_hash=token_hash)
            )
        except PackageAccessShare.DoesNotExist:
            raise ValidationError(
                "This access link is invalid."
            )

        if share.used_at:
            raise ValidationError(
                "This access link has already been used."
            )
        if share.revoked_at:
            raise ValidationError(
                "This access link is no longer valid."
            )

        now = timezone.now()

        if now >= share.expires_at:
            raise ValidationError(
                "This access link has expired."
            )

        task = share.task

        if task.task_type != Task.TaskType.PACKAGE_STORAGE:
            raise ValidationError(
                "This access link is not valid for package storage."
            )

        if task.status != Task.Status.ACTIVE:
            raise ValidationError(
                "This storage task is no longer active."
            )

        if not task.storage_until:
            raise ValidationError(
                "This storage task has no active expiry."
            )

        if now >= task.storage_until:
            raise ValidationError(
                "The storage period has expired."
            )

        if not task.cubby:
            raise ValidationError(
                "This storage task has no assigned cubby."
            )

        if not task.access_code:
            raise ValidationError(
                "This storage task has no access code."
            )

        # Mark the link as used BEFORE returning the sensitive information.
        share.used_at = now
        share.save(update_fields=["used_at"])

        seconds_remaining = int(
            (task.storage_until - now).total_seconds()
        )

        return {
            "box": {
                "id": task.box.id,
                "name": task.box.name,
                "latitude": task.box.latitude,
                "longitude": task.box.longitude,
            },
            "cubby": {
                "id": task.cubby.id,
                "code": task.cubby.code,
                "type": task.cubby.cubby_type,
            },
            "access_code": task.access_code,
            "expires_at": task.storage_until.isoformat(),
            "seconds_remaining": max(seconds_remaining, 0),
        }


    @staticmethod
    @transaction.atomic
    def _handle_withdrawal(session):
        task = session.task

        ConversationService._add_user_message(
            session,
            action="withdraw",
            label="Withdraw Item",
        )

        if task.status != Task.Status.ACTIVE:
            raise ValidationError("This task is not currently active.")

        task.status = Task.Status.WITHDRAWN
        task.completed_at = timezone.now()
        task.visible_until = timezone.now() + timedelta(hours=24)
        task.save()

        if task.cubby is not None:
            CubbyService.release_cubby(task.cubby)

        ConversationService._add_system_message(
            session,
            (
                "Your withdrawal has been recorded successfully.\n"
                "The cubby is now available for new tasks."
            ),
        )

        ConversationService._complete_conversation(session)

        return session


    @staticmethod
    @transaction.atomic
    def _handle_review_cancel(session):
        task = (
            Task.objects
            .select_for_update()
            .get(pk=session.task.pk)
        )

        if session.current_state == (
            ConversationSession.State.DOCUMENT_REVIEW
        ):
            PendingPrintDocument.objects.filter(
                task=task
            ).delete()

            message = {
                "title": "Document addition cancelled",
                "message": (
                    "The new document was not added. "
                    "Your existing stored print task "
                    "remains active."
                ),
            }

        elif session.current_state == (
            ConversationSession.State.EXTENSION_REVIEW
        ):
            task_data = task.task_data or {}

            task_data.pop(
                "pending_extension",
                None,
            )

            task.task_data = task_data

            task.save(
                update_fields=[
                    "task_data",
                    "updated_at",
                ]
            )

            message = {
                "title": "Storage extension cancelled",
                "message": (
                    "The storage extension was cancelled. "
                    "Your existing storage task remains active "
                    "with its current expiry."
                ),
            }

        else:
            raise ValidationError(
                "There is no payment review to cancel."
            )

        ConversationService._add_user_message(
            session,
            action="cancel",
            label="Cancel",
        )

        ConversationService._add_system_message(
            session,
            message,
            message_type=(
                ConversationMessage.MessageType.STATUS
            ),
        )

        session.current_state = (
            ConversationSession.State.ACTIVE_STORAGE
        )

        session.save(
            update_fields=[
                "current_state",
            ]
        )

        return session

    @staticmethod
    @transaction.atomic
    def _handle_cancel(session):
        task = session.task

        ConversationService._add_user_message(
            session,
            action="cancel",
            label="Cancel",
        )

        if task.status == Task.Status.PENDING and task.cubby is not None:
            CubbyService.release_cubby(task.cubby)

        task.status = Task.Status.CANCELLED
        task.completed_at = timezone.now()
        task.save()

        ConversationService._add_system_message(
            session,
            {
                "title": "Request cancelled",
                "message": (
                    "Your request has been cancelled successfully. "
                    "You can start a new printing or storage request at any time."
                ),
            },
            message_type=ConversationMessage.MessageType.STATUS,
        )

        ConversationService._complete_conversation(session)

        PendingPrintDocument.objects.filter(
            task=session.task
        ).delete()

        return session

    @staticmethod
    def _complete_conversation(session):
        session.current_state = ConversationSession.State.COMPLETED
        session.is_active = False
        session.ended_at = timezone.now()
        session.save(
            update_fields=[
                "current_state",
                "is_active",
                "ended_at",
            ]
        )

    @staticmethod
    def get_conversation_data(session):
        task = session.task

        return {
            "conversation_id": session.id,
            "task_id": task.id,
            "state": session.current_state,
            "is_active": session.is_active,

            "box": {
                "id": task.box.id,
                "name": task.box.name,
            } if task.box else None,

            "cubby": {
                "id": task.cubby.id,
                "code": task.cubby.code,
            } if task.cubby else None,

            "messages": [
                {
                    "id": msg.id,
                    "sender": msg.sender,
                    "content": msg.content,
                    "created_at": msg.created_at,
                }
                for msg in session.messages.all()
            ],

            "available_actions": (
                ConversationService.get_available_actions(session)
                if session.is_active
                else []
            ),
        }
