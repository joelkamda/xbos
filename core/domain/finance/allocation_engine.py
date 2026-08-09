"""Transactional M3.2 orchestration; caller owns the outer commit."""

from __future__ import annotations

from dataclasses import dataclass

from .allocation_contract import AllocationValidationError
from .allocation_repository import AllocationFact, AllocationRepository
from .obligation_engine import TransactionalObligationEngine
from .obligation_repository import ObligationRepository


@dataclass(frozen=True)
class AllocationCommandResult:
    fact: AllocationFact
    replayed: bool


class TransactionalAllocationEngine:
    repository = AllocationRepository
    obligations = TransactionalObligationEngine

    @classmethod
    def _reserve(cls, session, command):
        return ObligationRepository.reserve(session, command, command.request_fingerprint)

    @classmethod
    def _finish(cls, session, reservation, fact):
        ObligationRepository.complete(session, reservation, response_code=201,
                                      response_snapshot={"public_id": str(fact.public_id)})
        return AllocationCommandResult(fact, False)

    @classmethod
    def create_value_source(cls, session, command) -> AllocationCommandResult:
        with session.begin_nested():
            reservation = cls._reserve(session, command)
            if not reservation.created:
                fact = cls.repository.find_fact(session, "value_sources", command.tenant_id, command.public_id)
                if fact is None:
                    raise AllocationValidationError("idempotency_result_missing", "value source replay target is absent")
                return AllocationCommandResult(fact, True)
            return cls._finish(session, reservation, cls.repository.insert_value_source(session, command))

    @classmethod
    def allocate(cls, session, command) -> AllocationCommandResult:
        with session.begin_nested():
            reservation = cls._reserve(session, command)
            if not reservation.created:
                fact = cls.repository.find_fact(session, "payment_allocations", command.tenant_id, command.public_id)
                if fact is None:
                    raise AllocationValidationError("idempotency_result_missing", "allocation replay target is absent")
                return AllocationCommandResult(fact, True)
            # Fixed order for every writer: value source, obligation, allocation.
            source = cls.repository.lock_value_source(session, command.tenant_id, command.value_source_public_id)
            obligation = cls.repository.lock_obligation(session, command.tenant_id, command.obligation_public_id)
            if obligation["obligation_state"] in {"cancelled", "written_off"}:
                raise AllocationValidationError("obligation_not_allocatable", "terminal obligation cannot accept value")
            if source["currency_code"] != command.currency_code or obligation["currency_code"] != command.currency_code:
                raise AllocationValidationError("currency_mismatch", "source, obligation, and command currency must match")
            if cls.repository.source_available(session, command.tenant_id, source["id"]) < command.allocation_amount:
                raise AllocationValidationError("source_capacity_exceeded", "allocation exceeds active source capacity")
            if cls.repository.obligation_outstanding(session, command.tenant_id, obligation["id"]) < command.allocation_amount:
                raise AllocationValidationError("obligation_capacity_exceeded", "allocation exceeds obligation outstanding")
            fact = cls.repository.insert_allocation(session, command, source, obligation)
            cls.obligations.refresh_satisfaction_state(session, tenant_id=command.tenant_id,
                                                       obligation_public_id=command.obligation_public_id)
            return cls._finish(session, reservation, fact)

    @classmethod
    def reverse(cls, session, command) -> AllocationCommandResult:
        with session.begin_nested():
            reservation = cls._reserve(session, command)
            if not reservation.created:
                fact = cls.repository.find_fact(session, "allocation_reversals", command.tenant_id, command.public_id)
                if fact is None:
                    raise AllocationValidationError("idempotency_result_missing", "reversal replay target is absent")
                return AllocationCommandResult(fact, True)
            allocation = cls.repository.get_allocation(session, command.tenant_id, command.payment_allocation_public_id)
            # Obtain aggregate locks in the same order used by allocate.
            cls.repository.lock_value_source(session, command.tenant_id, allocation["value_source_public_id"])
            cls.repository.lock_obligation(session, command.tenant_id, allocation["obligation_public_id"])
            allocation = cls.repository.get_allocation(
                session, command.tenant_id, command.payment_allocation_public_id, lock=True
            )
            if allocation["organization_unit_id"] != command.organization_unit_id or allocation["currency_code"] != command.currency_code:
                raise AllocationValidationError("reversal_scope_mismatch", "reversal must preserve allocation scope")
            remaining = allocation["allocation_amount"] - cls.repository.reversed_amount(session, command.tenant_id, allocation["id"])
            if remaining < command.reversal_amount:
                raise AllocationValidationError("reversal_capacity_exceeded", "reversal exceeds active allocation")
            fact = cls.repository.insert_reversal(session, command, allocation)
            cls.obligations.refresh_satisfaction_state(session, tenant_id=command.tenant_id,
                                                       obligation_public_id=allocation["obligation_public_id"])
            return cls._finish(session, reservation, fact)
