"""Typed M7.4 dual-read, readiness, and writer-retirement support."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping

from .wnd_financial_mapping_contract import fingerprint, require_hash
from .wnd_shadow_rehearsal_contract import CONTROL_NAMES, FinancialControlTotals

CONTRACT_CODE = "XBOS_M74_WND_DUAL_READ_CUTOVER_READINESS_AND_WRITER_RETIREMENT_SUPPORT"
CONTRACT_VERSION = 1
SUBJECT_TYPES = frozenset({"commercial", "payment", "receivable", "refund", "inventory", "document"})
REQUIRED_READINESS_EVIDENCE = (
    "legacy_authority_inventory",
    "canonical_mapping_coverage",
    "shadow_rehearsal",
    "control_total_parity",
    "tenant_organization_isolation",
    "replay_conflict_safety",
    "recovery_rehearsal",
    "dual_read_compatibility",
    "rollback_runbook",
)


class WndCutoverSupportError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _hash(value: str, name: str) -> str:
    try:
        return require_hash(value, name)
    except Exception as exc:
        raise WndCutoverSupportError("invalid_evidence_hash", name) from exc


@dataclass(frozen=True)
class DualReadProjection:
    reader: str
    tenant_id: int
    organization_unit_id: int
    subject_type: str
    subject_identity: str
    as_of: datetime
    totals: FinancialControlTotals
    provenance_hash: str
    writer_routing: str = "unchanged"
    authority_switch_executed: bool = False
    projection_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        reader = str(self.reader).strip().lower()
        subject = str(self.subject_type).strip().lower()
        if reader not in {"legacy", "canonical"}:
            raise WndCutoverSupportError("invalid_reader", reader)
        if subject not in SUBJECT_TYPES:
            raise WndCutoverSupportError("invalid_subject_type", subject)
        if min(self.tenant_id, self.organization_unit_id) <= 0 or not self.subject_identity:
            raise WndCutoverSupportError("invalid_projection_scope", self.subject_identity)
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise WndCutoverSupportError("timezone_required", self.subject_identity)
        if self.writer_routing != "unchanged" or self.authority_switch_executed:
            raise WndCutoverSupportError("authority_switch_forbidden", self.subject_identity)
        object.__setattr__(self, "reader", reader)
        object.__setattr__(self, "subject_type", subject)
        object.__setattr__(self, "provenance_hash", _hash(self.provenance_hash, "provenance_hash"))
        object.__setattr__(self, "projection_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "reader": self.reader, "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "subject_type": self.subject_type, "subject_identity": self.subject_identity,
            "as_of": self.as_of, "totals": self.totals.canonical_payload(),
            "provenance_hash": self.provenance_hash, "writer_routing": "unchanged",
            "authority_switch_executed": False,
        }


@dataclass(frozen=True)
class DualReadComparison:
    legacy: DualReadProjection
    canonical: DualReadProjection
    deltas: Mapping[str, Any] = field(init=False)
    status: str = field(init=False)
    read_mode: str = "legacy_primary_canonical_shadow"
    fallback_authorized: bool = False
    comparison_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.legacy.reader != "legacy" or self.canonical.reader != "canonical":
            raise WndCutoverSupportError("reader_pair_required", self.legacy.reader)
        legacy_scope = (self.legacy.tenant_id, self.legacy.organization_unit_id,
                        self.legacy.subject_type, self.legacy.subject_identity, self.legacy.as_of)
        canonical_scope = (self.canonical.tenant_id, self.canonical.organization_unit_id,
                           self.canonical.subject_type, self.canonical.subject_identity, self.canonical.as_of)
        if legacy_scope != canonical_scope:
            raise WndCutoverSupportError("dual_read_scope_mismatch", repr((legacy_scope, canonical_scope)))
        if self.legacy.totals.currency_code != self.canonical.totals.currency_code:
            raise WndCutoverSupportError("dual_read_currency_mismatch", self.legacy.subject_identity)
        if self.read_mode != "legacy_primary_canonical_shadow" or self.fallback_authorized:
            raise WndCutoverSupportError("unsafe_read_routing", self.legacy.subject_identity)
        deltas = {name: self.canonical.totals.values[name] - self.legacy.totals.values[name]
                  for name in CONTROL_NAMES}
        object.__setattr__(self, "deltas", deltas)
        object.__setattr__(self, "status", "matched" if not any(deltas.values()) else "variance")
        object.__setattr__(self, "comparison_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "legacy_projection_fingerprint": self.legacy.projection_fingerprint,
            "canonical_projection_fingerprint": self.canonical.projection_fingerprint,
            "deltas": dict(getattr(self, "deltas", {})),
            "status": getattr(self, "status", "pending"),
            "read_mode": "legacy_primary_canonical_shadow", "fallback_authorized": False,
        }


@dataclass(frozen=True)
class ReadinessEvidence:
    code: str
    passed: bool
    evidence_hash: str
    observed_at: datetime
    detail: str

    def __post_init__(self) -> None:
        code = str(self.code).strip().lower()
        if code not in REQUIRED_READINESS_EVIDENCE:
            raise WndCutoverSupportError("unsupported_readiness_evidence", code)
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise WndCutoverSupportError("timezone_required", code)
        if not str(self.detail).strip():
            raise WndCutoverSupportError("evidence_detail_required", code)
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "evidence_hash", _hash(self.evidence_hash, "evidence_hash"))

    def canonical_payload(self) -> dict[str, Any]:
        return {"code": self.code, "passed": self.passed, "evidence_hash": self.evidence_hash,
                "observed_at": self.observed_at, "detail": self.detail}


@dataclass(frozen=True)
class FinancialCutoverReadinessAssessment:
    assessment_id: str
    source_snapshot_fingerprint: str
    evidence: tuple[ReadinessEvidence, ...]
    status: str = field(init=False)
    blockers: tuple[str, ...] = field(init=False)
    decision_authority: str = "R6"
    advisory_only: bool = True
    cutover_authorized: bool = False
    assessment_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))
        if not self.assessment_id or self.decision_authority != "R6" or not self.advisory_only or self.cutover_authorized:
            raise WndCutoverSupportError("unsafe_readiness_authority", self.assessment_id)
        object.__setattr__(self, "source_snapshot_fingerprint",
                           _hash(self.source_snapshot_fingerprint, "source_snapshot_fingerprint"))
        codes = tuple(item.code for item in self.evidence)
        if len(codes) != len(set(codes)) or set(codes) != set(REQUIRED_READINESS_EVIDENCE):
            raise WndCutoverSupportError("readiness_evidence_incomplete", repr(codes))
        blockers = tuple(item.code for item in self.evidence if not item.passed)
        object.__setattr__(self, "blockers", blockers)
        object.__setattr__(self, "status", "ready_for_r6_review" if not blockers else "not_ready")
        object.__setattr__(self, "assessment_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION,
            "assessment_id": self.assessment_id,
            "source_snapshot_fingerprint": self.source_snapshot_fingerprint,
            "evidence": [item.canonical_payload() for item in self.evidence],
            "status": getattr(self, "status", "pending"),
            "blockers": list(getattr(self, "blockers", ())),
            "decision_authority": "R6", "advisory_only": True, "cutover_authorized": False,
        }


@dataclass(frozen=True)
class WriterRetirementCandidate:
    surface_code: str
    source_path: str
    canonical_targets: tuple[str, ...]
    rollback_reference: str
    eligible_for_r6_review: bool
    current_writer_routing: str = "legacy"
    retirement_executed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_targets", tuple(self.canonical_targets))
        if not all((self.surface_code, self.source_path, self.canonical_targets, self.rollback_reference)):
            raise WndCutoverSupportError("incomplete_retirement_candidate", self.surface_code)
        if self.current_writer_routing != "legacy" or self.retirement_executed:
            raise WndCutoverSupportError("writer_retirement_forbidden", self.surface_code)

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "surface_code": self.surface_code, "source_path": self.source_path,
            "canonical_targets": list(self.canonical_targets),
            "rollback_reference": self.rollback_reference,
            "eligible_for_r6_review": self.eligible_for_r6_review,
            "current_writer_routing": "legacy", "retirement_executed": False,
        }


@dataclass(frozen=True)
class LegacyWriterRetirementPlan:
    plan_id: str
    readiness_assessment_fingerprint: str
    candidates: tuple[WriterRetirementCandidate, ...]
    status: str
    execution_allowed: bool = False
    reversible: bool = True
    decision_authority: str = "R6"
    plan_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        if not self.plan_id or not self.candidates or not self.reversible:
            raise WndCutoverSupportError("incomplete_retirement_plan", self.plan_id)
        object.__setattr__(self, "readiness_assessment_fingerprint",
                           _hash(self.readiness_assessment_fingerprint, "assessment_fingerprint"))
        if len({item.surface_code for item in self.candidates}) != len(self.candidates):
            raise WndCutoverSupportError("duplicate_retirement_candidate", self.plan_id)
        if self.status not in {"prepared_for_r6_review", "blocked"}:
            raise WndCutoverSupportError("invalid_retirement_status", self.status)
        if self.execution_allowed or self.decision_authority != "R6":
            raise WndCutoverSupportError("writer_retirement_forbidden", self.plan_id)
        object.__setattr__(self, "plan_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "readiness_assessment_fingerprint": self.readiness_assessment_fingerprint,
            "candidates": [item.canonical_payload() for item in self.candidates],
            "status": self.status, "execution_allowed": False,
            "reversible": True, "decision_authority": "R6",
        }


def assert_assessment_replay(existing: FinancialCutoverReadinessAssessment,
                             candidate: FinancialCutoverReadinessAssessment) -> FinancialCutoverReadinessAssessment:
    if existing.assessment_id != candidate.assessment_id:
        raise WndCutoverSupportError("replay_identity_mismatch", candidate.assessment_id)
    if existing.assessment_fingerprint != candidate.assessment_fingerprint:
        raise WndCutoverSupportError("readiness_idempotency_conflict", candidate.assessment_id)
    return existing
