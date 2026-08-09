"""Transactional creation and lifecycle orchestration for M3.1 obligations."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .obligation_balance_service import ObligationBalance, ObligationBalanceService
from .obligation_contract import (
    CreateObligationCommand,
    ObligationValidationError,
    TransitionObligationCommand,
)
from .obligation_repository import (
    ObligationIdempotencyReservation,
    ObligationRecord,
    ObligationRepository,
)


@dataclass(frozen=True)
class ObligationCommandResult:
    obligation: ObligationRecord
    idempotency_record: ObligationIdempotencyReservation
    replayed: bool


class TransactionalObligationEngine:
    repository = ObligationRepository
    balance_service = ObligationBalanceService

    @classmethod
    def create(cls, session, command: CreateObligationCommand) -> ObligationCommandResult:
        with session.begin_nested():
            reservation = cls.repository.reserve(session, command, command.request_fingerprint)
            if not reservation.created:
                obligation = cls.repository.find_by_public_id(
                    session, tenant_id=command.tenant_id, public_id=command.public_id
                )
                if obligation is None:
                    raise ObligationValidationError(
                        "idempotency_result_missing", "completed creation has no obligation"
                    )
                return ObligationCommandResult(
                    obligation=replace(obligation, replayed=True),
                    idempotency_record=reservation,
                    replayed=True,
                )
            existing = cls.repository.find_by_public_id(
                session, tenant_id=command.tenant_id, public_id=command.public_id
            )
            if existing is not None:
                raise ObligationValidationError("public_id_conflict", "obligation public_id already exists")
            obligation = cls.repository.insert(session, command)
            completed = cls.repository.complete(
                session,
                reservation,
                response_code=201,
                response_snapshot={
                    "obligation_public_id": str(obligation.public_id),
                    "obligation_state": obligation.obligation_state,
                    "row_version": obligation.row_version,
                },
            )
            return ObligationCommandResult(obligation=obligation, idempotency_record=completed, replayed=False)

    @classmethod
    def transition(cls, session, command: TransitionObligationCommand) -> ObligationCommandResult:
        with session.begin_nested():
            reservation = cls.repository.reserve(session, command, command.request_fingerprint)
            if not reservation.created:
                obligation = cls.repository.find_by_public_id(
                    session, tenant_id=command.tenant_id, public_id=command.obligation_public_id
                )
                if obligation is None:
                    raise ObligationValidationError(
                        "idempotency_result_missing", "completed transition has no obligation"
                    )
                return ObligationCommandResult(
                    obligation=replace(obligation, replayed=True),
                    idempotency_record=reservation,
                    replayed=True,
                )
            locked = cls.repository.lock(
                session, tenant_id=command.tenant_id, public_id=command.obligation_public_id
            )
            if int(locked["row_version"]) != command.expected_row_version:
                raise ObligationValidationError("obligation_version_conflict", "expected row version differs")
            current = locked["obligation_state"]
            allowed = {
                "open": {"cancelled", "written_off"},
                "partially_satisfied": {"written_off"},
                "satisfied": set(),
                "cancelled": set(),
                "written_off": set(),
            }
            if command.target_state not in allowed[current]:
                raise ObligationValidationError(
                    "invalid_obligation_transition", f"cannot transition {current} to {command.target_state}"
                )
            balance = cls.balance_service.get(
                session, tenant_id=command.tenant_id, obligation_public_id=command.obligation_public_id
            )
            if command.target_state == "cancelled" and balance.active_satisfaction != 0:
                raise ObligationValidationError(
                    "cancelled_obligation_has_satisfaction", "an allocated obligation cannot be cancelled"
                )
            if command.target_state == "written_off" and balance.outstanding_amount <= 0:
                raise ObligationValidationError(
                    "nothing_to_write_off", "written-off obligation must have outstanding value"
                )
            cls.repository.update_state(
                session,
                obligation_id=int(locked["id"]),
                expected_version=command.expected_row_version,
                target_state=command.target_state,
            )
            obligation = cls.repository.find_by_public_id(
                session, tenant_id=command.tenant_id, public_id=command.obligation_public_id
            )
            completed = cls.repository.complete(
                session,
                reservation,
                response_code=200,
                response_snapshot={
                    "obligation_public_id": str(obligation.public_id),
                    "obligation_state": obligation.obligation_state,
                    "row_version": obligation.row_version,
                    "reason_code": command.reason_code,
                    "actor_user_id": command.actor_user_id,
                    "actor_service": command.actor_service,
                },
            )
            return ObligationCommandResult(obligation=obligation, idempotency_record=completed, replayed=False)

    @classmethod
    def refresh_satisfaction_state(
        cls, session, *, tenant_id: int, obligation_public_id
    ) -> ObligationBalance:
        with session.begin_nested():
            locked = cls.repository.lock(
                session, tenant_id=tenant_id, public_id=obligation_public_id
            )
            if locked["obligation_state"] in {"cancelled", "written_off"}:
                return cls.balance_service.get(
                    session, tenant_id=tenant_id, obligation_public_id=obligation_public_id
                )
            balance = cls.balance_service.get(
                session, tenant_id=tenant_id, obligation_public_id=obligation_public_id
            )
            if balance.projected_state != locked["obligation_state"]:
                cls.repository.update_state(
                    session,
                    obligation_id=int(locked["id"]),
                    expected_version=int(locked["row_version"]),
                    target_state=balance.projected_state,
                )
                balance = cls.balance_service.get(
                    session, tenant_id=tenant_id, obligation_public_id=obligation_public_id
                )
            return balance
