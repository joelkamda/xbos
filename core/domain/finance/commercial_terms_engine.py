"""Atomic M5.2 commercial component event and journal orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from .atomic_posting_engine import AtomicPostedFinancialEventEngine, PostedFinancialEventResult
from .commercial_terms_contract import CommercialTermComponent, RecognizeCommercialTermsCommand
from .commercial_terms_repository import CommercialTermsRepository
from .commercial_terms_service import CommercialTermsService, CommercialTermsSummary
from .event_contract import CanonicalFinancialEventCommand


EVENT_POLICY = {
    "discount": ("DISCOUNT_GRANTED", "recognition"),
    "complimentary": ("COMPLIMENTARY_GRANTED", "recognition"),
    "customer_service_fee": ("COMMERCIAL_REVENUE_RECOGNIZED", "recognition"),
    "output_tax": ("TAX_LIABILITY_RECOGNIZED", "recognition"),
}


@dataclass(frozen=True)
class CommercialTermsResult:
    summary: CommercialTermsSummary
    posted_components: tuple[PostedFinancialEventResult, ...]

    @property
    def replayed(self) -> bool:
        return all(item.replayed for item in self.posted_components)


class TransactionalCommercialTermsEngine:
    repository = CommercialTermsRepository
    posting = AtomicPostedFinancialEventEngine

    @classmethod
    def recognize(cls, session, command: RecognizeCommercialTermsCommand) -> CommercialTermsResult:
        with session.begin_nested():
            for component in sorted(command.components, key=lambda item: str(item.public_id)):
                cls.repository.source_authority(session, tenant_id=command.tenant_id, organization_unit_id=command.organization_unit_id, source_record_id=component.source_record_id, component_type=component.component_type)
            posted = tuple(cls.posting.emit_and_post(session, cls._event(command, component)) for component in command.components)
            return CommercialTermsResult(CommercialTermsService.summarize(command), posted)

    @staticmethod
    def _event(command: RecognizeCommercialTermsCommand, component: CommercialTermComponent):
        event_type, economic_role = EVENT_POLICY[component.component_type]
        metadata = {"commercial_component_type": component.component_type, "gross_sales_amount": str(command.gross_sales_amount), "customer_collectible_amount": str(command.customer_collectible_amount), **component.metadata}
        return CanonicalFinancialEventCommand(
            public_id=component.public_id, tenant_id=command.tenant_id, organization_unit_id=command.organization_unit_id,
            event_type_code=event_type, event_version=1, amount=component.amount, currency_code=command.currency_code,
            economic_role=economic_role, source_record_id=component.source_record_id, occurred_at=command.occurred_at,
            business_date=command.business_date, calendar_policy_version=command.calendar_policy_version,
            idempotency_scope=command.idempotency_scope, idempotency_key=str(component.public_id), correlation_id=command.correlation_id,
            classification_snapshot=component.classification_snapshot, posting_context={"posting_profile_code": component.posting_profile_code},
            metadata=metadata, actor_user_id=command.actor_user_id, actor_service=command.actor_service, evidence_hash=command.evidence_hash,
        )
