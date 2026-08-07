"""Atomic idempotency, financial event, outbox, and correction orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .event_contract import (
    CanonicalFinancialEventCommand,
    FinancialEventValidationError,
    canonical_command_fingerprint,
    validate_command_against_policy,
    validate_command_structure,
)
from .event_repository import CanonicalFinancialEventRepository, FinancialEventRecord
from .idempotency_repository import (
    CanonicalIdempotencyRepository,
    IdempotencyReservation,
)
from .outbox_repository import CanonicalOutboxRepository, OutboxMessageRecord
from .reversal_policy import FinancialEventReversalPolicy


@dataclass(frozen=True)
class TransactionalFinancialEventResult:
    event: FinancialEventRecord
    outbox_message: OutboxMessageRecord
    idempotency_record: IdempotencyReservation
    replayed: bool


class TransactionalCanonicalFinancialEventEngine:
    """Write all command effects atomically without committing for the caller."""

    event_repository = CanonicalFinancialEventRepository
    idempotency_repository = CanonicalIdempotencyRepository
    outbox_repository = CanonicalOutboxRepository
    reversal_policy = FinancialEventReversalPolicy

    @classmethod
    def emit(
        cls, session, command: CanonicalFinancialEventCommand
    ) -> TransactionalFinancialEventResult:
        # One savepoint keeps callers that translate a validation exception from
        # accidentally committing a stranded processing reservation.
        with session.begin_nested():
            return cls._emit_inside_savepoint(session, command)

    @classmethod
    def _emit_inside_savepoint(
        cls, session, command: CanonicalFinancialEventCommand
    ) -> TransactionalFinancialEventResult:
        validate_command_structure(command)
        policy = cls.event_repository.load_catalog_policy(session, command)
        validate_command_against_policy(command, policy)
        fingerprint = canonical_command_fingerprint(command)
        reservation = cls.idempotency_repository.reserve(
            session, command, fingerprint
        )

        if not reservation.created and reservation.processing_state == "completed":
            event = cls.event_repository.find_by_idempotency(session, command)
            if event is None:
                raise FinancialEventValidationError(
                    "idempotency_result_missing",
                    "completed idempotency record has no authoritative event",
                )
            event = cls.event_repository.resolve_replay(event, command)
            outbox = cls.outbox_repository.find_for_event(session, event)
            if outbox is None:
                raise FinancialEventValidationError(
                    "idempotency_outbox_missing",
                    "completed idempotency record has no transactional outbox message",
                )
            return TransactionalFinancialEventResult(
                event=event,
                outbox_message=outbox,
                idempotency_record=reservation,
                replayed=True,
            )

        event = cls.event_repository.find_by_idempotency(session, command)
        if event is None:
            cls.event_repository.validate_references(session, command, policy)
            cls.reversal_policy.validate_and_lock(session, command, policy)
            event = cls.event_repository.insert(session, command)
        else:
            event = cls.event_repository.resolve_replay(event, command)

        outbox = cls.outbox_repository.ensure_for_event(session, event)
        completed = cls.idempotency_repository.complete(
            session,
            reservation,
            result_source_record_id=command.source_record_id,
            response_snapshot={
                "event_public_id": str(event.public_id),
                "outbox_message_public_id": str(outbox.public_id),
                "event_type": event.event_type_code,
                "event_version": event.event_version,
            },
        )
        return TransactionalFinancialEventResult(
            event=replace(event, replayed=False),
            outbox_message=outbox,
            idempotency_record=completed,
            replayed=False,
        )
