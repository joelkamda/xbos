"""PC2 Party application authority with deterministic fail-closed behavior."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date
from typing import Protocol

from .contracts import (
    AddPartyContact,
    AddPartyIdentifier,
    AssignPartyRole,
    CreateOrganizationParty,
    CreatePartyRelationship,
    CreatePerson,
    LinkLegalEntityParty,
    OrganizationParty,
    Party,
    PartyContact,
    PartyIdentifier,
    PartyRelationship,
    PartyRole,
    Person,
)


class PartyAuthorityError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        super().__init__(f"{code}: {detail}" if detail else code)


class PartyRepository(Protocol):
    def create_person(self, command: CreatePerson, fingerprint: str) -> Person: ...
    def create_organization(self, command: CreateOrganizationParty, fingerprint: str) -> OrganizationParty: ...
    def assign_role(self, command: AssignPartyRole, fingerprint: str) -> PartyRole: ...
    def create_relationship(self, command: CreatePartyRelationship, fingerprint: str) -> PartyRelationship: ...
    def add_identifier(self, command: AddPartyIdentifier, fingerprint: str) -> PartyIdentifier: ...
    def add_contact(self, command: AddPartyContact, fingerprint: str) -> PartyContact: ...
    def link_legal_entity(self, command: LinkLegalEntityParty, fingerprint: str) -> tuple[int, int]: ...
    def party(self, tenant_id: int, party_id: int) -> Party | None: ...
    def resolve_reference(self, tenant_id: int, scheme: str, value: str) -> Party | None: ...
    def search(self, tenant_id: int, normalized_query: str) -> tuple[Party, ...]: ...
    def export(self, tenant_id: int) -> dict[str, object]: ...


class PartyAuthority:
    def __init__(self, repository: PartyRepository):
        self.repository = repository

    @staticmethod
    def _fingerprint(payload: dict[str, object]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_text(value: str, code: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise PartyAuthorityError(code)
        return normalized

    @staticmethod
    def _valid_period(valid_from: date, valid_to: date | None) -> None:
        if valid_to is not None and valid_to < valid_from:
            raise PartyAuthorityError("invalid_validity_period")

    def create_person(self, command: CreatePerson) -> Person:
        self._require_text(command.command_key, "missing_command_key")
        self._require_text(command.external_key, "missing_external_key")
        self._require_text(command.given_name, "missing_given_name")
        self._require_text(command.family_name, "missing_family_name")
        return self.repository.create_person(command, self._fingerprint(command.canonical_payload()))

    def create_organization(self, command: CreateOrganizationParty) -> OrganizationParty:
        self._require_text(command.command_key, "missing_command_key")
        self._require_text(command.external_key, "missing_external_key")
        self._require_text(command.legal_name, "missing_legal_name")
        return self.repository.create_organization(command, self._fingerprint(command.canonical_payload()))

    def assign_role(self, command: AssignPartyRole) -> PartyRole:
        self._require_text(command.command_key, "missing_command_key")
        self._require_text(command.role_code, "missing_role_code")
        self._valid_period(command.valid_from, command.valid_to)
        if self.repository.party(command.tenant_id, command.party_id) is None:
            raise PartyAuthorityError("party_not_found_or_cross_tenant")
        return self.repository.assign_role(command, self._fingerprint(command.canonical_payload()))

    def create_relationship(self, command: CreatePartyRelationship) -> PartyRelationship:
        self._require_text(command.command_key, "missing_command_key")
        self._require_text(command.relationship_code, "missing_relationship_code")
        self._valid_period(command.valid_from, command.valid_to)
        if command.source_party_id == command.target_party_id:
            raise PartyAuthorityError("self_relationship_not_allowed")
        for party_id in (command.source_party_id, command.target_party_id):
            if self.repository.party(command.tenant_id, party_id) is None:
                raise PartyAuthorityError("party_not_found_or_cross_tenant")
        return self.repository.create_relationship(command, self._fingerprint(command.canonical_payload()))

    def add_identifier(self, command: AddPartyIdentifier) -> PartyIdentifier:
        self._require_text(command.command_key, "missing_command_key")
        self._require_text(command.scheme, "missing_identifier_scheme")
        self._require_text(command.value, "missing_identifier_value")
        self._valid_period(command.valid_from, command.valid_to)
        if self.repository.party(command.tenant_id, command.party_id) is None:
            raise PartyAuthorityError("party_not_found_or_cross_tenant")
        return self.repository.add_identifier(command, self._fingerprint(command.canonical_payload()))

    def add_contact(self, command: AddPartyContact) -> PartyContact:
        self._require_text(command.command_key, "missing_command_key")
        contact_type = self._require_text(command.contact_type, "missing_contact_type").lower()
        if contact_type not in {"email", "phone", "postal_address", "other"}:
            raise PartyAuthorityError("unsupported_contact_type")
        self._require_text(command.value, "missing_contact_value")
        self._valid_period(command.valid_from, command.valid_to)
        if self.repository.party(command.tenant_id, command.party_id) is None:
            raise PartyAuthorityError("party_not_found_or_cross_tenant")
        return self.repository.add_contact(command, self._fingerprint(command.canonical_payload()))

    def link_legal_entity(self, command: LinkLegalEntityParty) -> tuple[int, int]:
        self._require_text(command.command_key, "missing_command_key")
        party = self.repository.party(command.tenant_id, command.organization_party_id)
        if party is None or party.kind.value != "organization":
            raise PartyAuthorityError("organization_party_not_found_or_cross_tenant")
        return self.repository.link_legal_entity(command, self._fingerprint(command.canonical_payload()))

    def resolve_reference(self, *, tenant_id: int, scheme: str, value: str) -> Party:
        scheme = self._require_text(scheme, "missing_identifier_scheme").lower()
        value = self._require_text(value, "missing_identifier_value").lower()
        result = self.repository.resolve_reference(tenant_id, scheme, value)
        if result is None:
            raise PartyAuthorityError("party_reference_not_found_or_cross_tenant")
        return result

    def search(self, *, tenant_id: int, query: str) -> tuple[Party, ...]:
        normalized = self._require_text(query, "missing_search_query").casefold()
        return self.repository.search(tenant_id, normalized)

    def export(self, tenant_id: int) -> bytes:
        payload = self.repository.export(tenant_id)
        return (json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode("utf-8")
