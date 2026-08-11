"""Typed M7.3 shadow-rehearsal and control-total comparison authority."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from .wnd_financial_mapping_contract import fingerprint, money, require_hash

CONTRACT_CODE = "XBOS_M73_WND_SHADOW_EXECUTION_AND_CONTROL_TOTALS"
CONTRACT_VERSION = 1
CONTROL_NAMES = (
    "commercial_revenue", "customer_allowances", "cash_collections",
    "receivables_opened", "receivables_satisfied", "refunds",
    "fulfillment_cost", "financial_documents",
)


class WndShadowRehearsalError(ValueError):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _amount(value: Any, name: str) -> Decimal:
    try:
        return money(value, name)
    except Exception as exc:
        raise WndShadowRehearsalError("invalid_control_total", name) from exc


@dataclass(frozen=True)
class FinancialControlTotals:
    currency_code: str
    values: Mapping[str, Decimal]

    def __post_init__(self) -> None:
        currency = str(self.currency_code).strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise WndShadowRehearsalError("invalid_currency", currency)
        unknown = set(self.values) - set(CONTROL_NAMES)
        if unknown:
            raise WndShadowRehearsalError("unsupported_control", ",".join(sorted(unknown)))
        object.__setattr__(self, "currency_code", currency)
        object.__setattr__(self, "values", {
            name: _amount(self.values.get(name, 0), name) for name in CONTROL_NAMES
        })

    def canonical_payload(self) -> dict[str, Any]:
        return {"currency_code": self.currency_code, "values": dict(self.values)}


@dataclass(frozen=True)
class ShadowCase:
    sequence: int
    tenant_id: int
    organization_unit_id: int
    source_identity: str
    source_fingerprint: str
    mapping_package: str
    mapping_plan_fingerprint: str
    expected: FinancialControlTotals
    disposition: str = "ready"
    disposition_reason: str = "mapped_canonical_commands_available"
    writer_routing: str = "unchanged"
    production_writes_allowed: bool = False
    case_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if self.sequence <= 0 or min(self.tenant_id, self.organization_unit_id) <= 0:
            raise WndShadowRehearsalError("invalid_case_scope", self.source_identity)
        if not all((self.source_identity, self.source_fingerprint, self.mapping_package,
                    self.mapping_plan_fingerprint, self.disposition_reason)):
            raise WndShadowRehearsalError("incomplete_shadow_case", self.source_identity)
        try:
            require_hash(self.source_fingerprint, "source_fingerprint")
            require_hash(self.mapping_plan_fingerprint, "mapping_plan_fingerprint")
        except Exception as exc:
            raise WndShadowRehearsalError("invalid_case_fingerprint", self.source_identity) from exc
        if self.disposition not in {"ready", "withheld"}:
            raise WndShadowRehearsalError("invalid_disposition", self.disposition)
        if self.writer_routing != "unchanged" or self.production_writes_allowed:
            raise WndShadowRehearsalError("production_execution_forbidden", self.source_identity)
        object.__setattr__(self, "case_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence, "tenant_id": self.tenant_id,
            "organization_unit_id": self.organization_unit_id,
            "source_identity": self.source_identity,
            "source_fingerprint": self.source_fingerprint,
            "mapping_package": self.mapping_package,
            "mapping_plan_fingerprint": self.mapping_plan_fingerprint,
            "expected": self.expected.canonical_payload(),
            "disposition": self.disposition,
            "disposition_reason": self.disposition_reason,
            "writer_routing": "unchanged", "production_writes_allowed": False,
        }


@dataclass(frozen=True)
class ProductionShapedRehearsal:
    rehearsal_id: str
    source_snapshot_fingerprint: str
    cases: tuple[ShadowCase, ...]
    execution_environment: str = "isolated_disposable"
    writer_routing: str = "unchanged"
    migration_authority: str = "none"
    live_cutover_owner: str = "R6"
    rehearsal_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cases", tuple(self.cases))
        if not self.rehearsal_id or not self.source_snapshot_fingerprint or not self.cases:
            raise WndShadowRehearsalError("incomplete_rehearsal", self.rehearsal_id)
        try:
            require_hash(self.source_snapshot_fingerprint, "source_snapshot_fingerprint")
        except Exception as exc:
            raise WndShadowRehearsalError("invalid_source_snapshot_fingerprint", self.rehearsal_id) from exc
        if tuple(case.sequence for case in self.cases) != tuple(range(1, len(self.cases) + 1)):
            raise WndShadowRehearsalError("non_contiguous_case_sequence", self.rehearsal_id)
        identities = [(c.tenant_id, c.organization_unit_id, c.source_identity) for c in self.cases]
        if len(set(identities)) != len(identities):
            raise WndShadowRehearsalError("duplicate_source_case", self.rehearsal_id)
        if (self.execution_environment != "isolated_disposable" or self.writer_routing != "unchanged"
                or self.migration_authority != "none" or self.live_cutover_owner != "R6"):
            raise WndShadowRehearsalError("unsafe_rehearsal_boundary", self.rehearsal_id)
        object.__setattr__(self, "rehearsal_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "schema": CONTRACT_CODE, "schema_version": CONTRACT_VERSION,
            "rehearsal_id": self.rehearsal_id,
            "source_snapshot_fingerprint": self.source_snapshot_fingerprint,
            "cases": [case.canonical_payload() for case in self.cases],
            "execution_environment": "isolated_disposable",
            "writer_routing": "unchanged", "migration_authority": "none",
            "live_cutover_owner": "R6",
        }


@dataclass(frozen=True)
class ControlTotalComparison:
    case_fingerprint: str
    expected: FinancialControlTotals
    observed: FinancialControlTotals
    deltas: Mapping[str, Decimal] = field(init=False)
    status: str = field(init=False)
    comparison_fingerprint: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.case_fingerprint:
            raise WndShadowRehearsalError("case_fingerprint_required", "comparison")
        if self.expected.currency_code != self.observed.currency_code:
            raise WndShadowRehearsalError("control_currency_mismatch", self.case_fingerprint)
        deltas = {name: self.observed.values[name] - self.expected.values[name] for name in CONTROL_NAMES}
        object.__setattr__(self, "deltas", deltas)
        object.__setattr__(self, "status", "matched" if not any(deltas.values()) else "variance")
        object.__setattr__(self, "comparison_fingerprint", fingerprint(self.canonical_payload()))

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "case_fingerprint": self.case_fingerprint,
            "expected": self.expected.canonical_payload(),
            "observed": self.observed.canonical_payload(),
            "deltas": dict(getattr(self, "deltas", {})),
            "status": getattr(self, "status", "pending"),
        }


def assert_rehearsal_replay(existing: ProductionShapedRehearsal,
                            candidate: ProductionShapedRehearsal) -> ProductionShapedRehearsal:
    if existing.rehearsal_id != candidate.rehearsal_id:
        raise WndShadowRehearsalError("replay_identity_mismatch", candidate.rehearsal_id)
    if existing.rehearsal_fingerprint != candidate.rehearsal_fingerprint:
        raise WndShadowRehearsalError("rehearsal_idempotency_conflict", candidate.rehearsal_id)
    return existing
