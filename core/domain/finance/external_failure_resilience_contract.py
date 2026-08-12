"""Schema-neutral M8.2 failure classification and callback replay contract."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ExternalFailureControlError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ProviderObservation(str, Enum):
    TIMEOUT = "timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RETRYABLE_FAILURE = "retryable_failure"
    UNKNOWN = "unknown"
    TERMINAL_FAILURE = "terminal_failure"
    AUTHORITATIVE_SUCCESS = "authoritative_success"


@dataclass(frozen=True)
class ProviderDisposition:
    canonical_state: str
    retryable: bool
    settlement_allowed: bool


@dataclass(frozen=True)
class ProviderEvidence:
    tenant_id: int
    organization_unit_id: int
    provider_account_id: str
    event_reference: str
    payload_fingerprint: str
    observation: ProviderObservation


@dataclass(frozen=True)
class EvidenceProjection:
    evidence: tuple[ProviderEvidence, ...]
    replay_count: int
    terminal_state: str | None


def canonical_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
