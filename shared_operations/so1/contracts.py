"""Immutable public SO1 commands and results."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID


class TargetType(StrEnum):
    ATOMIC_UNIT = "atomic_unit"
    OFFER = "offer"


class ScopeType(StrEnum):
    TENANT = "tenant"
    LEGAL_ENTITY = "legal_entity"
    ORGANIZATION_UNIT = "organization_unit"
    LOCATION = "location"


class ComponentRule(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class AtomicUnit:
    id: int; public_id: UUID; tenant_id: int; code: str | None; name: str
    unit_kind: str | None; active: bool; metadata: dict[str, Any]; row_version: int


@dataclass(frozen=True)
class Catalog:
    id: int; public_id: UUID; tenant_id: int; code: str; name: str
    scope_type: ScopeType; scope_id: int | None; active: bool
    effective_from: datetime; effective_to: datetime | None; row_version: int


@dataclass(frozen=True)
class OfferComponent:
    atomic_unit_public_id: UUID; quantity: Decimal; rule: ComponentRule; sequence: int


@dataclass(frozen=True)
class Offer:
    id: int; public_id: UUID; tenant_id: int; code: str; name: str
    active: bool; components: tuple[OfferComponent, ...]; row_version: int


@dataclass(frozen=True)
class Price:
    id: int; public_id: UUID; tenant_id: int; target_type: TargetType; target_public_id: UUID
    price_code: str; amount: Decimal; currency: str; scope_type: ScopeType; scope_id: int | None
    precedence: int; effective_from: datetime; effective_to: datetime | None; active: bool; row_version: int


@dataclass(frozen=True)
class CreateAtomicUnit:
    command_key: str; tenant_id: int; code: str; name: str; unit_kind: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class UpdateAtomicUnit:
    command_key: str; tenant_id: int; public_id: UUID; expected_version: int
    name: str | None = None; unit_kind: str | None = None; metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class CreateCatalog:
    command_key: str; tenant_id: int; code: str; name: str; scope_type: ScopeType
    scope_id: int | None; effective_from: datetime; effective_to: datetime | None = None


@dataclass(frozen=True)
class PublishCatalogEntry:
    command_key: str; tenant_id: int; catalog_public_id: UUID; target_type: TargetType
    target_public_id: UUID; sort_order: int = 0; semantic_reference: str | None = None
    effective_from: datetime | None = None; effective_to: datetime | None = None


@dataclass(frozen=True)
class CreateOffer:
    command_key: str; tenant_id: int; code: str; name: str
    components: tuple[OfferComponent, ...]


@dataclass(frozen=True)
class UpdateOffer:
    command_key: str; tenant_id: int; public_id: UUID; expected_version: int
    name: str; components: tuple[OfferComponent, ...]


@dataclass(frozen=True)
class DefinePrice:
    command_key: str; tenant_id: int; target_type: TargetType; target_public_id: UUID
    price_code: str; amount: Decimal; currency: str; scope_type: ScopeType
    scope_id: int | None; precedence: int; effective_from: datetime; effective_to: datetime | None = None


@dataclass(frozen=True)
class ResolvePrice:
    tenant_id: int; target_type: TargetType; target_public_id: UUID; price_code: str
    currency: str; at: datetime; scope_type: ScopeType; scope_id: int | None
