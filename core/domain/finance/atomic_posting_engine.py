"""Atomic event, idempotency, outbox, and balanced-journal orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from .event_contract import CanonicalFinancialEventCommand
from .posting_engine import CanonicalFinancialPostingEngine
from .posting_repository import JournalEntryRecord
from .transactional_event_engine import (
    TransactionalCanonicalFinancialEventEngine,
    TransactionalFinancialEventResult,
)


@dataclass(frozen=True)
class PostedFinancialEventResult:
    financial_event_result: TransactionalFinancialEventResult
    journal_entry: JournalEntryRecord | None

    @property
    def replayed(self) -> bool:
        return self.financial_event_result.replayed


class AtomicPostedFinancialEventEngine:
    event_engine = TransactionalCanonicalFinancialEventEngine
    posting_engine = CanonicalFinancialPostingEngine

    @classmethod
    def emit_and_post(
        cls, session, command: CanonicalFinancialEventCommand
    ) -> PostedFinancialEventResult:
        with session.begin_nested():
            financial = cls.event_engine.emit(session, command)
            journal = cls.posting_engine.post(session, financial.event)
            return PostedFinancialEventResult(
                financial_event_result=financial,
                journal_entry=journal,
            )
