"""M3.3 atomic receipt and application workflows over M3.2 primitives."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text

from .allocation_contract import AllocateValueCommand
from .allocation_engine import TransactionalAllocationEngine
from .allocation_repository import AllocationFact, AllocationRepository
from .obligation_balance_service import ObligationBalanceService
from .value_application_contract import ApplyUnappliedValueCommand, ReceiveAndApplyValueCommand, ValueApplicationError
from .value_source_balance_service import ValueSourceBalance, ValueSourceBalanceService


@dataclass(frozen=True)
class ApplicationOutcome:
    obligation_public_id: object
    requested_mode: str
    applied_amount: Decimal
    allocation: AllocationFact | None
    status: str


@dataclass(frozen=True)
class ValueApplicationResult:
    source: AllocationFact
    outcomes: tuple[ApplicationOutcome, ...]
    balance: ValueSourceBalance
    disposition: str
    replayed: bool


class TransactionalValueApplicationEngine:
    allocation_engine = TransactionalAllocationEngine
    repository = AllocationRepository
    source_balances = ValueSourceBalanceService
    obligation_balances = ObligationBalanceService

    @classmethod
    def receive(cls, session, command: ReceiveAndApplyValueCommand) -> ValueApplicationResult:
        with session.begin_nested():
            source_result = cls.allocation_engine.create_value_source(session, command.value_source)
            if command.application_batch is None:
                balance = cls.source_balances.get(session, tenant_id=command.value_source.tenant_id,
                                                  value_source_public_id=command.value_source.public_id)
                return ValueApplicationResult(source_result.fact, (), balance, balance.disposition, source_result.replayed)
            applied = cls.apply_existing(session, command.application_batch)
            return ValueApplicationResult(source_result.fact, applied.outcomes, applied.balance,
                                          applied.disposition, source_result.replayed and applied.replayed)

    @classmethod
    def apply_existing(cls, session, command: ApplyUnappliedValueCommand) -> ValueApplicationResult:
        with session.begin_nested():
            ordered = sorted(command.applications, key=lambda item: str(item.obligation_public_id))
            obligations = {}
            for item in ordered:
                row = session.execute(text("""
                    SELECT organization_unit_id FROM public.financial_obligations
                    WHERE tenant_id=:tenant AND public_id=:public_id
                """), {"tenant": command.tenant_id, "public_id": str(item.obligation_public_id)}).mappings().one_or_none()
                if row is None:
                    raise ValueApplicationError("obligation_not_found", "obligation does not exist for tenant")
                obligations[item.obligation_public_id] = row
            source_fact = cls.repository.find_fact(session, "value_sources", command.tenant_id, command.value_source_public_id)
            if source_fact is None:
                raise ValueApplicationError("value_source_not_found", "value source does not exist for tenant")
            outcomes=[]; every_replay=True; used_ids=set()
            for item in ordered:
                if item.obligation_public_id in used_ids:
                    raise ValueApplicationError("duplicate_obligation_target", "one batch may target an obligation once")
                used_ids.add(item.obligation_public_id)
                existing = cls.repository.find_fact(
                    session, "payment_allocations", command.tenant_id, item.allocation_public_id
                )
                source_balance=cls.source_balances.get(session, tenant_id=command.tenant_id,
                                                       value_source_public_id=command.value_source_public_id)
                obligation_balance=cls.obligation_balances.get(session, tenant_id=command.tenant_id,
                                                               obligation_public_id=item.obligation_public_id)
                amount = item.exact_amount
                if amount is None and existing is not None:
                    # Auto-amount replay must reconstruct the original fingerprint,
                    # not recalculate from balances changed by that same fact.
                    amount = existing.amount
                elif amount is None:
                    amount = min(source_balance.available_amount, obligation_balance.outstanding_amount)
                if amount == 0:
                    outcomes.append(ApplicationOutcome(item.obligation_public_id,item.mode,Decimal("0"),None,"no_capacity"))
                    continue
                obligation = obligations[item.obligation_public_id]
                allocation_command = AllocateValueCommand(
                    public_id=item.allocation_public_id, tenant_id=command.tenant_id,
                    organization_unit_id=int(obligation["organization_unit_id"]),
                    value_source_public_id=command.value_source_public_id,
                    obligation_public_id=item.obligation_public_id, allocation_amount=amount,
                    currency_code=source_fact.currency_code, occurred_at=command.occurred_at,
                    business_date=command.business_date, calendar_policy_version=command.calendar_policy_version,
                    correlation_id=command.correlation_id, actor_user_id=command.actor_user_id,
                    actor_service=command.actor_service, source_component=command.source_component,
                    source_record_id=item.source_record_id, idempotency_scope=command.idempotency_scope,
                    idempotency_key=item.idempotency_key,
                    cross_organization_policy_code=item.cross_organization_policy_code,
                    cross_organization_policy_version=item.cross_organization_policy_version,
                    metadata=item.metadata)
                result=cls.allocation_engine.allocate(session,allocation_command)
                every_replay = every_replay and result.replayed
                outcomes.append(ApplicationOutcome(item.obligation_public_id,item.mode,amount,result.fact,"applied"))
            balance=cls.source_balances.get(session,tenant_id=command.tenant_id,
                                            value_source_public_id=command.value_source_public_id)
            auto_requested=any(item.exact_amount is None for item in ordered)
            disposition="overpayment_residual" if auto_requested and balance.available_amount > 0 else balance.disposition
            return ValueApplicationResult(source_fact,tuple(outcomes),balance,disposition,every_replay)
