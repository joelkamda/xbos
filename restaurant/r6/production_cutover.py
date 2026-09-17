"""R6.4 deterministic production-cutover planning helpers."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class CutoverFingerprint:
    head: str
    counts: Mapping[str, int]
    totals: Mapping[str, Any]
    composition: Mapping[str, Any]

    def digest(self) -> str:
        payload = {
            "head": self.head,
            "counts": dict(sorted(self.counts.items())),
            "totals": {k: str(v) for k, v in sorted(self.totals.items())},
            "composition": dict(sorted(self.composition.items())),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()


def assert_legacy_truth_preserved(
    before_counts: Mapping[str, int],
    after_counts: Mapping[str, int],
    before_totals: Mapping[str, Any],
    after_totals: Mapping[str, Any],
) -> None:
    if dict(before_counts) != dict(after_counts):
        raise ValueError("legacy row counts changed during cutover rehearsal")
    before = {k: str(v) for k, v in before_totals.items()}
    after = {k: str(v) for k, v in after_totals.items()}
    if before != after:
        raise ValueError("legacy control totals changed during cutover rehearsal")


def rollback_mode(*, reopened: bool, post_cutover_business_write: bool) -> str:
    if not reopened:
        return "FINAL_BACKUP_RESTORE_PERMITTED"
    if not post_cutover_business_write:
        return "FINAL_BACKUP_RESTORE_AFTER_REENTERING_MAINTENANCE"
    return "PRESERVE_LIVE_DB_APPLICATION_ROLLBACK_ONLY"
