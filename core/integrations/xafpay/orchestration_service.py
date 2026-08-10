"""Atomic XafPay initiation/callback orchestration over canonical M4 engines."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid5

from core.domain.finance.payment_attempt_contract import TransitionPaymentAttemptCommand
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_settlement_contract import (
    CreatePaymentSettlementCommand,
    TransitionPaymentSettlementCommand,
)
from core.domain.finance.payment_settlement_engine import TransactionalPaymentSettlementEngine

from .adapter import XafPayAdapter, XafPayTransport
from .contract import (
    ProcessXafPayCallbackCommand,
    RecordXafPayInitiationCommand,
    XafPayCallbackResult,
    XafPayInitiationRequest,
    XafPayInitiationResponse,
    XafPayIntegrationError,
)
from .repository import XafPayRepository


_TERMINAL = {"succeeded", "failed", "cancelled", "expired"}
_SUCCESS = {"succeeded", "paid", "confirmed"}
_STATUS_TARGET = {
    "created": "processing",
    "pending": "processing",
    "processing": "processing",
    "requires_action": "requires_action",
    "failed": "failed",
    "cancelled": "cancelled",
    "expired": "expired",
}


def _stable(kind: str, tenant_id: int, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"xbos:m45:{kind}:{tenant_id}:{key}")


class XafPayOrchestrationService:
    repository = XafPayRepository
    adapter = XafPayAdapter

    @classmethod
    def prepare_initiation(
        cls,
        session,
        *,
        tenant_id: int,
        organization_unit_id: int,
        payment_attempt_public_id: UUID,
        customer_phone: str,
        return_url: str,
        cancel_url: str,
        idempotency_key: str,
        description: str | None = None,
    ) -> XafPayInitiationRequest:
        authority = cls.repository.attempt_authority(
            session, tenant_id=tenant_id, public_id=payment_attempt_public_id, lock=False
        )
        if authority is None:
            raise XafPayIntegrationError("payment_attempt_not_found", "payment attempt does not exist")
        if authority["organization_unit_id"] != organization_unit_id:
            raise XafPayIntegrationError("payment_attempt_scope_mismatch", "payment attempt organization differs")
        if authority["orchestrator_code"] != "xafpay":
            raise XafPayIntegrationError("orchestrator_mismatch", "payment attempt is not assigned to XafPay")
        if authority["provider_code"] != "tranzak" or not authority["provider_account_active"]:
            raise XafPayIntegrationError("provider_account_unavailable", "active Tranzak provider authority is required")
        if authority["attempt_state"] not in {"pending", "processing", "requires_action"}:
            raise XafPayIntegrationError("attempt_not_initiable", "payment attempt is not initiable")
        return XafPayInitiationRequest(
            payment_attempt_public_id,
            Decimal(authority["attempted_amount"]),
            authority["currency_code"],
            authority["payment_rail_code"],
            customer_phone,
            return_url,
            cancel_url,
            idempotency_key,
            description,
        )

    @classmethod
    def initiate(
        cls,
        session,
        request: XafPayInitiationRequest,
        *,
        api_key: str,
        transport: XafPayTransport,
    ) -> XafPayInitiationResponse:
        """Perform the injected gateway call; recording remains an explicit transaction."""
        return cls.adapter.initiate(request, api_key=api_key, transport=transport)

    @classmethod
    def record_initiation(cls, session, command: RecordXafPayInitiationCommand):
        with session.begin_nested():
            authority = cls.repository.attempt_authority(
                session,
                tenant_id=command.tenant_id,
                public_id=command.payment_attempt_public_id,
                lock=True,
            )
            if authority is None or authority["organization_unit_id"] != command.organization_unit_id:
                raise XafPayIntegrationError("payment_attempt_not_found", "payment attempt does not exist in scope")
            gateway_reference = str(command.response.gateway_intent_id)
            if authority["external_attempt_reference"] not in {None, gateway_reference}:
                raise XafPayIntegrationError("gateway_identity_conflict", "gateway intent identity cannot be rewritten")
            current = authority
            if current["attempt_state"] == "pending":
                result = TransactionalPaymentAttemptEngine.transition(
                    session,
                    cls._attempt_transition(command, current, "processing", "xafpay_initiated", gateway_reference),
                )
                current = {
                    **current,
                    "attempt_state": result.payment_attempt.attempt_state,
                    "row_version": result.payment_attempt.row_version,
                }
            if command.response.payment_url and current["attempt_state"] == "processing":
                result = TransactionalPaymentAttemptEngine.transition(
                    session,
                    cls._attempt_transition(command, current, "requires_action", "xafpay_payment_url_ready", gateway_reference),
                )
                return result.payment_attempt
            refreshed = cls.repository.attempt_authority(
                session, tenant_id=command.tenant_id, public_id=command.payment_attempt_public_id
            )
            return refreshed

    @staticmethod
    def _attempt_transition(command, authority, state: str, reason: str, external_reference: str, *, evidence=None):
        terminal_evidence = evidence or ({"xafpay": reason} if state in {"succeeded", "failed", "expired"} else {})
        event_key = command.headers.get("x-xafpay-event-id") if hasattr(command, "headers") else external_reference
        return TransitionPaymentAttemptCommand(
            tenant_id=command.tenant_id,
            organization_unit_id=command.organization_unit_id,
            payment_attempt_public_id=UUID(str(authority["public_id"])),
            expected_row_version=int(authority["row_version"]),
            target_state=state,
            reason_code=reason,
            external_attempt_reference=external_reference,
            failure_code="xafpay_failed" if state == "failed" else None,
            evidence_payload=terminal_evidence,
            occurred_at=command.occurred_at if hasattr(command, "occurred_at") else command.received_at,
            business_date=command.business_date,
            calendar_policy_version=command.calendar_policy_version,
            correlation_id=command.correlation_id,
            actor_service=command.actor_service,
            source_component="xbos.xafpay",
            source_record_id=f"{reason}:{event_key}",
            idempotency_scope="m45.xafpay.attempt.transition",
            idempotency_key=f"{reason}:{event_key}",
            metadata={"integration": "xafpay"},
        )

    @classmethod
    def process_callback(cls, session, command: ProcessXafPayCallbackCommand) -> XafPayCallbackResult:
        event_reference = cls.adapter.callback_event_reference(command.headers)
        payload_hash = cls.adapter.payload_hash(command.raw_body)
        with session.begin_nested():
            provider = cls.repository.provider_account(
                session, tenant_id=command.tenant_id, public_id=command.provider_account_public_id
            )
            if provider is None or provider["organization_unit_id"] != command.organization_unit_id:
                raise XafPayIntegrationError("provider_scope_mismatch", "provider account does not exist in scope")
            if not provider["active"] or provider["provider_code"] != "tranzak":
                raise XafPayIntegrationError("provider_account_unavailable", "active Tranzak provider authority is required")
            existing = cls.repository.callback_by_reference(
                session,
                tenant_id=command.tenant_id,
                provider_account_id=int(provider["id"]),
                reference=event_reference,
            )
            if existing:
                if existing["payload_hash"] != payload_hash:
                    raise XafPayIntegrationError("callback_replay_conflict", "callback event identity has different bytes")
                settlement = cls.repository.settlement_for_callback(
                    session, tenant_id=command.tenant_id, callback_id=int(existing["id"])
                )
                return XafPayCallbackResult(
                    UUID(str(existing["public_id"])),
                    existing["processing_state"],
                    None,
                    UUID(str(settlement["public_id"])) if settlement else None,
                    True,
                )

            signature_valid = cls.adapter.verify_signature(command.raw_body, command.headers, command.callback_secret)
            if not signature_valid:
                callback_id = _stable("callback", command.tenant_id, f"{provider['public_id']}:{event_reference}")
                cls.repository.insert_callback(
                    session,
                    public_id=callback_id,
                    tenant_id=command.tenant_id,
                    organization_unit_id=command.organization_unit_id,
                    provider_account_id=int(provider["id"]),
                    payment_attempt_id=None,
                    provider_event_reference=event_reference,
                    event_type_code="xafpay.signature_rejected",
                    payload_hash=payload_hash,
                    signature_status="rejected",
                    processing_state="rejected",
                    evidence_payload={"payload_hash": payload_hash, "reason": "invalid_signature"},
                    received_at=command.received_at,
                    occurred_at=command.received_at,
                    business_date=command.business_date,
                    calendar_policy_version=command.calendar_policy_version,
                    correlation_id=command.correlation_id,
                    source_record_id=str(callback_id),
                    metadata={"integration": "xafpay"},
                )
                return XafPayCallbackResult(callback_id, "rejected", None)

            callback = cls.adapter.normalize_callback(command.raw_body, command.headers)
            attempt = cls.repository.attempt_authority(
                session,
                tenant_id=command.tenant_id,
                public_id=callback.payment_attempt_public_id,
                lock=True,
            )
            if attempt is None or attempt["organization_unit_id"] != command.organization_unit_id:
                raise XafPayIntegrationError("callback_attempt_not_found", "callback payment attempt does not exist in scope")
            cls._validate_callback_authority(attempt, provider, callback)
            callback_public_id = _stable("callback", command.tenant_id, f"{provider['public_id']}:{event_reference}")

            target = "succeeded" if callback.status in _SUCCESS else _STATUS_TARGET[callback.status]
            terminal = attempt["attempt_state"] in _TERMINAL
            ignored = terminal or (
                target == "processing" and attempt["attempt_state"] in {"requires_action", "authorized"}
            ) or (target == "requires_action" and attempt["attempt_state"] == "authorized")
            processing_state = "ignored" if ignored else "processed"
            callback_row = cls.repository.insert_callback(
                session,
                public_id=callback_public_id,
                tenant_id=command.tenant_id,
                organization_unit_id=command.organization_unit_id,
                provider_account_id=int(provider["id"]),
                payment_attempt_id=int(attempt["id"]),
                provider_event_reference=event_reference,
                event_type_code=f"xafpay.payment.{callback.status}",
                payload_hash=callback.payload_hash,
                signature_status="verified",
                processing_state=processing_state,
                evidence_payload=callback.evidence,
                received_at=command.received_at,
                occurred_at=callback.occurred_at,
                business_date=command.business_date,
                calendar_policy_version=command.calendar_policy_version,
                correlation_id=command.correlation_id,
                source_record_id=str(callback_public_id),
                metadata={"integration": "xafpay", "gateway_intent_id": str(callback.gateway_intent_id)},
            )
            if ignored:
                return XafPayCallbackResult(callback_public_id, processing_state, attempt["attempt_state"])

            current = attempt
            gateway_reference = str(callback.gateway_intent_id)
            if target in {"succeeded", "requires_action"} and current["attempt_state"] == "pending":
                result = TransactionalPaymentAttemptEngine.transition(
                    session,
                    cls._attempt_transition(command, current, "processing", "xafpay_callback_routed", gateway_reference),
                )
                current = {
                    **current,
                    "attempt_state": result.payment_attempt.attempt_state,
                    "row_version": result.payment_attempt.row_version,
                }
            if target != current["attempt_state"]:
                result = TransactionalPaymentAttemptEngine.transition(
                    session,
                    cls._attempt_transition(
                        command,
                        current,
                        target,
                        f"xafpay_{callback.status}",
                        gateway_reference,
                        evidence=callback.evidence,
                    ),
                )
                current = {
                    **current,
                    "attempt_state": result.payment_attempt.attempt_state,
                    "row_version": result.payment_attempt.row_version,
                }

            settlement_public_id = None
            if target == "succeeded":
                settlement_public_id = cls._settle(
                    session, command, current, callback, callback_public_id
                )
            return XafPayCallbackResult(
                callback_public_id,
                callback_row["processing_state"],
                current["attempt_state"],
                settlement_public_id,
            )

    @staticmethod
    def _validate_callback_authority(attempt, provider, callback) -> None:
        if int(attempt["provider_account_id"] or 0) != int(provider["id"]):
            raise XafPayIntegrationError("callback_provider_mismatch", "callback provider account differs from attempt")
        if attempt["orchestrator_code"] != "xafpay" or attempt["underlying_provider_code"] != "tranzak":
            raise XafPayIntegrationError("callback_routing_mismatch", "callback routing differs from attempt authority")
        if Decimal(attempt["attempted_amount"]) != callback.amount or attempt["currency_code"] != callback.currency_code:
            raise XafPayIntegrationError("callback_amount_mismatch", "callback amount or currency differs from attempt")
        existing = attempt["external_attempt_reference"]
        if existing and existing != str(callback.gateway_intent_id):
            raise XafPayIntegrationError("callback_gateway_identity_mismatch", "callback gateway identity differs from attempt")

    @classmethod
    def _settle(cls, session, command, attempt, callback, callback_public_id: UUID) -> UUID:
        settlement_id = _stable("settlement", command.tenant_id, str(callback_public_id))
        create = CreatePaymentSettlementCommand(
            public_id=settlement_id,
            tenant_id=command.tenant_id,
            organization_unit_id=command.organization_unit_id,
            payment_intent_public_id=UUID(str(attempt["payment_intent_public_id"])),
            payment_attempt_public_id=UUID(str(attempt["public_id"])),
            payment_tender_public_id=UUID(str(attempt["payment_tender_public_id"])) if attempt["payment_tender_public_id"] else None,
            provider_callback_event_public_id=callback_public_id,
            operational_account_public_id=command.operational_account_public_id,
            settlement_direction="incoming",
            gross_amount=callback.amount,
            fee_amount="0",
            net_amount=callback.amount,
            currency_code=callback.currency_code,
            payment_method_code=attempt["payment_method_code"],
            payment_rail_code=attempt["payment_rail_code"],
            external_settlement_reference=callback.provider_reference,
            value_date=callback.occurred_at.date(),
            occurred_at=callback.occurred_at,
            business_date=command.business_date,
            calendar_policy_version=command.calendar_policy_version,
            correlation_id=command.correlation_id,
            actor_service=command.actor_service,
            source_component="xbos.xafpay.settlement",
            source_record_id=str(callback_public_id),
            idempotency_scope="m45.xafpay.settlement",
            idempotency_key=str(callback_public_id),
            metadata={"integration": "xafpay", "gateway_intent_id": str(callback.gateway_intent_id)},
        )
        created = TransactionalPaymentSettlementEngine.create(session, create)
        transition = TransitionPaymentSettlementCommand(
            tenant_id=command.tenant_id,
            organization_unit_id=command.organization_unit_id,
            payment_settlement_public_id=settlement_id,
            expected_row_version=created.settlement.row_version,
            target_state="confirmed",
            finality_status="final",
            availability_state="available",
            reason_code="xafpay_confirmed",
            evidence_payload=callback.evidence,
            external_settlement_reference=callback.provider_reference,
            occurred_at=max(callback.occurred_at, created.settlement.occurred_at) + timedelta(microseconds=1),
            business_date=command.business_date,
            calendar_policy_version=command.calendar_policy_version,
            correlation_id=command.correlation_id,
            actor_service=command.actor_service,
            source_component="xbos.xafpay.settlement",
            source_record_id=f"confirm:{callback_public_id}",
            idempotency_scope="m45.xafpay.settlement.transition",
            idempotency_key=str(callback_public_id),
            metadata={"integration": "xafpay"},
        )
        TransactionalPaymentSettlementEngine.transition(session, transition)
        return settlement_id
