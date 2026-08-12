"""Deterministic M8.1 oracles; no persistence and no competing financial authority."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .adversarial_ordering_contract import (
    AdversarialControlError,
    AuthorityProbe,
    DelayedFinancialFact,
    REQUIRED_PERMISSION,
    require_single_scope,
)


@dataclass(frozen=True)
class OrderedFactProjection:
    facts: tuple[DelayedFinancialFact, ...]
    replay_count: int


def order_offline_facts(facts: Iterable[DelayedFinancialFact]) -> OrderedFactProjection:
    selected = tuple(facts)
    if not selected:
        return OrderedFactProjection((), 0)
    require_single_scope(selected)
    accepted: dict[tuple[int, str, str], DelayedFinancialFact] = {}
    replays = 0
    for fact in selected:
        prior = accepted.get(fact.identity)
        if prior is None:
            accepted[fact.identity] = fact
        elif prior.semantic_fingerprint != fact.semantic_fingerprint:
            raise AdversarialControlError("idempotency_conflict", repr(fact.identity))
        else:
            replays += 1
    ordered = tuple(sorted(accepted.values(), key=lambda fact: fact.ordering_key))
    return OrderedFactProjection(ordered, replays)


def authorize(probe: AuthorityProbe) -> None:
    if probe.tenant_id <= 0 or probe.organization_unit_id <= 0 or probe.actor_user_id <= 0:
        raise AdversarialControlError("invalid_authority_scope", probe.action)
    action = str(probe.action).strip().lower()
    required = REQUIRED_PERMISSION.get(action)
    if required is None:
        raise AdversarialControlError("unknown_privileged_action", action)
    if required not in probe.actor_permissions:
        raise AdversarialControlError("permission_denied", required)
    if action == "reopen_period":
        if probe.approved_by_user_id is None or probe.approved_by_user_id <= 0:
            raise AdversarialControlError("approval_required", action)
        if probe.approved_by_user_id == probe.actor_user_id:
            raise AdversarialControlError("approval_separation_required", action)
        if required not in probe.approver_permissions:
            raise AdversarialControlError("approver_permission_denied", required)
        if not probe.evidence_fingerprint:
            raise AdversarialControlError("approval_evidence_required", action)


def validate_authority_sources(root) -> None:
    markers = {
        "core/rbac/permissions/permission_codes.py": (
            'ACC_POST           = "accounting.post"',
            'ACC_RECONCILE      = "accounting.reconcile"',
            'ACC_CLOSE_PERIOD   = "accounting.close_period"',
        ),
        "core/domain/finance/reconciliation_close_engine.py": (
            "approval_authority_not_found", "accounting_period_not_open", "window_not_found",
        ),
        "alembic_neutral/sql/m63_reconciliation_close_governance_up.sql": (
            "tr_reconciliation_governance_immutable", "approved_by_user_id",
        ),
        "core/domain/finance/transactional_event_engine.py": (
            "validate_references", "canonical_command_fingerprint",
        ),
    }
    for relative, expected in markers.items():
        source = (root / relative).read_text(encoding="utf-8")
        for marker in expected:
            if marker not in source:
                raise AdversarialControlError("accepted_authority_guard_missing", f"{relative}: {marker}")
