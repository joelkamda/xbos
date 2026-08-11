"""In-memory replay/concurrency oracle used only by the M8 hardening harness."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Mapping

from .global_invariant_contract import GlobalInvariantError


@dataclass(frozen=True)
class ReplayDecision:
    identity: tuple[int, str, str]
    payload_fingerprint: str
    replayed: bool


class ReplayInvariantOracle:
    """Thread-safe oracle: one identity accepts one payload and only replays it."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._accepted: dict[tuple[int, str, str], str] = {}

    @staticmethod
    def fingerprint(payload: Mapping[str, object]) -> str:
        try:
            encoded = json.dumps(
                dict(payload), sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise GlobalInvariantError("invalid_replay_payload", "payload") from exc
        return hashlib.sha256(encoded).hexdigest()

    def accept(
        self, *, tenant_id: int, scope: str, key: str, payload: Mapping[str, object]
    ) -> ReplayDecision:
        identity = (int(tenant_id), str(scope).strip(), str(key).strip())
        if identity[0] <= 0 or not identity[1] or not identity[2]:
            raise GlobalInvariantError("invalid_idempotency_identity", repr(identity))
        fingerprint = self.fingerprint(payload)
        with self._lock:
            prior = self._accepted.get(identity)
            if prior is None:
                self._accepted[identity] = fingerprint
                return ReplayDecision(identity, fingerprint, False)
            if prior != fingerprint:
                raise GlobalInvariantError("idempotency_conflict", repr(identity))
            return ReplayDecision(identity, fingerprint, True)

    @property
    def accepted_count(self) -> int:
        with self._lock:
            return len(self._accepted)


def validate_kernel_concurrency_guards(root: Path) -> None:
    """Freeze the accepted database and repository guards M8.0 depends on."""
    markers = {
        "core/domain/finance/transactional_event_engine.py": ("session.begin_nested()",),
        "core/domain/finance/idempotency_repository.py": ("FOR UPDATE", "idempotency_conflict"),
        "alembic_neutral/sql/m13_financial_foundation_up.sql": (
            "UNIQUE (tenant_id, scope, idempotency_key)",
        ),
        "alembic_neutral/sql/m24_balanced_posting_up.sql": (
            "trg_journal_entries_balanced", "trg_journal_entries_immutable",
        ),
        "alembic_neutral/sql/m32_allocation_engine_up.sql": ("FOR UPDATE",),
        "alembic_neutral/sql/m43_payment_settlements_up.sql": (
            "FOR UPDATE", "trg_payment_settlement_transition_immutable",
        ),
        "alembic_neutral/sql/m61_operational_transfers_up.sql": (
            "tr_financial_events_m61_transfer_validate", "source_operational_account_id",
            "target_operational_account_id",
        ),
        "alembic_neutral/sql/m62_reconciliation_windows_up.sql": (
            "FOR UPDATE", "idempotency",
        ),
        "alembic_neutral/sql/m63_reconciliation_close_governance_up.sql": (
            "tr_reconciliation_governance_immutable", "idempotency",
        ),
        "alembic_neutral/sql/m64_reconciliation_controls_up.sql": (
            "FOR UPDATE", "idempotency",
        ),
    }
    for relative, expected in markers.items():
        try:
            source = (root / relative).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise GlobalInvariantError("guard_source_unreadable", relative) from exc
        for marker in expected:
            if marker not in source:
                raise GlobalInvariantError("kernel_guard_missing", f"{relative}: {marker}")
