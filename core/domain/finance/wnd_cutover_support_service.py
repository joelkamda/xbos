"""M7.4 deterministic compatibility and R6 cutover-decision support."""
from __future__ import annotations

from typing import Iterable, Mapping

from .legacy_authority_contract import AuthorityMode, LegacyAuthorityInventory
from .wnd_cutover_support_contract import (
    DualReadComparison, DualReadProjection, FinancialCutoverReadinessAssessment,
    LegacyWriterRetirementPlan, ReadinessEvidence, WriterRetirementCandidate,
)


class WndCutoverSupportService:
    @staticmethod
    def compare(legacy: DualReadProjection, canonical: DualReadProjection) -> DualReadComparison:
        return DualReadComparison(legacy, canonical)

    @staticmethod
    def assess(assessment_id: str, source_snapshot_fingerprint: str,
               evidence: Iterable[ReadinessEvidence]) -> FinancialCutoverReadinessAssessment:
        ordered = tuple(sorted(evidence, key=lambda item: item.code))
        return FinancialCutoverReadinessAssessment(
            assessment_id=assessment_id,
            source_snapshot_fingerprint=source_snapshot_fingerprint,
            evidence=ordered,
        )

    @staticmethod
    def retirement_plan(plan_id: str, assessment: FinancialCutoverReadinessAssessment,
                        inventory: LegacyAuthorityInventory,
                        rollback_references: Mapping[str, str]) -> LegacyWriterRetirementPlan:
        eligible = assessment.status == "ready_for_r6_review"
        writers = tuple(surface for surface in inventory.surfaces
                        if surface.authority_mode in {AuthorityMode.WRITER, AuthorityMode.READER_WRITER})
        candidates = tuple(WriterRetirementCandidate(
            surface_code=surface.code,
            source_path=surface.source_path,
            canonical_targets=surface.canonical_targets,
            rollback_reference=str(rollback_references.get(surface.code, "")).strip(),
            eligible_for_r6_review=eligible,
        ) for surface in sorted(writers, key=lambda item: item.code))
        return LegacyWriterRetirementPlan(
            plan_id=plan_id,
            readiness_assessment_fingerprint=assessment.assessment_fingerprint,
            candidates=candidates,
            status="prepared_for_r6_review" if eligible else "blocked",
        )
