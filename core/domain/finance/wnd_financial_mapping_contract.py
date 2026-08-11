"""Typed, side-effect-free M7.1 WND source-to-canonical mapping plans."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
from uuid import UUID

from .wnd_finance_adapter_contract import LegacyFinancialEnvelope

CONTRACT_CODE = "XBOS_M71_WND_SOURCE_TO_CANONICAL_FINANCIAL_MAPPING"
CONTRACT_VERSION = 1
SUPPORTED_KINDS = frozenset({"commercial_sale", "payment_settlement", "receivable_repayment", "refund"})
_HASH = re.compile(r"^[0-9a-f]{64}$")


class WndFinancialMappingError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def money(value: Any, name: str, *, allow_zero: bool = True) -> Decimal:
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise WndFinancialMappingError("invalid_amount", f"{name} must be a finite decimal") from exc
    if not selected.is_finite() or selected < 0 or (not allow_zero and selected == 0) or selected.as_tuple().exponent < -8:
        raise WndFinancialMappingError("invalid_amount", f"{name} is invalid")
    return selected


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise WndFinancialMappingError("unsupported_mapping_value", type(value).__name__)


def fingerprint(value: Any) -> str:
    encoded = json.dumps(json_safe(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CanonicalCommandDescriptor:
    sequence: int
    contract_code: str
    command_type: str
    public_id: UUID
    idempotency_scope: str
    idempotency_key: str
    payload: Mapping[str, Any]
    economic_effects: tuple[str, ...]
    execution_allowed: bool = False
    command_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "public_id", UUID(str(self.public_id)))
        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "economic_effects", tuple(self.economic_effects))
        if self.sequence <= 0 or not self.contract_code or not self.command_type:
            raise WndFinancialMappingError("invalid_command_descriptor", self.command_type)
        if not self.idempotency_scope or not self.idempotency_key:
            raise WndFinancialMappingError("missing_idempotency_identity", self.command_type)
        if self.execution_allowed:
            raise WndFinancialMappingError("m71_execution_forbidden", self.command_type)
        object.__setattr__(self, "command_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "contract_code": self.contract_code,
            "command_type": self.command_type,
            "public_id": str(self.public_id),
            "idempotency_scope": self.idempotency_scope,
            "idempotency_key": self.idempotency_key,
            "payload": self.payload,
            "economic_effects": self.economic_effects,
            "execution_allowed": False,
        }


@dataclass(frozen=True)
class CanonicalMappingPlan:
    tenant_id: int
    organization_unit_id: int
    source_identity: str
    source_fingerprint: str
    mapping_kind: str
    correlation_id: UUID
    commands: tuple[CanonicalCommandDescriptor, ...]
    writer_routing: str = "unchanged"
    execution_allowed: bool = False
    plan_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "correlation_id", UUID(str(self.correlation_id)))
        object.__setattr__(self, "commands", tuple(self.commands))
        if min(self.tenant_id, self.organization_unit_id) <= 0:
            raise WndFinancialMappingError("invalid_scope", self.source_identity)
        if self.mapping_kind not in SUPPORTED_KINDS or not self.commands:
            raise WndFinancialMappingError("unsupported_or_empty_plan", self.mapping_kind)
        if tuple(item.sequence for item in self.commands) != tuple(range(1, len(self.commands) + 1)):
            raise WndFinancialMappingError("non_contiguous_command_sequence", self.source_identity)
        if len({item.public_id for item in self.commands}) != len(self.commands):
            raise WndFinancialMappingError("duplicate_command_identity", self.source_identity)
        if self.writer_routing != "unchanged" or self.execution_allowed:
            raise WndFinancialMappingError("m71_execution_forbidden", self.source_identity)
        object.__setattr__(self, "plan_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE,
            "schema_version": CONTRACT_VERSION,
            "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "source_identity": self.source_identity,
            "source_fingerprint": self.source_fingerprint,
            "mapping_kind": self.mapping_kind,
            "correlation_id": str(self.correlation_id),
            "commands": [item.canonical_payload() for item in self.commands],
            "writer_routing": "unchanged",
            "execution_allowed": False,
        }


def require_hash(value: Any, name: str = "evidence_hash") -> str:
    selected = str(value or "").strip()
    if not _HASH.fullmatch(selected):
        raise WndFinancialMappingError("evidence_hash_required", f"{name} must be lowercase sha256")
    return selected


def assert_replay(existing: CanonicalMappingPlan, candidate: CanonicalMappingPlan) -> CanonicalMappingPlan:
    if (existing.tenant_id, existing.source_identity, existing.mapping_kind) != (
        candidate.tenant_id, candidate.source_identity, candidate.mapping_kind
    ):
        raise WndFinancialMappingError("replay_identity_mismatch", candidate.source_identity)
    if existing.plan_fingerprint != candidate.plan_fingerprint:
        raise WndFinancialMappingError("mapping_idempotency_conflict", candidate.source_identity)
    return existing


def validate_envelope_kind(envelope: LegacyFinancialEnvelope, expected_family: str) -> str:
    kind = str(envelope.payload.get("kind", "")).strip().lower()
    if kind not in SUPPORTED_KINDS:
        raise WndFinancialMappingError("unsupported_mapping_kind", kind)
    if envelope.source_family.value != expected_family:
        raise WndFinancialMappingError("source_family_mismatch", f"{envelope.source_family.value}:{kind}")
    return kind
