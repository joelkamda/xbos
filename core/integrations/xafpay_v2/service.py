"""XBOS-owned financial reaction to current canonical XafPay Gateway events."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping
from uuid import UUID, NAMESPACE_URL, uuid5

from core.domain.finance.payment_attempt_contract import TransitionPaymentAttemptCommand
from core.domain.finance.payment_attempt_engine import TransactionalPaymentAttemptEngine
from core.domain.finance.payment_settlement_contract import (
    CreatePaymentSettlementCommand,
    ReversePaymentSettlementCommand,
    TransitionPaymentSettlementCommand,
)
from core.domain.finance.payment_settlement_engine import TransactionalPaymentSettlementEngine
from core.domain.finance.payment_tender_contract import TransitionPaymentTenderCommand
from core.domain.finance.payment_tender_engine import TransactionalPaymentTenderEngine

from .contract import (
    XafPayV2IntegrationError,
    parse_gateway_event,
    payload_sha256,
    verify_gateway_signature,
)
from .repository import AttemptAuthority, XafPayV2Repository


def _stable(kind: str, identity: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"xbos:xafpay-v2:{kind}:{identity}")


class XafPayV2Service:
    repository = XafPayV2Repository

    @classmethod
    def consume_event(
        cls,
        session,
        *,
        raw_body: bytes,
        headers: Mapping[str, str],
        signing_secret: str,
        expected_gateway_merchant_id: str,
        operational_account_public_id: UUID,
        replay_window_seconds: int = 300,
        now: datetime | None = None,
    ) -> Mapping[str, Any]:
        verify_gateway_signature(
            raw_body,
            headers,
            signing_secret,
            now=now,
            replay_window_seconds=replay_window_seconds,
        )
        event = parse_gateway_event(raw_body, headers)
        if event.merchant_id != expected_gateway_merchant_id:
            raise XafPayV2IntegrationError(
                "gateway_merchant_mismatch",
                "event merchant differs from the configured XBOS merchant",
            )

        if event.payment_attempt_public_id is not None:
            attempt = cls.repository.attempt_authority(
                session, event.payment_attempt_public_id, lock=True
            )
        else:
            attempt = cls.repository.attempt_by_gateway_payment_id(
                session, event.payment_id, lock=True
            )
        if attempt is None:
            raise XafPayV2IntegrationError(
                "attempt_not_found",
                "event cannot resolve an XBOS payment attempt",
            )
        cls._validate_gateway_owned_provider_boundary(attempt)

        if (
            event.payment_attempt_public_id is not None
            and event.payment_attempt_public_id != attempt.public_id
        ):
            raise XafPayV2IntegrationError(
                "external_reference_mismatch",
                "Gateway external reference does not bind this XBOS attempt",
            )
        if attempt.currency_code != event.currency_code:
            raise XafPayV2IntegrationError(
                "gateway_currency_mismatch",
                "event currency differs from XBOS attempt",
            )
        if event.aggregate_type == "Payment":
            if attempt.attempted_amount != Decimal(event.amount_minor):
                raise XafPayV2IntegrationError(
                    "gateway_amount_mismatch",
                    "event amount differs from XBOS attempt",
                )
            if (
                event.requested_method is not None
                and event.requested_method != attempt.payment_method_code.upper()
            ):
                raise XafPayV2IntegrationError(
                    "gateway_method_mismatch",
                    "event method differs from XBOS attempt",
                )
            if (
                event.requested_rail is not None
                and event.requested_rail != attempt.payment_rail_code.upper()
            ):
                raise XafPayV2IntegrationError(
                    "gateway_rail_mismatch",
                    "event rail differs from XBOS attempt",
                )
        else:
            if attempt.attempt_state != "succeeded":
                raise XafPayV2IntegrationError(
                    "correction_requires_success",
                    "correction event requires a succeeded XBOS attempt",
                )
            if Decimal(event.amount_minor) > attempt.attempted_amount:
                raise XafPayV2IntegrationError(
                    "correction_amount_invalid",
                    "correction exceeds original attempt amount",
                )

        if attempt.external_attempt_reference is not None:
            if attempt.external_attempt_reference != event.payment_id:
                raise XafPayV2IntegrationError(
                    "gateway_payment_identity_mismatch",
                    "event Gateway payment differs from bound attempt",
                )
        elif event.aggregate_type != "Payment":
            raise XafPayV2IntegrationError(
                "gateway_payment_identity_missing",
                "correction cannot establish the original Gateway payment identity",
            )

        fingerprint = payload_sha256(raw_body)
        reservation = cls.repository.reserve_event(
            session,
            tenant_id=attempt.tenant_id,
            event_id=event.event_id,
            fingerprint=fingerprint,
        )
        if not reservation.created:
            if reservation.fingerprint != fingerprint:
                raise XafPayV2IntegrationError(
                    "event_identity_conflict",
                    "same Gateway event id carries different canonical bytes",
                )
            if reservation.state == "completed" and reservation.response_snapshot is not None:
                return {**dict(reservation.response_snapshot), "replayed": True}
            raise XafPayV2IntegrationError(
                "event_in_progress",
                "Gateway event identity is already processing",
            )

        current = attempt
        effect = "NO_SETTLED_EFFECT"
        anomaly = None

        if event.aggregate_type == "Payment":
            current = cls._ensure_gateway_payment_binding(session, current, event)

        if event.event_type == "payment.succeeded":
            if current.attempt_state == "succeeded":
                if cls.repository.settlement_count_for_attempt(
                    session,
                    tenant_id=current.tenant_id,
                    attempt_public_id=current.public_id,
                ) != 1:
                    raise XafPayV2IntegrationError(
                        "settlement_cardinality_conflict",
                        "successful attempt lacks exactly one confirmed settlement",
                    )
                effect = "ALREADY_SETTLED"
            elif current.attempt_state in {"failed", "cancelled", "expired"}:
                raise XafPayV2IntegrationError(
                    "terminal_success_conflict",
                    "success conflicts with prior XBOS terminal non-success",
                )
            else:
                current = cls._transition_attempt(session, current, "succeeded", event)
                cls._transition_bound_tender(session, current, "succeeded", event)
                cls._settle(session, current, event, operational_account_public_id)
                cls.repository.finalize_wnd_projection(
                    session,
                    current,
                    confirmed_at=event.occurred_at,
                )
                effect = "SETTLED_ONCE"
        elif event.event_type in {"payment.failed", "payment.canceled", "payment.expired"}:
            if current.attempt_state == "succeeded":
                anomaly = "LATE_NON_SUCCESS_AFTER_SUCCESS"
            elif current.attempt_state in {"failed", "cancelled", "expired"}:
                anomaly = "TERMINAL_NON_SUCCESS_ALREADY_RECORDED"
            elif event.event_type == "payment.failed":
                current = cls._transition_attempt(session, current, "failed", event)
            elif event.event_type == "payment.canceled":
                current = cls._transition_attempt(session, current, "cancelled", event)
            else:
                # Gateway presentation/payment expiry is evidence, not authority
                # to bypass the canonical XBOS attempt timeout invariant.
                anomaly = "GATEWAY_EXPIRED_NO_XBOS_TIMEOUT_AUTHORITY"
        elif event.event_type == "payment.requires_action":
            if current.attempt_state == "processing":
                current = cls._transition_attempt(
                    session, current, "requires_action", event
                )
        elif event.event_type in {"payment.created", "payment.pending"}:
            effect = "NO_SETTLED_EFFECT"
        elif event.event_type in {"refund.succeeded", "payment.reversed"}:
            cls._reverse_settlement(session, current, event)
            effect = (
                "REFUND_REVERSED_ONCE"
                if event.event_type == "refund.succeeded"
                else "PAYMENT_REVERSAL_APPLIED_ONCE"
            )
        else:
            raise XafPayV2IntegrationError("event_type_unhandled", event.event_type)

        settlements = cls.repository.settlement_count_for_attempt(
            session,
            tenant_id=current.tenant_id,
            attempt_public_id=current.public_id,
        )
        if (
            event.aggregate_type == "Payment"
            and event.event_type != "payment.succeeded"
            and settlements != 0
            and current.attempt_state != "succeeded"
        ):
            raise XafPayV2IntegrationError(
                "non_success_settlement_violation",
                "non-success event created settlement value",
            )

        response: dict[str, Any] = {
            "accepted": True,
            "event_id": event.event_id,
            "event_type": event.event_type,
            "effect": effect,
            "attempt_state": current.attempt_state,
            "confirmed_settlements": settlements,
            "tenant_id": current.tenant_id,
            "organization_unit_id": current.organization_unit_id,
            "replayed": False,
        }
        if event.correction_id:
            response["correction_id"] = event.correction_id
            response["settlement_reversals"] = cls.repository.reversal_count_for_attempt(
                session,
                tenant_id=current.tenant_id,
                attempt_public_id=current.public_id,
            )
        if anomaly:
            response["anomaly"] = anomaly
        cls.repository.complete_event(session, reservation, response)
        return response

    @staticmethod
    def _validate_gateway_owned_provider_boundary(attempt: AttemptAuthority) -> None:
        if attempt.orchestrator_code != "xafpay":
            raise XafPayV2IntegrationError(
                "orchestrator_mismatch",
                "attempt is not routed through XafPay",
            )
        if (
            attempt.provider_account_id is not None
            or attempt.underlying_provider_code is not None
        ):
            raise XafPayV2IntegrationError(
                "provider_authority_violation",
                "XBOS XafPay attempt must not select provider authority",
            )

    @classmethod
    def _ensure_gateway_payment_binding(
        cls,
        session,
        attempt: AttemptAuthority,
        event,
    ) -> AttemptAuthority:
        if attempt.external_attempt_reference:
            if attempt.external_attempt_reference != event.payment_id:
                raise XafPayV2IntegrationError(
                    "gateway_payment_identity_mismatch",
                    "Gateway payment identity cannot be rewritten",
                )
            return attempt
        if attempt.attempt_state != "pending":
            raise XafPayV2IntegrationError(
                "gateway_payment_identity_missing",
                "only the pending pre-execution attempt may bind first Gateway payment evidence",
            )
        result = TransactionalPaymentAttemptEngine.transition(
            session,
            TransitionPaymentAttemptCommand(
                tenant_id=attempt.tenant_id,
                organization_unit_id=attempt.organization_unit_id,
                payment_attempt_public_id=attempt.public_id,
                expected_row_version=attempt.row_version,
                target_state="processing",
                reason_code="xafpay_v2_gateway_bound",
                external_attempt_reference=event.payment_id,
                evidence_payload=dict(event.envelope),
                occurred_at=max(event.occurred_at, attempt.occurred_at),
                business_date=attempt.business_date,
                calendar_policy_version=attempt.calendar_policy_version,
                correlation_id=attempt.correlation_id,
                actor_service="xbos.xafpay_v2",
                source_component="xbos.xafpay_v2.event",
                source_record_id=event.event_id,
                idempotency_scope="xafpay_v2.attempt.bind",
                idempotency_key=event.event_id,
                metadata={"gateway_payment_id": event.payment_id},
            ),
        )
        updated = cls.repository.attempt_authority(
            session, result.payment_attempt.public_id, lock=True
        )
        if updated is None:
            raise XafPayV2IntegrationError(
                "gateway_identity_not_bound",
                "Gateway payment identity was not bound to XBOS attempt",
            )
        return updated

    @classmethod
    def _transition_attempt(
        cls,
        session,
        attempt: AttemptAuthority,
        target: str,
        event,
    ) -> AttemptAuthority:
        kwargs: dict[str, Any] = {}
        if target == "failed":
            kwargs["failure_code"] = "gateway_failed"
        result = TransactionalPaymentAttemptEngine.transition(
            session,
            TransitionPaymentAttemptCommand(
                tenant_id=attempt.tenant_id,
                organization_unit_id=attempt.organization_unit_id,
                payment_attempt_public_id=attempt.public_id,
                expected_row_version=attempt.row_version,
                target_state=target,
                reason_code=f"xafpay_v2_{target}",
                external_attempt_reference=attempt.external_attempt_reference,
                evidence_payload=dict(event.envelope),
                occurred_at=max(event.occurred_at, attempt.occurred_at),
                business_date=attempt.business_date,
                calendar_policy_version=attempt.calendar_policy_version,
                correlation_id=attempt.correlation_id,
                actor_service="xbos.xafpay_v2",
                source_component="xbos.xafpay_v2.event",
                source_record_id=event.event_id,
                idempotency_scope="xafpay_v2.attempt.transition",
                idempotency_key=event.event_id,
                metadata={"gateway_payment_id": event.payment_id},
                **kwargs,
            ),
        )
        updated = cls.repository.attempt_authority(
            session, result.payment_attempt.public_id, lock=True
        )
        if updated is None:
            raise XafPayV2IntegrationError(
                "attempt_transition_missing",
                "XBOS attempt transition result is missing",
            )
        return updated

    @classmethod
    def _transition_bound_tender(
        cls,
        session,
        attempt: AttemptAuthority,
        target: str,
        event,
    ) -> None:
        if attempt.payment_tender_public_id is None:
            return
        tender = TransactionalPaymentTenderEngine.repository.find_tender(
            session,
            attempt.tenant_id,
            attempt.payment_tender_public_id,
            lock=True,
        )
        if tender is None:
            raise XafPayV2IntegrationError(
                "payment_tender_not_found",
                "bound XBOS tender is missing",
            )
        if tender.tender_state == target:
            return
        TransactionalPaymentTenderEngine.transition(
            session,
            TransitionPaymentTenderCommand(
                tenant_id=attempt.tenant_id,
                organization_unit_id=attempt.organization_unit_id,
                payment_tender_public_id=tender.public_id,
                expected_row_version=tender.row_version,
                target_state=target,
                reason_code=f"xafpay_v2_{target}",
                evidence_payload=dict(event.envelope),
                occurred_at=max(event.occurred_at, tender.occurred_at),
                business_date=attempt.business_date,
                calendar_policy_version=attempt.calendar_policy_version,
                correlation_id=attempt.correlation_id,
                actor_service="xbos.xafpay_v2",
                source_component="xbos.xafpay_v2.tender",
                source_record_id=event.event_id,
                idempotency_scope="xafpay_v2.tender.transition",
                idempotency_key=event.event_id,
                metadata={"gateway_payment_id": event.payment_id},
            ),
        )

    @classmethod
    def _reverse_settlement(cls, session, attempt: AttemptAuthority, event) -> None:
        settlement = cls.repository.settlement_for_attempt(
            session,
            tenant_id=attempt.tenant_id,
            attempt_public_id=attempt.public_id,
            lock=True,
        )
        if settlement is None:
            raise XafPayV2IntegrationError(
                "correction_settlement_missing",
                "correction event has no confirmed settlement to reverse",
            )
        reversal_amount = Decimal(event.amount_minor)
        remaining = Decimal(settlement["gross_amount"]) - Decimal(settlement["reversed_amount"])
        if reversal_amount > remaining:
            raise XafPayV2IntegrationError(
                "correction_capacity_exceeded",
                "correction exceeds remaining settlement value",
            )
        correction_id = event.correction_id or event.event_id
        kind = "refund-reversal" if event.event_type == "refund.succeeded" else "provider-reversal"
        reason = "xafpay_v2_refund" if event.event_type == "refund.succeeded" else "xafpay_v2_reversal"
        TransactionalPaymentSettlementEngine.reverse(
            session,
            ReversePaymentSettlementCommand(
                public_id=_stable(kind, correction_id),
                tenant_id=attempt.tenant_id,
                organization_unit_id=attempt.organization_unit_id,
                payment_settlement_public_id=UUID(str(settlement["public_id"])),
                reversal_amount=reversal_amount,
                currency_code=event.currency_code,
                reason_code=reason,
                occurred_at=max(event.occurred_at, settlement["occurred_at"]),
                business_date=attempt.business_date,
                calendar_policy_version=attempt.calendar_policy_version,
                correlation_id=attempt.correlation_id,
                actor_service="xbos.xafpay_v2",
                source_component=f"xbos.xafpay_v2.{event.aggregate_type.lower()}",
                source_record_id=correction_id,
                idempotency_scope="xafpay_v2.correction.reversal",
                idempotency_key=event.event_id,
                metadata={
                    "gateway_payment_id": event.payment_id,
                    "gateway_correction_id": correction_id,
                    "provider_reference": event.provider_reference,
                },
            ),
        )

    @classmethod
    def _settle(
        cls,
        session,
        attempt: AttemptAuthority,
        event,
        operational_account_public_id: UUID,
    ) -> None:
        settlement_id = _stable("settlement", event.event_id)
        created = TransactionalPaymentSettlementEngine.create(
            session,
            CreatePaymentSettlementCommand(
                public_id=settlement_id,
                tenant_id=attempt.tenant_id,
                organization_unit_id=attempt.organization_unit_id,
                payment_intent_public_id=attempt.payment_intent_public_id,
                payment_attempt_public_id=attempt.public_id,
                payment_tender_public_id=attempt.payment_tender_public_id,
                operational_account_public_id=operational_account_public_id,
                settlement_direction="incoming",
                gross_amount=attempt.attempted_amount,
                fee_amount="0",
                net_amount=attempt.attempted_amount,
                currency_code=attempt.currency_code,
                payment_method_code=attempt.payment_method_code,
                payment_rail_code=attempt.payment_rail_code,
                external_settlement_reference=event.provider_reference,
                value_date=event.occurred_at.date(),
                occurred_at=event.occurred_at,
                business_date=attempt.business_date,
                calendar_policy_version=attempt.calendar_policy_version,
                correlation_id=attempt.correlation_id,
                actor_service="xbos.xafpay_v2",
                source_component="xbos.xafpay_v2.settlement",
                source_record_id=event.event_id,
                idempotency_scope="xafpay_v2.settlement.create",
                idempotency_key=event.event_id,
                metadata={
                    "gateway_payment_id": event.payment_id,
                    "gateway_event_id": event.event_id,
                },
            ),
        )
        TransactionalPaymentSettlementEngine.transition(
            session,
            TransitionPaymentSettlementCommand(
                tenant_id=attempt.tenant_id,
                organization_unit_id=attempt.organization_unit_id,
                payment_settlement_public_id=settlement_id,
                expected_row_version=created.settlement.row_version,
                target_state="confirmed",
                finality_status="final",
                availability_state="available",
                reason_code="xafpay_v2_confirmed",
                evidence_payload=dict(event.envelope),
                external_settlement_reference=event.provider_reference,
                occurred_at=event.occurred_at,
                business_date=attempt.business_date,
                calendar_policy_version=attempt.calendar_policy_version,
                correlation_id=attempt.correlation_id,
                actor_service="xbos.xafpay_v2",
                source_component="xbos.xafpay_v2.settlement",
                source_record_id=event.event_id,
                idempotency_scope="xafpay_v2.settlement.confirm",
                idempotency_key=event.event_id,
                metadata={"gateway_payment_id": event.payment_id},
            ),
        )
