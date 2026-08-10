"""M5.0 orchestration over frozen obligation, allocation, and aging authority."""

from __future__ import annotations

from decimal import Decimal

from .obligation_aging_service import ObligationAgingService
from .obligation_engine import TransactionalObligationEngine
from .receivable_contract import (
    AgeReceivablesCommand,
    ApplyCustomerValueCommand,
    IssueCustomerValueCommand,
    OpenReceivableCommand,
    ReceiveReceivablePaymentCommand,
    ReceivableLifecycleError,
)
from .receivable_repository import ReceivableLifecycleRepository
from .value_application_engine import TransactionalValueApplicationEngine


class TransactionalReceivableLifecycleEngine:
    obligations = TransactionalObligationEngine
    values = TransactionalValueApplicationEngine
    repository = ReceivableLifecycleRepository
    aging = ObligationAgingService

    @classmethod
    def open(cls, session, command: OpenReceivableCommand):
        return cls.obligations.create(session, command.obligation)

    @classmethod
    def receive_payment(cls, session, command: ReceiveReceivablePaymentCommand):
        with session.begin_nested():
            customer = command.receipt.value_source.owner_party_id
            currency = command.receipt.value_source.currency_code
            for application in sorted(
                command.receipt.application_batch.applications,
                key=lambda item: str(item.obligation_public_id),
            ):
                receivable = cls.repository.receivable_authority(
                    session,
                    tenant_id=command.receipt.value_source.tenant_id,
                    public_id=application.obligation_public_id,
                    lock=False,
                )
                if receivable["debtor_party_id"] != customer:
                    raise ReceivableLifecycleError(
                        "customer_mismatch", "payment owner must be the receivable debtor"
                    )
                if receivable["currency_code"] != currency:
                    raise ReceivableLifecycleError(
                        "currency_mismatch", "payment and receivable currencies must match"
                    )
            return cls.values.receive(session, command.receipt)

    @classmethod
    def issue_customer_value(cls, session, command: IssueCustomerValueCommand):
        return cls.values.allocation_engine.create_value_source(session, command.value_source)

    @classmethod
    def apply_customer_value(cls, session, command: ApplyCustomerValueCommand):
        with session.begin_nested():
            source = cls.repository.customer_value_authority(
                session,
                tenant_id=command.application.tenant_id,
                public_id=command.application.value_source_public_id,
                lock=True,
                allow_payment_residual=True,
            )
            for application in sorted(
                command.application.applications,
                key=lambda item: str(item.obligation_public_id),
            ):
                receivable = cls.repository.receivable_authority(
                    session,
                    tenant_id=command.application.tenant_id,
                    public_id=application.obligation_public_id,
                    lock=True,
                )
                if receivable["debtor_party_id"] != source["owner_party_id"]:
                    raise ReceivableLifecycleError(
                        "customer_mismatch", "customer value owner must be the receivable debtor"
                    )
                if receivable["currency_code"] != source["currency_code"]:
                    raise ReceivableLifecycleError(
                        "currency_mismatch", "customer value and receivable currencies must match"
                    )
            return cls.values.apply_existing(session, command.application)

    @classmethod
    def age(cls, session, command: AgeReceivablesCommand):
        summary = cls.aging.get(session, command.query)
        rows = tuple(
            row
            for row in summary.rows
            if cls.repository.is_receivable(
                session,
                tenant_id=command.query.tenant_id,
                public_id=row.obligation_public_id,
            )
        )
        totals = {bucket.code: Decimal("0") for bucket in command.query.policy.buckets}
        for row in rows:
            totals[row.bucket_code] += row.outstanding_amount
        currencies = {row.currency_code for row in rows}
        return summary.__class__(
            summary.tenant_id,
            summary.as_of,
            summary.as_of_business_date,
            summary.policy_code,
            summary.policy_version,
            rows,
            totals,
            next(iter(currencies)) if len(currencies) == 1 else None,
        )
