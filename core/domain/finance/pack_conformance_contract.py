"""Neutral, reusable financial-conformance evidence for industry and tenant packs."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

CONTRACT_CODE = "XBOS_M84_PACK_FINANCIAL_CONFORMANCE_AND_PRODUCTION_READINESS"
CONTRACT_VERSION = 1
_CODE = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")


class PackConformanceError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _decimal(value: Any, name: str) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PackConformanceError("invalid_control_total", name) from exc
    if not selected.is_finite() or selected < 0 or selected.as_tuple().exponent < -8:
        raise PackConformanceError("invalid_control_total", name)
    return selected


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list, frozenset, set)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise PackConformanceError("unsupported_evidence_value", type(value).__name__)


def semantic_fingerprint(value: Any) -> str:
    encoded = json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ControlTotalSet:
    currency_code: str
    values: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        currency = str(self.currency_code).strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise PackConformanceError("invalid_currency", currency)
        if not self.values:
            raise PackConformanceError("control_totals_required", currency)
        normalized: dict[str, Decimal] = {}
        for name, value in sorted(self.values.items()):
            code = str(name).strip().lower()
            if not _CODE.fullmatch(code):
                raise PackConformanceError("invalid_control_code", code)
            normalized[code] = _decimal(value, code)
        object.__setattr__(self, "currency_code", currency)
        object.__setattr__(self, "values", normalized)

    def canonical_payload(self) -> dict[str, Any]:
        return {"currency_code": self.currency_code, "values": dict(self.values)}


@dataclass(frozen=True)
class PackFlowEvidence:
    flow_code: str
    source_identity: str
    tenant_id: int
    organization_unit_id: int
    mapping_fingerprint: str
    effect_bundle_fingerprint: str
    canonical_effect_ids: tuple[str, ...]
    expected: ControlTotalSet
    observed: ControlTotalSet
    accepted_deliveries: int = 1
    replay_safe: bool = True
    conflicting_duplicate_rejected: bool = True
    delayed_delivery_safe: bool = True
    traceable: bool = True
    permission_compatible: bool = True
    approval_compatible: bool = True
    recovery_safe: bool = True
    evidence_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        flow = str(self.flow_code).strip().lower()
        source = str(self.source_identity).strip()
        effects = tuple(str(item).strip() for item in self.canonical_effect_ids)
        if not _CODE.fullmatch(flow) or not source or min(self.tenant_id, self.organization_unit_id) <= 0:
            raise PackConformanceError("invalid_flow_identity", f"{flow}:{source}")
        for name, value in (("mapping", self.mapping_fingerprint), ("effect_bundle", self.effect_bundle_fingerprint)):
            if not _HASH.fullmatch(str(value)):
                raise PackConformanceError("invalid_evidence_hash", name)
        if not effects or any(not item for item in effects) or len(effects) != len(set(effects)):
            raise PackConformanceError("duplicate_or_missing_effect_identity", source)
        if self.expected.currency_code != self.observed.currency_code or self.expected.values != self.observed.values:
            raise PackConformanceError("control_total_mismatch", source)
        if self.accepted_deliveries != 1:
            raise PackConformanceError("exact_once_violation", source)
        proofs = (
            self.replay_safe, self.conflicting_duplicate_rejected, self.delayed_delivery_safe,
            self.traceable, self.permission_compatible, self.approval_compatible, self.recovery_safe,
        )
        if not all(proofs):
            raise PackConformanceError("flow_conformance_incomplete", source)
        object.__setattr__(self, "flow_code", flow)
        object.__setattr__(self, "source_identity", source)
        object.__setattr__(self, "canonical_effect_ids", effects)
        object.__setattr__(self, "evidence_fingerprint", semantic_fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "flow_code": self.flow_code, "source_identity": self.source_identity,
            "tenant_id": self.tenant_id, "organization_unit_id": self.organization_unit_id,
            "mapping_fingerprint": self.mapping_fingerprint,
            "effect_bundle_fingerprint": self.effect_bundle_fingerprint,
            "canonical_effect_ids": list(self.canonical_effect_ids),
            "expected": self.expected.canonical_payload(), "observed": self.observed.canonical_payload(),
            "accepted_deliveries": self.accepted_deliveries, "replay_safe": self.replay_safe,
            "conflicting_duplicate_rejected": self.conflicting_duplicate_rejected,
            "delayed_delivery_safe": self.delayed_delivery_safe, "traceable": self.traceable,
            "permission_compatible": self.permission_compatible,
            "approval_compatible": self.approval_compatible, "recovery_safe": self.recovery_safe,
        }


@dataclass(frozen=True)
class PackConformanceProfile:
    pack_code: str
    pack_version: str
    authoritative_sources: tuple[str, ...]
    flows: tuple[PackFlowEvidence, ...]
    hidden_writers: tuple[str, ...] = ()
    known_exclusions: tuple[str, ...] = ()
    writer_routing: str = "unchanged"
    cutover_authorized: bool = False
    writer_retirement_executed: bool = False
    migration: str = "NONE"
    profile_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        code = str(self.pack_code).strip().lower()
        sources = tuple(str(item).strip() for item in self.authoritative_sources)
        flows = tuple(self.flows)
        hidden = tuple(self.hidden_writers)
        exclusions = tuple(str(item).strip() for item in self.known_exclusions)
        if not _CODE.fullmatch(code) or not str(self.pack_version).strip() or not sources or not flows:
            raise PackConformanceError("incomplete_pack_profile", code)
        if len(sources) != len(set(sources)) or any(not item for item in sources):
            raise PackConformanceError("duplicate_or_missing_authoritative_source", code)
        identities = tuple((item.tenant_id, item.organization_unit_id, item.source_identity) for item in flows)
        if len(identities) != len(set(identities)):
            raise PackConformanceError("duplicate_operational_source", code)
        if hidden:
            raise PackConformanceError("hidden_financial_writer", ",".join(hidden))
        if self.writer_routing != "unchanged" or self.cutover_authorized or self.writer_retirement_executed:
            raise PackConformanceError("unsafe_pack_authority", code)
        if self.migration != "NONE":
            raise PackConformanceError("schema_expansion_forbidden", self.migration)
        object.__setattr__(self, "pack_code", code)
        object.__setattr__(self, "authoritative_sources", sources)
        object.__setattr__(self, "flows", flows)
        object.__setattr__(self, "hidden_writers", hidden)
        object.__setattr__(self, "known_exclusions", exclusions)
        object.__setattr__(self, "profile_fingerprint", semantic_fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION,
            "pack_code": self.pack_code, "pack_version": self.pack_version,
            "authoritative_sources": list(self.authoritative_sources),
            "flows": [item.canonical_payload() for item in self.flows],
            "hidden_writers": list(self.hidden_writers), "known_exclusions": list(self.known_exclusions),
            "writer_routing": "unchanged", "cutover_authorized": False,
            "writer_retirement_executed": False, "migration": "NONE",
        }


@dataclass(frozen=True)
class PackReadinessReport:
    pack_code: str
    pack_version: str
    conformance_contract: str
    conformance_version: int
    profile_fingerprint: str
    covered_sources: tuple[str, ...]
    covered_flows: tuple[str, ...]
    readiness_verdict: str
    hidden_writers: str = "NONE"
    cutover: str = "NOT_AUTHORIZED"
    writer_retirement: str = "NOT_EXECUTED"
    migration: str = "NONE"
    report_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.readiness_verdict != "PASS" or self.hidden_writers != "NONE":
            raise PackConformanceError("readiness_not_proven", self.pack_code)
        if self.cutover != "NOT_AUTHORIZED" or self.writer_retirement != "NOT_EXECUTED" or self.migration != "NONE":
            raise PackConformanceError("unsafe_readiness_report", self.pack_code)
        if not _HASH.fullmatch(self.profile_fingerprint):
            raise PackConformanceError("invalid_evidence_hash", "profile_fingerprint")
        object.__setattr__(self, "covered_sources", tuple(self.covered_sources))
        object.__setattr__(self, "covered_flows", tuple(self.covered_flows))
        object.__setattr__(self, "report_fingerprint", semantic_fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "pack_code": self.pack_code, "pack_version": self.pack_version,
            "conformance_contract": self.conformance_contract, "conformance_version": self.conformance_version,
            "profile_fingerprint": self.profile_fingerprint,
            "covered_sources": list(self.covered_sources), "covered_flows": list(self.covered_flows),
            "readiness_verdict": self.readiness_verdict, "hidden_writers": "NONE",
            "cutover": "NOT_AUTHORIZED", "writer_retirement": "NOT_EXECUTED", "migration": "NONE",
        }


def assert_profile_replay(existing: PackConformanceProfile, candidate: PackConformanceProfile) -> PackConformanceProfile:
    if (existing.pack_code, existing.pack_version) != (candidate.pack_code, candidate.pack_version):
        raise PackConformanceError("replay_identity_mismatch", candidate.pack_code)
    if existing.profile_fingerprint != candidate.profile_fingerprint:
        raise PackConformanceError("pack_conformance_conflict", candidate.pack_code)
    return existing
