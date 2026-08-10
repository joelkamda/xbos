"""Atomic tip, commission, event, journal, and payable orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from .atomic_posting_engine import AtomicPostedFinancialEventEngine, PostedFinancialEventResult
from .event_contract import CanonicalFinancialEventCommand
from .obligation_engine import ObligationCommandResult, TransactionalObligationEngine
from .participant_earning_contract import RecognizeCommissionCommand, RecognizeTipCommand
from .participant_earning_repository import ParticipantEarningRepository


@dataclass(frozen=True)
class ParticipantEarningResult:
    posted_event: PostedFinancialEventResult
    payable: ObligationCommandResult | None

    @property
    def replayed(self) -> bool:
        return self.posted_event.replayed and (self.payable is None or self.payable.replayed)


class TransactionalParticipantEarningEngine:
    repository = ParticipantEarningRepository
    posting = AtomicPostedFinancialEventEngine
    obligations = TransactionalObligationEngine

    @classmethod
    def recognize_tip(cls, session, command: RecognizeTipCommand):
        with session.begin_nested():
            cls.repository.source_authority(session, tenant_id=command.context.tenant_id, organization_unit_id=command.context.organization_unit_id, source_record_id=command.context.source_record_id, allowed_kinds=("commercial_adjustment", "commercial_transaction_component"))
            posted = cls.posting.emit_and_post(session, cls._tip_event(command))
            payable = cls.obligations.create(session, command.payable) if command.payable is not None else None
            return ParticipantEarningResult(posted, payable)

    @classmethod
    def recognize_commission(cls, session, command: RecognizeCommissionCommand):
        with session.begin_nested():
            cls.repository.source_authority(session, tenant_id=command.context.tenant_id, organization_unit_id=command.context.organization_unit_id, source_record_id=command.context.source_record_id, allowed_kinds=("expense_transaction",))
            posted = cls.posting.emit_and_post(session, cls._commission_event(command))
            payable = cls.obligations.create(session, command.payable)
            return ParticipantEarningResult(posted, payable)

    @staticmethod
    def _base(context, *, event_type: str, classification, profile: str, metadata):
        return CanonicalFinancialEventCommand(
            public_id=context.event_public_id, tenant_id=context.tenant_id, organization_unit_id=context.organization_unit_id,
            event_type_code=event_type, event_version=1, amount=context.amount, currency_code=context.currency_code,
            economic_role="recognition", source_record_id=context.source_record_id, occurred_at=context.occurred_at,
            business_date=context.business_date, calendar_policy_version=context.calendar_policy_version,
            idempotency_scope=context.idempotency_scope, idempotency_key=str(context.event_public_id), correlation_id=context.correlation_id,
            classification_snapshot=classification, posting_context={"posting_profile_code": profile}, metadata={**context.metadata, **metadata},
            actor_user_id=context.actor_user_id, actor_service=context.actor_service, evidence_hash=context.evidence_hash,
        )

    @classmethod
    def _tip_event(cls, command: RecognizeTipCommand):
        beneficiary = str(command.beneficiary_party_id) if command.beneficiary_party_id else None
        return cls._base(command.context, event_type="TIP_RECOGNIZED", classification={"tip_policy": {"code": command.tip_policy}}, profile="tip_staff_liability" if command.tip_policy == "staff_beneficiary" else "tip_tenant_income", metadata={"earning_type": "tip", "beneficiary_party_id": beneficiary})

    @classmethod
    def _commission_event(cls, command: RecognizeCommissionCommand):
        basis = command.commission_basis
        return cls._base(command.context, event_type="EXPENSE_RECOGNIZED", classification={"expense_nature": {"code": "commission", "commission_code": command.commission_code}}, profile="expense_accrual", metadata={"earning_type": "commission", "beneficiary_party_id": str(command.beneficiary_party_id), "commission_code": command.commission_code, "basis_type": basis.basis_type, "basis_amount": str(basis.basis_amount), "rate_percent": str(basis.rate_percent)})
