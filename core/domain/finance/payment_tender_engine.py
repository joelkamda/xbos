"""Transactional M4.4 tender composition and lifecycle engine."""
from __future__ import annotations
from dataclasses import dataclass,replace
from uuid import UUID
from .payment_intent_repository import PaymentIdempotencyReservation,PaymentIntentRepository
from .payment_tender_contract import CreatePaymentTenderCommand,TransitionPaymentTenderCommand,PaymentTenderValidationError
from .payment_tender_repository import PaymentTenderRepository,PaymentTenderRecord,PaymentTenderTransitionRecord

@dataclass(frozen=True)
class PaymentTenderCommandResult:
    tender:PaymentTenderRecord; idempotency_record:PaymentIdempotencyReservation; replayed:bool
@dataclass(frozen=True)
class PaymentTenderTransitionResult:
    tender:PaymentTenderRecord; transition:PaymentTenderTransitionRecord; idempotency_record:PaymentIdempotencyReservation; replayed:bool

_ALLOWED={"pending":{"processing","succeeded","failed","cancelled"},"processing":{"partially_succeeded","succeeded","failed","cancelled"},"partially_succeeded":{"succeeded","failed","cancelled"},"succeeded":set(),"failed":set(),"cancelled":set()}

class TransactionalPaymentTenderEngine:
    repository=PaymentTenderRepository; idempotency=PaymentIntentRepository
    @classmethod
    def create(cls,session,command):
        with session.begin_nested():
            reservation=cls.idempotency.reserve(session,command,command.request_fingerprint)
            if not reservation.created:
                tender=cls.repository.find_tender(session,command.tenant_id,command.public_id)
                if tender is None: raise PaymentTenderValidationError("idempotency_result_missing","completed tender creation has no result")
                return PaymentTenderCommandResult(replace(tender,replayed=True),reservation,True)
            if cls.repository.public_id_exists(session,command.public_id): raise PaymentTenderValidationError("public_id_conflict","payment public_id already exists")
            intent=cls.repository.lock_intent(session,command.tenant_id,command.payment_intent_public_id)
            if intent is None: raise PaymentTenderValidationError("payment_intent_not_found","payment intent does not exist")
            if intent.organization_unit_id!=command.organization_unit_id or intent.currency_code!=command.currency_code: raise PaymentTenderValidationError("payment_intent_scope_mismatch","intent scope or currency differs")
            if intent.intent_state not in {"pending","processing"}: raise PaymentTenderValidationError("payment_intent_not_tenderable","intent is not tenderable")
            if intent.expires_at and command.occurred_at>=intent.expires_at: raise PaymentTenderValidationError("payment_intent_expired","intent expired before tender")
            policy=intent.payment_method_policy
            if command.payment_method_code not in policy["allowed_methods"]: raise PaymentTenderValidationError("payment_method_not_allowed","method is not allowed")
            count,total=cls.repository.composition(session,command.tenant_id,intent.id)
            if command.tender_number!=cls.repository.next_tender_number(session,command.tenant_id,intent.id): raise PaymentTenderValidationError("tender_sequence_invalid","tender number must be contiguous")
            if count>=policy["max_tenders"]: raise PaymentTenderValidationError("maximum_tenders_exceeded","intent maximum tenders exceeded")
            if not policy["allow_mixed_tender"] and (count or command.tender_amount!=intent.requested_amount): raise PaymentTenderValidationError("single_tender_must_match_intent","single tender must exactly match intent")
            if total+command.tender_amount>intent.requested_amount: raise PaymentTenderValidationError("tender_capacity_exceeded","tender composition exceeds intent")
            tender=cls.repository.insert_tender(session,command,intent.id)
            completed=cls.idempotency.complete(session,reservation,response_code=201,response_snapshot={"entity":"payment_tender","public_id":str(tender.public_id),"state":tender.tender_state,"row_version":tender.row_version})
            return PaymentTenderCommandResult(tender,completed,False)
    @classmethod
    def transition(cls,session,command):
        with session.begin_nested():
            reservation=cls.idempotency.reserve(session,command,command.request_fingerprint)
            if not reservation.created:
                snapshot=reservation.response_snapshot or {}; transition=cls.repository.find_transition(session,UUID(snapshot["transition_public_id"])) if snapshot.get("transition_public_id") else None; tender=cls.repository.find_tender(session,command.tenant_id,command.payment_tender_public_id)
                if transition is None or tender is None: raise PaymentTenderValidationError("idempotency_result_missing","completed tender transition is missing")
                return PaymentTenderTransitionResult(replace(tender,replayed=True),transition,reservation,True)
            tender=cls.repository.find_tender(session,command.tenant_id,command.payment_tender_public_id,lock=True)
            if tender is None or tender.organization_unit_id!=command.organization_unit_id: raise PaymentTenderValidationError("payment_tender_not_found","tender does not exist in scope")
            if tender.row_version!=command.expected_row_version: raise PaymentTenderValidationError("payment_tender_version_conflict","expected version differs")
            if command.target_state not in _ALLOWED[tender.tender_state]: raise PaymentTenderValidationError("invalid_tender_transition","tender transition is not allowed")
            if command.occurred_at<tender.occurred_at: raise PaymentTenderValidationError("transition_precedes_tender","transition precedes tender")
            transition=cls.repository.insert_transition(session,tender,command); updated=cls.repository.apply_transition(session,tender,command)
            if updated is None: raise PaymentTenderValidationError("payment_tender_version_conflict","tender changed concurrently")
            completed=cls.idempotency.complete(session,reservation,response_code=200,response_snapshot={"entity":"payment_tender_transition","payment_tender_public_id":str(updated.public_id),"transition_public_id":str(transition.public_id),"state":updated.tender_state,"row_version":updated.row_version})
            return PaymentTenderTransitionResult(updated,transition,completed,False)
