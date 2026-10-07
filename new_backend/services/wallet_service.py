import uuid
from decimal import Decimal

from django.db import transaction
from django.core.exceptions import ValidationError

from ..models import WalletTransaction


class WalletService:

    @staticmethod
    @transaction.atomic
    def charge(user, amount, task=None):
        wallet = (
    user.wallet.__class__.objects
    .select_for_update()
    .get(pk=user.wallet.pk)
    )

        amount = Decimal(str(amount))

        if wallet.balance < amount:
            raise ValidationError(
                'Insufficient wallet balance.'
            )

        before = wallet.balance

        wallet.balance -= amount
        wallet.save()

        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=WalletTransaction.TransactionType.PAYMENT,
            amount=amount,
            balance_before=before,
            balance_after=wallet.balance,
            reference=f'PAY-{uuid.uuid4().hex[:12].upper()}',
            description=(
                f'Payment for '
                f'{task.get_task_type_display()}'
                if task
                else 'Wallet payment'
            ),
            task=task,
        )

        return wallet

    @staticmethod
    @transaction.atomic
    def deposit(user, amount, reference, description='Wallet deposit'):
        wallet = (
            user.wallet.__class__.objects
            .select_for_update()
            .get(pk=user.wallet.pk)
        )

        # Prevent the same deposit/reference from being credited twice.
        existing_transaction = WalletTransaction.objects.filter(
            reference=reference
        ).first()

        if existing_transaction:
            return wallet

        amount = Decimal(str(amount))

        before = wallet.balance

        wallet.balance += amount
        wallet.save(update_fields=['balance'])

        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=WalletTransaction.TransactionType.DEPOSIT,
            amount=amount,
            balance_before=before,
            balance_after=wallet.balance,
            reference=reference,
            description=description,
        )

        return wallet


    @staticmethod
    @transaction.atomic
    def refund(user, amount, task=None):
        wallet = user.wallet

        amount = Decimal(str(amount))

        before = wallet.balance

        wallet.balance += amount
        wallet.save()

        WalletTransaction.objects.create(
            wallet=wallet,
            transaction_type=WalletTransaction.TransactionType.REFUND,
            amount=amount,
            balance_before=before,
            balance_after=wallet.balance,
            reference=f'REF-{uuid.uuid4().hex[:12].upper()}',
            description='Wallet refund',
            task=task,
        )

        return wallet

    @staticmethod
    def get_balance(user):
        return user.wallet.balance