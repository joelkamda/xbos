"""Contracts for the additive PC1 posthoc legacy-branch structural bridge."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnsureLegacyBranchStructuralBridge:
    tenant_id: int
    organization_unit_id: int
    location_id: int


@dataclass(frozen=True)
class LegacyBranchRecord:
    id: int
    tenant_id: int
    branch_code: str
    name: str
    is_active: bool


@dataclass(frozen=True)
class LegacyBranchStructuralMapping:
    tenant_id: int
    branch_id: int
    organization_unit_id: int
    location_id: int


@dataclass(frozen=True)
class LegacyBranchStructuralBridgeResult:
    tenant_id: int
    legacy_branch_id: int
    organization_unit_id: int
    location_id: int
    legal_entity_id: int | None
    replayed: bool
