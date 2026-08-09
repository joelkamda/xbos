"""Transactional creation, evidence transitions, timeout, and retry for M4.2 attempts."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from .payment_attempt_contract import (
    CreatePaymentAttemptCommand,
    PaymentAttemptValidationError,
    TERMINAL_STATES,
    TransitionPaymentAttemptCommand,
)
from .payment_attempt_repository import (
    PaymentAttemptRecord,
    PaymentAttemptRepository,
    PaymentAttemptTransitionRecord,
)
from .payment_intent_repository import (
    PaymentIdempotencyReservation,
    PaymentIntentRepository,
)


@dataclass(frozen=True)
class PaymentAttemptCommandResult:
    payment_attempt: PaymentAttemptRecord
    idempotency_record: PaymentIdempotencyReservation
    replayed: bool


@dataclass(frozen=True)
class PaymentAttemptTransitionResult:
    payment_attempt: PaymentAttemptRecord
    transition: PaymentAttemptTransitionRecord
    idempotency_record: PaymentIdempotencyReservation
    replayed: bool


_ALLOWED = {
    "pending": {"processing", "failed", "cancelled", "expired"},
    "processing": {"requires_action", "authorized", "succeeded", "failed", "cancelled", "expired"},
    "requires_action": {"processing", "authorized", "succeeded", "failed", "cancelled", "expired"},
    "authorized": {"succeeded", "failed", "cancelled", "expired"},
    "succeeded": set(),
    "failed": set(),
    "cancelled": set(),
    "expired": set(),
}


class TransactionalPaymentAttemptEngine:
    repository = PaymentAttemptRepository
    idempotency = PaymentIntentRepository

    @classmethod
    def create(cls, session, command: CreatePaymentAttemptCommand) -> PaymentAttemptCommandResult:
        with session.begin_nested():
            reservation = cls.idempotency.reserve(session, command, command.request_fingerprint)
            if not reservation.created:
                attempt = cls.repository.find_attempt(
                    session, tenant_id=command.tenant_id, public_id=command.public_id
                )
                if attempt is None:
                    raise PaymentAttemptValidationError(
                        "idempotency_result_missing", "completed creation has no payment attempt"
                    )
                return PaymentAttemptCommandResult(replace(attempt, replayed=True), reservation, True)
            if cls.repository.public_id_exists(session, command.public_id):
                raise PaymentAttemptValidationError("public_id_conflict", "payment public_id already exists")

            intent = cls.repository.lock_intent(
                session,
                tenant_id=command.tenant_id,
                public_id=command.payment_intent_public_id,
            )
            if intent is None:
                raise PaymentAttemptValidationError("payment_intent_not_found", "payment intent does not exist")
            if intent.organization_unit_id != command.organization_unit_id:
                raise PaymentAttemptValidationError("payment_intent_scope_mismatch", "intent organization differs")
            if intent.currency_code != command.currency_code:
                raise PaymentAttemptValidationError("payment_intent_currency_mismatch", "intent currency differs")
            if intent.intent_state not in {"pending", "processing"}:
                raise PaymentAttemptValidationError("payment_intent_not_attemptable", "intent is not attemptable")
            if intent.expires_at is not None and command.occurred_at >= intent.expires_at:
                raise PaymentAttemptValidationError("payment_intent_expired", "intent expired before attempt occurrence")
            if command.timeout_at is not None and intent.expires_at is not None and command.timeout_at > intent.expires_at:
                raise PaymentAttemptValidationError("attempt_timeout_exceeds_intent", "attempt timeout exceeds intent expiry")
            if command.attempted_amount > intent.requested_amount:
                raise PaymentAttemptValidationError("attempt_amount_exceeds_intent", "attempt exceeds intent amount")
            allowed_methods = intent.payment_method_policy.get("allowed_methods", [])
            if command.payment_method_code not in allowed_methods:
                raise PaymentAttemptValidationError("payment_method_not_allowed", "attempt method is not allowed by intent")

            provider_account_id = None
            if command.provider_account_public_id:
                provider = cls.repository.provider_account(
                    session,
                    tenant_id=command.tenant_id,
                    public_id=command.provider_account_public_id,
                )
                if provider is None or not provider["active"]:
                    raise PaymentAttemptValidationError("provider_account_unavailable", "provider account is unavailable")
                if provider["organization_unit_id"] not in (None, command.organization_unit_id):
                    raise PaymentAttemptValidationError("provider_account_scope_mismatch", "provider account organization differs")
                if command.underlying_provider_code and provider["provider_code"] != command.underlying_provider_code:
                    raise PaymentAttemptValidationError("provider_account_code_mismatch", "provider code differs from account")
                provider_account_id = int(provider["id"])

            retry_of_attempt_id = None
            if command.retry_of_attempt_public_id:
                prior = cls.repository.find_attempt(
                    session,
                    tenant_id=command.tenant_id,
                    public_id=command.retry_of_attempt_public_id,
                    lock=True,
                )
                if prior is None:
                    raise PaymentAttemptValidationError("retry_attempt_not_found", "retry authority does not exist")
                if prior.payment_intent_id != intent.id or prior.organization_unit_id != command.organization_unit_id:
                    raise PaymentAttemptValidationError("retry_scope_mismatch", "retry authority belongs to another intent")
                if prior.currency_code != command.currency_code or prior.attempt_state not in {"failed", "cancelled", "expired"}:
                    raise PaymentAttemptValidationError("retry_not_allowed", "retry requires a terminal unsuccessful attempt")
                retry_of_attempt_id = prior.id

            attempt = cls.repository.insert_attempt(
                session,
                command,
                payment_intent_id=intent.id,
                provider_account_id=provider_account_id,
                retry_of_attempt_id=retry_of_attempt_id,
            )
            completed = cls.idempotency.complete(
                session,
                reservation,
                response_code=201,
                response_snapshot={
                    "entity": "payment_attempt",
                    "public_id": str(attempt.public_id),
                    "state": attempt.attempt_state,
                    "row_version": attempt.row_version,
                },
            )
            return PaymentAttemptCommandResult(attempt, completed, False)

    @classmethod
    def transition(
        cls, session, command: TransitionPaymentAttemptCommand
    ) -> PaymentAttemptTransitionResult:
        with session.begin_nested():
            reservation = cls.idempotency.reserve(session, command, command.request_fingerprint)
            if not reservation.created:
                snapshot = reservation.response_snapshot or {}
                transition_id = snapshot.get("transition_public_id")
                if not transition_id:
                    raise PaymentAttemptValidationError(
                        "idempotency_result_missing", "completed transition has no historical evidence"
                    )
                transition = cls.repository.find_transition(session, public_id=UUID(transition_id))
                attempt = cls.repository.find_attempt(
                    session,
                    tenant_id=command.tenant_id,
                    public_id=command.payment_attempt_public_id,
                )
                if transition is None or attempt is None:
                    raise PaymentAttemptValidationError(
                        "idempotency_result_missing", "historical transition result is missing"
                    )
                return PaymentAttemptTransitionResult(
                    replace(attempt, replayed=True), transition, reservation, True
                )

            attempt = cls.repository.find_attempt(
                session,
                tenant_id=command.tenant_id,
                public_id=command.payment_attempt_public_id,
                lock=True,
            )
            if attempt is None:
                raise PaymentAttemptValidationError("payment_attempt_not_found", "payment attempt does not exist")
            if attempt.organization_unit_id != command.organization_unit_id:
                raise PaymentAttemptValidationError("payment_attempt_scope_mismatch", "attempt organization differs")
            if attempt.row_version != command.expected_row_version:
                raise PaymentAttemptValidationError("payment_attempt_version_conflict", "expected row version differs")
            if command.target_state not in _ALLOWED[attempt.attempt_state]:
                raise PaymentAttemptValidationError("invalid_attempt_transition", "attempt transition is not allowed")
            if command.occurred_at < attempt.occurred_at:
                raise PaymentAttemptValidationError("transition_precedes_attempt", "transition precedes attempt")
            if command.target_state == "expired" and (
                attempt.timeout_at is None or command.occurred_at < attempt.timeout_at
            ):
                raise PaymentAttemptValidationError("attempt_timeout_not_reached", "attempt timeout has not been reached")
            if attempt.external_attempt_reference and command.external_attempt_reference not in (
                None,
                attempt.external_attempt_reference,
            ):
                raise PaymentAttemptValidationError(
                    "external_reference_conflict", "external attempt reference cannot be rewritten"
                )
            external_reference = command.external_attempt_reference or attempt.external_attempt_reference
            if command.target_state in {"authorized", "succeeded"} and not external_reference:
                raise PaymentAttemptValidationError(
                    "external_reference_required", "provider-result transition requires external reference"
                )

            transition = cls.repository.insert_transition(
                session,
                attempt,
                command,
                external_reference=external_reference,
            )
            updated = cls.repository.apply_transition(
                session,
                attempt,
                command,
                external_reference=external_reference,
            )
            if updated is None:
                raise PaymentAttemptValidationError("payment_attempt_version_conflict", "attempt changed concurrently")
            completed = cls.idempotency.complete(
                session,
                reservation,
                response_code=200,
                response_snapshot={
                    "entity": "payment_attempt_transition",
                    "payment_attempt_public_id": str(updated.public_id),
                    "transition_public_id": str(transition.public_id),
                    "state": transition.to_state,
                    "row_version": updated.row_version,
                },
            )
            return PaymentAttemptTransitionResult(updated, transition, completed, False)
