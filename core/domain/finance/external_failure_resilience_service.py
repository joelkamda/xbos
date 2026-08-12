"""Pure M8.2 failure oracle over existing provider and kernel authorities."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .external_failure_resilience_contract import (
    EvidenceProjection,
    ExternalFailureControlError,
    ProviderDisposition,
    ProviderEvidence,
    ProviderObservation,
)


_DISPOSITIONS = {
    ProviderObservation.TIMEOUT: ProviderDisposition("uncertain", True, False),
    ProviderObservation.PROVIDER_UNAVAILABLE: ProviderDisposition("uncertain", True, False),
    ProviderObservation.RETRYABLE_FAILURE: ProviderDisposition("uncertain", True, False),
    ProviderObservation.UNKNOWN: ProviderDisposition("uncertain", True, False),
    ProviderObservation.TERMINAL_FAILURE: ProviderDisposition("failed", False, False),
    ProviderObservation.AUTHORITATIVE_SUCCESS: ProviderDisposition("succeeded", False, True),
}


def classify_provider_observation(observation: ProviderObservation) -> ProviderDisposition:
    return _DISPOSITIONS[ProviderObservation(observation)]


def project_provider_evidence(values: Iterable[ProviderEvidence]) -> EvidenceProjection:
    accepted: dict[tuple[int, str, str], ProviderEvidence] = {}
    scope: tuple[int, int, str] | None = None
    replay_count = 0
    terminal: str | None = None
    for evidence in values:
        current_scope = (evidence.tenant_id, evidence.organization_unit_id, evidence.provider_account_id)
        if scope is None:
            scope = current_scope
        elif current_scope != scope:
            raise ExternalFailureControlError("provider_scope_mismatch", "provider evidence crossed tenant, organization, or account scope")
        key = (evidence.tenant_id, evidence.provider_account_id, evidence.event_reference)
        prior = accepted.get(key)
        if prior:
            if prior.payload_fingerprint != evidence.payload_fingerprint:
                raise ExternalFailureControlError("callback_replay_conflict", "provider event identity has different bytes")
            replay_count += 1
            continue
        disposition = classify_provider_observation(evidence.observation)
        if terminal in {"succeeded", "failed"} and disposition.canonical_state != terminal:
            # Keep the late evidence visible without rewriting terminal truth.
            accepted[key] = evidence
            continue
        if disposition.canonical_state in {"succeeded", "failed"}:
            terminal = disposition.canonical_state
        accepted[key] = evidence
    return EvidenceProjection(tuple(accepted.values()), replay_count, terminal)


def validate_existing_failure_authorities(root: Path) -> None:
    required = {
        "core/integrations/xafpay/adapter.py": ("hmac.compare_digest", "callback_event_reference", "payload_hash"),
        "core/integrations/xafpay/orchestration_service.py": ("callback_replay_conflict", "begin_nested", "ignored"),
        "core/domain/finance/transactional_event_engine.py": ("begin_nested",),
        "core/domain/finance/atomic_posting_engine.py": ("begin_nested",),
    }
    for relative, markers in required.items():
        source = (root / relative).read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                raise ExternalFailureControlError("authority_guard_missing", f"{relative}: {marker}")
