"""Atomic M6.1 transfer and compensating-reversal orchestration."""

from __future__ import annotations

from .atomic_posting_engine import AtomicPostedFinancialEventEngine, PostedFinancialEventResult
from .event_contract import CanonicalFinancialEventCommand
from .operational_transfer_contract import (
    OperationalTransferValidationError,
    RecordOperationalTransferCommand,
    ReverseOperationalTransferCommand,
)
from .operational_transfer_repository import OperationalTransferRepository


class TransactionalOperationalTransferEngine:
    repository = OperationalTransferRepository
    posting_engine = AtomicPostedFinancialEventEngine

    @classmethod
    def record(cls, session, command: RecordOperationalTransferCommand) -> PostedFinancialEventResult:
        with session.begin_nested():
            existing = cls.repository.lock_transfer_by_idempotency(
                session, tenant_id=command.tenant_id,
                idempotency_scope=command.idempotency_scope, idempotency_key=command.idempotency_key,
            )
            if existing is None:
                source, destination = cls.repository.lock_accounts(
                    session, tenant_id=command.tenant_id,
                    source_public_id=command.source_operational_account_public_id,
                    destination_public_id=command.destination_operational_account_public_id,
                )
                cls._validate_pair(source, destination, command)
            else:
                source = cls.repository.account_by_id(session, tenant_id=command.tenant_id, account_id=existing.source_operational_account_id)
                destination = cls.repository.account_by_id(session, tenant_id=command.tenant_id, account_id=existing.target_operational_account_id)
                if source is None or destination is None:
                    raise OperationalTransferValidationError("idempotency_result_missing", "replayed transfer accounts are missing")
            event = CanonicalFinancialEventCommand(
                public_id=command.public_id, tenant_id=command.tenant_id,
                organization_unit_id=command.organization_unit_id,
                event_type_code="VALUE_TRANSFERRED", event_version=1, amount=command.amount,
                currency_code=command.currency_code, economic_role="transfer",
                source_operational_account_id=source.id, target_operational_account_id=destination.id,
                source_record_id=command.source_record_id, occurred_at=command.occurred_at,
                business_date=command.business_date, calendar_policy_version=command.calendar_policy_version,
                idempotency_scope=command.idempotency_scope, idempotency_key=command.idempotency_key,
                correlation_id=command.correlation_id, causation_id=command.causation_id,
                actor_user_id=command.actor_user_id, actor_service=command.actor_service,
                classification_snapshot={"transfer_purpose": {"code": command.transfer_purpose}},
                posting_context={"posting_profile_code": "operational_value_transfer"},
                evidence_hash=command.evidence_hash,
                metadata={**command.metadata, "transfer": {
                    "provenance": command.provenance, "value_at": command.value_at.isoformat(),
                    "request_fingerprint": command.request_fingerprint,
                    "evidence_payload": command.evidence_payload,
                    "source_account_public_id": str(source.public_id),
                    "destination_account_public_id": str(destination.public_id),
                }},
            )
            return cls.posting_engine.emit_and_post(session, event)

    @classmethod
    def reverse(cls, session, command: ReverseOperationalTransferCommand) -> PostedFinancialEventResult:
        with session.begin_nested():
            original = cls.repository.lock_original_transfer(
                session, tenant_id=command.tenant_id, public_id=command.original_transfer_public_id
            )
            if original is None:
                raise OperationalTransferValidationError("original_transfer_not_found", "original transfer is missing or cross-tenant")
            if original.organization_unit_id != command.organization_unit_id:
                raise OperationalTransferValidationError("original_transfer_scope_mismatch", "reversal organization differs from original")
            if original.currency_code != command.currency_code:
                raise OperationalTransferValidationError("original_transfer_currency_mismatch", "reversal currency differs from original")
            event = CanonicalFinancialEventCommand(
                public_id=command.public_id, tenant_id=command.tenant_id,
                organization_unit_id=command.organization_unit_id,
                event_type_code="FINANCIAL_FACT_REVERSED", event_version=1, amount=command.amount,
                currency_code=command.currency_code, economic_role="correction",
                source_operational_account_id=original.target_operational_account_id,
                target_operational_account_id=original.source_operational_account_id,
                source_record_id=command.source_record_id, original_event_id=original.id,
                occurred_at=command.occurred_at, business_date=command.business_date,
                calendar_policy_version=command.calendar_policy_version,
                idempotency_scope=command.idempotency_scope, idempotency_key=command.idempotency_key,
                correlation_id=command.correlation_id, causation_id=command.causation_id,
                actor_user_id=command.actor_user_id, actor_service=command.actor_service,
                classification_snapshot={"reversal_reason": {"code": command.reversal_reason}},
                posting_context={"posting_profile_code": "inverse_original_fact"},
                evidence_hash=command.evidence_hash,
                metadata={**command.metadata, "transfer_reversal": {
                    "provenance": "compensating_reversal", "value_at": command.value_at.isoformat(),
                    "request_fingerprint": command.request_fingerprint,
                    "evidence_payload": command.evidence_payload,
                    "original_transfer_public_id": str(original.public_id),
                }},
            )
            return cls.posting_engine.emit_and_post(session, event)

    @staticmethod
    def _validate_pair(source, destination, command) -> None:
        for account, side in ((source, "source"), (destination, "destination")):
            if account.organization_unit_id != command.organization_unit_id:
                raise OperationalTransferValidationError("account_organization_mismatch", f"{side} account organization differs")
            if account.currency_code != command.currency_code:
                raise OperationalTransferValidationError("account_currency_mismatch", f"{side} account currency differs")
            if account.aggregation_role != "leaf" or not account.active:
                raise OperationalTransferValidationError("account_not_eligible", f"{side} account must be an active leaf")
            for selected in (command.occurred_at, command.value_at):
                if selected < account.opened_at or (account.closed_at is not None and selected > account.closed_at):
                    raise OperationalTransferValidationError("outside_account_lifetime", f"{side} transfer time falls outside account lifetime")
