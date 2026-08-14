"""Stable public contracts for SO2 operational Party relationships."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class RelationshipStatus(StrEnum):
    PROSPECT = "prospect"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ENDED = "ended"


class ScopeType(StrEnum):
    TENANT = "tenant"
    ORGANIZATION_UNIT = "organization_unit"
    LOCATION = "location"


@dataclass(frozen=True)
class OperationalRelationship:
    id: int
    public_id: UUID
    tenant_id: int
    party_public_id: UUID
    relationship_type_code: str
    status: RelationshipStatus
    source_code: str | None
    purpose: str | None
    preferences: dict[str, Any]
    organization_unit_id: int | None
    location_id: int | None
    effective_from: datetime
    effective_to: datetime | None
    row_version: int


@dataclass(frozen=True)
class RelationshipHistory:
    sequence: int
    from_status: RelationshipStatus | None
    to_status: RelationshipStatus
    reason_code: str
    occurred_at: datetime


@dataclass(frozen=True)
class EstablishRelationship:
    command_key: str
    tenant_id: int
    party_public_id: UUID
    relationship_type_code: str
    initial_status: RelationshipStatus
    effective_from: datetime
    source_code: str | None = None
    purpose: str | None = None
    preferences: dict[str, Any] | None = None
    organization_unit_id: int | None = None
    location_id: int | None = None


@dataclass(frozen=True)
class ChangeRelationshipStatus:
    command_key: str
    tenant_id: int
    relationship_public_id: UUID
    expected_version: int
    to_status: RelationshipStatus
    reason_code: str
    occurred_at: datetime


@dataclass(frozen=True)
class UpdateRelationshipPreferences:
    command_key: str
    tenant_id: int
    relationship_public_id: UUID
    expected_version: int
    preferences: dict[str, Any]


@dataclass(frozen=True)
class ClassifyRelationship:
    command_key: str
    tenant_id: int
    relationship_public_id: UUID
    concept_qualified_code: str
    classified_on: datetime
