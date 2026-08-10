"""Atomic M5.4 refund, return, reversal, chargeback, and write-off orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from .atomic_posting_engine import AtomicPostedFinancialEventEngine, PostedFinancialEventResult
from .correction_contract import CorrectionLifecycleError, RecognizeChargebackCommand, RecognizeCommercialReturnCommand, RecognizeRefundCommand, ReverseFinancialFactCommand, WriteOffObligationCommand
from .correction_repository import CorrectionLifecycleRepository
from .event_contract import CanonicalFinancialEventCommand
from .obligation_balance_service import ObligationBalanceService
from .obligation_engine import ObligationCommandResult, TransactionalObligationEngine
from .provider_financial_engine import ProviderFinancialResult, TransactionalProviderFinancialEngine


@dataclass(frozen=True)
class WriteOffResult:
    posted_event: PostedFinancialEventResult
    transitioned_obligation: ObligationCommandResult

    @property
    def replayed(self): return self.posted_event.replayed and self.transitioned_obligation.replayed


class TransactionalCorrectionLifecycleEngine:
    repository = CorrectionLifecycleRepository
    posting = AtomicPostedFinancialEventEngine

    @classmethod
    def recognize_refund(cls, session, command: RecognizeRefundCommand):
        context = command.context
        with session.begin_nested():
            cls.repository.source_authority(session, tenant_id=context.tenant_id, organization_unit_id=context.organization_unit_id, source_record_id=context.source_record_id, expected_kind="payment_refund", document=context.document)
            original, refund = cls.repository.refund_authority(session, tenant_id=context.tenant_id, original_public_id=command.original_settlement_public_id, refund_public_id=command.refund_settlement_public_id)
            if original["settlement_state"] != "confirmed" or original["settlement_direction"] != "incoming": raise CorrectionLifecycleError("invalid_refund_original", "refund original must be a confirmed incoming settlement")
            if refund["settlement_state"] != "confirmed" or refund["settlement_direction"] != "outgoing": raise CorrectionLifecycleError("invalid_refund_evidence", "refund evidence must be a confirmed outgoing settlement")
            if original["organization_unit_id"] != context.organization_unit_id or refund["organization_unit_id"] != context.organization_unit_id or original["currency_code"] != context.currency_code or refund["currency_code"] != context.currency_code: raise CorrectionLifecycleError("refund_scope_mismatch", "refund settlement scope or currency differs")
            if Decimal(refund["gross_amount"]) != context.amount: raise CorrectionLifecycleError("refund_amount_mismatch", "refund event amount must equal outgoing settlement gross")
            if cls.repository.previous_refunds(session, tenant_id=context.tenant_id, original_public_id=command.original_settlement_public_id) + context.amount > Decimal(original["gross_amount"]) - Decimal(original["reversed_amount"]): raise CorrectionLifecycleError("refund_capacity_exceeded", "refund capacity exceeds active original settlement")
            return cls.posting.emit_and_post(session, cls._event(context, "REFUND_SETTLED", "settlement_out", {"refund_reason": {"code": command.refund_reason}}, "customer_refund", source_operational_account_id=int(refund["operational_account_id"]), metadata={"original_settlement_public_id": str(command.original_settlement_public_id), "refund_settlement_public_id": str(command.refund_settlement_public_id)}))

    @classmethod
    def recognize_return(cls, session, command: RecognizeCommercialReturnCommand):
        context = command.context
        with session.begin_nested():
            cls.repository.source_authority(session, tenant_id=context.tenant_id, organization_unit_id=context.organization_unit_id, source_record_id=context.source_record_id, expected_kind="commercial_adjustment", document=context.document)
            original = cls.repository.event_authority(session, tenant_id=context.tenant_id, public_id=command.original_event_public_id)
            return cls.posting.emit_and_post(session, cls._event(context, "COMMERCIAL_RETURN_RECOGNIZED", "correction", {"return_reason": {"code": command.return_reason}}, "commercial_return", original_event_id=int(original["id"]), metadata={"original_event_public_id": str(command.original_event_public_id)}))

    @classmethod
    def reverse_fact(cls, session, command: ReverseFinancialFactCommand):
        context = command.context
        with session.begin_nested():
            cls.repository.source_authority(session, tenant_id=context.tenant_id, organization_unit_id=context.organization_unit_id, source_record_id=context.source_record_id, expected_kind="financial_event_reversal", document=context.document)
            original = cls.repository.event_authority(session, tenant_id=context.tenant_id, public_id=command.original_event_public_id)
            return cls.posting.emit_and_post(session, cls._event(context, "FINANCIAL_FACT_REVERSED", "correction", {"reversal_reason": {"code": command.reversal_reason}}, "inverse_original_fact", source_operational_account_id=original["target_operational_account_id"], target_operational_account_id=original["source_operational_account_id"], original_event_id=int(original["id"]), metadata={"original_event_public_id": str(command.original_event_public_id)}))

    @classmethod
    def write_off(cls, session, command: WriteOffObligationCommand):
        context = command.context
        with session.begin_nested():
            cls.repository.source_authority(session, tenant_id=context.tenant_id, organization_unit_id=context.organization_unit_id, source_record_id=context.source_record_id, expected_kind="financial_obligation_adjustment", document=context.document)
            obligation = cls.repository.obligation_authority(session, tenant_id=context.tenant_id, public_id=command.obligation_public_id)
            balance = ObligationBalanceService.get(session, tenant_id=context.tenant_id, obligation_public_id=command.obligation_public_id)
            if balance.outstanding_amount != context.amount: raise CorrectionLifecycleError("writeoff_amount_mismatch", "write-off amount must equal exact outstanding obligation")
            expected_role = "receivable" if obligation["obligation_type"] in {"trade_receivable", "customer_receivable"} else "payable"
            if command.obligation_role != expected_role: raise CorrectionLifecycleError("writeoff_role_mismatch", "write-off role does not match obligation type")
            posted = cls.posting.emit_and_post(session, cls._event(context, "OBLIGATION_WRITTEN_OFF", "correction", {"obligation_role": {"code": command.obligation_role}, "writeoff_reason": {"code": command.writeoff_reason}}, "receivable_writeoff" if command.obligation_role == "receivable" else "payable_forgiveness", metadata={"obligation_public_id": str(command.obligation_public_id)}))
            transitioned = TransactionalObligationEngine.transition(session, command.transition)
            return WriteOffResult(posted, transitioned)

    @staticmethod
    def recognize_chargeback(session, command: RecognizeChargebackCommand) -> ProviderFinancialResult:
        metadata = command.component.evidence_payload
        if metadata.get("document_type") != command.document.document_type or metadata.get("document_number") != command.document.document_number or command.component.evidence_hash != command.document.evidence_hash: raise CorrectionLifecycleError("chargeback_document_mismatch", "chargeback component does not preserve correction document evidence")
        return TransactionalProviderFinancialEngine.create(session, command.component)

    @staticmethod
    def _event(context, event_type, economic_role, classification, profile, *, source_operational_account_id=None, target_operational_account_id=None, original_event_id=None, metadata=None):
        document = context.document
        return CanonicalFinancialEventCommand(public_id=context.event_public_id, tenant_id=context.tenant_id, organization_unit_id=context.organization_unit_id, event_type_code=event_type, event_version=1, amount=context.amount, currency_code=context.currency_code, economic_role=economic_role, source_operational_account_id=source_operational_account_id, target_operational_account_id=target_operational_account_id, source_record_id=context.source_record_id, original_event_id=original_event_id, occurred_at=context.occurred_at, business_date=context.business_date, calendar_policy_version=context.calendar_policy_version, idempotency_scope=context.idempotency_scope, idempotency_key=str(context.event_public_id), correlation_id=context.correlation_id, classification_snapshot=classification, posting_context={"posting_profile_code": profile}, metadata={**context.metadata, **(metadata or {}), "document_type": document.document_type, "document_number": document.document_number}, actor_user_id=context.actor_user_id, actor_service=context.actor_service, evidence_hash=document.evidence_hash)
