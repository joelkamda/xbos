"""Industry-neutral, tenant-safe PC2 Party contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from typing import Any
from uuid import UUID


class PartyKind(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"


class PartyStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    RETIRED = "retired"


@dataclass(frozen=True)
class Party:
    id: int
    public_id: UUID
    tenant_id: int
    kind: PartyKind
    display_name: str
    status: PartyStatus = PartyStatus.ACTIVE
    row_version: int = 1


@dataclass(frozen=True)
class Person:
    party: Party
    given_name: str
    family_name: str
    middle_name: str | None = None


@dataclass(frozen=True)
class OrganizationParty:
    party: Party
    legal_name: str
    registration_reference: str | None = None


@dataclass(frozen=True)
class PartyIdentifier:
    id: int
    tenant_id: int
    party_id: int
    scheme: str
    value: str
    is_primary: bool
    valid_from: date
    valid_to: date | None = None


@dataclass(frozen=True)
class PartyContact:
    id: int
    tenant_id: int
    party_id: int
    contact_type: str
    value: str
    is_primary: bool
    valid_from: date
    valid_to: date | None = None


@dataclass(frozen=True)
class PartyRole:
    id: int
    public_id: UUID
    tenant_id: int
    party_id: int
    role_code: str
    valid_from: date
    valid_to: date | None = None
    legal_entity_id: int | None = None
    organization_unit_id: int | None = None
    location_id: int | None = None


@dataclass(frozen=True)
class PartyRelationship:
    id: int
    public_id: UUID
    tenant_id: int
    source_party_id: int
    target_party_id: int
    relationship_code: str
    directed: bool
    valid_from: date
    valid_to: date | None = None


@dataclass(frozen=True)
class CreatePerson:
    command_key: str
    tenant_id: int
    external_key: str
    given_name: str
    family_name: str
    middle_name: str | None = None

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CreateOrganizationParty:
    command_key: str
    tenant_id: int
    external_key: str
    legal_name: str
    registration_reference: str | None = None

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AssignPartyRole:
    command_key: str
    tenant_id: int
    party_id: int
    role_code: str
    valid_from: date
    valid_to: date | None = None
    legal_entity_id: int | None = None
    organization_unit_id: int | None = None
    location_id: int | None = None

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CreatePartyRelationship:
    command_key: str
    tenant_id: int
    source_party_id: int
    target_party_id: int
    relationship_code: str
    directed: bool
    valid_from: date
    valid_to: date | None = None

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AddPartyIdentifier:
    command_key: str
    tenant_id: int
    party_id: int
    scheme: str
    value: str
    valid_from: date
    valid_to: date | None = None
    is_primary: bool = False

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AddPartyContact:
    command_key: str
    tenant_id: int
    party_id: int
    contact_type: str
    value: str
    valid_from: date
    valid_to: date | None = None
    is_primary: bool = False

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LinkLegalEntityParty:
    command_key: str
    tenant_id: int
    legal_entity_id: int
    organization_party_id: int

    def canonical_payload(self) -> dict[str, Any]:
        return asdict(self)
