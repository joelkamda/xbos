"""Typed evidence contract for M8.3 performance and recovery hardening."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Mapping, Sequence


class PerformanceRecoveryError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _required(value: object, field: str) -> str:
    selected = str(value).strip()
    if not selected:
        raise PerformanceRecoveryError("required_value_missing", field)
    return selected


@dataclass(frozen=True)
class QueryPlanEvidence:
    name: str
    relation: str
    plan_node_types: tuple[str, ...]
    index_names: tuple[str, ...]
    planning_time_ms: str
    execution_time_ms: str
    actual_rows: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _required(self.name, "name"))
        object.__setattr__(self, "relation", _required(self.relation, "relation"))
        object.__setattr__(self, "plan_node_types", tuple(str(v) for v in self.plan_node_types))
        object.__setattr__(self, "index_names", tuple(str(v) for v in self.index_names if v))
        if not self.plan_node_types:
            raise PerformanceRecoveryError("query_plan_missing", self.name)
        if self.actual_rows < 0:
            raise PerformanceRecoveryError("invalid_actual_rows", self.name)

    @property
    def uses_index(self) -> bool:
        return any("Index" in node or node == "Bitmap Heap Scan" for node in self.plan_node_types)


@dataclass(frozen=True)
class FinancialRecoveryFingerprint:
    canonical_head: str
    table_counts: Mapping[str, int]
    table_digests: Mapping[str, str]
    control_totals: Mapping[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_head", _required(self.canonical_head, "canonical_head"))
        counts = {str(k): int(v) for k, v in self.table_counts.items()}
        digests = {str(k): str(v) for k, v in self.table_digests.items()}
        totals = {str(k): str(v) for k, v in self.control_totals.items()}
        if not counts or set(counts) != set(digests):
            raise PerformanceRecoveryError("fingerprint_table_set_invalid", "counts/digests")
        if any(value < 0 for value in counts.values()):
            raise PerformanceRecoveryError("negative_table_count", repr(counts))
        if any(len(value) != 32 for value in digests.values()):
            raise PerformanceRecoveryError("invalid_table_digest", repr(digests))
        object.__setattr__(self, "table_counts", counts)
        object.__setattr__(self, "table_digests", digests)
        object.__setattr__(self, "control_totals", totals)

    @property
    def semantic_fingerprint(self) -> str:
        payload = {
            "canonical_head": self.canonical_head,
            "table_counts": dict(sorted(self.table_counts.items())),
            "table_digests": dict(sorted(self.table_digests.items())),
            "control_totals": dict(sorted(self.control_totals.items())),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PerformanceRecoveryEvidence:
    fixture_sizes: Mapping[str, int]
    plans: Sequence[QueryPlanEvidence]
    pre_backup: FinancialRecoveryFingerprint
    post_restore: FinancialRecoveryFingerprint
    rollback_head: str
    restored_head: str

    def __post_init__(self) -> None:
        sizes = {str(k): int(v) for k, v in self.fixture_sizes.items()}
        if not sizes or any(value < 0 for value in sizes.values()):
            raise PerformanceRecoveryError("fixture_sizes_invalid", repr(sizes))
        object.__setattr__(self, "fixture_sizes", sizes)
        object.__setattr__(self, "plans", tuple(self.plans))
