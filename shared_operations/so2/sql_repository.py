"""Private SQLAlchemy persistence adapter for SO2."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text

from .contracts import EstablishRelationship, OperationalRelationship, RelationshipHistory, RelationshipStatus
from .service import SO2AuthorityError


class SQLSO2Repository:
    def __init__(self, db_session):
        self.db_session = db_session

    @staticmethod
    def _relationship(row) -> OperationalRelationship:
        preferences = row.preferences if isinstance(row.preferences, dict) else json.loads(row.preferences or "{}")
        return OperationalRelationship(
            row.id, UUID(str(row.public_id)), row.tenant_id, UUID(str(row.party_public_id)), row.relationship_type_code,
            RelationshipStatus(row.lifecycle_status), row.source_code, row.purpose, preferences,
            row.organization_unit_id, row.location_id, row.effective_from, row.effective_to, row.row_version,
        )

    def _command(self, key: str, fingerprint: str, command_type: str):
        self.db_session.execute(text("""INSERT INTO so2_relationship_commands(command_key,request_fingerprint,command_type)
            VALUES(:key,:fingerprint,:type) ON CONFLICT(command_key) DO NOTHING"""), {"key": key, "fingerprint": fingerprint, "type": command_type})
        row = self.db_session.execute(text("""SELECT command_key,request_fingerprint,command_type,result_id
            FROM so2_relationship_commands WHERE command_key=:key FOR UPDATE"""), {"key": key}).one()
        if row.request_fingerprint != fingerprint or row.command_type != command_type:
            raise SO2AuthorityError("SO2_COMMAND_CONFLICT", "conflict", "The command key was already used with different content")
        return row

    def _complete(self, key: str, result_id: int) -> None:
        self.db_session.execute(text("""UPDATE so2_relationship_commands SET result_id=:id,completed_at=now()
            WHERE command_key=:key"""), {"key": key, "id": result_id})

    def _by_id(self, tenant_id: int, relationship_id: int):
        return self.db_session.execute(text("""SELECT r.*,p.public_id AS party_public_id FROM so2_operational_relationships r
            JOIN parties p ON p.tenant_id=r.tenant_id AND p.id=r.party_id
            WHERE r.tenant_id=:tenant AND r.id=:id"""), {"tenant": tenant_id, "id": relationship_id}).one()

    def establish(self, command: EstablishRelationship, party_id: int, public_id: UUID, fingerprint: str) -> OperationalRelationship:
        replay = self._command(command.command_key, fingerprint, "establish")
        if replay.result_id is not None:
            return self._relationship(self._by_id(command.tenant_id, replay.result_id))
        try:
            row = self.db_session.execute(text("""INSERT INTO so2_operational_relationships
                (public_id,tenant_id,party_id,relationship_type_code,lifecycle_status,source_code,purpose,preferences,
                 organization_unit_id,location_id,effective_from)
                VALUES(:public_id,:tenant,:party,:type,:status,:source,:purpose,CAST(:preferences AS jsonb),:organization,:location,:effective)
                RETURNING id"""), {
                    "public_id": str(public_id), "tenant": command.tenant_id, "party": party_id,
                    "type": command.relationship_type_code, "status": command.initial_status.value,
                    "source": command.source_code, "purpose": command.purpose,
                    "preferences": json.dumps(command.preferences or {}, sort_keys=True, separators=(",", ":")),
                    "organization": command.organization_unit_id, "location": command.location_id, "effective": command.effective_from,
                }).one()
        except Exception as exc:
            raise SO2AuthorityError("SO2_RELATIONSHIP_CONFLICT", "conflict", "This Party already has that operational relationship") from exc
        self.db_session.execute(text("""INSERT INTO so2_relationship_history
            (tenant_id,relationship_id,sequence,from_status,to_status,reason_code,occurred_at)
            VALUES(:tenant,:relationship,1,NULL,:status,'established',:at)"""), {
                "tenant": command.tenant_id, "relationship": row.id, "status": command.initial_status.value, "at": command.effective_from,
            })
        self._complete(command.command_key, row.id)
        return self._relationship(self._by_id(command.tenant_id, row.id))

    def relationship(self, tenant_id: int, public_id: UUID) -> OperationalRelationship | None:
        row = self.db_session.execute(text("""SELECT r.*,p.public_id AS party_public_id FROM so2_operational_relationships r
            JOIN parties p ON p.tenant_id=r.tenant_id AND p.id=r.party_id
            WHERE r.tenant_id=:tenant AND r.public_id=:public_id"""), {"tenant": tenant_id, "public_id": str(public_id)}).first()
        return self._relationship(row) if row else None

    def list(self, tenant_id: int, party_public_id: UUID | None = None, relationship_type_code: str | None = None) -> tuple[OperationalRelationship, ...]:
        rows = self.db_session.execute(text("""SELECT r.*,p.public_id AS party_public_id FROM so2_operational_relationships r
            JOIN parties p ON p.tenant_id=r.tenant_id AND p.id=r.party_id
            WHERE r.tenant_id=:tenant AND (:party IS NULL OR p.public_id=CAST(:party AS uuid))
              AND (:type IS NULL OR r.relationship_type_code=:type)
            ORDER BY r.relationship_type_code,r.public_id"""), {
                "tenant": tenant_id, "party": str(party_public_id) if party_public_id else None, "type": relationship_type_code,
            }).all()
        return tuple(self._relationship(row) for row in rows)

    def change_status(self, command, fingerprint: str) -> OperationalRelationship | None:
        replay = self._command(command.command_key, fingerprint, "change_status")
        if replay.result_id is not None:
            return self._relationship(self._by_id(command.tenant_id, replay.result_id))
        current = self.db_session.execute(text("""SELECT id,lifecycle_status,row_version FROM so2_operational_relationships
            WHERE tenant_id=:tenant AND public_id=:public_id FOR UPDATE"""), {"tenant": command.tenant_id, "public_id": str(command.relationship_public_id)}).first()
        if current is None or current.row_version != command.expected_version:
            return None
        sequence = self.db_session.execute(text("SELECT COALESCE(max(sequence),0)+1 FROM so2_relationship_history WHERE tenant_id=:tenant AND relationship_id=:id"), {"tenant": command.tenant_id, "id": current.id}).scalar_one()
        changed = self.db_session.execute(text("""UPDATE so2_operational_relationships
            SET lifecycle_status=:status,effective_to=CASE WHEN :status='ended' THEN :at ELSE NULL END,
                row_version=row_version+1,updated_at=now()
            WHERE tenant_id=:tenant AND id=:id AND row_version=:version RETURNING id"""), {
                "status": command.to_status.value, "at": command.occurred_at, "tenant": command.tenant_id,
                "id": current.id, "version": command.expected_version,
            }).first()
        if changed is None:
            return None
        self.db_session.execute(text("""INSERT INTO so2_relationship_history
            (tenant_id,relationship_id,sequence,from_status,to_status,reason_code,occurred_at)
            VALUES(:tenant,:id,:sequence,:from_status,:to_status,:reason,:at)"""), {
                "tenant": command.tenant_id, "id": current.id, "sequence": sequence,
                "from_status": current.lifecycle_status, "to_status": command.to_status.value,
                "reason": command.reason_code, "at": command.occurred_at,
            })
        self._complete(command.command_key, current.id)
        return self._relationship(self._by_id(command.tenant_id, current.id))

    def update_preferences(self, command, fingerprint: str) -> OperationalRelationship | None:
        replay = self._command(command.command_key, fingerprint, "update_preferences")
        if replay.result_id is not None:
            return self._relationship(self._by_id(command.tenant_id, replay.result_id))
        row = self.db_session.execute(text("""UPDATE so2_operational_relationships
            SET preferences=CAST(:preferences AS jsonb),row_version=row_version+1,updated_at=now()
            WHERE tenant_id=:tenant AND public_id=:public_id AND row_version=:version RETURNING id"""), {
                "preferences": json.dumps(command.preferences, sort_keys=True, separators=(",", ":")),
                "tenant": command.tenant_id, "public_id": str(command.relationship_public_id), "version": command.expected_version,
            }).first()
        if row is None:
            return None
        self._complete(command.command_key, row.id)
        return self._relationship(self._by_id(command.tenant_id, row.id))

    def history(self, tenant_id: int, public_id: UUID) -> tuple[RelationshipHistory, ...]:
        rows = self.db_session.execute(text("""SELECT h.sequence,h.from_status,h.to_status,h.reason_code,h.occurred_at
            FROM so2_relationship_history h JOIN so2_operational_relationships r
              ON r.tenant_id=h.tenant_id AND r.id=h.relationship_id
            WHERE r.tenant_id=:tenant AND r.public_id=:public_id ORDER BY h.sequence"""), {
                "tenant": tenant_id, "public_id": str(public_id),
            }).all()
        return tuple(RelationshipHistory(row.sequence, RelationshipStatus(row.from_status) if row.from_status else None, RelationshipStatus(row.to_status), row.reason_code, row.occurred_at) for row in rows)

    def export(self, tenant_id: int) -> dict[str, object]:
        relationships = self.list(tenant_id)
        return {"schema_version": 1, "tenant_id": tenant_id, "relationships": [
            {
                "public_id": str(item.public_id), "party_public_id": str(item.party_public_id),
                "relationship_type_code": item.relationship_type_code, "status": item.status.value,
                "source_code": item.source_code, "purpose": item.purpose, "preferences": item.preferences,
                "organization_unit_id": item.organization_unit_id, "location_id": item.location_id,
                "effective_from": item.effective_from, "effective_to": item.effective_to, "row_version": item.row_version,
            } for item in relationships
        ]}
