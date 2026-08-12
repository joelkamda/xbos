"""SQLAlchemy persistence boundary for the PC2 Party authority."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import text

from .contracts import (
    AddPartyContact, AddPartyIdentifier, AssignPartyRole, CreateOrganizationParty,
    CreatePartyRelationship, CreatePerson, OrganizationParty, Party, PartyContact,
    LinkLegalEntityParty, PartyIdentifier, PartyKind, PartyRelationship, PartyRole, PartyStatus, Person,
)
from .service import PartyAuthorityError


class SQLPartyRepository:
    def __init__(self, session):
        self.session = session

    @staticmethod
    def _party(row) -> Party:
        return Party(row.id, UUID(str(row.public_id)), row.tenant_id, PartyKind(row.party_kind), row.display_name, PartyStatus(row.status), row.row_version)

    def party(self, tenant_id: int, party_id: int) -> Party | None:
        row = self.session.execute(text("""SELECT id,public_id,tenant_id,party_kind,display_name,status,row_version
            FROM parties WHERE tenant_id=:tenant AND id=:id"""), {"tenant":tenant_id,"id":party_id}).first()
        return self._party(row) if row else None

    def _command(self, key: str, fingerprint: str, command_type: str):
        self.session.execute(text("""INSERT INTO party_commands(command_key,request_fingerprint,command_type)
            VALUES(:key,:fingerprint,:type) ON CONFLICT(command_key) DO NOTHING"""),
            {"key":key,"fingerprint":fingerprint,"type":command_type})
        row = self.session.execute(text("""SELECT command_key,request_fingerprint,command_type,result_table,result_id
            FROM party_commands WHERE command_key=:key FOR UPDATE"""), {"key":key}).one()
        if row.request_fingerprint != fingerprint or row.command_type != command_type:
            raise PartyAuthorityError("conflicting_party_command_replay")
        return row

    def _complete(self, key: str, table: str, result_id: int) -> None:
        self.session.execute(text("""UPDATE party_commands SET result_table=:table,result_id=:id,completed_at=now()
            WHERE command_key=:key"""), {"key":key,"table":table,"id":result_id})

    def _person(self, tenant_id: int, party_id: int) -> Person:
        row = self.session.execute(text("""SELECT p.id,p.public_id,p.tenant_id,p.party_kind,p.display_name,p.status,p.row_version,
                   x.given_name,x.family_name,x.middle_name
            FROM parties p JOIN persons x ON x.tenant_id=p.tenant_id AND x.party_id=p.id
            WHERE p.tenant_id=:tenant AND p.id=:id"""), {"tenant":tenant_id,"id":party_id}).one()
        return Person(self._party(row), row.given_name, row.family_name, row.middle_name)

    def _organization(self, tenant_id: int, party_id: int) -> OrganizationParty:
        row = self.session.execute(text("""SELECT p.id,p.public_id,p.tenant_id,p.party_kind,p.display_name,p.status,p.row_version,
                   x.legal_name,x.registration_reference
            FROM parties p JOIN organization_parties x ON x.tenant_id=p.tenant_id AND x.party_id=p.id
            WHERE p.tenant_id=:tenant AND p.id=:id"""), {"tenant":tenant_id,"id":party_id}).one()
        return OrganizationParty(self._party(row), row.legal_name, row.registration_reference)

    def create_person(self, command: CreatePerson, fingerprint: str) -> Person:
        replay = self._command(command.command_key, fingerprint, "create_person")
        if replay.result_id:
            return self._person(command.tenant_id, replay.result_id)
        display = " ".join(value for value in (command.given_name.strip(), (command.middle_name or "").strip(), command.family_name.strip()) if value)
        party_id = self.session.execute(text("""INSERT INTO parties(tenant_id,party_kind,display_name)
            VALUES(:tenant,'person',:name) RETURNING id"""), {"tenant":command.tenant_id,"name":display}).scalar_one()
        self.session.execute(text("""INSERT INTO persons(tenant_id,party_id,given_name,family_name,middle_name)
            VALUES(:tenant,:party,:given,:family,:middle)"""), {"tenant":command.tenant_id,"party":party_id,"given":command.given_name.strip(),"family":command.family_name.strip(),"middle":command.middle_name})
        self._add_external_key(command.tenant_id, party_id, command.external_key)
        self._complete(command.command_key, "parties", party_id)
        return self._person(command.tenant_id, party_id)

    def create_organization(self, command: CreateOrganizationParty, fingerprint: str) -> OrganizationParty:
        replay = self._command(command.command_key, fingerprint, "create_organization")
        if replay.result_id:
            return self._organization(command.tenant_id, replay.result_id)
        party_id = self.session.execute(text("""INSERT INTO parties(tenant_id,party_kind,display_name)
            VALUES(:tenant,'organization',:name) RETURNING id"""), {"tenant":command.tenant_id,"name":command.legal_name.strip()}).scalar_one()
        self.session.execute(text("""INSERT INTO organization_parties(tenant_id,party_id,legal_name,registration_reference)
            VALUES(:tenant,:party,:name,:registration)"""), {"tenant":command.tenant_id,"party":party_id,"name":command.legal_name.strip(),"registration":command.registration_reference})
        self._add_external_key(command.tenant_id, party_id, command.external_key)
        self._complete(command.command_key, "parties", party_id)
        return self._organization(command.tenant_id, party_id)

    def _add_external_key(self, tenant_id: int, party_id: int, value: str) -> None:
        try:
            self.session.execute(text("""INSERT INTO party_identifiers(tenant_id,party_id,scheme,identifier_value,normalized_value,is_primary)
                VALUES(:tenant,:party,'external_key',:value,lower(btrim(:value)),true)"""), {"tenant":tenant_id,"party":party_id,"value":value})
        except Exception as exc:
            raise PartyAuthorityError("conflicting_external_party_key") from exc

    def assign_role(self, command: AssignPartyRole, fingerprint: str) -> PartyRole:
        replay = self._command(command.command_key, fingerprint, "assign_role")
        if replay.result_id:
            row = self.session.execute(text("SELECT * FROM party_roles WHERE tenant_id=:tenant AND id=:id"), {"tenant":command.tenant_id,"id":replay.result_id}).one()
        else:
            row = self.session.execute(text("""INSERT INTO party_roles
                (tenant_id,party_id,role_code,valid_from,valid_to,legal_entity_id,organization_unit_id,location_id)
                VALUES(:tenant,:party,lower(btrim(:role)),:start,:end,:legal,:organization,:location)
                ON CONFLICT (tenant_id,party_id,role_code,valid_from,
                    (COALESCE(legal_entity_id,0)),(COALESCE(organization_unit_id,0)),(COALESCE(location_id,0)))
                DO NOTHING
                RETURNING *"""), {"tenant":command.tenant_id,"party":command.party_id,"role":command.role_code,"start":command.valid_from,"end":command.valid_to,"legal":command.legal_entity_id,"organization":command.organization_unit_id,"location":command.location_id}).first()
            if row is None:
                row = self.session.execute(text("""SELECT * FROM party_roles WHERE tenant_id=:tenant AND party_id=:party
                    AND role_code=lower(btrim(:role)) AND valid_from=:start
                    AND COALESCE(legal_entity_id,0)=COALESCE(:legal,0)
                    AND COALESCE(organization_unit_id,0)=COALESCE(:organization,0)
                    AND COALESCE(location_id,0)=COALESCE(:location,0)"""), {"tenant":command.tenant_id,"party":command.party_id,"role":command.role_code,"start":command.valid_from,"legal":command.legal_entity_id,"organization":command.organization_unit_id,"location":command.location_id}).one()
                if row.valid_to != command.valid_to:
                    raise PartyAuthorityError("conflicting_role_validity")
            self._complete(command.command_key, "party_roles", row.id)
        return PartyRole(row.id,UUID(str(row.public_id)),row.tenant_id,row.party_id,row.role_code,row.valid_from,row.valid_to,row.legal_entity_id,row.organization_unit_id,row.location_id)

    def create_relationship(self, command: CreatePartyRelationship, fingerprint: str) -> PartyRelationship:
        replay = self._command(command.command_key, fingerprint, "create_relationship")
        if replay.result_id:
            row = self.session.execute(text("SELECT * FROM party_relationships WHERE tenant_id=:tenant AND id=:id"), {"tenant":command.tenant_id,"id":replay.result_id}).one()
        else:
            row = self.session.execute(text("""INSERT INTO party_relationships
                (tenant_id,source_party_id,target_party_id,relationship_code,directed,valid_from,valid_to)
                VALUES(:tenant,:source,:target,lower(btrim(:code)),:directed,:start,:end)
                ON CONFLICT (tenant_id,source_party_id,target_party_id,relationship_code,directed,valid_from)
                DO NOTHING RETURNING *"""), {"tenant":command.tenant_id,"source":command.source_party_id,"target":command.target_party_id,"code":command.relationship_code,"directed":command.directed,"start":command.valid_from,"end":command.valid_to}).first()
            if row is None:
                row = self.session.execute(text("""SELECT * FROM party_relationships WHERE tenant_id=:tenant
                    AND source_party_id=:source AND target_party_id=:target
                    AND relationship_code=lower(btrim(:code)) AND directed=:directed AND valid_from=:start"""), {"tenant":command.tenant_id,"source":command.source_party_id,"target":command.target_party_id,"code":command.relationship_code,"directed":command.directed,"start":command.valid_from}).one()
                if row.valid_to != command.valid_to:
                    raise PartyAuthorityError("conflicting_relationship_validity")
            self._complete(command.command_key, "party_relationships", row.id)
        return PartyRelationship(row.id,UUID(str(row.public_id)),row.tenant_id,row.source_party_id,row.target_party_id,row.relationship_code,row.directed,row.valid_from,row.valid_to)

    def add_identifier(self, command: AddPartyIdentifier, fingerprint: str) -> PartyIdentifier:
        replay = self._command(command.command_key, fingerprint, "add_identifier")
        if replay.result_id:
            row = self.session.execute(text("SELECT * FROM party_identifiers WHERE tenant_id=:tenant AND id=:id"), {"tenant":command.tenant_id,"id":replay.result_id}).one()
        else:
            try:
                row = self.session.execute(text("""INSERT INTO party_identifiers
                    (tenant_id,party_id,scheme,identifier_value,normalized_value,is_primary,valid_from,valid_to)
                    VALUES(:tenant,:party,lower(btrim(:scheme)),:value,lower(btrim(:value)),:primary,:start,:end)
                    RETURNING *"""), {"tenant":command.tenant_id,"party":command.party_id,"scheme":command.scheme,"value":command.value,"primary":command.is_primary,"start":command.valid_from,"end":command.valid_to}).one()
            except Exception as exc:
                raise PartyAuthorityError("conflicting_party_identifier") from exc
            self._complete(command.command_key,"party_identifiers",row.id)
        return PartyIdentifier(row.id,row.tenant_id,row.party_id,row.scheme,row.identifier_value,row.is_primary,row.valid_from,row.valid_to)

    def add_contact(self, command: AddPartyContact, fingerprint: str) -> PartyContact:
        replay = self._command(command.command_key, fingerprint, "add_contact")
        if replay.result_id:
            row = self.session.execute(text("SELECT * FROM party_contacts WHERE tenant_id=:tenant AND id=:id"), {"tenant":command.tenant_id,"id":replay.result_id}).one()
        else:
            try:
                row = self.session.execute(text("""INSERT INTO party_contacts
                    (tenant_id,party_id,contact_type,contact_value,normalized_value,is_primary,valid_from,valid_to)
                    VALUES(:tenant,:party,lower(btrim(:type)),:value,lower(btrim(:value)),:primary,:start,:end)
                    RETURNING *"""), {"tenant":command.tenant_id,"party":command.party_id,"type":command.contact_type,"value":command.value,"primary":command.is_primary,"start":command.valid_from,"end":command.valid_to}).one()
            except Exception as exc:
                raise PartyAuthorityError("conflicting_primary_party_contact") from exc
            self._complete(command.command_key,"party_contacts",row.id)
        return PartyContact(row.id,row.tenant_id,row.party_id,row.contact_type,row.contact_value,row.is_primary,row.valid_from,row.valid_to)

    def link_legal_entity(self, command: LinkLegalEntityParty, fingerprint: str) -> tuple[int, int]:
        replay = self._command(command.command_key, fingerprint, "link_legal_entity")
        if replay.result_id:
            row = self.session.execute(text("SELECT legal_entity_id,organization_party_id FROM legal_entity_party_links WHERE tenant_id=:tenant AND id=:id"), {"tenant":command.tenant_id,"id":replay.result_id}).one()
        else:
            try:
                row = self.session.execute(text("""INSERT INTO legal_entity_party_links(tenant_id,legal_entity_id,organization_party_id)
                    VALUES(:tenant,:legal,:party) RETURNING id,legal_entity_id,organization_party_id"""), {"tenant":command.tenant_id,"legal":command.legal_entity_id,"party":command.organization_party_id}).one()
            except Exception as exc:
                raise PartyAuthorityError("conflicting_legal_entity_party_link") from exc
            self._complete(command.command_key,"legal_entity_party_links",row.id)
        return row.legal_entity_id,row.organization_party_id

    def resolve_reference(self, tenant_id: int, scheme: str, value: str) -> Party | None:
        row = self.session.execute(text("""SELECT p.id,p.public_id,p.tenant_id,p.party_kind,p.display_name,p.status,p.row_version
            FROM party_identifiers i JOIN parties p ON p.tenant_id=i.tenant_id AND p.id=i.party_id
            WHERE i.tenant_id=:tenant AND i.scheme=:scheme AND i.normalized_value=:value
              AND (i.valid_to IS NULL OR i.valid_to>=CURRENT_DATE)"""), {"tenant":tenant_id,"scheme":scheme,"value":value}).first()
        return self._party(row) if row else None

    def search(self, tenant_id: int, normalized_query: str) -> tuple[Party, ...]:
        rows = self.session.execute(text("""SELECT DISTINCT p.id,p.public_id,p.tenant_id,p.party_kind,p.display_name,p.status,p.row_version
            FROM parties p LEFT JOIN party_identifiers i ON i.tenant_id=p.tenant_id AND i.party_id=p.id
            LEFT JOIN party_contacts c ON c.tenant_id=p.tenant_id AND c.party_id=p.id
            WHERE p.tenant_id=:tenant AND (lower(p.display_name) LIKE :query OR i.normalized_value=:exact OR c.normalized_value=:exact)
            ORDER BY p.display_name,p.public_id"""), {"tenant":tenant_id,"query":f"%{normalized_query}%","exact":normalized_query}).all()
        return tuple(self._party(row) for row in rows)

    def export(self, tenant_id: int) -> dict[str, object]:
        def rows(table: str, columns: str):
            return [dict(row._mapping) for row in self.session.execute(text(f"SELECT {columns} FROM {table} WHERE tenant_id=:tenant ORDER BY id"), {"tenant":tenant_id})]
        return {
            "schema":"xbos.pc2.party-export.v1", "tenant_id":tenant_id,
            "parties":rows("parties","id,public_id,party_kind,display_name,status,row_version"),
            "persons":rows("persons","id,party_id,given_name,family_name,middle_name"),
            "organization_parties":rows("organization_parties","id,party_id,legal_name,registration_reference"),
            "identifiers":rows("party_identifiers","id,party_id,scheme,identifier_value,is_primary,valid_from,valid_to"),
            "contacts":rows("party_contacts","id,party_id,contact_type,contact_value,is_primary,valid_from,valid_to"),
            "roles":rows("party_roles","id,party_id,role_code,valid_from,valid_to,legal_entity_id,organization_unit_id,location_id"),
            "relationships":rows("party_relationships","id,source_party_id,target_party_id,relationship_code,directed,valid_from,valid_to"),
            "legal_entity_links":rows("legal_entity_party_links","id,legal_entity_id,organization_party_id"),
        }
