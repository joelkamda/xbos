"""Transactional M4.1 payment request and provider-neutral intent engine."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .obligation_balance_service import ObligationBalanceService
from .payment_intent_contract import (
    CreatePaymentIntentCommand,
    CreatePaymentRequestCommand,
    PaymentCommandValidationError,
)
from .payment_intent_repository import (
    PaymentIdempotencyReservation,
    PaymentIntentRecord,
    PaymentIntentRepository,
    PaymentRequestRecord,
)


@dataclass(frozen=True)
class PaymentRequestCommandResult:
    payment_request: PaymentRequestRecord
    idempotency_record: PaymentIdempotencyReservation
    replayed: bool


@dataclass(frozen=True)
class PaymentIntentCommandResult:
    payment_intent: PaymentIntentRecord
    idempotency_record: PaymentIdempotencyReservation
    replayed: bool


class TransactionalPaymentIntentEngine:
    repository = PaymentIntentRepository
    balance_service = ObligationBalanceService

    @classmethod
    def create_request(
        cls, session, command: CreatePaymentRequestCommand
    ) -> PaymentRequestCommandResult:
        with session.begin_nested():
            reservation = cls.repository.reserve(session, command, command.request_fingerprint)
            if not reservation.created:
                record = cls.repository.find_request(
                    session, tenant_id=command.tenant_id, public_id=command.public_id
                )
                if record is None:
                    raise PaymentCommandValidationError(
                        "idempotency_result_missing", "completed request command has no payment request"
                    )
                return PaymentRequestCommandResult(
                    payment_request=replace(record, replayed=True),
                    idempotency_record=reservation,
                    replayed=True,
                )
            if cls.repository.public_id_exists(session, command.public_id):
                raise PaymentCommandValidationError("public_id_conflict", "payment public_id already exists")
            record = cls.repository.insert_request(session, command)
            completed = cls.repository.complete(
                session,
                reservation,
                response_code=201,
                response_snapshot={
                    "entity": "payment_request",
                    "public_id": str(record.public_id),
                    "state": record.request_state,
                    "row_version": record.row_version,
                },
            )
            return PaymentRequestCommandResult(record, completed, False)

    @classmethod
    def create_intent(
        cls, session, command: CreatePaymentIntentCommand
    ) -> PaymentIntentCommandResult:
        with session.begin_nested():
            reservation = cls.repository.reserve(session, command, command.request_fingerprint)
            if not reservation.created:
                record = cls.repository.find_intent(
                    session, tenant_id=command.tenant_id, public_id=command.public_id
                )
                if record is None:
                    raise PaymentCommandValidationError(
                        "idempotency_result_missing", "completed intent command has no payment intent"
                    )
                return PaymentIntentCommandResult(
                    payment_intent=replace(record, replayed=True),
                    idempotency_record=reservation,
                    replayed=True,
                )
            if cls.repository.public_id_exists(session, command.public_id):
                raise PaymentCommandValidationError("public_id_conflict", "payment public_id already exists")

            payment_request_id = None
            if command.payment_request_public_id:
                request = cls.repository.find_request(
                    session,
                    tenant_id=command.tenant_id,
                    public_id=command.payment_request_public_id,
                    lock=True,
                )
                if request is None:
                    raise PaymentCommandValidationError(
                        "payment_request_not_found", "payment request does not exist for tenant"
                    )
                if request.organization_unit_id != command.organization_unit_id:
                    raise PaymentCommandValidationError(
                        "payment_request_scope_mismatch", "payment request organization differs"
                    )
                if request.currency_code != command.currency_code:
                    raise PaymentCommandValidationError(
                        "payment_request_currency_mismatch", "payment request currency differs"
                    )
                if request.request_state not in {"open", "partially_satisfied"}:
                    raise PaymentCommandValidationError(
                        "payment_request_not_collectible", "payment request is not open for collection"
                    )
                if request.expires_at is not None:
                    if command.occurred_at >= request.expires_at:
                        raise PaymentCommandValidationError(
                            "payment_request_expired", "payment request expired before intent occurrence"
                        )
                    if command.expires_at is not None and command.expires_at > request.expires_at:
                        raise PaymentCommandValidationError(
                            "intent_exceeds_request_expiry", "intent expiry cannot exceed request expiry"
                        )
                remaining = request.requested_amount - request.committed_intent_amount
                if command.requested_amount > remaining:
                    raise PaymentCommandValidationError(
                        "payment_request_capacity_exceeded", "intent exceeds uncommitted request capacity"
                    )
                payment_request_id = request.id

            if command.financial_obligation_public_id:
                obligation = cls.repository.lock_obligation(
                    session,
                    tenant_id=command.tenant_id,
                    public_id=command.financial_obligation_public_id,
                )
                if obligation is None:
                    raise PaymentCommandValidationError(
                        "financial_obligation_not_found", "obligation does not exist for tenant"
                    )
                if int(obligation["organization_unit_id"]) != command.organization_unit_id:
                    raise PaymentCommandValidationError(
                        "financial_obligation_scope_mismatch", "obligation organization differs"
                    )
                if obligation["currency_code"] != command.currency_code:
                    raise PaymentCommandValidationError(
                        "financial_obligation_currency_mismatch", "obligation currency differs"
                    )
                if obligation["obligation_state"] in {"satisfied", "cancelled", "written_off"}:
                    raise PaymentCommandValidationError(
                        "financial_obligation_not_collectible", "obligation is terminal"
                    )
                balance = cls.balance_service.get(
                    session,
                    tenant_id=command.tenant_id,
                    obligation_public_id=command.financial_obligation_public_id,
                )
                if command.requested_amount > balance.outstanding_amount:
                    raise PaymentCommandValidationError(
                        "financial_obligation_capacity_exceeded",
                        "intent exceeds current obligation outstanding amount",
                    )

            record = cls.repository.insert_intent(
                session, command, payment_request_id=payment_request_id
            )
            completed = cls.repository.complete(
                session,
                reservation,
                response_code=201,
                response_snapshot={
                    "entity": "payment_intent",
                    "public_id": str(record.public_id),
                    "state": record.intent_state,
                    "origin": command.intent_origin,
                    "row_version": record.row_version,
                },
            )
            return PaymentIntentCommandResult(record, completed, False)
