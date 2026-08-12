"""Validation helpers for reproducible M8.3 evidence."""
from __future__ import annotations

from pathlib import Path

from .performance_recovery_contract import (
    PerformanceRecoveryError,
    PerformanceRecoveryEvidence,
    QueryPlanEvidence,
)


def validate_query_plan(evidence: QueryPlanEvidence) -> None:
    if not evidence.uses_index or not evidence.index_names:
        raise PerformanceRecoveryError("required_index_not_used", evidence.name)


def validate_recovery_evidence(evidence: PerformanceRecoveryEvidence) -> None:
    if not evidence.plans:
        raise PerformanceRecoveryError("query_plan_evidence_required", "plans")
    for plan in evidence.plans:
        validate_query_plan(plan)
    if evidence.pre_backup.semantic_fingerprint != evidence.post_restore.semantic_fingerprint:
        raise PerformanceRecoveryError(
            "financial_restore_mismatch",
            f"pre={evidence.pre_backup.semantic_fingerprint}; post={evidence.post_restore.semantic_fingerprint}",
        )
    if evidence.rollback_head != evidence.restored_head:
        raise PerformanceRecoveryError(
            "deployment_recovery_head_mismatch",
            f"rollback={evidence.rollback_head}; restored={evidence.restored_head}",
        )


def validate_operator_runbook(root: Path) -> None:
    selected = root / "docs/track_b/M8_3_OPERATOR_RECOVERY_RUNBOOK.md"
    try:
        source = selected.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PerformanceRecoveryError("operator_runbook_unreadable", str(selected)) from exc
    markers = (
        "Failed deployment before migration",
        "Failed deployment after migration",
        "Interrupted verification",
        "Restore from a known backup",
        "Recovery verification before writes",
        "Financial correction is not technical retry",
        "Never edit financial truth manually",
        "R6 owns live WND cutover",
    )
    for marker in markers:
        if marker not in source:
            raise PerformanceRecoveryError("operator_runbook_incomplete", marker)
