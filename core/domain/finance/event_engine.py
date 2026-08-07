"""Application service for validated immutable financial-event emission."""

from __future__ import annotations

from .event_contract import (
    CanonicalFinancialEventCommand,
    validate_command_against_policy,
    validate_command_structure,
)
from .event_repository import (
    CanonicalFinancialEventRepository,
    FinancialEventRecord,
)


class CanonicalFinancialEventEngine:
    """Emit one canonical fact without committing the caller's transaction."""

    repository = CanonicalFinancialEventRepository

    @classmethod
    def emit(cls, session, command: CanonicalFinancialEventCommand) -> FinancialEventRecord:
        validate_command_structure(command)
        policy = cls.repository.load_catalog_policy(session, command)
        validate_command_against_policy(command, policy)

        existing = cls.repository.find_by_idempotency(session, command)
        if existing is not None:
            return cls.repository.resolve_replay(existing, command)

        cls.repository.validate_references(session, command, policy)
        return cls.repository.insert(session, command)
