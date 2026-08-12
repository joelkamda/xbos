from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest

from core.platform.party import (
    AddPartyContact, AddPartyIdentifier, AssignPartyRole, CreateOrganizationParty,
    CreatePartyRelationship, CreatePerson, LinkLegalEntityParty, OrganizationParty, Party, PartyAuthority,
    PartyAuthorityError, PartyContact, PartyIdentifier, PartyKind, PartyRelationship,
    PartyRole, PartyStatus, Person,
)

ROOT = Path(__file__).resolve().parents[2]
UP = (ROOT / "alembic_neutral/sql/pc2_party_authority_up.sql").read_text(encoding="utf-8")
DOWN = (ROOT / "alembic_neutral/sql/pc2_party_authority_down.sql").read_text(encoding="utf-8")


class MemoryRepository:
    def __init__(self):
        self.next_id = 1
        self.parties: dict[tuple[int,int],Party] = {}
        self.commands: dict[str,tuple[str,object]] = {}
        self.references: dict[tuple[int,str,str],int] = {}
        self.roles: list[PartyRole] = []
        self.relationships: list[PartyRelationship] = []
        self.relationship_keys: dict[tuple,PartyRelationship] = {}
        self.identifiers: list[PartyIdentifier] = []
        self.contacts: list[PartyContact] = []
        self.links: dict[int,int] = {}

    def _replay(self, key, fingerprint, create):
        prior=self.commands.get(key)
        if prior and prior[0]!=fingerprint: raise PartyAuthorityError("conflicting_party_command_replay")
        if prior: return prior[1]
        result=create();self.commands[key]=(fingerprint,result);return result
    def _base(self, tenant, kind, name):
        item=Party(self.next_id,UUID(int=self.next_id),tenant,kind,name,PartyStatus.ACTIVE)
        self.next_id+=1;self.parties[(tenant,item.id)]=item;return item
    def create_person(self, command, fingerprint):
        def create():
            party=self._base(command.tenant_id,PartyKind.PERSON,f"{command.given_name} {command.family_name}")
            self.references[(command.tenant_id,"external_key",command.external_key.lower())]=party.id
            return Person(party,command.given_name,command.family_name,command.middle_name)
        return self._replay(command.command_key,fingerprint,create)
    def create_organization(self, command, fingerprint):
        def create():
            party=self._base(command.tenant_id,PartyKind.ORGANIZATION,command.legal_name)
            self.references[(command.tenant_id,"external_key",command.external_key.lower())]=party.id
            return OrganizationParty(party,command.legal_name,command.registration_reference)
        return self._replay(command.command_key,fingerprint,create)
    def party(self, tenant_id, party_id): return self.parties.get((tenant_id,party_id))
    def assign_role(self, command, fingerprint):
        def create():
            item=PartyRole(len(self.roles)+1,UUID(int=100+len(self.roles)),command.tenant_id,command.party_id,command.role_code,command.valid_from,command.valid_to,command.legal_entity_id,command.organization_unit_id,command.location_id)
            self.roles.append(item);return item
        return self._replay(command.command_key,fingerprint,create)
    def create_relationship(self, command, fingerprint):
        def create():
            natural=(command.tenant_id,command.source_party_id,command.target_party_id,command.relationship_code,command.directed,command.valid_from)
            prior=self.relationship_keys.get(natural)
            if prior:
                if prior.valid_to!=command.valid_to:raise PartyAuthorityError("conflicting_relationship_validity")
                return prior
            item=PartyRelationship(len(self.relationships)+1,UUID(int=200+len(self.relationships)),command.tenant_id,command.source_party_id,command.target_party_id,command.relationship_code,command.directed,command.valid_from,command.valid_to)
            self.relationships.append(item);self.relationship_keys[natural]=item;return item
        return self._replay(command.command_key,fingerprint,create)
    def resolve_reference(self, tenant_id, scheme, value):
        item=self.references.get((tenant_id,scheme,value));return self.party(tenant_id,item) if item else None
    def add_identifier(self, command, fingerprint):
        def create():
            item=PartyIdentifier(len(self.identifiers)+1,command.tenant_id,command.party_id,command.scheme.lower(),command.value,command.is_primary,command.valid_from,command.valid_to)
            self.identifiers.append(item);self.references[(command.tenant_id,command.scheme.lower(),command.value.lower())]=command.party_id;return item
        return self._replay(command.command_key,fingerprint,create)
    def add_contact(self, command, fingerprint):
        def create():
            item=PartyContact(len(self.contacts)+1,command.tenant_id,command.party_id,command.contact_type.lower(),command.value,command.is_primary,command.valid_from,command.valid_to)
            self.contacts.append(item);return item
        return self._replay(command.command_key,fingerprint,create)
    def link_legal_entity(self, command, fingerprint):
        def create():
            if command.legal_entity_id in self.links or command.organization_party_id in self.links.values():raise PartyAuthorityError("conflicting_legal_entity_party_link")
            self.links[command.legal_entity_id]=command.organization_party_id;return command.legal_entity_id,command.organization_party_id
        return self._replay(command.command_key,fingerprint,create)
    def search(self, tenant_id, query): return tuple(sorted((p for (t,_),p in self.parties.items() if t==tenant_id and query in p.display_name.casefold()),key=lambda p:(p.display_name,p.public_id)))
    def export(self, tenant_id):
        return {"schema":"xbos.pc2.party-export.v1","tenant_id":tenant_id,"parties":[p.__dict__ for (t,_),p in sorted(self.parties.items()) if t==tenant_id]}


def _person(authority, tenant=1, key="p1"):
    return authority.create_person(CreatePerson(key,tenant,key,"Ada","Lovelace"))


def test_contract_covers_all_eleven_pc2_obligations_and_boundaries():
    contract=json.loads((ROOT/"contracts/platform/v1/pc2_party_authority.json").read_text())
    assert contract["scope"] == [f"PC2.{n}" for n in range(1,12)]
    assert contract["canonical_root"] == "parties"
    assert contract["tenant_model"].startswith("tenant-scoped")
    assert contract["business_roles"]["authorization_roles"] is False


def test_person_and_organization_are_distinct_party_subtypes_not_identity_or_structure():
    authority=PartyAuthority(MemoryRepository())
    person=_person(authority)
    organization=authority.create_organization(CreateOrganizationParty("o1",1,"o1","Analytical Engines Ltd"))
    assert isinstance(person,Person) and person.party.kind is PartyKind.PERSON
    assert isinstance(organization,OrganizationParty) and organization.party.kind is PartyKind.ORGANIZATION
    assert type(person) is not type(organization)


def test_creation_replay_is_stable_and_conflicting_replay_fails_closed():
    authority=PartyAuthority(MemoryRepository());command=CreatePerson("same",1,"person-1","Ada","Lovelace")
    assert authority.create_person(command) == authority.create_person(command)
    with pytest.raises(PartyAuthorityError,match="conflicting_party_command_replay"):
        authority.create_person(replace(command,family_name="Byron"))


def test_exact_reference_and_search_are_deterministic_and_tenant_scoped():
    authority=PartyAuthority(MemoryRepository());created=_person(authority)
    assert authority.resolve_reference(tenant_id=1,scheme="EXTERNAL_KEY",value="P1") == created.party
    assert authority.search(tenant_id=1,query="ada") == (created.party,)
    with pytest.raises(PartyAuthorityError,match="party_reference_not_found_or_cross_tenant"):
        authority.resolve_reference(tenant_id=2,scheme="external_key",value="p1")


def test_same_party_holds_multiple_business_roles_and_replays_deterministically():
    authority=PartyAuthority(MemoryRepository());party=_person(authority).party
    customer=AssignPartyRole("r1",1,party.id,"customer",date(2026,1,1))
    supplier=AssignPartyRole("r2",1,party.id,"supplier",date(2026,1,1))
    assert authority.assign_role(customer) == authority.assign_role(customer)
    assert {authority.assign_role(customer).role_code,authority.assign_role(supplier).role_code} == {"customer","supplier"}


def test_identifier_and_contact_models_are_replay_safe_and_not_authentication_authority():
    authority=PartyAuthority(MemoryRepository());party=_person(authority).party
    identifier=AddPartyIdentifier("id-1",1,party.id,"tax_reference","CM-123",date(2026,1,1),is_primary=True)
    contact=AddPartyContact("contact-1",1,party.id,"email","business@example.test",date(2026,1,1),is_primary=True)
    assert authority.add_identifier(identifier) == authority.add_identifier(identifier)
    assert authority.add_contact(contact) == authority.add_contact(contact)
    assert authority.resolve_reference(tenant_id=1,scheme="tax_reference",value="cm-123") == party


def test_legal_entity_link_preserves_distinct_organization_party_authority():
    authority=PartyAuthority(MemoryRepository())
    organization=authority.create_organization(CreateOrganizationParty("o1",1,"o1","Company"))
    command=LinkLegalEntityParty("link-1",1,101,organization.party.id)
    assert authority.link_legal_entity(command) == authority.link_legal_entity(command) == (101,organization.party.id)
    person=_person(authority)
    with pytest.raises(PartyAuthorityError,match="organization_party_not_found_or_cross_tenant"):
        authority.link_legal_entity(LinkLegalEntityParty("bad-link",1,102,person.party.id))


def test_relationship_is_directional_period_bound_and_cross_tenant_safe():
    authority=PartyAuthority(MemoryRepository());source=_person(authority).party
    target=authority.create_organization(CreateOrganizationParty("o1",1,"o1","Company")).party
    command=CreatePartyRelationship("rel",1,source.id,target.id,"employee_of",True,date(2026,1,1))
    assert authority.create_relationship(command) == authority.create_relationship(command)
    with pytest.raises(PartyAuthorityError,match="invalid_validity_period"):
        authority.create_relationship(replace(command,command_key="bad",valid_to=date(2025,1,1)))
    with pytest.raises(PartyAuthorityError,match="conflicting_relationship_validity"):
        authority.create_relationship(replace(command,command_key="conflict",valid_to=date(2026,12,31)))
    outsider=_person(authority,2,"p2").party
    with pytest.raises(PartyAuthorityError,match="party_not_found_or_cross_tenant"):
        authority.create_relationship(replace(command,command_key="cross",target_party_id=outsider.id))


def test_export_is_deterministic_and_tenant_scoped():
    authority=PartyAuthority(MemoryRepository());_person(authority);_person(authority,2,"p2")
    first=authority.export(1)
    assert first == authority.export(1) and first.endswith(b"\n")
    assert json.loads(first)["tenant_id"] == 1 and b'"tenant_id":2' not in first


def test_migration_is_single_canonical_child_and_preserves_finance_semantics():
    version=(ROOT/"alembic_neutral/versions/pc2_party_authority_022_party_person_organization_roles_relationships.py").read_text()
    assert 'revision = "pc2_party_authority_022"' in version
    assert 'down_revision = "pc1_structural_context_021"' in version
    assert "ALTER TABLE public.financial_counterparties" not in UP
    assert "COMMENT ON COLUMN public.financial_counterparties.party_id" in UP
    assert "INSERT INTO public.users" not in UP and "INSERT INTO public.parties" not in UP
    assert "DROP TABLE IF EXISTS public.parties" in DOWN


def test_compatibility_is_explicit_and_never_name_email_or_phone_deduplicated():
    manifest=json.loads((ROOT/"contracts/platform/v1/pc2_compatibility_migration_manifest.json").read_text())
    assert all(item["automatic_conversion"] is False for item in manifest["entries"])
    assert "party_compatibility_mappings" in UP
    assert "users" not in UP.lower()
