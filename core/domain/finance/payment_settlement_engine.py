"""Transactional settlement creation, terminal evidence, and reversal engine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from uuid import UUID

from .payment_intent_repository import PaymentIdempotencyReservation, PaymentIntentRepository
from .payment_settlement_contract import (
    CreatePaymentSettlementCommand,
    PaymentSettlementValidationError,
    ReversePaymentSettlementCommand,
    TransitionPaymentSettlementCommand,
)
from .payment_settlement_repository import (
    PaymentSettlementRecord,
    PaymentSettlementRepository,
    PaymentSettlementReversalRecord,
    PaymentSettlementTransitionRecord,
)
from .payment_tender_repository import PaymentTenderRepository


@dataclass(frozen=True)
class PaymentSettlementCommandResult:
    settlement: PaymentSettlementRecord
    idempotency_record: PaymentIdempotencyReservation
    replayed: bool


@dataclass(frozen=True)
class PaymentSettlementTransitionResult:
    settlement: PaymentSettlementRecord
    transition: PaymentSettlementTransitionRecord
    idempotency_record: PaymentIdempotencyReservation
    replayed: bool


@dataclass(frozen=True)
class PaymentSettlementReversalResult:
    settlement: PaymentSettlementRecord
    reversal: PaymentSettlementReversalRecord
    idempotency_record: PaymentIdempotencyReservation
    replayed: bool


class TransactionalPaymentSettlementEngine:
    repository = PaymentSettlementRepository
    idempotency = PaymentIntentRepository

    @classmethod
    def create(cls, session, command: CreatePaymentSettlementCommand) -> PaymentSettlementCommandResult:
        with session.begin_nested():
            reservation = cls.idempotency.reserve(session, command, command.request_fingerprint)
            if not reservation.created:
                settlement = cls.repository.find_settlement(session, tenant_id=command.tenant_id, public_id=command.public_id)
                if settlement is None:
                    raise PaymentSettlementValidationError("idempotency_result_missing", "completed settlement creation has no result")
                return PaymentSettlementCommandResult(replace(settlement, replayed=True), reservation, True)
            if cls.repository.public_id_exists(session, command.public_id):
                raise PaymentSettlementValidationError("public_id_conflict", "payment public_id already exists")

            intent = cls.repository.lock_intent(session, tenant_id=command.tenant_id, public_id=command.payment_intent_public_id)
            if intent is None:
                raise PaymentSettlementValidationError("payment_intent_not_found", "payment intent does not exist")
            if intent.organization_unit_id != command.organization_unit_id or intent.currency_code != command.currency_code:
                raise PaymentSettlementValidationError("payment_intent_scope_mismatch", "intent scope or currency differs")
            if intent.intent_state not in {"pending", "processing", "succeeded"}:
                raise PaymentSettlementValidationError("payment_intent_not_settleable", "intent is not settleable")
            if command.payment_method_code not in intent.payment_method_policy.get("allowed_methods", []):
                raise PaymentSettlementValidationError("payment_method_not_allowed", "settlement method is not allowed by intent")
            if cls.repository.committed_amount(session, tenant_id=command.tenant_id, payment_intent_id=intent.id) + command.gross_amount > intent.requested_amount:
                raise PaymentSettlementValidationError("settlement_capacity_exceeded", "settlement exceeds remaining intent capacity")

            attempt_id = None
            if command.payment_attempt_public_id:
                attempt = cls.repository.lock_attempt(session, tenant_id=command.tenant_id, public_id=command.payment_attempt_public_id)
                if attempt is None or attempt.payment_intent_id != intent.id:
                    raise PaymentSettlementValidationError("payment_attempt_not_found", "matching payment attempt does not exist")
                if attempt.organization_unit_id != command.organization_unit_id or attempt.currency_code != command.currency_code:
                    raise PaymentSettlementValidationError("payment_attempt_scope_mismatch", "attempt scope or currency differs")
                if attempt.attempt_state != "succeeded" or command.gross_amount > attempt.attempted_amount:
                    raise PaymentSettlementValidationError("payment_attempt_not_settleable", "attempt lacks successful settlement capacity")
                if attempt.payment_method_code != command.payment_method_code or attempt.payment_rail_code != command.payment_rail_code:
                    raise PaymentSettlementValidationError("payment_attempt_routing_mismatch", "attempt routing differs")
                attempt_id = attempt.id
            elif command.payment_rail_code not in {"cash", "internal_credit"}:
                raise PaymentSettlementValidationError("payment_attempt_required", "external settlement requires successful attempt")

            tender_id = None
            if command.payment_tender_public_id:
                tender = PaymentTenderRepository.find_tender(
                    session, tenant_id=command.tenant_id,
                    public_id=command.payment_tender_public_id, lock=True,
                )
                if tender is None or tender.payment_intent_id != intent.id:
                    raise PaymentSettlementValidationError("payment_tender_not_found", "matching payment tender does not exist")
                if tender.organization_unit_id != command.organization_unit_id or tender.currency_code != command.currency_code:
                    raise PaymentSettlementValidationError("payment_tender_scope_mismatch", "tender scope or currency differs")
                if tender.payment_method_code != command.payment_method_code or command.gross_amount > tender.tender_amount:
                    raise PaymentSettlementValidationError("payment_tender_capacity_mismatch", "settlement differs from tender authority")
                if attempt_id is not None and attempt.payment_tender_id != tender.id:
                    raise PaymentSettlementValidationError("payment_tender_attempt_mismatch", "settlement tender and attempt differ")
                tender_id = tender.id
            elif intent.payment_method_policy.get("allow_mixed_tender"):
                raise PaymentSettlementValidationError("payment_tender_required", "mixed settlement requires explicit tender authority")

            account = cls.repository.operational_account(session, tenant_id=command.tenant_id, public_id=command.operational_account_public_id)
            if account is None or not account["active"] or account["aggregation_role"] != "leaf":
                raise PaymentSettlementValidationError("operational_account_unavailable", "operational account is unavailable")
            if account["organization_unit_id"] != command.organization_unit_id or account["currency_code"] != command.currency_code:
                raise PaymentSettlementValidationError("operational_account_scope_mismatch", "operational account scope or currency differs")

            callback_id = None
            if command.provider_callback_event_public_id:
                callback = cls.repository.callback_event(session, tenant_id=command.tenant_id, public_id=command.provider_callback_event_public_id)
                if callback is None or callback["organization_unit_id"] != command.organization_unit_id:
                    raise PaymentSettlementValidationError("callback_scope_mismatch", "provider callback does not exist in scope")
                if callback["signature_status"] not in {"verified", "not_applicable"}:
                    raise PaymentSettlementValidationError("callback_not_verified", "provider callback is not verified")
                if callback["payment_attempt_id"] not in (None, attempt_id):
                    raise PaymentSettlementValidationError("callback_attempt_mismatch", "provider callback belongs to another attempt")
                callback_id = int(callback["id"])

            settlement = cls.repository.insert_settlement(session, command, intent_id=intent.id,
                                                           attempt_id=attempt_id, tender_id=tender_id, callback_id=callback_id,
                                                           account_id=int(account["id"]))
            completed = cls.idempotency.complete(session, reservation, response_code=201, response_snapshot={
                "entity": "payment_settlement", "public_id": str(settlement.public_id),
                "state": settlement.settlement_state, "row_version": settlement.row_version,
            })
            return PaymentSettlementCommandResult(settlement, completed, False)

    @classmethod
    def transition(cls, session, command: TransitionPaymentSettlementCommand) -> PaymentSettlementTransitionResult:
        with session.begin_nested():
            reservation = cls.idempotency.reserve(session, command, command.request_fingerprint)
            if not reservation.created:
                snapshot = reservation.response_snapshot or {}
                transition_id = snapshot.get("transition_public_id")
                transition = cls.repository.find_transition(session, public_id=UUID(transition_id)) if transition_id else None
                settlement = cls.repository.find_settlement(session, tenant_id=command.tenant_id, public_id=command.payment_settlement_public_id)
                if transition is None or settlement is None:
                    raise PaymentSettlementValidationError("idempotency_result_missing", "completed transition result is missing")
                return PaymentSettlementTransitionResult(replace(settlement, replayed=True), transition, reservation, True)

            settlement = cls.repository.find_settlement(session, tenant_id=command.tenant_id,
                                                         public_id=command.payment_settlement_public_id, lock=True)
            if settlement is None:
                raise PaymentSettlementValidationError("payment_settlement_not_found", "settlement does not exist")
            if settlement.organization_unit_id != command.organization_unit_id:
                raise PaymentSettlementValidationError("payment_settlement_scope_mismatch", "settlement organization differs")
            if settlement.row_version != command.expected_row_version:
                raise PaymentSettlementValidationError("payment_settlement_version_conflict", "expected row version differs")
            if settlement.settlement_state != "pending":
                raise PaymentSettlementValidationError("settlement_terminal", "settlement is no longer pending")
            if command.occurred_at < settlement.occurred_at:
                raise PaymentSettlementValidationError("transition_precedes_settlement", "transition precedes settlement")
            if settlement.external_settlement_reference and command.external_settlement_reference not in (None, settlement.external_settlement_reference):
                raise PaymentSettlementValidationError("provider_identity_conflict", "provider transaction identity cannot be rewritten")
            external_reference = command.external_settlement_reference or settlement.external_settlement_reference
            if command.target_state == "confirmed" and settlement.payment_rail_code not in {"cash", "internal_credit"} and not external_reference:
                raise PaymentSettlementValidationError("provider_identity_required", "confirmed external settlement requires provider identity")

            transition = cls.repository.insert_transition(session, settlement, command, external_reference=external_reference)
            updated = cls.repository.apply_transition(session, settlement, command, external_reference=external_reference)
            if updated is None:
                raise PaymentSettlementValidationError("payment_settlement_version_conflict", "settlement changed concurrently")
            completed = cls.idempotency.complete(session, reservation, response_code=200, response_snapshot={
                "entity": "payment_settlement_transition", "payment_settlement_public_id": str(updated.public_id),
                "transition_public_id": str(transition.public_id), "state": transition.to_state,
                "row_version": updated.row_version,
            })
            return PaymentSettlementTransitionResult(updated, transition, completed, False)

    @classmethod
    def reverse(cls, session, command: ReversePaymentSettlementCommand) -> PaymentSettlementReversalResult:
        with session.begin_nested():
            reservation = cls.idempotency.reserve(session, command, command.request_fingerprint)
            if not reservation.created:
                reversal = cls.repository.find_reversal(session, public_id=command.public_id)
                settlement = cls.repository.find_settlement(session, tenant_id=command.tenant_id, public_id=command.payment_settlement_public_id)
                if reversal is None or settlement is None:
                    raise PaymentSettlementValidationError("idempotency_result_missing", "completed reversal result is missing")
                return PaymentSettlementReversalResult(replace(settlement, replayed=True), replace(reversal, replayed=True), reservation, True)
            if cls.repository.public_id_exists(session, command.public_id):
                raise PaymentSettlementValidationError("public_id_conflict", "payment public_id already exists")
            settlement = cls.repository.find_settlement(session, tenant_id=command.tenant_id,
                                                         public_id=command.payment_settlement_public_id, lock=True)
            if settlement is None or settlement.organization_unit_id != command.organization_unit_id:
                raise PaymentSettlementValidationError("payment_settlement_not_found", "settlement does not exist in scope")
            if settlement.currency_code != command.currency_code:
                raise PaymentSettlementValidationError("reversal_currency_mismatch", "reversal currency differs")
            if settlement.settlement_state not in {"confirmed", "partially_reversed"}:
                raise PaymentSettlementValidationError("settlement_not_reversible", "only confirmed value can be reversed")
            if command.occurred_at < settlement.occurred_at:
                raise PaymentSettlementValidationError("reversal_precedes_settlement", "reversal precedes settlement")
            if settlement.reversed_amount + command.reversal_amount > settlement.gross_amount:
                raise PaymentSettlementValidationError("reversal_capacity_exceeded", "reversal exceeds original gross amount")
            reversal = cls.repository.insert_reversal(session, settlement, command)
            updated = cls.repository.find_settlement(session, tenant_id=command.tenant_id,
                                                      public_id=command.payment_settlement_public_id)
            completed = cls.idempotency.complete(session, reservation, response_code=200, response_snapshot={
                "entity": "payment_settlement_reversal", "payment_settlement_public_id": str(updated.public_id),
                "reversal_public_id": str(reversal.public_id), "state": updated.settlement_state,
                "reversed_amount": str(updated.reversed_amount), "row_version": updated.row_version,
            })
            return PaymentSettlementReversalResult(updated, reversal, completed, False)
