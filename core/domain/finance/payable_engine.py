"""M5.1 payable lifecycle and settlement-backed disbursement orchestration."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from .obligation_engine import TransactionalObligationEngine
from .payable_contract import ApplyDisbursementCommand, DisbursePayablesCommand, OpenPayableCommand, PayableLifecycleError
from .payable_repository import PayableLifecycleRepository
from .value_application_engine import TransactionalValueApplicationEngine


class TransactionalPayableLifecycleEngine:
    obligations = TransactionalObligationEngine
    values = TransactionalValueApplicationEngine
    repository = PayableLifecycleRepository

    @classmethod
    def open(cls, session, command: OpenPayableCommand):
        return cls.obligations.create(session, command.obligation)

    @classmethod
    def _validate_targets(cls, session, application, *, payer: UUID, payee: UUID, currency: str, lock: bool):
        for item in sorted(application.applications, key=lambda selected: str(selected.obligation_public_id)):
            payable = cls.repository.payable_authority(
                session, tenant_id=application.tenant_id, public_id=item.obligation_public_id, lock=lock
            )
            if payable["debtor_party_id"] != payer:
                raise PayableLifecycleError("payer_mismatch", "disbursement owner must be the payable debtor")
            if payable["creditor_party_id"] != payee:
                raise PayableLifecycleError("payee_mismatch", "disbursement payee must be the payable creditor")
            if payable["currency_code"] != currency:
                raise PayableLifecycleError("currency_mismatch", "disbursement and payable currencies must match")

    @classmethod
    def disburse(cls, session, command: DisbursePayablesCommand):
        with session.begin_nested():
            source = command.disbursement.value_source
            settlement = cls.repository.settlement_authority(
                session, tenant_id=source.tenant_id, public_id=source.payment_settlement_public_id, lock=True
            )
            if settlement["settlement_direction"] != "outgoing" or settlement["settlement_state"] != "confirmed":
                raise PayableLifecycleError(
                    "confirmed_outgoing_settlement_required", "disbursement requires confirmed outgoing settlement"
                )
            if settlement["organization_unit_id"] != source.organization_unit_id:
                raise PayableLifecycleError("organization_mismatch", "settlement and disbursement organization must match")
            if settlement["currency_code"] != source.currency_code:
                raise PayableLifecycleError("currency_mismatch", "settlement and disbursement currencies must match")
            available = Decimal(settlement["gross_amount"]) - Decimal(settlement["reversed_amount"])
            if source.source_amount != available:
                raise PayableLifecycleError(
                    "settlement_amount_mismatch", "disbursement amount must equal active outgoing settlement gross"
                )
            cls._validate_targets(
                session, command.disbursement.application_batch, payer=source.owner_party_id,
                payee=command.payee_party_id, currency=source.currency_code, lock=False,
            )
            return cls.values.receive(session, command.disbursement)

    @classmethod
    def apply_existing(cls, session, command: ApplyDisbursementCommand):
        with session.begin_nested():
            source = cls.repository.disbursement_authority(
                session, tenant_id=command.application.tenant_id,
                public_id=command.application.value_source_public_id, lock=True,
            )
            cls._validate_targets(
                session, command.application, payer=UUID(str(source["owner_party_id"])),
                payee=UUID(str(source["payee_party_id"])), currency=source["currency_code"], lock=True,
            )
            return cls.values.apply_existing(session, command.application)
